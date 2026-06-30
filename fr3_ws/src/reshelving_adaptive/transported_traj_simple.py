#!/usr/bin/env python3
import json
import numpy as np
import os
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
            
        # 2. Load Demo Source Keypoints (The original 16 points from the demo)
        if not os.path.exists(source_kp_path):
            raise FileNotFoundError(f"Cannot find {source_kp_path}")
        with open(source_kp_path, 'r') as f:
            source_data = json.load(f)
            self.S_demo = self._get_ordered_keypoints(source_data)

        # 3. Extract Trajectory Components into fast Numpy arrays
        self.X_demo = np.array(self.demo_traj['positions'])
        self.Q_demo = np.array(self.demo_traj['orientations'])
        self.modes = np.array(self.demo_traj.get('mode_labels', self.demo_traj.get('modes')))

        if 'velocities_lin' in self.demo_traj:
            self.V_demo = np.array(self.demo_traj['velocities_lin'])
        else:
            print("[OnlineWarper] Warning: 'velocities_lin' not found. Using zeros.")
            self.V_demo = np.zeros_like(self.X_demo)

        print(f"[OnlineWarper] Ready. Loaded {len(self.X_demo)} points and {len(self.S_demo)} keypoints.")

    def _get_ordered_keypoints(self, data_dict):
        """Helper to ensure the 16 keypoints are always in the correct order."""
        if "order_reference" in data_dict:
            kp_map = {kp['label']: kp['coords'] for kp in data_dict['keypoints']}
            return np.array([kp_map[label] for label in data_dict['order_reference']])
        else:
            return np.array([kp['coords'] for kp in data_dict['keypoints']])
    
    def rotation_z(R_warp_matrix):
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

    def warp_mode(self, mode_id, live_target_kps):
        """
        Warps ONLY the requested mode segment to the new 16-point smudge coordinates.
        
        Args:
            mode_id: (int) The specific mode to warp (e.g., 2 for CLEAN)
            live_target_kps: (16, 3) array of the live mesh points from the camera
            
        Returns:
            Dictionary containing the warped 'positions', 'orientations', and 'velocities'.
        """
        # 1. Ensure live keypoints are a numpy array
        T_live = np.array(live_target_kps)
        
        # 2. Extract the segment of the trajectory belonging to this mode
        idx_seg = np.where(self.modes == mode_id)[0]
        if len(idx_seg) == 0:
            print(f"[OnlineWarper] Error: Mode {mode_id} not found in demo.")
            return None
            
        X_seg = self.X_demo[idx_seg]
        V_seg = self.V_demo[idx_seg]
        Q_seg = self.Q_demo[idx_seg]

        # 3. Global Affine Warping
        # This aligns the overall scale, rotation, and translation of the wipe
        affine = AffineWarper()
        affine.fit(self.S_demo, T_live)
        
        S_affine = affine.predict(self.S_demo)
        X_affine = affine.predict(X_seg) 
        R_aff = affine.get_jacobian() 
        V_affine = np.dot(V_seg, R_aff.T)

        # 4. GP Warping
        # Handles any non-linear surface variations (e.g., moving from a flat to curved board)
        kernel = C(1.0, constant_value_bounds='fixed') * RBF(length_scale=[0.2, 0.2, 0.3], length_scale_bounds='fixed')
        # gp = GPWarper(kernel=kernel, n_restarts_optimizer=2) 
        gp = GPWarper(kernel=kernel, alpha=1e-3, optimizer=None, normalize_y=False)
        gp.fit(S_affine, T_live)

        # 5. Apply Warp to Segment
        X_final, V_final, Q_final = [], [], []

        for i in range(len(X_affine)):
            x_curr = X_affine[i]
            v_curr = V_affine[i]
            q_curr = Q_seg[i]
            
            # Position Warp
            x_new = gp.predict(x_curr)
            X_final.append(x_new.tolist())
            
            # Velocity Warp (Jacobian)
            J_gp = gp.get_jacobian(x_curr)
            V_final.append(np.dot(J_gp, v_curr).tolist())
            
            J_final = np.einsum("ij,jk->ik", J_gp, R_aff)
            # C. Orientation
            R_warp, S_warp = polar(J_final)
            rot_orig = Rot.from_quat(q_curr)
            r_warp = Rot.from_matrix(R_warp)
            # r_warp   = rotation_z(R_warp)
            q_new = (r_warp * rot_orig).as_quat()
            Q_final.append(q_new.tolist())

        return {
            'positions': X_final,
            'orientations': Q_final,
            'velocities': V_final
        }
