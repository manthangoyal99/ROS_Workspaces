#!/usr/bin/env python3
import rospy
import json
import os
import argparse
from std_msgs.msg import String
import tf2_ros

class KeypointDetector:
    def __init__(self, skill: str, object_names: list, use_ee: bool = False):
        self.skill = skill
        self.object_names = object_names
        self.use_ee = use_ee
        self.latest_data = None
        
        rospy.init_node('keypoint_detector', anonymous=True)
        rospy.Subscriber('/realsense_zmq_bridge/tracking_data_base', String, self.callback)
        
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        
        # Get the path to the data directory
        import rospkg
        rospack = rospkg.RosPack()
        try:
            pkg_path = rospack.get_path('TPGPT_two_args')
        except Exception:
            pkg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            
        self.data_dir = os.path.join(pkg_path, 'data')
        os.makedirs(self.data_dir, exist_ok=True)
        
    def callback(self, msg):
        try:
            self.latest_data = json.loads(msg.data)
        except Exception as e:
            rospy.logerr("Failed to parse JSON: %s", e)
            
    def run(self):
        rospy.loginfo("Keypoint detector initialized.")
        rospy.loginfo("Waiting for messages on /realsense_zmq_bridge/tracking_data_base ...")
        
        while not rospy.is_shutdown():
            if self.latest_data is None:
                rospy.sleep(0.1)
                continue
                
            # Wait for user input to capture the frame
            try:
                input(f"\nPress ENTER to capture keypoints for {self.object_names} and skill '{self.skill}'... (or Ctrl+C to quit)\n")
            except EOFError:
                break
                
            # Make a copy of the latest data to avoid race conditions
            current_data = self.latest_data.copy()
            
            ee_pos = None
            if self.use_ee:
                try:
                    t = self.tf_buffer.lookup_transform('panda_link0', 'panda_EE', rospy.Time(0), rospy.Duration(1.0))
                    ee_pos = [t.transform.translation.x, t.transform.translation.y, t.transform.translation.z]
                except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException) as e:
                    rospy.logerr(f"TF Error getting EE pos: {e}")
            
            output_data = {
                "skill": self.skill,
                "frame_id": current_data.get("header", {}).get("frame_id", "panda_link0"),
                "timestamp": current_data.get("header", {}).get("stamp_secs", 0),
                "objects": {}
            }
            
            objects_dict = current_data.get("objects", {})
            success_count = 0
            
            # The "keypoints" array contains a single consolidated list of 3D coordinates.
            # It is ordered sequentially by the list of objects requested in self.object_names.
            #
            # Structure for N requested objects:
            # - [Object 1 Center (x, y, z)] -> Index 0
            # - [Object 1 Vertex 0 (x, y, z)] to [Object 1 Vertex 7 (x, y, z)] -> Indices 1 to 8
            # ...
            # - [Object N Center (x, y, z)] -> Index (N-1)*9
            # - [Object N Vertex 0 (x, y, z)] to [Object N Vertex 7 (x, y, z)] -> Indices (N-1)*9 + 1 to (N-1)*9 + 8
            # - [End-Effector (x, y, z)] (Optional, appended once at the very end if --ee_pos was enabled)
            global_keypoints = []
            
            for obj_name in self.object_names:
                if obj_name in objects_dict:
                    obj_data = objects_dict[obj_name]
                    
                    # 1. 3D pose of the object (position)
                    pos = obj_data.get("pose", {}).get("position", {})
                    global_keypoints.append([pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)])
                    
                    # 2. 8 vertices in their consistent original order
                    flat_bb = obj_data.get("bbox", [])
                    if len(flat_bb) == 24:
                        for i in range(0, 24, 3):
                            global_keypoints.append([flat_bb[i], flat_bb[i+1], flat_bb[i+2]])
                            
                    output_data["objects"][obj_name] = obj_data
                    rospy.loginfo(f"Extracted pose and vertices for '{obj_name}'")
                    success_count += 1
                else:
                    rospy.logwarn(f"Object '{obj_name}' not found in current tracking data!")
            
            # Only save if we found all requested objects (to keep keypoints array length consistent)
            if success_count == len(self.object_names):
                # 3. End effector 3D pose (if requested and available)
                if self.use_ee and ee_pos is not None:
                    global_keypoints.append(ee_pos)
                    
                output_data["keypoints"] = global_keypoints
                
                # Save to file
                filename = f"keypoints_{self.skill}.json"
                filepath = os.path.join(self.data_dir, filename)
                
                with open(filepath, 'w') as f:
                    json.dump(output_data, f, indent=4)
                    
                rospy.loginfo(f"Successfully saved {len(global_keypoints)} global keypoints for {success_count} objects to: {filepath}")
            else:
                rospy.logwarn(f"Did not save file because only {success_count}/{len(self.object_names)} requested objects were found in the camera frame.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Capture keypoints from tracking data.')
    parser.add_argument('--skill', type=str, required=True, help='Name of the skill (e.g., pick, push)')
    parser.add_argument('--objects', nargs='+', required=True, help='List of object names to track (e.g., bowl apple)')
    parser.add_argument('--ee_pos', action='store_true', help='Include end-effector position in keypoints')
    
    # ROS args are appended, so we need to filter them out
    args, unknown = parser.parse_known_args()
    
    detector = KeypointDetector(skill=args.skill, object_names=args.objects, use_ee=args.ee_pos)
    try:
        detector.run()
    except rospy.ROSInterruptException:
        pass
    except KeyboardInterrupt:
        pass
