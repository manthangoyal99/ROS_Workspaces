#!/usr/bin/env python3

import rospy
import pandas as pd
import os
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import Point

class CSVVisualizer:
    def __init__(self):
        rospy.init_node('csv_to_rviz_visualizer')

        # --- CONFIGURATION ---
        # Update this path to your actual CSV file location
        self.csv_path = "/home/ravi/fr3_ws/src/camera_calibration/data/camera_points_3d.csv"
        self.frame_id = "camera_color_optical_frame" # Use your camera's frame
        
        self.marker_pub = rospy.Publisher('/checkerboard_verification', MarkerArray, queue_size=1, latch=True)

        if not os.path.exists(self.csv_path):
            rospy.logerr(f"CSV file not found at: {self.csv_path}")
            return

        rospy.loginfo(f"Visualizing points from {self.csv_path}")
        self.publish_markers()
        rospy.spin()

    def publish_markers(self):
        df = pd.read_csv(self.csv_path)
        marker_array = MarkerArray()

        for i, row in df.iterrows():
            p_id = int(row['id'])
            pos = [row['x'], row['y'], row['z']]

            # 1. Sphere Marker for the Point
            sphere = Marker()
            sphere.header.frame_id = self.frame_id
            sphere.header.stamp = rospy.Time.now()
            sphere.ns = "points"
            sphere.id = p_id
            sphere.type = Marker.SPHERE
            sphere.action = Marker.ADD
            sphere.pose.position.x = pos[0]
            sphere.pose.position.y = pos[1]
            sphere.pose.position.z = pos[2]
            sphere.scale.x = 0.005  # 1cm diameter
            sphere.scale.y = 0.005
            sphere.scale.z = 0.005
            sphere.color.a = 1.0
            sphere.color.r = 0.0
            sphere.color.g = 1.0 # Green points
            sphere.color.b = 0.0
            marker_array.markers.append(sphere)

            # 2. Text Marker for the ID
            text = Marker()
            text.header.frame_id = self.frame_id
            text.header.stamp = rospy.Time.now()
            text.ns = "labels"
            text.id = p_id
            text.type = Marker.TEXT_VIEW_FACING
            text.action = Marker.ADD
            text.pose.position.x = pos[0]
            text.pose.position.y = pos[1]
            text.pose.position.z = pos[2] + 0.015 # Offset slightly
            text.scale.z = 0.01 # Text size 1cm
            text.color.a = 1.0
            text.color.r = 1.0
            text.color.g = 1.0
            text.color.b = 1.0
            text.text = str(p_id)
            marker_array.markers.append(text)

        self.marker_pub.publish(marker_array)
        rospy.loginfo(f"Published {len(df)} points to RViz.")

if __name__ == "__main__":
    CSVVisualizer()