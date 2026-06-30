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

import sys

# Ensure this directory is in sys.path so we can import affine_transform and warping_transform
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

def load_json(filename, data_dir=DATA_DIR):
    path = os.path.join(data_dir, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Cannot find {path}")
    with open(path, 'r') as f:
        return json.load(f)

def save_json(data, filename, data_dir=DATA_DIR):
    path = os.path.join(data_dir, filename)
    with open(path, 'w') as f:
        json.dump(data, f, indent=4)
    print(f"[Success] Saved json to: {path}")

def extract_keypoints(data_dict):
    """
    Robustly extracts keypoints. Supports both the new start/goal structure
    and the old order_reference list structure.
    """
    if "start" in data_dict and "goal" in data_dict:
        # Stack the start (object bounding box) and goal (EE pos) vertically
        S_start = np.array(data_dict["start"])
        S_goal = np.array(data_dict["goal"])
        # Handle cases where goal is a single point or array
        if S_goal.ndim == 1:
            S_goal = S_goal.reshape(1, 3)
        return np.vstack((S_start, S_goal))
    elif "order_reference" in data_dict:
        kp_map = {kp['label']: kp['coords'] for kp in data_dict['keypoints']}
        return np.array([kp_map[label] for label in data_dict['order_reference']])
    elif "keypoints" in data_dict:
        kp_data = data_dict['keypoints']
        if len(kp_data) > 0 and isinstance(kp_data[0], dict) and 'coords' in kp_data[0]:
            return np.array([kp['coords'] for kp in kp_data])
        else:
            return np.array(kp_data)
    else:
        # Assume it's already a list of coordinates
        return np.array(data_dict)

def transport_trajectory(target_keypoints, source_data, demo_traj):
    S = extract_keypoints(source_data)
    T = extract_keypoints(target_keypoints)
    
    if S.shape != T.shape:
        raise ValueError(f"Shape mismatch: Source keypoints {S.shape} vs Target keypoints {T.shape}")

    # Extract Trajectory Components
    X_demo = np.array(demo_traj['positions'])
    Q_demo = np.array(demo_traj['orientations'])
    
    if 'velocities_lin' in demo_traj:
        V_demo = np.array(demo_traj['velocities_lin'])
    else:
        print("[Warning] 'velocities_lin' not found in demo. Using zeros.")
        V_demo = np.zeros_like(X_demo)

    print(f"Loaded {len(X_demo)} trajectory points. Keypoint dimensions: {S.shape}")

    # --- 2. Affine Warping (Global Alignment) ---
    print("--- 2. Computing Affine Fit ---")
    affine = AffineWarper()
    affine.fit(S, T)
    S_affine = affine.predict(S)
    
    # --- 3. GP Warping (Local Deformation) ---
    print("--- 3. Computing GP Fit ---")
    kernel = C(1.0) * RBF(length_scale=0.2) + WhiteKernel(noise_level=1e-5)
    gp = GPWarper(kernel=kernel, n_restarts_optimizer=5)
    gp.fit(S_affine, T)

    S_final = []
    for i in range(len(S_affine)):
        s_curr = S_affine[i]
        s_new = gp.predict(s_curr)
        S_final.append(s_new.tolist())
    S_final = np.array(S_final)

    # Apply Affine Transforms
    X_affine = affine.predict(X_demo)
    R = affine.get_jacobian()
    V_affine = np.dot(V_demo, R.T)

    # --- 4. Warping Trajectory & Velocities ---
    print("--- 4. Generating Warped Path ---")
    X_final = []
    V_final = []
    Q_final = []

    for i in range(len(X_affine)):
        x_curr = X_affine[i]
        v_curr = V_affine[i]
        q_curr = Q_demo[i]
        
        x_new = gp.predict(x_curr)
        X_final.append(x_new.tolist())
        
        J_gp = gp.get_jacobian(x_curr)
        v_new = np.dot(J_gp, v_curr)
        V_final.append(v_new.tolist())
        
        J_final = np.einsum("ij,jk->ik", J_gp, R)
        R_warp, S_warp = polar(J_final)
        rot_warp = Rot.from_matrix(R_warp)
        rot_orig = Rot.from_quat(q_curr)
        q_new = (rot_warp * rot_orig).as_quat()
        Q_final.append(q_new.tolist())

    # --- 5. Return and Save Result ---
    affine_traj = copy.deepcopy(demo_traj)
    warped_traj = copy.deepcopy(demo_traj)

    affine_traj['positions'] = X_affine.tolist()
    affine_traj['velocities_lin'] = V_affine.tolist()
    affine_traj['orientations'] = Q_demo.tolist()
    if 'metadata' not in affine_traj:
        affine_traj['metadata'] = {}
    if 'metadata' not in warped_traj:
        warped_traj['metadata'] = {}
        
    affine_traj['metadata']['source'] = "policy_transportation_affine"

    warped_traj['positions'] = X_final
    warped_traj['velocities_lin'] = V_final
    warped_traj['orientations'] = Q_final
    warped_traj['metadata']['source'] = "policy_transportation"
    
    return warped_traj, affine_traj, S_affine, S_final

if __name__ == "__main__":
    # Test block for standalone execution
    # Loads target_keypoints.json assuming it exists in the data directory
    print("Running in standalone demo mode...")
    try:
        target_data = load_json("target_keypoints.json", DATA_DIR)
        source_data = load_json("source_keypoints.json", DATA_DIR)
        demo_traj = load_json("demo_trajectory.json", DATA_DIR)
        warped_traj, affine_traj, S_affine, S_final = transport_trajectory(target_data, source_data, demo_traj)
        save_json(warped_traj, "warped_trajectory.json", DATA_DIR)
    except Exception as e:
        print(f"Error in standalone mode: {e}")
