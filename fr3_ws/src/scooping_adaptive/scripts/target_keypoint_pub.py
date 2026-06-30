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
from std_msgs.msg import Float32MultiArray
from cv_bridge import CvBridge, CvBridgeError
from image_geometry import PinholeCameraModel

class LiveKeypointPublisherRGBD:
    def __init__(self):
        rospy.init_node('live_keypoint_publisher_rgbd', anonymous=True)

        # --- CONFIGURATION ---
        self.object_marker_id = 0  # ID for the object (Source)
        self.shelf_marker_id = 2   # ID for the shelf slot (Target)
        self.camera_frame = "camera_color_optical_frame"
        self.base_frame = "panda_link0"
        # self.marker_size is removed (Not needed for RGB-D projection)

        # --- PUBLISHERS ---
        self.source_pub = rospy.Publisher('/vision/live_source_kps', Float32MultiArray, queue_size=1)
        self.target_pub = rospy.Publisher('/vision/live_target_kps', Float32MultiArray, queue_size=1)

        # --- SUBSCRIBERS ---
        self.bridge = CvBridge()
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.camera_model = PinholeCameraModel()
        
        # 1. Camera Info (Runs once)
        self.cam_info_sub = rospy.Subscriber("/camera_base/color/camera_info", CameraInfo, self.info_callback)
        self.camera_info_received = False
        
        # 2. Synchronized RGB and Depth Streams
        self.color_sub = message_filters.Subscriber("/camera_base/color/image_raw", Image)
        self.depth_sub = message_filters.Subscriber("/camera_base/aligned_depth_to_color/image_raw", Image)
        self.ts = message_filters.ApproximateTimeSynchronizer([self.color_sub, self.depth_sub], queue_size=10, slop=0.1)
        self.ts.registerCallback(self.rgbd_callback)
        
        # --- OCCLUSION LATCHES (Memory Buffer) ---
        self.last_known_source = None
        self.last_known_target = None

        rospy.loginfo("Live Keypoint Publisher started. Waiting for RGB-D streams...")

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
            trans = self.tf_buffer.lookup_transform(
                self.base_frame, 
                self.camera_frame, 
                rospy.Time(0), 
                rospy.Duration(0.1)
            )
            for pt in points_cam:
                p = PointStamped()
                p.header.frame_id = self.camera_frame
                p.point.x, p.point.y, p.point.z = pt[0], pt[1], pt[2]
                
                p_base = tf2_geometry_msgs.do_transform_point(p, trans)
                points_base.append([p_base.point.x, p_base.point.y, p_base.point.z])
                
            return np.array(points_base)
            
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException):
            return None

    def publish_keypoints(self, publisher, keypoints_array):
        """Helper to format and publish a numpy array as a Float32MultiArray"""
        msg = Float32MultiArray()
        # Flatten the (4, 3) array into a 1D list of 12 floats
        msg.data = keypoints_array.flatten().tolist()
        publisher.publish(msg)

    def rgbd_callback(self, color_msg, depth_msg):
        if not self.camera_info_received: return

        try:
            cv_image = self.bridge.imgmsg_to_cv2(color_msg, "bgr8")
            depth_image = self.bridge.imgmsg_to_cv2(depth_msg, "16UC1")
        except CvBridgeError as e:
            rospy.logerr(e)
            return

        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_5X5_250)
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
        corners, ids, _ = detector.detectMarkers(gray)

        detected_map = {} 

        if ids is not None:
            cv2.aruco.drawDetectedMarkers(cv_image, corners)
            
            for i, marker_id in enumerate(ids.flatten()):
                if marker_id not in [self.object_marker_id, self.shelf_marker_id]:
                    continue

                corners_3d = []
                
                # Center pixel (Fallback for edge noise)
                center_u = int(np.mean(corners[i][0][:, 0]))
                center_v = int(np.mean(corners[i][0][:, 1]))
                center_depth = self.get_depth_robust(depth_image, center_u, center_v)

                for corner_px in corners[i][0]:
                    u, v = corner_px.ravel()
                    
                    z = self.get_depth_robust(depth_image, u, v)
                    
                    if z is None and center_depth is not None:
                        z = center_depth

                    if z is not None:
                        # Project 2D pixel to 3D Ray (Unit Vector), then scale by Z
                        ray = self.camera_model.projectPixelTo3dRay((u, v))
                        x = ray[0] * z
                        y = ray[1] * z
                        corners_3d.append([x, y, z])
                        
                        cv2.circle(cv_image, (int(u), int(v)), 4, (255, 0, 0), -1)

                if len(corners_3d) == 4:
                    detected_map[marker_id] = np.array(corners_3d)

        # --- 1. PROCESS SOURCE (OBJECT) ---
        if self.object_marker_id in detected_map:
            source_base = self.transform_points_to_base(detected_map[self.object_marker_id])
            if source_base is not None:
                self.last_known_source = source_base
                cv2.putText(cv_image, "SRC: Live", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        else:
            cv2.putText(cv_image, "SRC: Latched", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

        # --- 2. PROCESS TARGET (SHELF) ---
        if self.shelf_marker_id in detected_map:
            target_base = self.transform_points_to_base(detected_map[self.shelf_marker_id])
            if target_base is not None:
                self.last_known_target = target_base
                cv2.putText(cv_image, "TGT: Live", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        else:
            cv2.putText(cv_image, "TGT: Latched", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

        # --- 3. PUBLISH LATEST DATA ---
        if self.last_known_source is not None:
            self.publish_keypoints(self.source_pub, self.last_known_source)
            
        if self.last_known_target is not None:
            self.publish_keypoints(self.target_pub, self.last_known_target)

        cv2.imshow("Live ArUco Tracking", cv_image)
        cv2.waitKey(1)

if __name__ == '__main__':
    try:
        tracker = LiveKeypointPublisherRGBD()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
    cv2.destroyAllWindows()