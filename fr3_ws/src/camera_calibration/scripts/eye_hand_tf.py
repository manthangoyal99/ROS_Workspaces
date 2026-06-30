#!/usr/bin/env python3
import rospy
import numpy as np
import csv
import os

import tf2_ros
from geometry_msgs.msg import TransformStamped
from tf.transformations import quaternion_from_matrix, quaternion_matrix, translation_matrix, concatenate_matrices, inverse_matrix

def load_points(csv_file):
    points = []
    with open(csv_file, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            points.append([int(row[0]), float(row[1]), float(row[2]), float(row[3])])
    return np.array(points)

def svd_rigid_transform(Pc, Pb):
    """ Returns T_base_optical (4x4 matrix) """
    assert Pc.shape == Pb.shape
    centroid_c = np.mean(Pc, axis=0)
    centroid_b = np.mean(Pb, axis=0)
    Pc_centered = Pc - centroid_c
    Pb_centered = Pb - centroid_b

    H = Pc_centered.T @ Pb_centered
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T

    if np.linalg.det(R) < 0:
        Vt[2, :] *= -1
        R = Vt.T @ U.T

    t = centroid_b - R @ centroid_c
    
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T

def main():
    rospy.init_node("eye_to_hand_tf_publisher")
    
    # --- 1. Compute Base -> Optical (Your existing logic) ---
    data_dir = "/home/ravi/fr3_ws/src/camera_calibration/data"
    camera_filepath = os.path.join(data_dir, "camera_points_3d.csv")
    robot_filepath  = os.path.join(data_dir, "robo_3d_pose.csv")

    Pc = load_points(camera_filepath)
    Pb = load_points(robot_filepath)

    Pb = Pb[Pb[:, 0].argsort()]
    id_match = np.where(np.isin(Pc[:, 0], Pb[:, 0]))[0]
    Pc = Pc[id_match, :]

    # This is T_base -> optical
    T_base_optical = svd_rigid_transform(Pc[:, 1:], Pb[:, 1:])
    rospy.loginfo(f"Computed Calibration (Base -> Optical):\n{T_base_optical}")

    # --- 2. Get Optical -> Link (The Correction) ---
    tf_buffer = tf2_ros.Buffer()
    tf_listener = tf2_ros.TransformListener(tf_buffer)
    
    # We need to know how the driver defines the relationship between the link (housing)
    # and the optical frame (lens).
    # NOTE: Ensure your realsense driver is running!
    rospy.loginfo("Waiting for Realsense TF (camera_link -> camera_color_optical_frame)...")
    try:
        # We look up Link -> Optical
        # Target: camera_link, Source: camera_color_optical_frame
        # This gives us the matrix to transform a point FROM Optical TO Link.
        trans_msg = tf_buffer.lookup_transform( 
            "camera_base_link", 
            "camera_base_color_optical_frame",
            rospy.Time(0), 
            rospy.Duration(10.0)
        )
        
        # Convert msg to Matrix
        q = trans_msg.transform.rotation
        t = trans_msg.transform.translation
        T_optical_to_link = concatenate_matrices(
            translation_matrix([t.x, t.y, t.z]),
            quaternion_matrix([q.x, q.y, q.z, q.w])
        )
        print("camera to optical matrix: \n", T_optical_to_link)
        rospy.loginfo("Found driver offset. Correcting transform...")

    except Exception as e:
        rospy.logerr(f"Could not find Realsense TF: {e}")
        rospy.logerr("Is the camera driver running? Cannot compute offset without it.")
        return

    # --- 3. Compute Base -> Link ---
    # T_base_link = T_base_optical * T_optical_link
    # We looked up T_link_optical (Link is parent, Optical is child in ROS tree usually)
    # But mathematically, we want to convert Optical Points to Link Points.
    # The lookup 'target=camera_link, source=optical' gives exactly that matrix: T_optical_to_link

    
    # MATRIX MULTIPLICATION
    T_link_to_optical = inverse_matrix(T_optical_to_link)
    T_base_link = np.dot(T_base_optical, T_link_to_optical)
    # T_base_link = np.dot(T_base_optical, T_optical_to_link)

    # --- 4. Publish Corrected TF ---
    broadcaster = tf2_ros.StaticTransformBroadcaster()
    tf_msg = TransformStamped()
    tf_msg.header.stamp = rospy.Time.now()
    tf_msg.header.frame_id = "panda_link0"
    tf_msg.child_frame_id  = "camera_base_link" 
    # tf_msg.header.frame_id = "panda_link0"
    # tf_msg.child_frame_id  = "camera_color_optical_frame" 

    t_final = T_base_link[:3, 3]
    q_final = quaternion_from_matrix(T_base_link)
    # t_final = T_base_optical[:3, 3]
    # q_final = quaternion_from_matrix(T_base_optical)
    tf_msg.transform.translation.x = t_final[0]
    tf_msg.transform.translation.y = t_final[1]
    tf_msg.transform.translation.z = t_final[2]
    tf_msg.transform.rotation.x = q_final[0]
    tf_msg.transform.rotation.y = q_final[1]
    tf_msg.transform.rotation.z = q_final[2]
    tf_msg.transform.rotation.w = q_final[3]

    broadcaster.sendTransform(tf_msg)
    rospy.loginfo("CORRECTED TF Published: panda_link0 -> camera_base_link")
    rospy.loginfo(f"Computed Calibration (Base -> Link):\n{T_base_link}")
    rospy.spin()

if __name__ == "__main__":
    main()

