#!/usr/bin/env python3
import rospy
import numpy as np
import tf.transformations as tr
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import Int8MultiArray, Float32MultiArray
from franka_gripper.msg import MoveAction, MoveGoal, GraspAction, GraspGoal
import actionlib
import os
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from task_automaton import PickPlaceAutomaton
from transported_traj import OnlineTrajectoryWarper # Import your new class

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
        self.data_dir = "/home/ravi/fr3_ws/src/reshelving_adaptive/data"
        self.demo_path = os.path.join(self.data_dir, "demo_trajectory.json") 
        self.demo_kp_path = os.path.join(self.data_dir, "source_keypoints.json") 
        self.control_rate = 50.0 
        
        # --- TUNING ---
        self.BRIDGE_ALPHA = 0.01 
        self.FAST_ALPHA   = 0.50 
        self.BRIDGE_TOLERANCE = 0.03 
        self.SENSOR_LOCKOUT_CYCLES = 75 # 1.5 seconds of debounce at 50Hz

        self.NEXT_MODE_MAP = {1: 2, 2: 3, 3: 4, 4: 5, 5: 1}
        self.MODE_NAMES = {1: "APPROACH", 2: "PICK", 3: "TRANSPORT", 4: "PLACE", 5: "RETREAT"}

        # --- INITIALIZE WARPER ---
        self.warper = OnlineTrajectoryWarper(self.demo_path, self.demo_kp_path)
        self.traj_library = {} # Starts empty, filled dynamically
        
        # --- PERCEPTION BUFFERS ---
        self.live_source_kps = None
        self.live_target_kps = None
        self.frozen_source_kps = None
        self.frozen_target_kps = None

        rospy.Subscriber('/vision/live_source_kps', Float32MultiArray, self.cb_source_kps)
        rospy.Subscriber('/vision/live_target_kps', Float32MultiArray, self.cb_target_kps)
        
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
        
    def cb_source_kps(self, msg):
        self.live_source_kps = np.array(msg.data).reshape(-1, 3)

    def cb_target_kps(self, msg):
        self.live_target_kps = np.array(msg.data).reshape(-1, 3)

    def process_gripper_command(self, desired_state):
        if desired_state != self.last_commanded_gripper:
            if desired_state == 1:
                rospy.loginfo("Trajectory Command: Closing Gripper...")
                goal = GraspGoal(width=0.0, speed=0.1, force=10.0)
                goal.epsilon.inner, goal.epsilon.outer = 0.08, 0.08
                self.grasp_client.send_goal(goal)
            else:
                rospy.loginfo("Trajectory Command: Opening Gripper...")
                goal = MoveGoal(width=0.08, speed=0.1)
                self.move_client.send_goal(goal)
            self.last_commanded_gripper = desired_state

    def visualize_warped_trajectory(self, mode_id, trajectory):
        """Generates a 3D plot of the newly warped trajectory segment."""
        pos = np.array(trajectory['pos'])
        
        fig = plt.figure(figsize=(8, 6))
        ax = fig.add_subplot(111, projection='3d')
        
        # Plot the trajectory
        ax.plot(pos[:, 0], pos[:, 1], pos[:, 2], 'b-', label=f'Mode {mode_id} Path')
        
        # Highlight the start point (where the robot snaps/aligns)
        ax.scatter(pos[self.traj_index, 0], pos[self.traj_index, 1], pos[self.traj_index, 2], 
                   color='red', s=50, label='Alignment Start')
        
        # Highlight keypoints if available (frozen ones used for the warp)
        if self.frozen_source_kps is not None:
            ax.scatter(self.frozen_source_kps[:, 0], self.frozen_source_kps[:, 1], self.frozen_source_kps[:, 2], 
                       color='green', marker='X', s=100, label='Source KPs')
        
        if self.frozen_source_kps is not None:
            ax.scatter(self.frozen_source_kps[:, 0], self.frozen_source_kps[:, 1], self.frozen_source_kps[:, 2], 
                       color='green', marker='X', s=100, label='Source KPs')
        
        if self.frozen_target_kps is not None:
            ax.scatter(self.frozen_target_kps[:, 0], self.frozen_target_kps[:, 1], self.frozen_target_kps[:, 2], 
                       color='orange', marker='^', s=100, label='Target KPs')
        
        ax.set_title(f"Warped Trajectory: {self.MODE_NAMES.get(mode_id)}")
        ax.set_xlabel('X (m)')
        ax.set_ylabel('Y (m)')
        ax.set_zlabel('Z (m)')
        ax.legend()
        
        # Save or show
        plot_filename = os.path.join(self.data_dir, f"latest_warp_mode_{mode_id}.png")
        plt.savefig(plot_filename)
        rospy.loginfo(f"  [Visualization] Plot saved to {plot_filename}")
        plt.close(fig) # Close to free memory

    def trigger_mode_switch(self, new_mode):
        """ Handles State Syncing, Asymmetric Latching, Dynamic Warping, and Path Alignment """
        rospy.loginfo(f">>> EVENT TRIGGERED: Switching to Mode {new_mode}")
        
        # --- 1. SYNC AUTOMATON & CONTROLLER STATE ---
        self.automaton.mode_id = new_mode
        self.automaton.current_mode = self.MODE_NAMES.get(new_mode, "UNKNOWN")
        
        self.active_mode = new_mode
        self.is_bridging = True
        self.lockout_counter = self.SENSOR_LOCKOUT_CYCLES

        # --- 2. ASYMMETRIC LATCHING ---
        if new_mode in [1, 2]: 
            if self.live_source_kps is not None:
                self.frozen_source_kps = self.live_source_kps.copy()
            if self.live_target_kps is not None:
                self.frozen_target_kps = self.live_target_kps.copy()
        
        elif new_mode in [3, 4, 5]:
            if self.live_target_kps is not None:
                self.frozen_target_kps = self.live_target_kps.copy()
                rospy.loginfo("As in mode 3/4/5, using old source keypoints for warping.")

        # --- 3. DYNAMIC WARPING ---
        if self.frozen_source_kps is not None and self.frozen_target_kps is not None:
            rospy.loginfo(f"  [Replanning] Warping Mode {new_mode} using latest perception...")
            
            warped_segment = self.warper.warp_mode(new_mode, self.frozen_source_kps, self.frozen_target_kps)
            
            if warped_segment is not None:
                self.traj_library[new_mode] = {
                    'pos': warped_segment['positions'],
                    'ori': warped_segment['orientations'],
                    'grip': warped_segment['gripper_states']
                }
                rospy.loginfo("  [Replanning] Success.")
            else:
                rospy.logerr(f"  [Replanning] Mode {new_mode} missing from demo!")
        else:
            rospy.logwarn("  [Replanning] Missing visual keypoints! Trajectory library not updated.")

        # --- 4. NEAREST POINT ALIGNMENT ---
        # Instead of starting at 0, find the index closest to our current physical position
        if new_mode in self.traj_library:
            if self.filter.pos is not None:
                new_path = np.array(self.traj_library[new_mode]['pos'])
                
                # Calculate Euclidean distance from current pos to ALL points in the new path
                distances = np.linalg.norm(new_path - self.filter.pos, axis=1)
                
                # Find the index with the minimum distance
                self.traj_index = int(np.argmin(distances))
                
                rospy.loginfo(f"  [Alignment] Snapped to nearest point: index {self.traj_index} / {len(new_path)}")
            else:
                # Fallback if filter.pos is None (e.g., at startup)
                self.traj_index = 0
                rospy.loginfo("  [Alignment] No physical pose yet, starting at index 0.")
        else:
            self.traj_index = 0

        # --- 5. VISUALIZATION ---
        if new_mode in self.traj_library:
             self.visualize_warped_trajectory(new_mode, self.traj_library[new_mode])

    def run(self):
        # Bootstrapping: Wait for initial vision data before starting
        rospy.loginfo("Waiting for initial camera keypoints...")
        while not rospy.is_shutdown() and (self.live_source_kps is None or self.live_target_kps is None):
            rospy.sleep(0.1)
            
        rospy.loginfo("Initial Vision acquired. Triggering startup warp...")
        self.trigger_mode_switch(1) # Warp initial Approach trajectory

        rate = rospy.Rate(self.control_rate)
        rospy.loginfo("Resilient Controller Running at 50Hz...")
        
        while not rospy.is_shutdown():
            
            traj_finished = False
            if (self.active_mode in self.traj_library) and (self.traj_index >= len(self.traj_library[self.active_mode]['pos']) - 1):
                proposed_mode = self.NEXT_MODE_MAP.get(self.active_mode, 1)
                rospy.loginfo("Trajectory Finished naturally.")
                self.trigger_mode_switch(proposed_mode)
                traj_finished = True

            # --- 1. SENSOR LOCKOUT CHECK ---
            elif self.lockout_counter > 0:
                self.lockout_counter -= 1
            else:
                # --- 2. LOGIC CHECKS (Only when unlocked) ---
                # Mid-trajectory safety check
                new_mode, _ = self.automaton.update(self.current_props)
                if new_mode != self.active_mode:

                    rospy.logwarn(f"Mid-Trajectory Safety Trigger! current_props: {self.current_props}")
                    self.trigger_mode_switch(new_mode)
        # while not rospy.is_shutdown():
            
            
            # # --- 1. SENSOR LOCKOUT CHECK ---
            # if self.lockout_counter > 0:
            #     self.lockout_counter -= 1
            # else:
            #     # --- 2. LOGIC CHECKS (Only when unlocked) ---
            #     traj_finished = False
            #     if self.active_mode in self.traj_library:
            #         if self.traj_index >= len(self.traj_library[self.active_mode]['pos']) - 1:
            #             traj_finished = True

            #     if traj_finished:
            #         # Trajectory ended naturally. Propose next mode.
            #         proposed_mode = self.NEXT_MODE_MAP.get(self.active_mode, 1)
            #         rospy.loginfo("Trajectory Finished naturally.")
            #         self.trigger_mode_switch(proposed_mode)
                
            #     else:
            #         # Mid-trajectory safety check
            #         new_mode, _ = self.automaton.update(self.current_props)
            #         if new_mode != self.active_mode:

            #             rospy.logwarn(f"Mid-Trajectory Safety Trigger! current_props: {self.current_props}")
            #             self.trigger_mode_switch(new_mode)

            # --- 3. EXECUTION ---
            if self.active_mode in self.traj_library:
                traj_data = self.traj_library[self.active_mode]
                
                target_p = traj_data['pos'][self.traj_index]
                target_q = traj_data['ori'][self.traj_index]
                desired_grip = traj_data['grip'][self.traj_index]
                
                self.process_gripper_command(desired_grip)
                
                if self.is_bridging:
                    current_alpha = self.BRIDGE_ALPHA
                    if self.filter.pos is not None:
                        dist_error = np.linalg.norm(np.array(target_p) - self.filter.pos)
                        if dist_error < self.BRIDGE_TOLERANCE:
                            rospy.loginfo("Bridge Done. Engaging Fast Mode.")
                            self.is_bridging = False
                else:
                    current_alpha = self.FAST_ALPHA
                    if self.traj_index < len(traj_data['pos']) - 1:
                        self.traj_index += 1
            else:
                # Safe fallback if library is empty
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