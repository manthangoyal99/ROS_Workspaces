#!/usr/bin/env python3
import rospy
import json
import numpy as np
import tf.transformations as tr
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import Int8MultiArray
from franka_gripper.msg import MoveAction, MoveGoal, GraspAction, GraspGoal
import actionlib
import os

from task_automaton import PickPlaceAutomaton

class LowPassFilter:
    def __init__(self):
        self.pos = None
        self.quat = None 

    def update(self, target_pos, target_quat, alpha):
        if self.pos is None:
            self.pos = np.array(target_pos)
            self.quat = np.array(target_quat)
            return self.pos, self.quat
        
        self.pos = self.pos + alpha * (np.array(target_pos) - self.pos)
        self.quat = tr.quaternion_slerp(self.quat, target_quat, alpha)
        return self.pos, self.quat

class ResilientController:
    def __init__(self):
        rospy.init_node('resilient_controller')
        
        # --- CONFIGURATION ---
        self.data_dir = "/home/ravi/fr3_ws/src/reshelving_gpr_ltl/data"
        self.json_path = os.path.join(self.data_dir, "demo_trajectory.json") 
        self.control_rate = 50.0 
        
        # --- TUNING ---
        self.BRIDGE_ALPHA = 0.01    # Smooth ghosting
        self.FAST_ALPHA   = 0.50    # Sharp tracking
        self.BRIDGE_TOLERANCE = 0.03 
        
        # STABILIZATION BUFFER (Debouncing)
        # 25 cycles @ 50Hz = 0.5 seconds of "deafness" after switch
        self.SENSOR_LOCKOUT_CYCLES = 100

        self.NEXT_MODE_MAP = {1: 2, 2: 3, 3: 4, 4: 1, 5: 1}
        self.MODE_NAMES = {1: "APPROACH", 2: "PICK", 3: "TRANSPORT", 4: "PLACE", 5: "RETREAT"}

        # --- LOAD DATA ---
        self.traj_library = self.load_and_segment_trajectory(self.json_path)
        rospy.loginfo(f"Library Loaded. Modes: {list(self.traj_library.keys())}")

        # --- SETUP ---
        self.automaton = PickPlaceAutomaton()
        self.current_props = [0, 0, 0] 
        
        rospy.Subscriber('/task/atomic_propositions', Int8MultiArray, self.cb_props)
        self.pub_pose = rospy.Publisher('/cartesian_impedance_example_controller/equilibrium_pose', PoseStamped, queue_size=1)

        self.grasp_client = actionlib.SimpleActionClient('/franka_gripper/grasp', GraspAction)
        self.move_client = actionlib.SimpleActionClient('/franka_gripper/move', MoveAction)
        
        # --- STATE ---
        self.filter = LowPassFilter()
        self.active_mode = 1 
        self.traj_index = 0
        self.last_commanded_gripper = 0 
        self.is_bridging = False 
        self.lockout_counter = 0

    def cb_props(self, msg):
        self.current_props = list(msg.data)

    def load_and_segment_trajectory(self, filepath):
        with open(filepath, 'r') as f: data = json.load(f)
        modes = data.get('mode_labels', data.get('modes'))
        pos = data['positions']
        ori = data['orientations']
        grip = data['gripper_states']
        
        library = {}
        for i, m in enumerate(modes):
            if m not in library:
                library[m] = {'pos': [], 'ori': [], 'grip': []}
            library[m]['pos'].append(pos[i])
            library[m]['ori'].append(ori[i])
            library[m]['grip'].append(grip[i])
        return library

    def process_gripper_command(self, desired_state):
        if desired_state != self.last_commanded_gripper:
            if desired_state == 1:
                rospy.loginfo("Trajectory Command: Closing Gripper...")
                goal = GraspGoal(width=0.0, speed=0.1, force=40.0)
                goal.epsilon.inner = 0.08
                goal.epsilon.outer = 0.08
                self.grasp_client.send_goal(goal)
            else:
                rospy.loginfo("Trajectory Command: Opening Gripper...")
                goal = MoveGoal(width=0.08, speed=0.1)
                self.move_client.send_goal(goal)
            self.last_commanded_gripper = desired_state

    def trigger_mode_switch(self, new_mode):
        """ Handles Switching + Bridging + Debouncing """
        rospy.loginfo(f">>> SWITCHING: {self.active_mode} -> {new_mode}")
        
        # 1. Update Controller State
        self.active_mode = new_mode
        self.traj_index = 0
        self.is_bridging = True
        
        # 2. Force Automaton State
        mode_name = self.MODE_NAMES.get(new_mode, "UNKNOWN")
        self.automaton.current_mode = mode_name
        self.automaton.mode_id = new_mode
        
        # 3. Activate Lockout (The Debounce)
        self.lockout_counter = self.SENSOR_LOCKOUT_CYCLES

    def run(self):
        rate = rospy.Rate(self.control_rate)
        rospy.loginfo("Resilient Controller Running...")
        
        while not rospy.is_shutdown():
            
            # --- 1. SENSOR LOCKOUT CHECK ---
            if self.lockout_counter > 0:
                self.lockout_counter -= 1
                # rospy.loginfo_throttle(1.0, f"[LOCKOUT] Ignoring sensors for {self.lockout_counter} more cycles.")
                # Purely execute trajectory logic while locked out
            
            else:
                # --- 2. LOGIC CHECKS (Only when unlocked) ---
                # A. Trajectory Completion?
                traj_finished = False
                if self.active_mode in self.traj_library:
                    if self.traj_index >= len(self.traj_library[self.active_mode]['pos']) - 1:
                        traj_finished = True

                if traj_finished:
                    # Force Next Mode
                    next_mode = self.NEXT_MODE_MAP.get(self.active_mode, 1)
                    self.trigger_mode_switch(next_mode)
                    rospy.loginfo(f"Trajectory Finished. Forcing switch to Mode {next_mode} ({self.MODE_NAMES.get(next_mode, 'UNKNOWN')})")
                
                else:
                    # B. Automaton Update (Using Raw Sensors, trusting Hysteresis Monitor)
                    new_mode, _ = self.automaton.update(self.current_props)
                    
                    if new_mode != self.active_mode:
                        rospy.logwarn(f"Safety/Sensor Triggered Switch!")
                        self.trigger_mode_switch(new_mode)

            # --- 3. TRAJECTORY GENERATION ---
            if self.active_mode in self.traj_library:
                traj_data = self.traj_library[self.active_mode]
                
                target_p = traj_data['pos'][self.traj_index]
                target_q = traj_data['ori'][self.traj_index]
                desired_grip = traj_data['grip'][self.traj_index]
                self.process_gripper_command(desired_grip)
                if self.is_bridging:
                    # BRIDGING (Slow)
                    current_alpha = self.BRIDGE_ALPHA
                    if self.filter.pos is not None:
                        dist_error = np.linalg.norm(np.array(target_p) - self.filter.pos)
                        if dist_error < self.BRIDGE_TOLERANCE:
                            rospy.loginfo(f"Bridge Done. Engaging Fast Mode.")
                            self.is_bridging = False
                else:
                    # EXECUTION (Fast)
                    current_alpha = self.FAST_ALPHA
                    if self.traj_index < len(traj_data['pos']) - 1:
                        self.traj_index += 1
            else:
                target_p = [0.3, 0.0, 0.5] 
                target_q = [1, 0, 0, 0]
                current_alpha = self.BRIDGE_ALPHA

            # --- 4. FILTER & PUBLISH ---
            smooth_p, smooth_q = self.filter.update(target_p, target_q, current_alpha)

            msg = PoseStamped()
            msg.header.stamp = rospy.Time.now()
            msg.header.frame_id = "panda_link0"
            msg.pose.position.x = smooth_p[0]
            msg.pose.position.y = smooth_p[1]
            msg.pose.position.z = smooth_p[2]
            msg.pose.orientation.x = smooth_q[0]
            msg.pose.orientation.y = smooth_q[1]
            msg.pose.orientation.z = smooth_q[2]
            msg.pose.orientation.w = smooth_q[3]
            
            status = "LOCKED" if self.lockout_counter > 0 else ("BRIDGE" if self.is_bridging else "RUN")
            rospy.loginfo_throttle(1.0, f"[{status}] Mode:{self.active_mode} Idx:{self.traj_index} Props:{self.current_props}") 
            
            self.pub_pose.publish(msg)
            rate.sleep()

if __name__ == '__main__':
    try:
        ResilientController().run()
    except rospy.ROSInterruptException:
        pass