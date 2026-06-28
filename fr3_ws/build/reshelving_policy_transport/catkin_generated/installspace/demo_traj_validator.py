#!/usr/bin/env python3
import rospy
import json
import os
import actionlib
from geometry_msgs.msg import PoseStamped
from franka_gripper.msg import GraspAction, GraspGoal, MoveAction, MoveGoal

class TrajectoryValidator:
    def __init__(self):
        rospy.init_node('trajectory_validator')
        
        # --- CONFIG ---
        self.data_dir = "/home/ravi/fr3_ws/src/reshelving_policy_transport/data"
        self.traj_file = os.path.join(self.data_dir, "demo_trajectory.json")
        
        # Publisher for the robot's Cartesian Goal
        # Note: Ensure your controller listens to this topic (e.g., equilibrium_pose)
        self.pose_pub = rospy.Publisher('/cartesian_impedance_example_controller/equilibrium_pose', PoseStamped, queue_size=1)
        
        # Gripper Clients
        self.grasp_client = actionlib.SimpleActionClient('/franka_gripper/grasp', GraspAction)
        self.move_client = actionlib.SimpleActionClient('/franka_gripper/move', MoveAction)
        
        self.load_trajectory()

    def load_trajectory(self):
        if not os.path.exists(self.traj_file):
            rospy.logerr("Trajectory file not found!")
            return
        with open(self.traj_file, 'r') as f:
            self.data = json.load(f)
        rospy.loginfo(f"Loaded {len(self.data['positions'])} points.")

    def play(self):
        rate = rospy.Rate(50) # Match the 50Hz recording
        prev_gripper_state = 0 # 0 for open, 1 for closed

        rospy.loginfo("Starting Replay in 3 seconds... Clear the robot area!")
        rospy.sleep(3.0)

        for i in range(len(self.data['positions'])):
            if rospy.is_shutdown(): break

            # 1. Create and Publish Pose
            pose = PoseStamped()
            pose.header.frame_id = "panda_link0"
            pose.header.stamp = rospy.Time.now()
            
            p = self.data['positions'][i]
            o = self.data['orientations'][i]
            
            pose.pose.position.x, pose.pose.position.y, pose.pose.position.z = p
            pose.pose.orientation.x, pose.pose.orientation.y, pose.pose.orientation.z, pose.pose.orientation.w = o
            
            self.pose_pub.publish(pose)

            # 2. Check for Gripper State Transitions
            curr_gripper_state = self.data['gripper_states'][i]
            
            if curr_gripper_state == 1 and prev_gripper_state == 0:
                rospy.loginfo("Event: Closing Gripper")
                # Send non-blocking grasp goal
                goal = GraspGoal(width=self.data['metadata'].get('object_width', 0.0), speed=0.1, force=50.0)
                goal.epsilon.inner = 0.08; goal.epsilon.outer = 0.08
                self.grasp_client.send_goal(goal)
                
            elif curr_gripper_state == 0 and prev_gripper_state == 1:
                rospy.loginfo("Event: Opening Gripper")
                self.move_client.send_goal(MoveGoal(width=0.08, speed=0.1))

            prev_gripper_state = curr_gripper_state
            rate.sleep()

        rospy.loginfo("Replay Finished.")

if __name__ == '__main__':
    validator = TrajectoryValidator()
    validator.play()
