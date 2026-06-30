#!/usr/bin/env python3
import rospy
import tf
import json
import numpy as np
import os
from sensor_msgs.msg import JointState
from std_msgs.msg import Int8MultiArray, Float32MultiArray

class AtomicStateMonitor:
    def __init__(self):
        rospy.init_node('atomic_state_monitor')
        
        # --- CONFIGURATION ---
        self.base_frame = "panda_link0"
        self.ee_frame = "panda_EE"
        
        # Thresholds (meters)
        self.dist_thresh = 0.20            # 20cm: Trigger "Near"
        #The thresholds are for the bottle
        # self.width_grasped_thresh = 0.044  # 4.4cm: Max width to be considered grasped
        # self.width_drop_thresh = 0.010     # 1cm: Min width to prevent "empty closed gripper" being grasped
        
        #The thresholds are for the box
        self.width_grasped_thresh = 0.065  # 4.4cm: Max width to be considered grasped
        self.width_drop_thresh = 0.042     # 1cm: Min width to prevent "empty closed gripper" being grasped

        # --- 1. LOAD INITIAL KEYPOINTS (Fallback) ---
        self.data_dir = "/home/ravi/fr3_ws/src/reshelving_adaptive/data"
        # self.source_file = os.path.join(self.data_dir, "source_keypoints.json")
        self.target_file = os.path.join(self.data_dir, "target_keypoints.json")
        
        self.keypoint_clusters = {
            'source': self.load_json_keypoints(self.target_file, is_target=False),
            'target': self.load_json_keypoints(self.target_file, is_target=True)
        }
        
        # --- INTERNAL STATE ---
        self.gripper_width = 0.08
        self.tf_listener = tf.TransformListener()
        
        # --- SUBSCRIBERS ---
        rospy.Subscriber('/franka_gripper/joint_states', JointState, self.cb_gripper)
        
        # LIVE VISION SUBSCRIPTIONS
        rospy.Subscriber('/vision/live_source_kps', Float32MultiArray, self.cb_live_source)
        rospy.Subscriber('/vision/live_target_kps', Float32MultiArray, self.cb_live_target)
        
        # --- PUBLISHERS ---
        self.pub_props = rospy.Publisher('/task/atomic_propositions', Int8MultiArray, queue_size=10)
        self.rate = rospy.Rate(50) 

    def load_json_keypoints(self, filename, is_target=False):
        """ Fallback loader for initial state """
        if not os.path.exists(filename):
            rospy.logwarn(f"Monitor: File not found {filename}")
            return np.array([])
        with open(filename, 'r') as f:
            data = json.load(f)
        
        points = np.array([kp['coords'] for kp in data['keypoints']])
        
        # If the file has 8 points (like target usually does), split it appropriately
        if len(points) == 8:
            return points[4:] if is_target else points[:4]
        return points

    # --- LIVE VISION CALLBACKS ---
    def cb_live_source(self, msg):
        """ Updates the object location in real-time """
        self.keypoint_clusters['source'] = np.array(msg.data).reshape(-1, 3)

    def cb_live_target(self, msg):
        """ Updates the shelf location in real-time """
        self.keypoint_clusters['target'] = np.array(msg.data).reshape(-1, 3)

    def cb_gripper(self, msg):
        self.gripper_width = sum(msg.position)

    def get_ee_position(self):
        try:
            (trans, rot) = self.tf_listener.lookupTransform(self.base_frame, self.ee_frame, rospy.Time(0))
            return np.array(trans)
        except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
            return None

    def check_proximity(self, ee_pos, cluster_points):
        """ 
        Calculates distance from EE to the CENTROID of the cluster.
        """
        if ee_pos is None or len(cluster_points) == 0:
            return 0
            
        # Calculate the center of the 4 ArUco virtual corners
        centroid = np.mean(cluster_points, axis=0)
        dist = np.linalg.norm(centroid - ee_pos)
        
        if dist < self.dist_thresh:
            return 1
        return 0

    def run(self):
        rospy.loginfo("Atomic State Monitor running (Tracking LIVE topics).")
        
        while not rospy.is_shutdown():
            ee_pos = self.get_ee_position()
            
            if ee_pos is not None:
                # 1. Near Source (Bowl/Box)
                n = self.check_proximity(ee_pos, self.keypoint_clusters['source'])
                
                # 2. Is Grasped (g)
                g = 1 if (self.gripper_width < self.width_grasped_thresh and 
                          self.gripper_width > self.width_drop_thresh) else 0
                
                # 3. Near Target (Shelf)
                t = self.check_proximity(ee_pos, self.keypoint_clusters['target'])

                # Publish
                msg = Int8MultiArray()
                msg.data = [n, g, t]
                self.pub_props.publish(msg)
            
            self.rate.sleep()

if __name__ == '__main__':
    try:
        monitor = AtomicStateMonitor()
        monitor.run()
    except rospy.ROSInterruptException:
        pass