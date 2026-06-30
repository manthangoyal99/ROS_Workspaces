#!/usr/bin/env python3
import rospy
import tf
import json
import numpy as np
import os
from sensor_msgs.msg import JointState
from std_msgs.msg import Int8MultiArray

class AtomicStateMonitor:
    def __init__(self):
        rospy.init_node('atomic_state_monitor')
        
        # --- CONFIGURATION ---
        self.base_frame = "panda_link0"  # The frame your JSON points are defined in
        self.ee_frame = "panda_EE"    # The frame we are tracking (Robot Hand)
        
        # Thresholds (meters)
        self.dist_thresh = 0.20        # 10cm: Trigger "Near" if within 10cm of any corner
        self.width_grasped_thresh = 0.058  # 4.4cm: Max width to be considered grasped
        self.width_drop_thresh = 0.042     # 1cm: Min width to prevent "empty closed gripper" being grasped
        # --- 1. LOAD KEYPOINTS FROM JSON ---
        # We assume the JSON is in the same folder or provide full path
        self.data_dir = "/home/ravi/fr3_ws/src/reshelving_gpr_ltl/data"
        # self.traj_file = os.path.join(self.data_dir, "source_keypoints.json")
        self.traj_file = os.path.join(self.data_dir, "target_keypoints.json")
        self.keypoint_clusters = self.load_keypoints(self.traj_file)
        
        # --- INTERNAL STATE ---
        self.gripper_width = 0.08
        self.tf_listener = tf.TransformListener()
        
        # --- SUBSCRIBERS ---
        rospy.Subscriber('/franka_gripper/joint_states', JointState, self.cb_gripper)
        
        # --- PUBLISHERS ---
        # Data: [is_near_source, is_near_target, is_grasped]
        self.pub_props = rospy.Publisher('/task/atomic_propositions', Int8MultiArray, queue_size=10)
        
        self.rate = rospy.Rate(50) # 50Hz

    def load_keypoints(self, filename):
        """ 
        Parses the JSON. 
        First 4 points -> Source Cluster (Bowl/Box)
        Last 4 points  -> Target Cluster (Shelf/Place)
        """
        if not os.path.exists(filename):
            rospy.logerr(f"Keypoints file not found: {filename}")
            return {'source': [], 'target': []}

        with open(filename, 'r') as f:
            data = json.load(f)
        
        # Extract the raw [x, y, z] coordinates from the list
        all_points = [kp['coords'] for kp in data['keypoints']]
        
        # Convert to numpy array for fast distance math
        points_np = np.array(all_points)
        
        if len(points_np) < 8:
            rospy.logwarn("JSON contains fewer than 8 points! Check your file.")
        
        # Split according to your logic:
        # First 4 = Source (Object), Last 4 = Target
        return {
            'source': points_np[:4], 
            'target': points_np[4:]
        }

    def cb_gripper(self, msg):
        # Sum of finger positions = total width
        self.gripper_width = sum(msg.position)

    def get_ee_position(self):
        """ Get current [x,y,z] of End Effector in Base Frame """
        try:
            (trans, rot) = self.tf_listener.lookupTransform(self.base_frame, self.ee_frame, rospy.Time(0))
            return np.array(trans)
        except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
            return None

    def check_proximity(self, ee_pos, cluster_points):
        """ 
        Returns 1 if EE is within threshold of ANY point in the cluster.
        Using Euclidean distance.
        """
        if ee_pos is None or len(cluster_points) == 0:
            return 0
            
        # Vectorized distance calculation:
        # Calculate dist from EE to ALL 4 corners at once
        dists = np.linalg.norm(cluster_points - ee_pos, axis=1)
        
        # If the minimum distance is less than threshold, we are "Near"
        min_dist = np.min(dists)
        
        if min_dist < self.dist_thresh:
            return 1
        return 0

    def run(self):
        rospy.loginfo(f"Monitor running. Loaded {len(self.keypoint_clusters['source'])} source and {len(self.keypoint_clusters['target'])} target points.")
        
        while not rospy.is_shutdown():
            # 1. Get Robot Position
            ee_pos = self.get_ee_position()
            
            if ee_pos is not None:
                # 2. Check Proximity to JSON Clusters
                # Prop 1: Near Source (Bowl/Box)
                n = self.check_proximity(ee_pos, self.keypoint_clusters['source'])
                
                # Prop 2: Is Grasped (g)
                # Logic: Width < 5.5cm AND Width > 1cm
                g = 1 if (self.gripper_width < self.width_grasped_thresh and 
                          self.gripper_width > self.width_drop_thresh) else 0
                
                # Prop 3: Near Target (Shelf)
                t = self.check_proximity(ee_pos, self.keypoint_clusters['target'])

                # 3. Publish
                msg = Int8MultiArray()
                msg.data = [n, g, t]
                self.pub_props.publish(msg)
                
                # Debug info to verify it's working
                # print(f"NearSrc: {n} | NearTgt: {t} | Grasped: {g} | Width: {self.gripper_width:.3f}")
            
            self.rate.sleep()

if __name__ == '__main__':
    try:
        monitor = AtomicStateMonitor()
        monitor.run()
    except rospy.ROSInterruptException:
        pass
