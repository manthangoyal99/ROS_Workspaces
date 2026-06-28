#!/usr/bin/env python3
import rospy
import numpy as np
import csv
import os
import tf2_ros
# Use the tf2_geometry_msgs utility for easier point transformation
import tf2_geometry_msgs
from geometry_msgs.msg import PointStamped

def load_points_dict(filepath):
    """
    Load points as a dict: id -> np.array([x, y, z])
    """
    pts = {}
    if not os.path.exists(filepath):
        rospy.logerr(f"File not found: {filepath}")
        return pts
        
    with open(filepath, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            try:
                pid = int(row[0])
                pts[pid] = np.array([
                    float(row[1]),
                    float(row[2]),
                    float(row[3])
                ])
            except ValueError:
                continue
    return pts

def main():
    # 1. INIT NODE (CRITICAL!)
    rospy.init_node("calibration_validator")

    # 2. CONFIGURATION
    data_dir = "/home/ravi/fr3_ws/src/camera_calibration/data"
    # Ensure you are using the correct filenames
    camera_csv = os.path.join(data_dir, "camera_points_3d.csv") 
    robot_csv  = os.path.join(data_dir, "robo_3d_pose_validation.csv")

    rospy.loginfo("Loading data...")
    Pc = load_points_dict(camera_csv)
    Pb = load_points_dict(robot_csv)

    common_ids = sorted(set(Pc.keys()) & set(Pb.keys()))
    if not common_ids:
        rospy.logerr("No matching point IDs found between the two files!")
        return

    # 3. SETUP TF LISTENER
    tf_buffer = tf2_ros.Buffer()
    tf_listener = tf2_ros.TransformListener(tf_buffer)

    target_frame = "panda_link0"
    source_frame = "camera_base_color_optical_frame"

    rospy.loginfo(f"Waiting for transform: {target_frame} <-- {source_frame}")
    
    try:
        # LOOKUP DIRECTION:
        # We want to transform points FROM source (Camera) TO target (Base).
        # lookup_transform(target_frame, source_frame, ...)
        trans = tf_buffer.lookup_transform(
            target_frame, 
            source_frame, 
            rospy.Time(0), 
            rospy.Duration(5.0)
        )
    except Exception as e:
        rospy.logerr(f"TF Lookup Failed: {e}")
        return

    errors = []
    print(trans)
    print(f"\n{'ID':<5} | {'Measured (Base)':<25} | {'Predicted (Base)':<25} | {'Error (mm)':<10}")
    print("-" * 75)

    for pid in common_ids:
        # Raw point in Camera Frame
        pt_cam_np = Pc[pid]
        
        # Helper: Convert numpy -> PointStamped for TF2
        p_cam = PointStamped()
        p_cam.header.frame_id = source_frame
        p_cam.point.x = pt_cam_np[0]
        p_cam.point.y = pt_cam_np[1]
        p_cam.point.z = pt_cam_np[2]

        try:
            # 4. TRANSFORM POINT
            # This handles the Matrix multiplication automatically
            p_base = tf2_geometry_msgs.do_transform_point(p_cam, trans)
            
            # Extract result
            pt_pred_np = np.array([p_base.point.x, p_base.point.y, p_base.point.z])
            pt_true_np = Pb[pid]

            # Calculate Error
            err = np.linalg.norm(pt_pred_np - pt_true_np)
            errors.append(err)

            # Format for clean printing
            meas_str = f"[{pt_true_np[0]:.3f}, {pt_true_np[1]:.3f}, {pt_true_np[2]:.3f}]"
            pred_str = f"[{pt_pred_np[0]:.3f}, {pt_pred_np[1]:.3f}, {pt_pred_np[2]:.3f}]"
            
            print(f"{pid:<5} | {meas_str:<25} | {pred_str:<25} | {err*1000:.2f}")

        except Exception as e:
            rospy.logwarn(f"Point transformation failed for ID {pid}: {e}")

    # 5. STATISTICS
    if errors:
        errors = np.array(errors)
        rmse = np.sqrt(np.mean(errors**2))
        print("-" * 75)
        print(f"Summary over {len(errors)} points:")
        print(f"Mean Error : {np.mean(errors)*1000:.2f} mm")
        print(f"RMSE       : {rmse*1000:.2f} mm")
        print(f"Max Error  : {np.max(errors)*1000:.2f} mm")
        print(f"Std Dev    : {np.std(errors)*1000:.2f} mm")

if __name__ == "__main__":
    main()
