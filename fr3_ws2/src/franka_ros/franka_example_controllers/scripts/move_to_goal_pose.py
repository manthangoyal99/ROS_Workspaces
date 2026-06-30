#!/usr/bin/env python3

import rospy
from geometry_msgs.msg import PoseStamped
import tf.transformations as tf

def main():
    rospy.init_node("cartesian_pose_msg_publisher")

    pose_pub = rospy.Publisher(
        "/cartesian_impedance_example_controller/equilibrium_pose",
        PoseStamped,
        queue_size=10
    )

    rate_hz = 50.0
    rate = rospy.Rate(rate_hz)

    # -------- Desired pose_msg pose (base frame) --------
    pose_msg = PoseStamped()
    pose_msg.header.frame_id = "panda_link0"

    # Position (meters)
    pose_msg.pose.position.x = 0.5
    pose_msg.pose.position.y = 0.5
    pose_msg.pose.position.z = 0.5

    # Orientation (quaternion)
    quat = tf.quaternion_from_euler(0.0, 3.14, 0.0)
    pose_msg.pose.orientation.x = 0
    pose_msg.pose.orientation.y = 1
    pose_msg.pose.orientation.z = 0
    pose_msg.pose.orientation.w = 0

    rospy.loginfo("Publishing constant Cartesian pose_msg...")

    while not rospy.is_shutdown():
        pose_msg.header.stamp = rospy.Time.now()
        pose_pub.publish(pose_msg)
        rate.sleep()

if __name__ == "__main__":
    main()

