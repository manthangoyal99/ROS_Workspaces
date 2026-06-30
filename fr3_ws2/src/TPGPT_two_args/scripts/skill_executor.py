#!/usr/bin/env python3
import rospy
import json
import os
import actionlib
import tf2_ros
from std_msgs.msg import String
from geometry_msgs.msg import PoseStamped
from franka_gripper.msg import GraspAction, GraspGoal, MoveAction, MoveGoal

from transported_traj import transport_trajectory

class SkillExecutor:
    def __init__(self):
        rospy.init_node('skill_executor')
        
        # --- PARAMETERS ---
        self.skill_name = rospy.get_param('~skill_name', 'pick')
        self.object_name = rospy.get_param('~object_name', 'apple')
        self.object2_name = rospy.get_param('~object2_name', '')
        import rospkg
        rospack = rospkg.RosPack()
        try:
            default_data_dir = os.path.join(rospack.get_path('TPGPT_two_args'), 'data')
        except Exception:
            default_data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
        self.data_dir = rospy.get_param('~data_dir', default_data_dir)
        
        # --- ROS PUBLISHERS & ACTION CLIENTS ---
        self.pose_pub = rospy.Publisher('/cartesian_impedance_example_controller/equilibrium_pose', PoseStamped, queue_size=1)
        self.grasp_client = actionlib.SimpleActionClient('/franka_gripper/grasp', GraspAction)
        self.move_client = actionlib.SimpleActionClient('/franka_gripper/move', MoveAction)
        
        # --- TF ---
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        
        # --- SUBSCRIBER ---
        self.latest_bounding_boxes = None
        self.bb_sub = rospy.Subscriber("/realsense_zmq_bridge/tracking_data_base", String, self.bb_callback)
        
        rospy.loginfo(f"--- SKILL EXECUTOR READY ---")
        rospy.loginfo(f"Executing Skill: {self.skill_name} on Object: {self.object_name}")
        rospy.loginfo("Waiting for bounding box data on /realsense_zmq_bridge/tracking_data_base...")

    def get_ee_position(self):
        try:
            t = self.tf_buffer.lookup_transform('panda_link0', 'panda_EE', rospy.Time(0), rospy.Duration(1.0))
            return [t.transform.translation.x, t.transform.translation.y, t.transform.translation.z]
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException) as e:
            rospy.logerr(f"TF Error: {e}")
            return None

    def bb_callback(self, msg):
        try:
            self.latest_bounding_boxes = json.loads(msg.data)
        except json.JSONDecodeError:
            pass

    def run(self):
        rospy.loginfo("Waiting for initial bounding box data...")
        
        while not rospy.is_shutdown():
            if self.latest_bounding_boxes is None:
                rospy.sleep(0.1)
                continue
                
            # Prepare target objects dynamically based on what was provided
            target_objs = [self.object_name]
            if self.object2_name:
                target_objs.append(self.object2_name)
                
            # Validate skill existence dynamically
            method_name = f"execute_{self.skill_name}"
            if not hasattr(self, method_name):
                rospy.logwarn(f"Unknown skill '{self.skill_name}': Method '{method_name}' not implemented!")
                break
                
            # Wait for user input to capture the frame
            try:
                input(f"\nPress ENTER to capture the current frame and execute skill '{self.skill_name}' on {target_objs}... (or Ctrl+C to quit)\n")
            except EOFError:
                break
                
            # Execute exactly once dynamically
            skill_method = getattr(self, method_name)
            success = skill_method()
                
            if not success:
                rospy.logwarn("Failed to find the requested objects in the captured frame! Aborting execution.")
                
            break # Exit the loop after one attempt so it doesn't execute repeatedly

    def execute_pick(self):
        objects_dict = self.latest_bounding_boxes.get("objects", {})
        if self.object_name not in objects_dict:
            return False
            
        flat_bb = objects_dict[self.object_name].get("bbox", [])
        if len(flat_bb) != 24:
            return False
            
        # Reshape flat list of 24 into 8 points of 3 coordinates
        obj_bb = [[flat_bb[i], flat_bb[i+1], flat_bb[i+2]] for i in range(0, 24, 3)]
            
        ee_pos = self.get_ee_position()
        if ee_pos is None:
            return False
            
        obj_center = [objects_dict[self.object_name].get("pose", {}).get("position", {}).get("x", 0),
                      objects_dict[self.object_name].get("pose", {}).get("position", {}).get("y", 0),
                      objects_dict[self.object_name].get("pose", {}).get("position", {}).get("z", 0)]
                      
        # 10 points array: 1 (center) + 8 (vertices) + 1 (ee)
        target_keypoints = [obj_center] + obj_bb + [ee_pos]
        
        rospy.loginfo(f"Successfully retrieved target keypoints for pick: {self.object_name} and EE.")
        self.bb_sub.unregister()
        self._perform_transport(target_keypoints)
        return True

    def execute_push(self):
        objects_dict = self.latest_bounding_boxes.get("objects", {})
        if self.object_name not in objects_dict or self.object2_name not in objects_dict:
            return False
            
        flat_bb1 = objects_dict[self.object_name].get("bbox", [])
        flat_bb2 = objects_dict[self.object2_name].get("bbox", [])
        
        if len(flat_bb1) != 24 or len(flat_bb2) != 24:
            return False
            
        # Reshape flat list of 24 into 8 points of 3 coordinates
        obj1_bb = [[flat_bb1[i], flat_bb1[i+1], flat_bb1[i+2]] for i in range(0, 24, 3)]
        obj2_bb = [[flat_bb2[i], flat_bb2[i+1], flat_bb2[i+2]] for i in range(0, 24, 3)]
            
        ee_pos = self.get_ee_position()
        if ee_pos is None:
            return False
            
        obj1_center = [objects_dict[self.object_name].get("pose", {}).get("position", {}).get("x", 0),
                       objects_dict[self.object_name].get("pose", {}).get("position", {}).get("y", 0),
                       objects_dict[self.object_name].get("pose", {}).get("position", {}).get("z", 0)]
                       
        obj2_center = [objects_dict[self.object2_name].get("pose", {}).get("position", {}).get("x", 0),
                       objects_dict[self.object2_name].get("pose", {}).get("position", {}).get("y", 0),
                       objects_dict[self.object2_name].get("pose", {}).get("position", {}).get("z", 0)]
        
        # 19 points array: 1+8 (obj1) + 1+8 (obj2) + 1 (ee)
        target_keypoints = [obj1_center] + obj1_bb + [obj2_center] + obj2_bb + [ee_pos]
        
        rospy.loginfo(f"Successfully retrieved 17 target keypoints for push: {self.object_name}, {self.object2_name}, and EE.")
        self.bb_sub.unregister()
        self._perform_transport(target_keypoints)
        return True

    def save_json(self, data, filename):
        path = os.path.join(self.data_dir, filename)
        with open(path, 'w') as f:
            json.dump(data, f, indent=4)
        rospy.loginfo(f"[Success] Saved json to: {path}")

    def _perform_transport(self, target_keypoints):
        rospy.loginfo(f"Starting trajectory transport for {self.skill_name}...")
        
        source_kp_file = f"keypoints_{self.skill_name}.json"
        demo_traj_file = f"demo_trajectory_{self.skill_name}.json"
        
        if not os.path.exists(os.path.join(self.data_dir, source_kp_file)):
            rospy.logwarn(f"{source_kp_file} not found, falling back to keypoints.json")
            source_kp_file = "keypoints.json"
            
        if not os.path.exists(os.path.join(self.data_dir, demo_traj_file)):
            rospy.logwarn(f"{demo_traj_file} not found, falling back to demo_trajectory.json")
            demo_traj_file = "demo_trajectory.json"
            
        try:
            with open(os.path.join(self.data_dir, source_kp_file), 'r') as f:
                source_data = json.load(f)
            with open(os.path.join(self.data_dir, demo_traj_file), 'r') as f:
                demo_traj = json.load(f)
                
            warped_traj, affine_traj, S_affine, S_final = transport_trajectory(
                target_keypoints, source_data, demo_traj
            )
            
            # Update metadata and save
            warped_traj['metadata']['source'] = f"policy_transportation_{self.skill_name}"
            affine_traj['metadata']['source'] = f"policy_transportation_affine_{self.skill_name}"
            
            self.save_json(warped_traj, f"warped_trajectory_{self.skill_name}.json")
            self.save_json(affine_traj, f"affine_trajectory_{self.skill_name}.json")
            #self.save_json(warped_traj, "warped_trajectory.json")
            #self.save_json(affine_traj, "affine_trajectory.json")
            self.save_json(S_affine.tolist(), f"source_affine_keypoints_{self.skill_name}.json")
            self.save_json(S_final.tolist(), f"source_final_keypoints_{self.skill_name}.json")
            
        except Exception as e:
            rospy.logerr(f"Error during trajectory transport: {e}")
            return
            
        self.play_trajectory(warped_traj)

    def play_trajectory(self, data):
        rate = rospy.Rate(50)
        prev_gripper_state = 0 

        rospy.loginfo("Starting Replay in 3 seconds... Clear the robot area!")
        rospy.sleep(3.0)

        for i in range(len(data['positions'])):
            if rospy.is_shutdown(): break

            pose = PoseStamped()
            pose.header.frame_id = "panda_link0"
            pose.header.stamp = rospy.Time.now()
            
            p = data['positions'][i]
            o = data['orientations'][i]
            
            pose.pose.position.x, pose.pose.position.y, pose.pose.position.z = p
            pose.pose.orientation.x, pose.pose.orientation.y, pose.pose.orientation.z, pose.pose.orientation.w = o
            
            self.pose_pub.publish(pose)

            curr_gripper_state = data['gripper_states'][i]
            if curr_gripper_state == 1 and prev_gripper_state == 0:
                rospy.loginfo("Event: Closing Gripper")
                goal = GraspGoal(width=data['metadata'].get('object_width', 0.0), speed=0.1, force=20.0)
                goal.epsilon.inner = 0.08; goal.epsilon.outer = 0.08
                self.grasp_client.send_goal(goal)
                
            elif curr_gripper_state == 0 and prev_gripper_state == 1:
                rospy.loginfo("Event: Opening Gripper")
                self.move_client.send_goal(MoveGoal(width=0.08, speed=0.1))

            prev_gripper_state = curr_gripper_state
            rate.sleep()

        rospy.loginfo("Skill Execution Finished.")

if __name__ == '__main__':
    try:
        executor = SkillExecutor()
        executor.run()
    except rospy.ROSInterruptException:
        pass
