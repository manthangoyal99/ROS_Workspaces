#!/usr/bin/env python3
import rospy
import csv
import os
from geometry_msgs.msg import PoseStamped

class TrajectoryPublisher:
    def __init__(self):
        rospy.init_node('franka_csv_trajectory_publisher')
        
        # --- CONFIG ---
        self.data_dir = "/home/ravi/fr3_ws/src/reshelving_policy_transport/data"
        # Update this path if the CSV is located elsewhere
        self.traj_file = os.path.join(self.data_dir, "exp3b_trajectory.csv")
        
        # Publisher for the robot's Cartesian Goal
        self.pose_pub = rospy.Publisher('/cartesian_impedance_example_controller/equilibrium_pose', PoseStamped, queue_size=1)
        
        self.trajectory_data = []
        self.load_trajectory()

    def load_trajectory(self):
        if not os.path.exists(self.traj_file):
            rospy.logerr(f"Trajectory file not found: {self.traj_file}")
            return
        
        with open(self.traj_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.trajectory_data.append(row)
                
        rospy.loginfo(f"Loaded {len(self.trajectory_data)} points from CSV.")

    def play(self):
        if not self.trajectory_data:
            rospy.logerr("No trajectory data available to play.")
            return

        rate = rospy.Rate(500) # Match the 50Hz recording

        rospy.loginfo("Starting Replay in 3 seconds... Clear the robot area!")
        rospy.sleep(3.0)

        for point in self.trajectory_data:
            if rospy.is_shutdown(): 
                break

            # Create and Publish Pose
            pose = PoseStamped()
            pose.header.frame_id = "panda_link0"
            pose.header.stamp = rospy.Time.now()
            
            # Extract Positions
            pose.pose.position.x = float(point['x'])
            pose.pose.position.y = float(point['y'])
            pose.pose.position.z = float(point['z'])
            
            # Extract Orientations 
            pose.pose.orientation.x = float(point['qx'])
            pose.pose.orientation.y = float(point['qy'])
            pose.pose.orientation.z = float(point['qz'])
            pose.pose.orientation.w = float(point['qw'])
            
            self.pose_pub.publish(pose)
            rate.sleep()

        rospy.loginfo("Replay Finished.")

if __name__ == '__main__':
    try:
        publisher = TrajectoryPublisher()
        publisher.play()
    except rospy.ROSInterruptException:
        pass
