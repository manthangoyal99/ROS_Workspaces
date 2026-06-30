#!/usr/bin/env python3
import rospy
import numpy as np
import tf.transformations as tr
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import Int8MultiArray, Float32MultiArray
import os

# Import your new classes
from task_automaton import CleaningAutomaton
from transported_traj import OnlineTrajectoryWarper 

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
        self.data_dir = "/home/ravi/fr3_ws/src/cleaning_adaptive/data"
        self.demo_path = os.path.join(self.data_dir, "cleaning_demo_trajectory.json") 
        self.demo_kp_path = os.path.join(self.data_dir, "cleaning_keypoints.json") 
        self.control_rate = 50.0 
        
        # --- TUNING ---
        self.BRIDGE_ALPHA = 0.01 
        self.FAST_ALPHA   = 0.50 
        self.BRIDGE_TOLERANCE = 0.03 
        self.SENSOR_LOCKOUT_CYCLES = 75 # 1.5 seconds of debounce at 50Hz
        self.EE_Z_OFFSET = 0.02

        # Mode Mapping for the Cleaning Task
        self.NEXT_MODE_MAP = {1: 2, 2: 3, 3: 1} # 0 is DONE
        self.MODE_NAMES = {3: "DONE", 1: "APPROACH", 2: "CLEAN"}

        # --- INITIALIZE WARPER ---
        self.warper = OnlineTrajectoryWarper(self.demo_path, self.demo_kp_path)
        self.traj_library = {} 
        
        # --- PERCEPTION BUFFERS ---
        self.live_mesh_kps = None
        self.frozen_mesh_kps = None

        # Only one vision topic needed for cleaning!
        rospy.Subscriber('/vision/live_target_kps', Float32MultiArray, self.cb_live_mesh)
        
        # --- SETUP AUTOMATON & ROBOT PUB ---
        self.automaton = CleaningAutomaton()
        self.current_props = [0, 0] # [is_near_mesh, mesh_exists]
        rospy.Subscriber('/task/atomic_propositions', Int8MultiArray, self.cb_props)
        self.pub_pose = rospy.Publisher('/cartesian_impedance_example_controller/equilibrium_pose', PoseStamped, queue_size=1)
        
        # --- STATE ---
        self.filter = LowPassFilter()
        self.active_mode = 1 
        self.traj_index = 0
        self.is_bridging = False 
        self.lockout_counter = 0

    def cb_props(self, msg):
        self.current_props = list(msg.data)
        
    def cb_live_mesh(self, msg):
        if self.active_mode == 2:
            return
        self.live_mesh_kps = np.array(msg.data).reshape(-1, 3)

    def trigger_mode_switch(self, new_mode):
        """ Handles State Syncing, Dynamic Warping, and Path Alignment """
        rospy.loginfo(f">>> EVENT TRIGGERED: Switching to Mode {new_mode} ({self.MODE_NAMES.get(new_mode, 'UNKNOWN')})")
        
        # --- 1. SYNC AUTOMATON & CONTROLLER STATE ---
        self.automaton.mode_id = new_mode
        self.automaton.current_mode = self.MODE_NAMES.get(new_mode, "UNKNOWN")
        
        self.active_mode = new_mode
        self.is_bridging = True
        self.lockout_counter = self.SENSOR_LOCKOUT_CYCLES

        if new_mode == 0:
            rospy.loginfo("Task Complete. Robot holding position.")
            return

        # --- 2. PERCEPTION LATCHING ---
        # Freeze the camera points so the trajectory doesn't warp mid-motion
        if self.live_mesh_kps is not None:
            self.frozen_mesh_kps = self.live_mesh_kps.copy()

        # --- 3. DYNAMIC WARPING ---
        if self.frozen_mesh_kps is not None:
            rospy.loginfo(f"  [Replanning] Warping Mode {new_mode} using latest 16-point mesh...")
            
            # Pass the mode and the frozen 16-point grid to the warper
            warped_segment = self.warper.warp_mode(new_mode, self.frozen_mesh_kps)
            
            if warped_segment is not None:
                self.traj_library[new_mode] = {
                    'pos': warped_segment['positions'],
                    'ori': warped_segment['orientations']
                }
                rospy.loginfo("  [Replanning] Success.")
            else:
                rospy.logerr(f"  [Replanning] Mode {new_mode} missing from demo!")
        else:
            rospy.logwarn("  [Replanning] Missing visual keypoints! Trajectory library not updated.")

        # --- 4. NEAREST POINT ALIGNMENT ---
        if new_mode in self.traj_library:
            if self.filter.pos is not None:
                new_path = np.array(self.traj_library[new_mode]['pos'])
                distances = np.linalg.norm(new_path - self.filter.pos, axis=1)
                self.traj_index = int(np.argmin(distances))
                rospy.loginfo(f"  [Alignment] Snapped to nearest point: index {self.traj_index} / {len(new_path)}")
            else:
                self.traj_index = 0
        else:
            self.traj_index = 0

    def run(self):
        # Bootstrapping: Wait for initial vision data before starting
        rospy.loginfo("Waiting for initial camera keypoints...")
        while not rospy.is_shutdown() and self.live_mesh_kps is None:
            rospy.sleep(0.1)
            
        rospy.loginfo("Initial Vision acquired. Triggering startup warp...")
        self.trigger_mode_switch(1) # Start with Approach

        rate = rospy.Rate(self.control_rate)
        rospy.loginfo("Resilient Controller Running at 50Hz...")
        
        while not rospy.is_shutdown():
            
            # --- 0. DONE STATE HANDLING ---
            if self.active_mode == 0:
                # Keep publishing the last known position to hold the robot still
                self.publish_current_pose(rate)
                continue

            # --- 1. TRAJECTORY END CHECK ---
            traj_finished = False
            if (self.active_mode in self.traj_library) and (self.traj_index >= len(self.traj_library[self.active_mode]['pos']) - 1):
                
                # If we finish wiping (Mode 2), strictly push to Retreat (Mode 3)
                if self.active_mode == 2:
                    proposed_mode = 3
                # If we finish retreating (Mode 3), let the Automaton decide if we are Done (0) or Retry (1)
                elif self.active_mode == 3:
                    proposed_mode, _ = self.automaton.update(self.current_props)
                else:
                    proposed_mode = self.NEXT_MODE_MAP.get(self.active_mode, 1)
                    
                rospy.loginfo(f"Mode {self.active_mode} finished. Transitioning...")
                self.trigger_mode_switch(proposed_mode)
                traj_finished = True

            # --- 2. SENSOR LOCKOUT & MID-TRAJECTORY CHECKS ---
            if not traj_finished:
                if self.lockout_counter > 0:
                    self.lockout_counter -= 1
                else:
                    # Let the Automaton monitor the props (e.g., if is_near_mesh triggers early)
                    new_mode, _ = self.automaton.update(self.current_props)
                    if new_mode != self.active_mode:
                        rospy.logwarn(f"Mid-Trajectory Safety Trigger! Props: {self.current_props}")
                        self.trigger_mode_switch(new_mode)

            # --- 3. EXECUTION LOGIC ---
            if self.active_mode in self.traj_library:
                traj_data = self.traj_library[self.active_mode]
                
                # Cast to numpy arrays for vector math
                target_p = np.array(traj_data['pos'][self.traj_index])
                target_q = np.array(traj_data['ori'][self.traj_index])
                
                # --- APPLY LOCAL Z-OFFSET (ONLY DURING CLEANING) ---
                if self.active_mode == 2: # 2 is "CLEAN"
                    # 1. Convert quaternion to a 3x3 rotation matrix
                    rot_mat = tr.quaternion_matrix(target_q)[:3, :3]
                    
                    # 2. Define offset in local tool frame [x, y, z]
                    # Note: If your tool's Z-axis points OUT to the table, this is positive. 
                    # If it points IN towards the wrist, make this negative (-self.EE_Z_OFFSET)
                    local_offset = np.array([0.0, 0.0, self.EE_Z_OFFSET])
                    
                    # 3. Rotate offset into the global (panda_link0) frame
                    global_offset = np.dot(rot_mat, local_offset)
                    
                    # 4. Push the target position deeper
                    target_p = target_p + global_offset
                # ---------------------------------------------------

                if self.is_bridging:
                    current_alpha = self.BRIDGE_ALPHA
                    if self.filter.pos is not None:
                        dist_error = np.linalg.norm(target_p - self.filter.pos)
                        if dist_error < self.BRIDGE_TOLERANCE:
                            rospy.loginfo("Bridge Done. Engaging Fast Tracking.")
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

    def publish_current_pose(self, rate):
        """ Helper to hold position when task is done """
        if self.filter.pos is not None:
            msg = PoseStamped()
            msg.header.stamp = rospy.Time.now()
            msg.header.frame_id = "panda_link0"
            msg.pose.position.x = self.filter.pos[0]
            msg.pose.position.y = self.filter.pos[1]
            msg.pose.position.z = self.filter.pos[2]
            msg.pose.orientation.x = self.filter.quat[0]
            msg.pose.orientation.y = self.filter.quat[1]
            msg.pose.orientation.z = self.filter.quat[2]
            msg.pose.orientation.w = self.filter.quat[3]
            self.pub_pose.publish(msg)
        rate.sleep()

if __name__ == '__main__':
    try:
        ResilientController().run()
    except rospy.ROSInterruptException:
        pass