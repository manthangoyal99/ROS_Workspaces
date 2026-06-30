#!/usr/bin/env python3
import json
import numpy as np
import os
import copy
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C, WhiteKernel
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from scipy.linalg import polar
from scipy.spatial.transform import Rotation as Rot

# Import your helper classes
try:
    from affine_transform import AffineWarper
    from warping_transform import GPWarper
except ImportError as e:
    print("Error: Could not import AffineWarper or GPWarper.")
    print("Ensure 'affine_transform.py' and 'warping_transform.py' are in the same directory.")
    raise e

# --- CONFIGURATION ---
DATA_DIR ="/home/ravi/fr3_ws/src/reshelving_policy_transport/data"  # Or set a specific path like "./data"
SOURCE_KP_FILE = "source_keypoints.json"
TARGET_KP_FILE = "target_keypoints.json"
DEMO_TRAJ_FILE = "demo_trajectory.json"
OUTPUT_FILE = "warped_trajectory.json"
AFFINE_TRAJ_FILE = "affine_trajectory.json"
SOURCE_AFFINE_FILE = "source_affine_keypoints.json"
SOURCE_FINAL_FILE = "source_final_keypoints.json"

def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Cannot find {path}")
    with open(path, 'r') as f:
        return json.load(f)

def save_json(data, filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w') as f:
        json.dump(data, f, indent=4)
    print(f"[Success] Warped trajectory saved to: {path}")

def get_ordered_keypoints(data_dict):
    """
    Extracts keypoints in the order specified by 'order_reference' if it exists,
    otherwise assumes the list order is correct.
    """
    if "order_reference" in data_dict:
        # Map label -> coords
        kp_map = {kp['label']: kp['coords'] for kp in data_dict['keypoints']}
        # Return list ordered by reference
        return np.array([kp_map[label] for label in data_dict['order_reference']])
    else:
        # Fallback: just take them in order
        return np.array([kp['coords'] for kp in data_dict['keypoints']])

def transport_demo():
    print("--- 1. Loading Data ---")
    source_data = load_json(SOURCE_KP_FILE)
    target_data = load_json(TARGET_KP_FILE)
    demo_traj = load_json(DEMO_TRAJ_FILE)

    S = get_ordered_keypoints(source_data)
    T = get_ordered_keypoints(target_data)
    
    # Extract Trajectory Components
    # Note: demo_recorder usually saves positions as list of lists
    X_demo = np.array(demo_traj['positions'])
    Q_demo = np.array(demo_traj['orientations'])
    
    # robustly handle velocities (defaults to zero if missing)
    if 'velocities_lin' in demo_traj:
        V_demo = np.array(demo_traj['velocities_lin'])
    else:
        print("[Warning] 'velocities_lin' not found in demo. Using zeros.")
        V_demo = np.zeros_like(X_demo)

    print(f"Loaded {len(X_demo)} trajectory points.")

    # --- 2. Affine Warping (Global Alignment) ---
    print("--- 2. Computing Affine Fit ---")
    affine = AffineWarper()
    affine.fit(S, T)
    
    # Apply Affine to Source Keypoints (to learn residuals later)
    S_affine = affine.predict(S)
    
    # --- 3. GP Warping (Local Deformation) ---
    print("--- 3. Computing GP Fit ---")
    # Define Kernel: Constant * RBF + Noise
    # length_scale=0.2 is standard for table-top manipulation
    kernel = C(1.0) * RBF(length_scale=0.2) + WhiteKernel(noise_level=1e-5)
    
    gp = GPWarper(kernel=kernel, n_restarts_optimizer=5)
    
    # Learn mapping: Affine(Source) -> Target
    gp.fit(S_affine, T)

    S_final = []

    for i in range(len(S_affine)):
        s_curr = S_affine[i]
        s_new = gp.predict(s_curr)
        S_final.append(s_new.tolist())
    S_final = np.array(S_final)
    
    print("--- 2. Computing Affine Transform ---")

    # Apply Affine to Trajectory Positions
    X_affine = affine.predict(X_demo)
    
    # Apply Affine Rotation to Velocities
    # v_affine = R * v_demo
    R = affine.get_jacobian() # Constant Rotation Matrix
    V_affine = np.dot(V_demo, R.T)

    # --- 4. Warping Trajectory & Velocities ---
    print("--- 4. Generating Warped Path ---")
    X_final = []
    V_final = []
    Q_final = []

    for i in range(len(X_affine)):
        # Current Affine-Transformed State
        x_curr = X_affine[i]
        v_curr = V_affine[i]
        q_curr = Q_demo[i]
        
        # A. Position Warp: x_new = x + GP(x)
        x_new = gp.predict(x_curr)
        X_final.append(x_new.tolist())
        # B. Velocity Warp: v_new = J_gp(x) * v
        # J_gp is (I + dResidual/dx)
        J_gp = gp.get_jacobian(x_curr)
        v_new = np.dot(J_gp, v_curr)
        V_final.append(v_new.tolist())
        J_final = np.einsum("ij,jk->ik", J_gp, R)
        # C. Orientation
        R_warp, S_warp = polar(J_final)
        rot_warp = Rot.from_matrix(R_warp)
        rot_orig = Rot.from_quat(q_curr)
        q_new = (rot_warp * rot_orig).as_quat()
        # r_warp   = rotation_z(R_warp)
        Q_final.append(q_new.tolist())

    # --- 5. Save Result ---
    # We deepcopy to preserve metadata, gripper states, timestamps, etc.
    affine_traj = copy.deepcopy(demo_traj)
    warped_traj = copy.deepcopy(demo_traj)

    affine_traj['positions'] = X_affine.tolist()
    affine_traj['velocities_lin'] = V_affine.tolist()
    affine_traj['orientations'] = Q_demo.tolist()
    affine_traj['metadata']['source'] = "policy_transportation_affine"

    warped_traj['positions'] = X_final
    warped_traj['velocities_lin'] = V_final
    warped_traj['orientations'] = Q_final
    warped_traj['metadata']['source'] = "policy_transportation"
    
    save_json(warped_traj, OUTPUT_FILE)
    save_json(affine_traj, AFFINE_TRAJ_FILE)
    save_json(S_affine.tolist(), SOURCE_AFFINE_FILE)
    save_json(S_final.tolist(), SOURCE_FINAL_FILE)

if __name__ == "__main__":
    transport_demo()
