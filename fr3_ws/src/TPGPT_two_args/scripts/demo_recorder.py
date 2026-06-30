#!/usr/bin/env python3
import rospy
import tf2_ros
import json
import os
import sys
import select
import termios
import tty
import numpy as np
import actionlib
from franka_msgs.msg import FrankaState
from franka_gripper.msg import GraspAction, GraspGoal, MoveAction, MoveGoal

class FiniteDiffRecorder:
    def __init__(self, skill_name=None):
        rospy.init_node('demo_recorder_finite_diff')
        self.skill_name = skill_name
        
        # --- CONFIGURATION ---
        import rospkg
        rospack = rospkg.RosPack()
        try:
            self.data_dir = os.path.join(rospack.get_path('TPGPT_two_args'), 'data')
        except Exception:
            self.data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
        self.object_width = 0.0   
        self.grasp_force = 50.0    
        self.freq = 50.0           
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        # --- TF & SUBSCRIBERS ---
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        
        # Gripper Clients
        self.grasp_client = actionlib.SimpleActionClient('/franka_gripper/grasp', GraspAction)
        self.move_client = actionlib.SimpleActionClient('/franka_gripper/move', MoveAction)
        
        # Subscriber for Safety Stop only (Not used for velocity anymore)
        self.state_sub = rospy.Subscriber(
            "/franka_state_controller/franka_states", 
            FrankaState, 
            self.safety_callback,
            queue_size=1
        )

        # State Variables for Finite Diff
        self.prev_pos = None
        self.prev_time = None

        # Data Containers
        self.reset_data()
        self.recording = False
        self.gripper_is_holding = False

        rospy.loginfo("--- FINITE DIFF RECORDER READY ---")

    def reset_data(self):
        self.timestamps = []
        self.positions = []
        self.orientations = []
        self.linear_vels = [] # Calculated manually
        self.gripper_states = [] 
        self.prev_pos = None
        self.prev_time = None

    def safety_callback(self, msg):
        # Safety Stop Check
        if msg.robot_mode == FrankaState.ROBOT_MODE_USER_STOPPED and self.recording:
            rospy.logwarn("User Stop detected! Stopping recording...")
            self.recording = False

    def close_gripper(self):
        rospy.loginfo(f"Gripping to {self.object_width}m...")
        goal = GraspGoal()
        goal.width = self.object_width
        goal.epsilon.inner = 0.08
        goal.epsilon.outer = 0.08
        goal.speed = 0.1
        goal.force = self.grasp_force
        self.grasp_client.send_goal(goal)
        self.gripper_is_holding = True

    def open_gripper(self):
        rospy.loginfo("Opening gripper...")
        goal = MoveGoal()
        goal.width = 0.08
        goal.speed = 0.1
        self.move_client.send_goal(goal)
        self.gripper_is_holding = False

    def calc_velocity(self, curr_pos, curr_time):
        if self.prev_pos is None:
            return np.zeros(3)
        
        dt = curr_time - self.prev_time
        if dt < 1e-4:
            return np.zeros(3)
        
        vel = (curr_pos - self.prev_pos) / dt
        return vel
    
    def run(self):
        rate = rospy.Rate(self.freq)
        print(" [ENTER] Start/Stop | [C] Close Gripper | [O] Open Gripper | [Q] Quit")
        
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

        try:
            while not rospy.is_shutdown():
                # Keyboard Handling
                if select.select([sys.stdin], [], [], 0)[0]:
                    key = sys.stdin.read(1)
                    if key == '\n':
                        if not self.recording:
                            rospy.loginfo(">>> STARTED RECORDING <<<")
                            self.reset_data()
                            self.recording = True
                        else:
                            rospy.loginfo(">>> STOPPED RECORDING <<<")
                            self.recording = False
                            self.save_data()
                    elif key.lower() == 'c': self.close_gripper()
                    elif key.lower() == 'o': self.open_gripper()
                    elif key.lower() == 'q': break

                # Recording Loop
                if self.recording:
                    try:
                        # 1. Get Pose from TF
                        t = self.tf_buffer.lookup_transform('panda_link0', 'panda_EE', rospy.Time(0))
                        
                        curr_time = rospy.get_time()
                        curr_pos = np.array([t.transform.translation.x, t.transform.translation.y, t.transform.translation.z])
                        curr_ori = [t.transform.rotation.x, t.transform.rotation.y, t.transform.rotation.z, t.transform.rotation.w]
                        
                        # 2. Calculate Velocity (Finite Difference)
                        vel_lin = np.zeros(3)
                        vel_lin = self.calc_velocity(curr_pos, curr_time)
                        
                        # 3. Store Data
                        self.timestamps.append(curr_time)
                        self.positions.append(curr_pos.tolist())
                        self.orientations.append(curr_ori)
                        self.linear_vels.append(vel_lin.tolist())
                        self.gripper_states.append(1 if self.gripper_is_holding else 0)
                        
                        # Update previous state
                        self.prev_pos = curr_pos
                        self.prev_time = curr_time
                        
                    except (tf2_ros.LookupException, tf2_ros.ExtrapolationException):
                        pass

                rate.sleep()

        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            print("\nDone.")

    def save_data(self):
        if not self.timestamps: return
        
        # Normalize time
        t0 = self.timestamps[0]
        norm_time = [t - t0 for t in self.timestamps]
        
        data = {
            "metadata": {"freq": self.freq, "source": "finite_difference_tf"},
            "timestamps": norm_time,
            "positions": self.positions,
            "orientations": self.orientations,
            "velocities_lin": self.linear_vels,
            "gripper_states": self.gripper_states
        }
        
        if self.skill_name:
            filename = f"demo_trajectory_{self.skill_name}.json"
        else:
            filename = "demo_trajectory.json"
            
        path = os.path.join(self.data_dir, filename)
        with open(path, 'w') as f:
            json.dump(data, f, indent=4) # indent=4 makes it readable
        rospy.loginfo(f"Saved {len(self.positions)} points to {path}")

if __name__ == '__main__':
    # Filter out ROS remapping arguments (they contain ':=')
    args = [arg for arg in sys.argv[1:] if ':=' not in arg]
    skill_name = args[0] if len(args) > 0 else None
    
    if skill_name:
        print(f"Recording trajectory for skill: {skill_name}")
    else:
        print("Recording generic trajectory. (Pass a skill name as argument to record for a specific skill)")
        
    rec = FiniteDiffRecorder(skill_name)
    rec.run()
