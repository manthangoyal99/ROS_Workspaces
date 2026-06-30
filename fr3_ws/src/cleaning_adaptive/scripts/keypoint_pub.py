#!/usr/bin/env python3
import rospy
import cv2
import numpy as np
import tf2_ros
import tf2_geometry_msgs
from sensor_msgs.msg import Image, CameraInfo
from geometry_msgs.msg import PointStamped
from std_msgs.msg import Float32MultiArray
from cv_bridge import CvBridge, CvBridgeError
import image_geometry

class LiveMeshPublisher:
    def __init__(self):
        rospy.init_node('live_mesh_publisher', anonymous=True)

        # --- CONFIGURATION ---
        self.base_frame = "panda_link0"
        self.camera_frame = "camera_color_optical_frame"
        
        # Mesh Settings (Must match your demo settings exactly)
        self.grid_rows = 4
        self.grid_cols = 8
        
        # Detection Settings
        self.min_contour_area = 50
        self.max_contour_area = 50000

        # --- ROI INTERFACE ---
        self.roi_points = []
        self.window_name = "Live Target Mesh Publisher"
        self.window_initialized = False 

        # --- SUBSCRIBERS & PUBLISHERS ---
        self.bridge = CvBridge()
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.cam_model = image_geometry.PinholeCameraModel()

        self.cam_info_sub = rospy.Subscriber("/camera/color/camera_info", CameraInfo, self.info_cb)
        self.color_sub = rospy.Subscriber("/camera/color/image_raw", Image, self.color_cb)
        self.depth_sub = rospy.Subscriber("/camera/aligned_depth_to_color/image_raw", Image, self.depth_cb)

        # The Output Topic your Controller and Monitor will listen to
        self.mesh_pub = rospy.Publisher('/vision/live_target_kps', Float32MultiArray, queue_size=1)

        self.latest_depth = None
        self.current_mesh_base = None

        rospy.loginfo("Live Mesh Publisher ready. Click 4 points to lock ROI and begin publishing.")

    def mouse_cb(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            if len(self.roi_points) < 4:
                self.roi_points.append((x, y))
                rospy.loginfo(f"ROI Point {len(self.roi_points)} selected at ({x}, {y})")

    def info_cb(self, msg):
        self.cam_model.fromCameraInfo(msg)
        self.camera_frame = msg.header.frame_id
        self.cam_info_sub.unregister()

    def depth_cb(self, msg):
        try:
            self.latest_depth = self.bridge.imgmsg_to_cv2(msg, "16UC1")
        except CvBridgeError as e:
            pass

    def get_3d_point(self, u, v):
        if self.latest_depth is None: return None
        u = np.clip(int(u), 0, self.latest_depth.shape[1] - 1)
        v = np.clip(int(v), 0, self.latest_depth.shape[0] - 1)
        
        roi = self.latest_depth[max(0, v-1):min(self.latest_depth.shape[0], v+2), 
                                max(0, u-1):min(self.latest_depth.shape[1], u+2)]
        valid_depths = roi[roi > 0]
        if len(valid_depths) == 0: return None
            
        z = np.median(valid_depths) / 1000.0 
        ray = self.cam_model.projectPixelTo3dRay((u, v))
        return [ray[0] * z, ray[1] * z, z]

    def transform_to_base(self, pt_cam):
        try:
            trans = self.tf_buffer.lookup_transform(self.base_frame, self.camera_frame, rospy.Time(0), rospy.Duration(0.1))
            p = PointStamped()
            p.header.frame_id = self.camera_frame
            p.point.x, p.point.y, p.point.z = pt_cam[0], pt_cam[1], pt_cam[2]
            p_base = tf2_geometry_msgs.do_transform_point(p, trans)
            return [p_base.point.x, p_base.point.y, p_base.point.z]
        except Exception:
            return None

    def color_cb(self, msg):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, "bgr8")
        except CvBridgeError:
            return

        if not self.window_initialized:
            cv2.namedWindow(self.window_name)
            cv2.setMouseCallback(self.window_name, self.mouse_cb)
            self.window_initialized = True

        if self.latest_depth is None or not self.cam_model.tfFrame():
            cv2.rectangle(cv_image, (5, 5), (450, 60), (0,0,0), -1)
            cv2.putText(cv_image, "ERROR: Waiting for Aligned Depth!", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.imshow(self.window_name, cv_image)
            cv2.waitKey(1)
            return

        # gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        # blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        # thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        #                                cv2.THRESH_BINARY_INV, 25, 1)
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        
        # 1. Morphological Black-Hat to extract dark marks ignoring lighting/curves
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
        blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
        
        # 2. Mild blur to connect any slightly fragmented pixels in faint strokes
        smoothed = cv2.GaussianBlur(blackhat, (3, 3), 0)
        
        # 3. Standard global threshold (marks are now bright on a pure black background)
        # You can adjust '15' up or down slightly to tune sensitivity.
        _, thresh = cv2.threshold(smoothed, 15, 255, cv2.THRESH_BINARY)

        for i in range(len(self.roi_points)):
            cv2.circle(cv_image, self.roi_points[i], 5, (255, 0, 0), -1)
            if i > 0:
                cv2.line(cv_image, self.roi_points[i-1], self.roi_points[i], (255, 0, 0), 2)
        if len(self.roi_points) == 4:
            cv2.line(cv_image, self.roi_points[3], self.roi_points[0], (255, 0, 0), 2)

        mesh_valid = False
        self.current_mesh_base = []

        if len(self.roi_points) == 4:
            mask = np.zeros_like(thresh)
            poly_pts = np.array(self.roi_points, np.int32)
            cv2.fillPoly(mask, [poly_pts], 255)

            thresh_roi = cv2.bitwise_and(thresh, mask)

            contours, _ = cv2.findContours(thresh_roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            valid_contours = []
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if self.min_contour_area < area < self.max_contour_area:
                    valid_contours.append(cnt)

            if valid_contours:
                all_points = np.vstack(valid_contours)
                x, y, w, h = cv2.boundingRect(all_points)
                cv2.rectangle(cv_image, (x, y), (x+w, y+h), (0, 255, 0), 2)

                u_steps = np.linspace(x, x + w, self.grid_cols, dtype=int)
                v_steps = np.linspace(y, y + h, self.grid_rows, dtype=int)

                all_points_transformed = []
                for v in v_steps:
                    for u in u_steps:
                        cv2.circle(cv_image, (u, v), 5, (0, 0, 255), -1)
                        pt_3d_cam = self.get_3d_point(u, v)
                        if pt_3d_cam is not None:
                            pt_base = self.transform_to_base(pt_3d_cam)
                            if pt_base is not None:
                                all_points_transformed.append(pt_base)

                if len(all_points_transformed) == (self.grid_rows * self.grid_cols):
                    self.current_mesh_base = all_points_transformed
                    mesh_valid = True

        # --- PUBLISH THE MESH ---
        if mesh_valid:
            msg = Float32MultiArray()
            flat_mesh = []
            # Flatten the [16, 3] array into a 1D list of 48 floats
            for pt in self.current_mesh_base:
                flat_mesh.extend(pt)
            msg.data = flat_mesh
            self.mesh_pub.publish(msg)

        # --- UI Overlay ---
        cv2.rectangle(cv_image, (5, 5), (320, 100), (0,0,0), -1)
        if len(self.roi_points) < 4:
            cv2.putText(cv_image, f"Click Points: {len(self.roi_points)}/4", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
        elif mesh_valid:
            cv2.putText(cv_image, "STATUS: PUBLISHING", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(cv_image, f"Topic: /vision/live_target_kps", (15, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        else:
            cv2.putText(cv_image, "STATUS: NO INK FOUND", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        cv2.putText(cv_image, "[r] Reset Points", (15, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(cv_image, "[q] Quit", (15, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1)
            
        cv2.imshow(self.window_name, cv_image)
        key = cv2.waitKey(1) & 0xFF

        if key == ord('r'):
            self.roi_points = []
            rospy.loginfo("ROI reset. Click 4 points again.")
        elif key == ord('q'):
            rospy.signal_shutdown("Quit")

if __name__ == '__main__':
    try:
        LiveMeshPublisher()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
    cv2.destroyAllWindows()