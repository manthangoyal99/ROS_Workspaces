#!/usr/bin/env python3
import rospy
import cv2
import numpy as np
import csv
import os
import message_filters
from sensor_msgs.msg import Image, CameraInfo
from cv_bridge import CvBridge, CvBridgeError
from image_geometry import PinholeCameraModel

# --- CONFIGURATION ---
CHECKERBOARD_DIMS = (4, 6)   # (rows, columns) of INNER corners
SAVE_FILENAME = "camera_points_3d.csv"
SAVE_DIR = "/home/ravi/fr3_ws/src/camera_calibration/data"
# ---------------------

class ChessboardCollector:
    def __init__(self):
        self.node_name = "chessboard_collector"
        rospy.init_node(self.node_name)

        self.bridge = CvBridge()
        self.camera_model = PinholeCameraModel()
        self.camera_info_received = False
        
        # Subscribe to Camera Info (only need once)
        self.info_sub = rospy.Subscriber(
            "/camera_base/color/camera_info", 
            CameraInfo, 
            self.info_callback
        )

        # Synchronized Subscriber for Aligned Depth and Color
        # We use ApproximateTime because hardware timestamps might drift slightly
        self.color_sub = message_filters.Subscriber("/camera_base/color/image_raw", Image)
        self.depth_sub = message_filters.Subscriber("/camera_base/aligned_depth_to_color/image_raw", Image)
        
        self.ts = message_filters.ApproximateTimeSynchronizer(
            [self.color_sub, self.depth_sub], queue_size=10, slop=0.1
        )
        self.ts.registerCallback(self.image_callback)

        rospy.loginfo("Waiting for camera info and images...")

    def info_callback(self, info_msg):
        if not self.camera_info_received:
            self.camera_model.fromCameraInfo(info_msg)
            self.camera_info_received = True
            rospy.loginfo(f"Camera Intrinsics Loaded! Frame ID: {info_msg.header.frame_id}")
            # We can unregister after getting info to save bandwidth, 
            # but keeping it is fine for simple scripts.
            self.info_sub.unregister()

    def get_depth_robust(self, depth_img, u, v):
        """ Get median depth from 3x3 neighborhood """
        height, width = depth_img.shape
        u, v = int(u), int(v)
        
        # Bounds check
        if u < 1 or u >= width - 1 or v < 1 or v >= height - 1:
            return None

        # Extract 3x3 window
        # window = depth_img[v-1:v+2, u-1:u+2]
        window = depth_img[v-2:v+3, u-2:u+3]
        valid_pixels = window[window > 0]

        if len(valid_pixels) == 0:
            return None
        
        # Return median depth in meters (ROS depth is usually mm)
        return np.median(valid_pixels) / 1000.0

    def save_to_csv(self, points):
        os.makedirs(SAVE_DIR, exist_ok=True)
        filepath = os.path.join(SAVE_DIR, SAVE_FILENAME)
        
        with open(filepath, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["id", "x", "y", "z"])
            for p in points:
                writer.writerow(p)
        rospy.loginfo(f"Saved {len(points)} points to {filepath}")

    def image_callback(self, color_msg, depth_msg):
        if not self.camera_info_received:
            return

        try:
            # Convert ROS messages to OpenCV
            cv_image = self.bridge.imgmsg_to_cv2(color_msg, "bgr8")
            depth_image = self.bridge.imgmsg_to_cv2(depth_msg, "16UC1")
        except CvBridgeError as e:
            rospy.logerr(e)
            return

        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        
        # Find Checkerboard
        flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE + cv2.CALIB_CB_FAST_CHECK
        ret, corners = cv2.findChessboardCornersSB(gray, CHECKERBOARD_DIMS, None)

        if ret:
            # Subpixel refinement
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners_subpix = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            
            cv2.drawChessboardCorners(cv_image, CHECKERBOARD_DIMS, corners_subpix, ret)
            
            points_3d = []
            valid_frame = True

            for i, corner in enumerate(corners_subpix):
                u, v = corner.ravel()
                
                z = self.get_depth_robust(depth_image, u, v)
                
                if z is None:
                    valid_frame = False
                    cv2.circle(cv_image, (int(u), int(v)), 5, (0,0,255), -1)
                    continue

                # Project Pixel to 3D Ray (Unit Vector) -> Scale by Z
                # PinholeCameraModel handles the K matrix automatically
                ray = self.camera_model.projectPixelTo3dRay((u, v))
                x = ray[0] * z
                y = ray[1] * z
                
                points_3d.append([i, x, y, z])
                
                # Draw ID
                cv2.putText(cv_image, str(i), (int(u)+5, int(v)-5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # UI Logic
            if valid_frame:
                cv2.putText(cv_image, "Press 's' to SAVE", (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            else:
                cv2.putText(cv_image, "INVALID DEPTH", (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

            cv2.imshow("ROS Calibration", cv_image)
            key = cv2.waitKey(1)

            if key == ord('s') and valid_frame:
                self.save_to_csv(points_3d)
                rospy.signal_shutdown("Saved and exiting")
            elif key == ord('q'):
                rospy.signal_shutdown("User quit")

        else:
            cv2.imshow("ROS Calibration", cv_image)
            cv2.waitKey(1)

if __name__ == "__main__":
    try:
        collector = ChessboardCollector()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
    finally:
        cv2.destroyAllWindows()

