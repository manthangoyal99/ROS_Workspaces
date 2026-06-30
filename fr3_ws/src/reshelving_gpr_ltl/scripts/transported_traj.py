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

# --- CONFIGURATION ---
DATA_DIR = "/home/ravi/fr3_ws/src/reshelving_gpr_ltl/data"
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
    if "order_reference" in data_dict:
        kp_map = {kp['label']: kp['coords'] for kp in data_dict['keypoints']}
        return np.array([kp_map[label] for label in data_dict['order_reference']])
    else:
        return np.array([kp['coords'] for kp in data_dict['keypoints']])

# ---------------------------------------------------------
# GENERIC ANCHOR GENERATOR
# ---------------------------------------------------------
def generate_mode_anchor(demo_traj, demo_modes, source_kps, target_kps, trigger_mode, kp_indices):
    """
    Generates a generic anchor pair for a specific mode transition.
    
    Args:
        demo_traj: (N, 3) Robot positions
        demo_modes: (N,) Mode labels
        source_kps: (K, 3) All source keypoints
        target_kps: (K, 3) All target keypoints
        trigger_mode: (int) The mode ID to search for (e.g., 2 for Pick)
        kp_indices: (slice) Which keypoints belong to the object of interest
                    (e.g., slice(0,4) for Bowl)
    
    Returns:
        anchor_src: (1, 3) or None
        anchor_tgt: (1, 3) or None
    """
    try:
        modes = np.array(demo_modes)
        # Find the START of the specific mode
        idx = np.where(modes == trigger_mode)[0][0]
    except IndexError:
        print(f"  [Warning] Mode {trigger_mode} not found. Skipping anchor.")
        return None, None

    # 1. Get Robot Switch Position
    p_demo_switch = np.array(demo_traj[idx])
    
    local_affine = AffineWarper()
    local_affine.fit(source_kps[kp_indices], target_kps[kp_indices])

    p_target_anchor = local_affine.predict(np.array([p_demo_switch]))

    
    print(f"  [Anchor Mode {trigger_mode}] Demo Switch Point: {p_demo_switch}, Target Anchor: {p_target_anchor}")
    
    return p_demo_switch, p_target_anchor

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
# ---------------------------------------------------------
# MAIN TRANSPORT FUNCTION
# ---------------------------------------------------------
def transport_demo():
    print("--- 1. Loading Data ---")
    source_data = load_json(SOURCE_KP_FILE)
    target_data = load_json(TARGET_KP_FILE)
    demo_traj = load_json(DEMO_TRAJ_FILE)

    S = get_ordered_keypoints(source_data)
    T = get_ordered_keypoints(target_data)
    
    X_demo = np.array(demo_traj['positions'])
    Q_demo = np.array(demo_traj['orientations'])
    modes = demo_traj.get('mode_labels', demo_traj.get('modes'))

    if 'velocities_lin' in demo_traj:
        V_demo = np.array(demo_traj['velocities_lin'])
    else:
        print("[Warning] 'velocities_lin' not found. Using zeros.")
        V_demo = np.zeros_like(X_demo)

    print(f"Loaded {len(X_demo)} trajectory points.")

    # --- 2. Generating Anchors (Pre-Affine) ---
    print("--- 2. Generating Anchors ---")
    
    anchors_src_list = []
    anchors_tgt_list = []

    if modes is not None:
        # A. PICK ANCHOR (Transition to Mode 2)
        # Assuming first 4 keypoints (0:4) are the BOWL
        a_src_pick, a_tgt_pick = generate_mode_anchor(
            X_demo, modes, S, T, 
            trigger_mode=2, 
            kp_indices=slice(0, 4)
        )
        if a_src_pick is not None:
            anchors_src_list.append(a_src_pick)
            anchors_tgt_list.append(a_tgt_pick)

        # B. PLACE ANCHOR (Transition to Mode 4)
        # Assuming last 4 keypoints (4:8) are the SHELF
        a_src_place, a_tgt_place = generate_mode_anchor(
            X_demo, modes, S, T, 
            trigger_mode=4, 
            kp_indices=slice(4, 8)
        )
        if a_src_place is not None:
            anchors_src_list.append(a_src_place)
            anchors_tgt_list.append(a_tgt_place)
    else:
        print("  [Info] No modes found. Skipping anchors.")

    # Stack Anchors onto Keypoints
    if anchors_src_list:
        S_aug = np.vstack([S, np.array(anchors_src_list)])
        T_aug = np.vstack([T, np.array(anchors_tgt_list)])
        print(f"  [Info] Augmented Keypoints: {len(S)} -> {len(S_aug)}")
    else:
        S_aug, T_aug = S, T
    # S_aug, T_aug = S, T
    # --- 3. Affine Warping (With Anchors) ---
    print("--- 3. Computing Affine Fit ---")
    affine = AffineWarper()
    # Now fitting on Source + Anchors -> Target + Anchors
    affine.fit(S_aug, T_aug)
    
    # Transform everything to Affine Space
    S_affine = affine.predict(S_aug) # Transformed KPs + Anchors
    X_affine = affine.predict(X_demo)
    
    R_aff = affine.get_jacobian() 
    V_affine = np.dot(V_demo, R_aff.T)

    # --- 4. GP Warping ---
    print("--- 4. Computing GP Fit ---")
    
    # We train the GP on the EXACT same augmented set.
    # Input: Affine-Transformed Source KPs + Anchors
    # Output: Real Target KPs + Anchors
    gp_train_source = S_affine
    gp_train_target = T_aug # The GP target is the real world target

    # Define Kernel
    kernel = C(1.0) * RBF(length_scale=0.2) + WhiteKernel(noise_level=1e-5)
    gp = GPWarper(kernel=kernel, n_restarts_optimizer=5)
    gp.fit(gp_train_source, gp_train_target)

    # Visualization Data
    S_final = []
    for i in range(len(S_affine)):
        S_final.append(gp.predict(S_affine[i]).tolist())
    S_final = np.array(S_final)

    # --- 5. Warping Trajectory ---
    print("--- 5. Generating Warped Path ---")
    X_final = []
    V_final = []
    Q_final = []

    for i in range(len(X_affine)):
        x_curr = X_affine[i]
        v_curr = V_affine[i]    
        q_curr = Q_demo[i]
        
        # A. Position
        x_new = gp.predict(x_curr)
        X_final.append(x_new.tolist())
        
        # B. Velocity
        J_gp = gp.get_jacobian(x_curr)
        v_new = np.dot(J_gp, v_curr)
        V_final.append(v_new.tolist())
        
        J_final = np.einsum("ij,jk->ik", J_gp, R_aff)
        # C. Orientation
        R_warp, S_warp = polar(J_final)
        rot_warp = Rot.from_matrix(R_warp)
        rot_orig = Rot.from_quat(q_curr)
        q_new = (rot_warp * rot_orig).as_quat()
        # r_warp   = rotation_z(R_warp)
        Q_final.append(q_new.tolist())

    # --- 6. Save Result ---
    affine_traj = copy.deepcopy(demo_traj)
    warped_traj = copy.deepcopy(demo_traj)

    affine_traj['positions'] = X_affine.tolist()
    affine_traj['velocities_lin'] = V_affine.tolist()
    affine_traj['orientations'] = Q_demo.tolist()
    affine_traj['metadata']['source'] = "policy_transportation_affine_anchored"

    warped_traj['positions'] = X_final
    warped_traj['velocities_lin'] = V_final
    warped_traj['orientations'] = Q_final
    warped_traj['metadata']['source'] = "policy_transportation_gp_anchored"
    
    save_json(warped_traj, OUTPUT_FILE)
    save_json(affine_traj, AFFINE_TRAJ_FILE)
    # Save the augmented keypoints used for debug
    save_json(S_affine.tolist(), SOURCE_AFFINE_FILE)
    save_json(S_final.tolist(), SOURCE_FINAL_FILE)

if __name__ == "__main__":
    transport_demo()