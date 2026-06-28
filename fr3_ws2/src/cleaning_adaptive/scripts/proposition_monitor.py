#!/usr/bin/env python3
import rospy
import tf
import numpy as np
import json
import os
import sys
import argparse
from std_msgs.msg import Int8MultiArray, Float32MultiArray

class CleaningStateMonitor:
    def __init__(self, mode):
        rospy.init_node('cleaning_state_monitor')
        
        self.mode = mode
        
        # --- CONFIGURATION ---
        self.base_frame = "panda_link0"
        self.ee_frame = "panda_EE"
        self.dist_thresh = 0.15#15cm from the CLOSEST point
        self.vision_timeout = 0.5    
        
        self.DATA_DIR = "/home/ravi/fr3_ws/src/cleaning_adaptive/data"
        self.keypoints_file = os.path.join(self.DATA_DIR, "cleaning_keypoints.json")
        
        # --- INTERNAL STATE ---
        self.tf_listener = tf.TransformListener()
        self.mesh_points = None      # Changed from centroid to hold the full array
        self.last_mesh_time = rospy.Time(0)
        
        # --- MODE SETUP ---
        if self.mode == "live":
            rospy.loginfo("Mode: LIVE. Subscribing to /vision/live_target_kps...")
            rospy.Subscriber('/vision/live_target_kps', Float32MultiArray, self.cb_live_mesh)
        elif self.mode == "source":
            rospy.loginfo(f"Mode: SOURCE. Loading static keypoints from {self.keypoints_file}...")
            self.load_source_keypoints()
            
        # --- PUBLISHERS ---
        self.pub_props = rospy.Publisher('/task/atomic_propositions', Int8MultiArray, queue_size=10)
        self.rate = rospy.Rate(50) 

    def load_source_keypoints(self):
        """ Reads the JSON file and loads all static points for the Demo Phase """
        try:
            with open(self.keypoints_file, 'r') as f:
                data = json.load(f)
            
            # Extract the [x, y, z] coordinates from the JSON structure
            pts = [kp['coords'] for kp in data['keypoints']]
            self.mesh_points = np.array(pts)
            
            rospy.loginfo(f"SUCCESS: Loaded {len(self.mesh_points)} static keypoints.")
            
        except Exception as e:
            rospy.logerr(f"Failed to load source keypoints! Make sure you saved them first. Error: {e}")
            rospy.signal_shutdown("Missing Source File")

    def cb_live_mesh(self, msg):
        """ Processes the incoming 16-point grid from the RealSense (Live Phase Only) """
        points = np.array(msg.data).reshape(-1, 3)
        if len(points) > 0:
            self.mesh_points = points
            self.last_mesh_time = rospy.Time.now()

    def get_ee_position(self):
        try:
            (trans, rot) = self.tf_listener.lookupTransform(self.base_frame, self.ee_frame, rospy.Time(0))
            return np.array(trans)
        except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
            return None

    def run(self):
        while not rospy.is_shutdown():
            ee_pos = self.get_ee_position()
            
            is_near_mesh = 0
            mesh_exists = 0

            # --- 1. EVALUATE EXISTENCE ---
            if self.mode == "source":
                mesh_exists = 1 
            elif self.mode == "live":
                if (rospy.Time.now() - self.last_mesh_time).to_sec() < self.vision_timeout:
                    mesh_exists = 1

            # --- 2. EVALUATE PROXIMITY (Minimum Distance) ---
            if mesh_exists == 1 and ee_pos is not None and self.mesh_points is not None:
                # Calculate Euclidean distance from EE to EVERY point in the mesh simultaneously
                # self.mesh_points is shape (N, 3), ee_pos is shape (3,)
                # axis=1 computes the norm along the rows
                distances = np.linalg.norm(self.mesh_points - ee_pos, axis=1)
                
                # Get the shortest distance
                min_dist = np.min(distances)
                
                if min_dist < self.dist_thresh:
                    is_near_mesh = 1

            # --- 3. PUBLISH ---
            msg = Int8MultiArray()
            msg.data = [is_near_mesh, mesh_exists]
            self.pub_props.publish(msg)
            
            self.rate.sleep()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Cleaning State Monitor")
    parser.add_argument('--mode', type=str, default='live', choices=['live', 'source'],
                        help="Set to 'source' for recording demo, 'live' for autonomous execution.")
    
    args = parser.parse_args(rospy.myargv(argv=sys.argv)[1:])
    
    try:
        monitor = CleaningStateMonitor(mode=args.mode)
        monitor.run()
    except rospy.ROSInterruptException:
        pass