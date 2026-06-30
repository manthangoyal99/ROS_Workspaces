#!/usr/bin/env python3
import rospy
import json
import os
import sys
import select
import termios
import tty
import tf2_ros
from std_msgs.msg import String

class DemoKeypointSubscriber:
    def __init__(self):
        rospy.init_node('demo_keypoint_subscriber', anonymous=True)
        
        # --- PARAMETERS ---
        self.skill_name = rospy.get_param('~skill_name', 'pick')
        self.object_name = rospy.get_param('~object_name', 'apple')
        self.data_dir = rospy.get_param('~data_dir', '/home/ravi/fr3_ws/src/reshelving_policy_transport/data')
        
        os.makedirs(self.data_dir, exist_ok=True)
        
        # --- TF & SUBSCRIBERS ---
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        
        self.latest_bounding_boxes = {}
        self.bb_sub = rospy.Subscriber("/realsense_zmq_bridge/bounding_box", String, self.bb_callback)
        
        rospy.loginfo(f"--- DEMO KEYPOINT SUBSCRIBER READY ---")
        rospy.loginfo(f"Skill: {self.skill_name} | Target Object: {self.object_name}")
        rospy.loginfo("Press [ENTER] to save the current source keypoints. Press [Q] to quit.")

    def bb_callback(self, msg):
        try:
            self.latest_bounding_boxes = json.loads(msg.data)
        except json.JSONDecodeError:
            rospy.logwarn("Received invalid JSON on bounding_box topic")

    def get_ee_position(self):
        try:
            t = self.tf_buffer.lookup_transform('panda_link0', 'panda_EE', rospy.Time(0), rospy.Duration(1.0))
            return [t.transform.translation.x, t.transform.translation.y, t.transform.translation.z]
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException) as e:
            rospy.logerr(f"TF Error: {e}")
            return None

    def save_keypoints(self):
        if not self.latest_bounding_boxes:
            rospy.logwarn("No bounding box data received yet.")
            return

        if self.object_name not in self.latest_bounding_boxes:
            rospy.logwarn(f"Object '{self.object_name}' not found in latest bounding boxes: {list(self.latest_bounding_boxes.keys())}")
            return
            
        obj_bb = self.latest_bounding_boxes[self.object_name]
        if len(obj_bb) != 8:
            rospy.logwarn(f"Object '{self.object_name}' bounding box does not have 8 vertices. Found {len(obj_bb)}.")
            return

        ee_pos = self.get_ee_position()
        if ee_pos is None:
            rospy.logwarn("Could not get end-effector position. Aborting save.")
            return

        # Structure exactly 9 keypoints
        data = {
            "type": "source",
            "skill_name": self.skill_name,
            "object_name": self.object_name,
            "frame": "panda_link0",
            "timestamp": rospy.get_time(),
            "start": obj_bb,         # 8 vertices
            "goal": [ee_pos]         # 1 vertex (wrapped in list for consistent array stacking)
        }
        
        filename = os.path.join(self.data_dir, f"source_keypoints_{self.skill_name}.json")
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)
        
        rospy.loginfo(f"SAVED {self.skill_name.upper()} source keypoints to {filename}")
        rospy.loginfo(f"Included 8 vertices for '{self.object_name}' and 1 vertex for EE position: {ee_pos}")

    def run(self):
        rate = rospy.Rate(10)
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

        try:
            while not rospy.is_shutdown():
                if select.select([sys.stdin], [], [], 0)[0]:
                    key = sys.stdin.read(1)
                    if key == '\n':
                        self.save_keypoints()
                    elif key.lower() == 'q':
                        break
                rate.sleep()
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            print("\nDone.")

if __name__ == '__main__':
    try:
        node = DemoKeypointSubscriber()
        node.run()
    except rospy.ROSInterruptException:
        pass
