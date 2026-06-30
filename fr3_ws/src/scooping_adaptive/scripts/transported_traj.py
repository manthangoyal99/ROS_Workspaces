#!/usr/bin/env python3
import json
import numpy as np
import os
import copy
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C, WhiteKernel
from scipy.linalg import polar
from scipy.spatial.transform import Rotation as Rot

# Import your helper classes
try:
    from affine_transform import AffineWarper
    from warping_transform import GPWarper
except ImportError as e:
    print("Error: Could not import AffineWarper or GPWarper.")
    raise e

class OnlineTrajectoryWarper:
    def __init__(self, demo_traj_path, source_kp_path):
        """
        Initializes the warper by loading the static demo data into memory once.
        """
        print("[OnlineWarper] Loading Demo Data...")
        
        # 1. Load Demo Trajectory
        if not os.path.exists(demo_traj_path):
            raise FileNotFoundError(f"Cannot find {demo_traj_path}")
        with open(demo_traj_path, 'r') as f:
            self.demo_traj = json.load(f)
            
        # 2. Load Demo Source Keypoints (The original 8 points from the demo)
        if not os.path.exists(source_kp_path):
            raise FileNotFoundError(f"Cannot find {source_kp_path}")
        with open(source_kp_path, 'r') as f:
            source_data = json.load(f)
            self.S_demo = self._get_ordered_keypoints(source_data)

        # 3. Extract Trajectory Components into fast Numpy arrays
        self.X_demo = np.array(self.demo_traj['positions'])
        self.Q_demo = np.array(self.demo_traj['orientations'])
        self.modes = np.array(self.demo_traj.get('mode_labels', self.demo_traj.get('modes')))
        self.grippers = np.array(self.demo_traj.get('gripper_states', np.zeros(len(self.X_demo))))

        if 'velocities_lin' in self.demo_traj:
            self.V_demo = np.array(self.demo_traj['velocities_lin'])
        else:
            print("[OnlineWarper] Warning: 'velocities_lin' not found. Using zeros.")
            self.V_demo = np.zeros_like(self.X_demo)

        print(f"[OnlineWarper] Ready. Loaded {len(self.X_demo)} demo points.")

    def rotation_z(self, R_warp_matrix):
        """
        Filters a full 3D warping rotation to only apply heading (Z-axis) changes,
        preserving the tilt/pitch of the demonstration for spill-free transport.
        
        Args:
            R_warp_matrix: 3x3 numpy array, the rotation extracted from the Jacobian.
            
        Returns:
            R_target_matrix: 3x3 numpy array, the final constrained orientation.	
        """
        
        # 1. Convert the warping matrix to a Rotation object
        r_warp = Rot.from_matrix(R_warp_matrix)
        
        # 2. Extract Euler angles. 
        # 'ZYX' (intrinsic) or 'zxy' (extrinsic) isolates the global Z rotation first.
        # Returns [yaw (Z), pitch (Y), roll (X)]
        euler_angles = r_warp.as_euler('ZYX', degrees=False)
        
        # 3. Extract ONLY the Z-axis rotation (yaw)
        yaw_angle = euler_angles[0]
        
        # 4. Construct a new rotation matrix that ONLY rotates around Z
        r_z_only = Rot.from_euler('z', yaw_angle, degrees=False)
        
        return r_z_only

    def _get_ordered_keypoints(self, data_dict):
        """Helper to ensure keypoints are always in the correct order."""
        if "order_reference" in data_dict:
            kp_map = {kp['label']: kp['coords'] for kp in data_dict['keypoints']}
            return np.array([kp_map[label] for label in data_dict['order_reference']])
        else:
            return np.array([kp['coords'] for kp in data_dict['keypoints']])

    def _generate_mode_anchor(self, live_kps, trigger_mode, kp_indices):
        """
        Generates a rotation-aware anchor pair for a specific mode transition
        using a local Affine transformation.
        """
        try:
            # Find the exact index where the requested mode begins in the demo
            idx = np.where(self.modes == trigger_mode)[0][0]
        except IndexError:
            return None, None

        # 1. Get the original switch position (Source Anchor)
        p_demo_switch = self.X_demo[idx]
        
        # 2. Extract ONLY the keypoints for the object we are interacting with
        # (e.g., just the 4 shelf keypoints)
        local_demo_kps = self.S_demo[kp_indices]
        local_live_kps = live_kps[kp_indices]
        
        # 3. Compute a LOCAL Affine Transformation
        # This captures the exact Rotation, Translation, and Scale of just this object
        local_affine = AffineWarper()
        local_affine.fit(local_demo_kps, local_live_kps)
        
        # 4. Transform the switch position using this local mapping
        # predict() expects a 2D array, so we wrap it in np.array() and extract [0]
        p_target_anchor = local_affine.predict(np.array([p_demo_switch]))
        
        # (Optional) For debugging, you can print the rotation matrix applied
        # R_local = local_affine.get_jacobian()
        # print(f"  [Anchor Mode {trigger_mode}] Local Rotation Applied:\n{R_local}")
        
        return p_demo_switch, p_target_anchor

    def warp_mode(self, mode_id, live_source_kps, live_target_kps):
        """
        Warps ONLY the requested mode segment to the new real-world coordinates.
        
        Args:
            mode_id: (int) The specific mode to warp (e.g., 1, 2, 3, 4)
            live_source_kps: (4, 3) array of the current Object keypoints
            live_target_kps: (4, 3) array of the current Shelf keypoints
            
        Returns:
            Dictionary containing the warped 'positions', 'orientations', 
            'velocities', and 'gripper_states' for that specific mode.
        """
        # 1. Stack the live keypoints into an 8-point array to match S_demo
        T_live = np.vstack((live_source_kps, live_target_kps))
        
        # 2. Extract the segment of the trajectory belonging to this mode
        idx_seg = np.where(self.modes == mode_id)[0]
        if len(idx_seg) == 0:
            print(f"[OnlineWarper] Error: Mode {mode_id} not found in demo.")
            return None
            
        X_seg = self.X_demo[idx_seg]
        V_seg = self.V_demo[idx_seg]
        Q_seg = self.Q_demo[idx_seg]
        grip_seg = self.grippers[idx_seg]

        # 3. Generate Anchors based on the Live Keypoints
        anchors_src_list, anchors_tgt_list = [], []

        # Pick Anchor (Mode 2) -> Reference object is indices 0:4
        a_src_pick, a_tgt_pick = self._generate_mode_anchor(T_live, trigger_mode=2, kp_indices=slice(0, 4))
        if a_src_pick is not None:
            anchors_src_list.append(a_src_pick)
            anchors_tgt_list.append(a_tgt_pick)

        # Place Anchor (Mode 4) -> Reference object is indices 4:8
        a_src_place, a_tgt_place = self._generate_mode_anchor(T_live, trigger_mode=4, kp_indices=slice(4, 8))
        if a_src_place is not None:
            anchors_src_list.append(a_src_place)
            anchors_tgt_list.append(a_tgt_place)

        # Stack Anchors onto Keypoints
        if anchors_src_list:
            S_aug = np.vstack([self.S_demo, np.array(anchors_src_list)])
            T_aug = np.vstack([T_live, np.array(anchors_tgt_list)])
        else:
            S_aug, T_aug = self.S_demo, T_live

        # 4. Affine Warping
        affine = AffineWarper()
        affine.fit(S_aug, T_aug)
        
        S_affine = affine.predict(S_aug)
        X_affine = affine.predict(X_seg) # Only predict the requested segment!
        R_aff = affine.get_jacobian() 
        V_affine = np.dot(V_seg, R_aff.T)

        # 5. GP Warping
        # Use fewer restarts for speed during online execution
        # kernel = C(1.0) * RBF(length_scale=0.4) + WhiteKernel(noise_level=1e-5)
        # gp = GPWarper(kernel=kernel, n_restarts_optimizer=2) 
        kernel = C(1.0, constant_value_bounds='fixed') * RBF(length_scale=[0.2, 0.2, 0.2], length_scale_bounds='fixed')
        gp = GPWarper(kernel=kernel, alpha=1e-3, optimizer=None, normalize_y=False)
        gp.fit(S_affine, T_aug)

        # 6. Apply Warp to Segment
        X_final, V_final, Q_final = [], [], []

        for i in range(len(X_affine)):
            x_curr = X_affine[i]
            v_curr = V_affine[i]
            q_curr = Q_seg[i]
            
            # Position
            x_new = gp.predict(x_curr)
            X_final.append(x_new.tolist())
            
            # Velocity
            J_gp = gp.get_jacobian(x_curr)
            V_final.append(np.dot(J_gp, v_curr).tolist())
            
            J_final = np.einsum("ij,jk->ik", J_gp, R_aff)
            # C. Orientation
            R_warp, S_warp = polar(J_final)
            # rot_warp = Rot.from_matrix(R_warp)
            rot_warp   = self.rotation_z(R_warp)
            rot_orig = Rot.from_quat(q_curr)
            q_new = (rot_warp * rot_orig).as_quat()
            Q_final.append(q_new.tolist())
            # Q_final.append((rot_warp * rot_orig).as_quat().tolist())

        return {
            'positions': X_final,
            'orientations': Q_final,
            'velocities': V_final,
            'gripper_states': grip_seg.tolist()
        }
