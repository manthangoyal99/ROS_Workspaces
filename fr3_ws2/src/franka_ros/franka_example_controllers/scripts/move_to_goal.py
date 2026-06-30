#!/usr/bin/env python3

import rospy
from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import TwistStamped
import tf.transformations as tf

def main():
    rospy.init_node("cartesian_pose_msg_publisher")

    pose_pub = rospy.Publisher(
        "/cartesian_velocity_impedance_example_controller/equilibrium_pose",
        PoseStamped,
        queue_size=10
    )
    twist_pub = rospy.Publisher(
        "/cartesian_velocity_impedance_example_controller/equilibrium_twist",
        TwistStamped,
        queue_size=10
    )

    rate_hz = 50.0
    rate = rospy.Rate(rate_hz)

    # -------- Desired pose_msg pose (base frame) --------
    pose_msg = PoseStamped()
    pose_msg.header.frame_id = "panda_link0"

    # Position (meters)
    pose_msg.pose.position.x = 0.0
    pose_msg.pose.position.y = 0.0
    pose_msg.pose.position.z = 0.5

    # Orientation (quaternion)
    quat = tf.quaternion_from_euler(0.0, 3.14, 0.0)
    pose_msg.pose.orientation.x = 0
    pose_msg.pose.orientation.y = 1
    pose_msg.pose.orientation.z = 0
    pose_msg.pose.orientation.w = 0
    
    # -------- Desired Twist (Velocity) --------
    # Since this is a STATIC pose_msg (move to point and stop), 
    # the desired velocity (feedforward) is ZERO.
    twist_msg = TwistStamped()
    twist_msg.header.frame_id = "panda_link0"
    twist_msg.twist.linear.x = 0.0
    twist_msg.twist.linear.y = 0.0
    twist_msg.twist.linear.z = 4.0
    twist_msg.twist.angular.x = 0.0
    twist_msg.twist.angular.y = 0.0
    twist_msg.twist.angular.z = 0.0

    rospy.loginfo("Publishing constant Cartesian pose_msg...")

    while not rospy.is_shutdown():
        pose_msg.header.stamp = rospy.Time.now()
        twist_msg.header.stamp = rospy.Time.now()
        pose_pub.publish(pose_msg)
        twist_pub.publish(twist_msg)
        rate.sleep()

if __name__ == "__main__":
    main()

