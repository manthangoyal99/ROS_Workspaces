#!/usr/bin/env python3

import rospy
import actionlib
from franka_gripper.msg import GraspAction, GraspGoal

def grasp_object_continuously():
    # 1. INITIALIZE NODE (Crucial!)
    rospy.init_node('franka_gripper_commander')

    client = actionlib.SimpleActionClient('/franka_gripper/grasp', GraspAction)
    print("Waiting for gripper action server...")
    client.wait_for_server()
    print("Connected to server.")

    goal = GraspGoal()
    # Target Width: 0.0 -> Try to close fully
    goal.width = 0.00
    
    # Epsilon: Huge tolerance so it succeeds even if it hits an object at 5cm
    goal.epsilon.inner = 0.08 
    goal.epsilon.outer = 0.08 
    
    goal.speed = 0.1
    goal.force = 30.0 
    
    print("Sending Grasp Goal...")
    # Send non-blocking
    client.send_goal(goal)
    
    print("Goal sent. Gripper should be closing.")

    # 2. KEEP SCRIPT ALIVE
    # Option A: If you just want to test the grasp, wait for the result:
    # client.wait_for_result()
    # print("Grasp finished:", client.get_result())

    # Option B (Your Use Case): Keep running to monitor the drop
    # We loop here so the node doesn't die.
    rate = rospy.Rate(10) # 10Hz
    while not rospy.is_shutdown():
        # You can add your "Drop Detection" logic here later
        rate.sleep()

if __name__ == "__main__":
    try:
        grasp_object_continuously()
    except rospy.ROSInterruptException:
        pass