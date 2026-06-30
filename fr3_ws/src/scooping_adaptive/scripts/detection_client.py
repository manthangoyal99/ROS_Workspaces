#!/usr/bin/env python3
import rospy
from sensor_msgs.msg import Image
from std_msgs.msg import Int8
from cv_bridge import CvBridge
import cv2
import requests

class LadleInferenceClient:
    def __init__(self):
        rospy.init_node('ladle_inference_client', anonymous=True)
        self.bridge = CvBridge()
        
        # --- CONFIGURATION ---
        # Replace with your actual server IP
        self.server_url = "http://10.72.18.159:5000/detect" 
        
        # The topic your RealSense is publishing to 
        self.camera_topic = "/camera_wrist/color/image_raw" 
        
        # The topic your atomic_proposition script will listen to
        self.status_pub = rospy.Publisher('/ladle_status', Int8, queue_size=10)
        
        # Subscribe to the RealSense feed
        self.image_sub = rospy.Subscriber(self.camera_topic, Image, self.image_callback, queue_size=1)
        
        # Throttle requests to 2 Hz (0.5 seconds) to avoid network bottleneck
        self.last_request_time = rospy.Time.now()
        self.request_interval = rospy.Duration(0.5) 
        
        rospy.loginfo("Ladle Inference Client initialized and waiting for RealSense frames...")

    def image_callback(self, data):
        # Throttle the frequency of requests going to the server
        if rospy.Time.now() - self.last_request_time < self.request_interval:
            return
        self.last_request_time = rospy.Time.now()

        try:
            # 1. Convert ROS Image to OpenCV format
            cv_image = self.bridge.imgmsg_to_cv2(data, "bgr8")
            
            # 2. Compress frame to JPEG before sending (crucial for latency)
            _, img_encoded = cv2.imencode('.jpg', cv_image)
            
            # 3. Send HTTP POST request to your server
            files = {'image': ('frame.jpg', img_encoded.tobytes(), 'image/jpeg')}
            response = requests.post(self.server_url, files=files, timeout=1.0)
            
            # 4. Parse the response and publish the atomic proposition
            if response.status_code == 200:
                status = response.json().get('grains_detected', 0)
                self.status_pub.publish(status)
                # Optional: Print to terminal for debugging
                rospy.loginfo(f"Ladle Status: {status}")
                
        except requests.exceptions.Timeout:
            rospy.logwarn("Server request timed out.")
        except Exception as e:
            rospy.logerr(f"Inference error: {e}")

if __name__ == '__main__':
    try:
        LadleInferenceClient()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass