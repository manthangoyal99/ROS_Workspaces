#!/usr/bin/env python3
import rospy
import tf
import json
import numpy as np
import os
from std_msgs.msg import Int8, Int8MultiArray, Float32MultiArray
from collections import deque

class ScoopingStateMonitor:
    def __init__(self):
        rospy.init_node('scooping_state_monitor')
        
        # --- CONFIGURATION ---
        self.base_frame = "panda_link0"
        self.ee_frame = "panda_EE"
        
        # Distance threshold (meters) for the ladle to be considered "Near" the bowls
        self.dist_thresh_s = 0.25 
        self.dist_thresh_t = 0.3    

        #A queue for applying temporal filtering to is_filled status, removing the noise 
        self.queue_size = 10
        self.spoon_status = deque(maxlen=self.queue_size)   
        self.fill_thresh = 0.1    

        # --- LOAD INITIAL KEYPOINTS (Fallback) ---
        self.data_dir = "/home/ravi/fr3_ws/src/scooping_adaptive/data"
        self.target_file = os.path.join(self.data_dir, "target_keypoints.json")
        
        self.keypoint_clusters = {
            'source': self.load_json_keypoints(self.target_file, is_target=False),
            'target': self.load_json_keypoints(self.target_file, is_target=True)
        }
        
        # --- INTERNAL STATE ---
        self.is_filled = 0  # Replaces gripper_width
        self.tf_listener = tf.TransformListener()
        
        # --- SUBSCRIBERS ---
        # 1. LIVE VISION FOR SPATIAL TRACKING (Bowls)
        rospy.Subscriber('/vision/live_source_kps', Float32MultiArray, self.cb_live_source)
        rospy.Subscriber('/vision/live_target_kps', Float32MultiArray, self.cb_live_target)
        
        # 2. YOLO PERCEPTION FOR GRAIN DETECTION
        rospy.Subscriber('/ladle_status', Int8, self.cb_ladle_status)
        
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
        
        if len(points) == 8:
            return points[4:] if is_target else points[:4]
        return points

    # --- CALLBACKS ---
    def cb_live_source(self, msg):
        """ Updates the grain bowl location in real-time """
        self.keypoint_clusters['source'] = np.array(msg.data).reshape(-1, 3)

    def cb_live_target(self, msg):
        """ Updates the empty target bowl location in real-time """
        self.keypoint_clusters['target'] = np.array(msg.data).reshape(-1, 3)

    def cb_ladle_status(self, msg):
        """ Updates based on YOLO Server response (1 = Full, 0 = Empty) """
        self.is_filled = msg.data

    # --- KINEMATICS & MATH ---
    def get_ee_position(self):
        try:
            (trans, rot) = self.tf_listener.lookupTransform(self.base_frame, self.ee_frame, rospy.Time(0))
            return np.array(trans)
        except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
            return None

    def check_proximity(self, ee_pos, cluster_points, point):
        """ Calculates distance from EE to the CENTROID of the cluster. """
        if ee_pos is None or len(cluster_points) == 0:
            return 0
            
        centroid = np.mean(cluster_points, axis=0)
        dist = np.linalg.norm(centroid - ee_pos)
        if point=="source":
            if dist < self.dist_thresh_s:
                return 1
        if point=="target":
            if dist < self.dist_thresh_t:
                return 1       
        return 0
    
    def check_filled(self):
        self.spoon_status.append(self.is_filled)
        spoon_mean = sum(self.spoon_status)/len(self.spoon_status)
        if(spoon_mean>self.fill_thresh):
            return 1
        return 0

    def run(self):
        rospy.loginfo("Scooping State Monitor running. Tracking spatial and YOLO topics.")
        
        while not rospy.is_shutdown():
            ee_pos = self.get_ee_position()
            
            if ee_pos is not None:
                # 1. Near Source (Grain Bowl)
                n = self.check_proximity(ee_pos, self.keypoint_clusters['source'],'source')
                
                # 2. Is Filled (From YOLO)
                f = self.check_filled()
                
                # 3. Near Target (Drop Bowl)
                t = self.check_proximity(ee_pos, self.keypoint_clusters['target'],'target')

                # Publish [Near Source, Is Filled, Near Target]
                msg = Int8MultiArray()
                msg.data = [n, f, t]
                self.pub_props.publish(msg)
            
            self.rate.sleep()

if __name__ == '__main__':
    try:
        monitor = ScoopingStateMonitor()
        monitor.run()
    except rospy.ROSInterruptException:
        pass    