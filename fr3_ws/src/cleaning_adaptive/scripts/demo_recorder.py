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
from franka_msgs.msg import FrankaState
from std_msgs.msg import Int8MultiArray

# Import your new cleaning automaton! Make sure cleaning_automaton.py is in the same folder 
# or properly installed in your ROS package.
from task_automaton import CleaningAutomaton

class CleaningDemoRecorder:
    def __init__(self):
        rospy.init_node('cleaning_demo_recorder')
        
        # --- CONFIGURATION ---
        self.data_dir = "/home/ravi/fr3_ws/src/cleaning_adaptive/data"
        self.freq = 50.0          
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        # --- TF & SUBSCRIBERS ---
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        
        # Subscriber for Safety Stop
        self.state_sub = rospy.Subscriber(
            "/franka_state_controller/franka_states", 
            FrankaState, 
            self.safety_callback,
            queue_size=1
        )
        
        # Listen to the 2 propositions: [is_near_mesh, mesh_exists]
        self.current_propositions = [0, 0] 
        rospy.Subscriber('/task/atomic_propositions', Int8MultiArray, self.cb_propositions)

        self.automaton = CleaningAutomaton()

        # State Variables for Finite Diff
        self.prev_pos = None
        self.prev_time = None

        # Data Containers
        self.reset_data()
        self.recording = False

        rospy.loginfo("--- CLEANING DEMO RECORDER READY ---")

    def reset_data(self):
        self.timestamps = []
        self.positions = []
        self.orientations = []
        self.linear_vels = [] 
        self.sensor_props = []
        self.mode_labels = [] 
        self.prev_pos = None
        self.prev_time = None
    
    def cb_propositions(self, msg):
        self.current_propositions = list(msg.data)
    
    def safety_callback(self, msg):
        if msg.robot_mode == FrankaState.ROBOT_MODE_USER_STOPPED and self.recording:
            rospy.logwarn("User Stop detected! Stopping recording...")
            self.recording = False

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
        print("\nControls: [ENTER] Start/Stop Recording | [Q] Quit")
        
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
                        vel_lin = self.calc_velocity(curr_pos, curr_time)
                        
                        # 3. Get Current Mode from Automaton
                        # update() returns (mode_id, has_changed_bool)
                        mode_id, _ = self.automaton.update(list(self.current_propositions))
                        
                        # 4. Store Data
                        self.timestamps.append(curr_time)
                        self.positions.append(curr_pos.tolist())
                        self.orientations.append(curr_ori)
                        self.linear_vels.append(vel_lin.tolist())
                        self.sensor_props.append(list(self.current_propositions))
                        self.mode_labels.append(mode_id)
                        
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
            "metadata": {
                "task": "cleaning_wiping",
                "freq": self.freq, 
                "source": "finite_difference_tf",
                "keypoints_ref": "cleaning_keypoints.json"  # Link to the source mesh!
            },
            "timestamps": norm_time,
            "positions": self.positions,
            "orientations": self.orientations,
            "velocities_lin": self.linear_vels,
            "propositions": self.sensor_props,
            "mode_labels": self.mode_labels
        }
        
        path = os.path.join(self.data_dir, "cleaning_demo_trajectory.json")
        with open(path, 'w') as f:
            json.dump(data, f, indent=4)
        rospy.loginfo(f"Saved {len(self.positions)} points to {path}")

if __name__ == '__main__':
    rec = CleaningDemoRecorder()
    rec.run()