#!/usr/bin/env python3
import rospy
import json
import os
from geometry_msgs.msg import PoseStamped

class TrajectoryValidator:
    def __init__(self):
        rospy.init_node('go_go_good_robot')
        
        # --- CONFIG ---
        self.data_dir = "/home/ravi/fr3_ws/src/cleaning_adaptive/data"
        self.traj_file = os.path.join(self.data_dir, "warped_trajectory.json")
        
        # Publisher for the robot's Cartesian Goal
        self.pose_pub = rospy.Publisher('/cartesian_impedance_example_controller/equilibrium_pose', PoseStamped, queue_size=1)
        
        self.load_trajectory()

    def load_trajectory(self):
        if not os.path.exists(self.traj_file):
            rospy.logerr("Trajectory file not found!")
            return
        with open(self.traj_file, 'r') as f:
            self.data = json.load(f)
        rospy.loginfo(f"Loaded {len(self.data['positions'])} points.")

    def play(self):
        rate = rospy.Rate(50)  # Match the 50Hz recording

        rospy.loginfo("Starting Replay in 3 seconds... Clear the robot area!")
        rospy.sleep(3.0)

        for i in range(len(self.data['positions'])):
            if rospy.is_shutdown():
                break

            pose = PoseStamped()
            pose.header.frame_id = "panda_link0"
            pose.header.stamp = rospy.Time.now()
            
            p = self.data['positions'][i]
            o = self.data['orientations'][i]
            
            pose.pose.position.x, pose.pose.position.y, pose.pose.position.z = p
            pose.pose.orientation.x, pose.pose.orientation.y, pose.pose.orientation.z, pose.pose.orientation.w = o
            
            self.pose_pub.publish(pose)
            rate.sleep()

        rospy.loginfo("Replay Finished.")

if __name__ == '__main__':
    validator = TrajectoryValidator()
    validator.play()