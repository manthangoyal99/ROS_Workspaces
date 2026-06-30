#!/usr/bin/env python3
import rospy
import cv2
import cv2.aruco as aruco
import numpy as np
import tf2_ros
import tf2_geometry_msgs
import message_filters
from sensor_msgs.msg import Image, CameraInfo
from geometry_msgs.msg import PointStamped
from cv_bridge import CvBridge, CvBridgeError
from image_geometry import PinholeCameraModel
import json
import os

class KeypointLoggerRGBD:
    def __init__(self):
        rospy.init_node('aruco_keypoint_logger_rgbd', anonymous=True)

        # --- CONFIGURATION ---
        self.object_marker_id = 0  
        self.shelf_marker_id = 2    
        self.camera_frame = "camera_color_optical_frame"
        self.base_frame = "panda_link0"
        self.SAVE_DIR = "/home/ravi/fr3_ws/src/reshelving_adaptive/data"
        os.makedirs(self.SAVE_DIR, exist_ok=True)
        # Note: self.marker_size is completely gone! We don't need it anymore.

        # --- SUBSCRIBERS ---
        self.bridge = CvBridge()
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.camera_model = PinholeCameraModel()
        
        # Subscribe to camera info once
        self.cam_info_sub = rospy.Subscriber("/camera_base/color/camera_info", CameraInfo, self.info_callback)
        self.camera_info_received = False
        
        # Synchronized RGB and Aligned Depth Subscribers
        self.color_sub = message_filters.Subscriber("/camera_base/color/image_raw", Image)
        self.depth_sub = message_filters.Subscriber("/camera_base/aligned_depth_to_color/image_raw", Image)
        
        self.ts = message_filters.ApproximateTimeSynchronizer([self.color_sub, self.depth_sub], queue_size=10, slop=0.1)
        self.ts.registerCallback(self.rgbd_callback)

        self.current_keypoints_base = None

        rospy.loginfo("Waiting for synchronized RGB-D streams...")

    def info_callback(self, msg):
        if not self.camera_info_received:
            self.camera_model.fromCameraInfo(msg)
            self.camera_frame = msg.header.frame_id
            self.camera_info_received = True
            rospy.loginfo(f"Camera intrinsics received. Camera frame: {self.camera_frame}")
            self.cam_info_sub.unregister()

    def get_depth_robust(self, depth_img, u, v):
        """ Get median depth from a 5x5 window to ignore noise/zeros """
        u, v = int(u), int(v)
        h, w = depth_img.shape
        if u < 2 or u >= w - 2 or v < 2 or v >= h - 2:
            return None
        
        window = depth_img[v-2:v+3, u-2:u+3]
        valid_pixels = window[window > 0]
        
        if len(valid_pixels) == 0:
            return None
        return np.median(valid_pixels) / 1000.0  # mm to meters

    def transform_points_to_base(self, points_cam):
        points_base = []
        try:
            trans = self.tf_buffer.lookup_transform(self.base_frame, self.camera_frame, rospy.Time(0), rospy.Duration(1.0))
            for pt in points_cam:
                p = PointStamped()
                p.header.frame_id = self.camera_frame
                p.point.x, p.point.y, p.point.z = pt[0], pt[1], pt[2]
                
                p_base = tf2_geometry_msgs.do_transform_point(p, trans)
                points_base.append([p_base.point.x, p_base.point.y, p_base.point.z])
            return points_base
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException) as e:
            return None

    def rgbd_callback(self, color_msg, depth_msg):
        if not self.camera_info_received:
            return

        try:
            cv_image = self.bridge.imgmsg_to_cv2(color_msg, "bgr8")
            depth_image = self.bridge.imgmsg_to_cv2(depth_msg, "16UC1")
        except CvBridgeError as e:
            rospy.logerr(e)
            return

        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_100)
        parameters = aruco.DetectorParameters()
         # --- FAR-DISTANCE TUNING ---
        # 1. Allow much smaller markers to be detected
        parameters.minMarkerPerimeterRate = 0.005
        
        # 2. Tune thresholding for small pixel blobs
        parameters.adaptiveThreshWinSizeMin = 3
        parameters.adaptiveThreshWinSizeMax = 15
        parameters.adaptiveThreshConstant = 5.0
        
        # 3. Be more forgiving on jagged edges caused by low resolution
        parameters.polygonalApproxAccuracyRate = 0.05
        
        # 4. Refine corners accurately without grabbing background noise
        parameters.cornerRefinementMethod = aruco.CORNER_REFINE_SUBPIX
        parameters.cornerRefinementWinSize = 3
        detector = aruco.ArucoDetector(aruco_dict, parameters)
        
        corners, ids, rejected = detector.detectMarkers(gray)
        detected_map = {} 

        if ids is not None:
            cv2.aruco.drawDetectedMarkers(cv_image, corners)
            
            for i, marker_id in enumerate(ids.flatten()):
                if marker_id not in [self.object_marker_id, self.shelf_marker_id]:
                    continue

                corners_3d = []
                
                # Center pixel (Fallback in case corner depth is noisy)
                center_u = int(np.mean(corners[i][0][:, 0]))
                center_v = int(np.mean(corners[i][0][:, 1]))
                center_depth = self.get_depth_robust(depth_image, center_u, center_v)

                for corner_px in corners[i][0]:
                    u, v = corner_px.ravel()
                    
                    # 1. Get Hardware Z Depth
                    z = self.get_depth_robust(depth_image, u, v)
                    
                    # Black/White edges sometimes confuse the IR camera. 
                    # If corner depth fails, use the center of the marker.
                    if z is None and center_depth is not None:
                        z = center_depth

                    if z is not None:
                        # 2. Project 2D pixel to 3D Ray (Unit Vector), then scale by Z
                        ray = self.camera_model.projectPixelTo3dRay((u, v))
                        x = ray[0] * z
                        y = ray[1] * z
                        corners_3d.append([x, y, z])
                        
                        # Visual debugging: draw a circle where depth was found
                        cv2.circle(cv_image, (int(u), int(v)), 4, (255, 0, 0), -1)

                if len(corners_3d) == 4:
                    detected_map[marker_id] = np.array(corners_3d)

        # Ensure both are found
        if self.object_marker_id in detected_map and self.shelf_marker_id in detected_map:
            obj_pts = detected_map[self.object_marker_id]
            shelf_pts = detected_map[self.shelf_marker_id]
            
            combined_pts_cam = np.vstack((obj_pts, shelf_pts))
            # rospy.loginfo(f"Combined camera-frame points:\n{combined_pts_cam}")
            
            self.current_keypoints_base = self.transform_points_to_base(combined_pts_cam)
            # rospy.loginfo(f"Transformed to base frame:\n{self.current_keypoints_base}")
            
            if self.current_keypoints_base is not None:
                cv2.putText(cv_image, "Tracking: LOCKED", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.rectangle(cv_image, (5, 50), (280, 150), (0,0,0), -1) 
                cv2.putText(cv_image, "MENU:", (15, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                cv2.putText(cv_image, "[s] Save SOURCE", (15, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
                cv2.putText(cv_image, "[t] Save TARGET", (15, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
                cv2.putText(cv_image, "[q] Quit", (15, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        else:
            self.current_keypoints_base = None
            cv2.putText(cv_image, "Tracking: SEARCHING...", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        cv2.imshow("RGB-D ArUco Tracker", cv_image)
        key = cv2.waitKey(1) & 0xFF

        if key == ord('s'):
            self.save_keypoints("source")
        elif key == ord('t'):
            self.save_keypoints("target")
        elif key == ord('q'):
            rospy.signal_shutdown("User quit")

    def save_keypoints(self, point_type):
        if self.current_keypoints_base is None:
            return
            
        labels = ["Object_TL", "Object_TR", "Object_BR", "Object_BL", "Shelf_TL", "Shelf_TR", "Shelf_BR", "Shelf_BL"]
        labeled_keypoints = [{"label": labels[i], "coords": pt} for i, pt in enumerate(self.current_keypoints_base)]
        rospy.loginfo(f"Saving {point_type} keypoints with labels:\n{labeled_keypoints}")
        data = {
            "type": point_type,
            "order_reference": labels,
            "keypoints": labeled_keypoints,
            "frame": self.base_frame,
            "timestamp": rospy.get_time()
        }
        
        filename = os.path.join(self.SAVE_DIR, f"{point_type}_keypoints.json")
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)
        
        rospy.loginfo(f"SAVED {point_type.upper()} keypoints to {filename}")

if __name__ == '__main__':
    try:
        tracker = KeypointLoggerRGBD()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
    cv2.destroyAllWindows()