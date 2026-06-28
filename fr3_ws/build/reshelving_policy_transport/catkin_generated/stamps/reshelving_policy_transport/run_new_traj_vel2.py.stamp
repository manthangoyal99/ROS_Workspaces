#!/usr/bin/env python3

import rospy
import numpy as np
import json
import os
import tf2_ros
from geometry_msgs.msg import TwistStamped, PoseStamped, Point
from visualization_msgs.msg import Marker, MarkerArray # <--- NEW IMPORTS
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C, WhiteKernel

class GPVelocityAttractor:
    def __init__(self):
        rospy.init_node('gp_velocity_attractor')

        # --- CONFIGURATION ---
        default_path = "/home/ravi/fr3_ws/src/reshelving_policy_transport/data/demo_trajectory.json"
        self.data_path = rospy.get_param("~traj_file", default_path) 
        self.link_base = "panda_link0"
        self.link_ee = "panda_EE"
        
        # --- PUBLISHERS ---
        self.twist_pub = rospy.Publisher(
            '/cartesian_velocity_impedance_example_controller/equilibrium_twist', 
            TwistStamped, queue_size=1)
        
        # NEW: Visualization Publisher
        self.marker_pub = rospy.Publisher('/gp_vector_field', MarkerArray, queue_size=1, latch=True)

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)

        # --- LOAD & TRAIN ---
        if not self.load_and_train_gp():
            rospy.logerr("Failed to initialize GP. Node will shut down.")
            return

        # --- VISUALIZE ONCE ---
        rospy.loginfo("Generating 3D Vector Field in RViz...")
        # self.publish_vector_field()
        self.publish_streamlines()

        # --- CONTROL LOOP ---
        self.rate = rospy.Rate(50) 
        self.run_loop()

    def load_and_train_gp(self):
        if not os.path.exists(self.data_path):
            rospy.logerr(f"FILE NOT FOUND: {self.data_path}")
            return False

        try:
            with open(self.data_path, 'r') as f:
                data = json.load(f)

            X_train = np.array(data['positions'])
            Y_train = np.array(data['velocities_lin'])
            self.train_positions = X_train

            # Increase length scale to 0.25 or 0.35 to avoid "dead zones"
            kernel = C(1.0) * RBF(length_scale=0.3) + WhiteKernel(noise_level=1e-5)

            rospy.loginfo("Training Gaussian Process...")
            self.gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=0, normalize_y=True)
            self.gp.fit(X_train, Y_train)
            rospy.loginfo("GP Training Complete.")
            
            return True
        except Exception as e:
            rospy.logerr(f"Error during GP training: {e}")
            return False
    
    def publish_streamlines(self):
        """
        Simulates 'virtual particles' moving through the GP field.
        Highlights the 'True Start' particle in WHITE/THICK.
        """
        marker_array = MarkerArray()
        
        # 1. Define Start Points
        start_center = self.train_positions[0]
        
        # The list starts with the EXACT True Start, followed by random neighbors
        starts = [start_center]
        
        # Add 20 random neighbors around the start
        padding = 0.15
        for _ in range(20):
            offset = np.random.uniform(-padding, padding, 3)
            starts.append(start_center + offset)
        
        id_counter = 0
        
        for i, start_pos in enumerate(starts):
            marker = Marker()
            marker.header.frame_id = self.link_base
            marker.header.stamp = rospy.Time.now()
            marker.ns = "gp_streamlines"
            marker.id = id_counter
            marker.type = Marker.LINE_STRIP
            marker.action = Marker.ADD
            marker.color.a = 0.8
            
            # --- HIGHLIGHT LOGIC ---
            if i == 0:
                # TRUE PATH: White and Thick
                marker.scale.x = 0.01  # 1cm thick
                marker.color.r = 1.0
                marker.color.g = 0.0
                marker.color.b = 0.0
                marker.lifetime = rospy.Duration(0) # Forever
            else:
                # NEIGHBORS: Cyan and Thin
                marker.scale.x = 0.002 # 2mm thin
                marker.color.r = 0.0
                marker.color.g = 1.0
                marker.color.b = 1.0
                marker.lifetime = rospy.Duration(0)

            # 2. Integrate the Path
            curr = start_pos.copy()
            
            # Simulate for 200 steps (longer trace)
            for step in range(100):
                p = Point(curr[0], curr[1], curr[2])
                marker.points.append(p)
                
                # Get Velocity
                vel = self.gp.predict(curr.reshape(1, -1)).flatten()
                
                speed = np.linalg.norm(vel)
                if speed > 0.001:
                    # Move particle
                    direction = vel / speed
                    curr += direction * 0.02 # 2cm steps
                else:
                    break # Stop at goal
            
            marker_array.markers.append(marker)
            id_counter += 1

        self.marker_pub.publish(marker_array)
        rospy.loginfo("Published Streamlines: WHITE = True Start, CYAN = Converging Neighbors")

    def publish_vector_field(self):
        """
        Creates a grid of arrows around the trajectory and publishes to RViz.
        """
        markers = MarkerArray()
        
        # 1. Define Grid Bounds (with padding)
        padding = 0.15
        x_min, x_max = self.train_positions[:,0].min()-padding, self.train_positions[:,0].max()+padding
        y_min, y_max = self.train_positions[:,1].min()-padding, self.train_positions[:,1].max()+padding
        z_min, z_max = self.train_positions[:,2].min()-padding, self.train_positions[:,2].max()+padding

        # 2. Create Grid Points (5x5x5 = 125 arrows)
        grid_x = np.linspace(x_min, x_max, 6)
        grid_y = np.linspace(y_min, y_max, 6)
        grid_z = np.linspace(z_min, z_max, 6)
        
        id_counter = 0
        
        for x in grid_x:
            for y in grid_y:
                for z in grid_z:
                    pos = np.array([x, y, z])
                    
                    # Predict Velocity
                    vel = self.gp.predict(pos.reshape(1, -1)).flatten()
                    speed = np.linalg.norm(vel)
                    
                    # Only draw if speed is significant
                    if speed > 0.05:
                        marker = Marker()
                        marker.header.frame_id = self.link_base
                        marker.header.stamp = rospy.Time.now()
                        marker.ns = "gp_field"
                        marker.id = id_counter
                        marker.type = Marker.ARROW
                        marker.action = Marker.ADD
                        
                        # Start Point
                        p_start = Point(x, y, z)
                        # End Point (scaled for visualization)
                        scale_vis = 1.2 # Length multiplier for visual
                        p_end = Point(x + vel[0]*scale_vis, y + vel[1]*scale_vis, z + vel[2]*scale_vis)
                        
                        marker.points.append(p_start)
                        marker.points.append(p_end)
                        
                        # Appearance (Red Arrows)
                        marker.scale.x = 0.005 # Shaft diameter
                        marker.scale.y = 0.01  # Head diameter
                        marker.scale.z = 0.0   # Head length (auto)
                        marker.color.a = 0.8
                        marker.color.r = 1.0
                        marker.color.g = 0.0
                        marker.color.b = 0.0
                        
                        markers.markers.append(marker)
                        id_counter += 1

        self.marker_pub.publish(markers)
        rospy.loginfo(f"Published {len(markers.markers)} field vectors to /gp_vector_field")

    def run_loop(self):
        rospy.loginfo("Starting Robust Control Loop...")
        
        # Get the Goal Position (last point of training data)
        goal_pos = self.train_positions[-1]
        
        while not rospy.is_shutdown():
            try:
                # 1. Get State
                trans = self.tf_buffer.lookup_transform(self.link_base, self.link_ee, rospy.Time(0))
                curr_pos = np.array([trans.transform.translation.x, trans.transform.translation.y, trans.transform.translation.z])

                # --- SAFETY 1: THE GOAL CLAMP ---
                # If we are close to the goal, STOP asking the GP. Just hold position.
                dist_to_goal = np.linalg.norm(curr_pos - goal_pos)
                
                if dist_to_goal < 0.02: # 2cm Threshold
                    rospy.loginfo_throttle(1.0, "Goal Reached. Holding...")
                    cmd_vel = np.zeros(3)
                
                else:
                    # 2. Predict Velocity AND Uncertainty (Sigma)
                    # We ask for standard deviation (return_std=True)
                    vel_pred, sigma = self.gp.predict(curr_pos.reshape(1, -1), return_std=True)
                    vel_pred = vel_pred.flatten()
                    
                    # --- SAFETY 2: THE UNCERTAINTY BRAKE ---
                    # If sigma is high, the robot is in an unknown area. Don't move!
                    # Typical sigma for "known" areas is < 0.1. "Unknown" is > 0.5 (depending on kernel)
                    # Adjust this threshold based on what you see in testing.
                    if sigma > 0.5: 
                        rospy.logwarn_throttle(0.5, f"Lost in space (Uncertainty: {sigma[0]:.2f}). Stopping.")
                        cmd_vel = np.zeros(3)
                    else:
                        # 3. Standard Logic (Normalize & Force Speed)
                        speed_magnitude = np.linalg.norm(vel_pred)
                        if speed_magnitude > 0.001: 
                            direction = vel_pred / speed_magnitude
                            cmd_vel = direction * 0.05 # Constant crawl speed
                        else:
                            cmd_vel = np.zeros(3)

                # 4. Publish
                twist_msg = TwistStamped()
                twist_msg.header.stamp = rospy.Time.now()
                twist_msg.header.frame_id = self.link_base
                twist_msg.twist.linear.x = cmd_vel[0]
                twist_msg.twist.linear.y = cmd_vel[1]
                twist_msg.twist.linear.z = cmd_vel[2]
                self.twist_pub.publish(twist_msg)

            except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException):
                pass
            
            self.rate.sleep()

if __name__ == "__main__":
    GPVelocityAttractor()