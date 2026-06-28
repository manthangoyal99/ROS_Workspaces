#!/usr/bin/env python3
import json
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from scipy.spatial.transform import Rotation as Rot
import os
DATA_DIR ="/home/ravi/fr3_ws/src/cleaning_adaptive/data" 
def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"Warning: {path} not found.")
        return None
    with open(path, 'r') as f:
        return json.load(f)

def get_keypoint_array(json_data):
    """Extracts coordinate array from keypoint dictionary"""
    if json_data is None or 'keypoints' not in json_data:
        return np.empty((0, 3))
    
    # If there is a specific order reference, follow it
    if 'order_reference' in json_data:
        kp_map = {kp['label']: kp['coords'] for kp in json_data['keypoints']}
        try:
            return np.array([kp_map[label] for label in json_data['order_reference']])
        except KeyError:
            pass # Fallback to default order if labels don't match

    # Default: just take them in order
    return np.array([kp['coords'] for kp in json_data['keypoints']])

def plot_orientations(ax, positions, orientations, step=10, scale=0.05, alpha=0.6):
    """Plots RGB coordinate frames at sampled points."""
    for i in range(0, len(positions), step):
        p = positions[i]
        q = orientations[i] # [x, y, z, w]
        R = Rot.from_quat(q).as_matrix()
        
        # Plot Quivers: X=Red, Y=Green, Z=Blue
        ax.quiver(p[0], p[1], p[2], R[0,0], R[1,0], R[2,0], length=scale, color='red', alpha=alpha)
        ax.quiver(p[0], p[1], p[2], R[0,1], R[1,1], R[2,1], length=scale, color='green', alpha=alpha)
        ax.quiver(p[0], p[1], p[2], R[0,2], R[1,2], R[2,2], length=scale, color='blue', alpha=alpha)

def main():
    # 1. Load All Data
    demo_data = load_json('cleaning_demo_trajectory.json')
    warp_data = load_json('warped_trajectory.json')
    affine_data = load_json('affine_trajectory.json')
    source_keypoints = load_json('cleaning_keypoints.json')
    target_keypoints = load_json('target_keypoints.json')
    source_affine_keypoints = load_json('source_affine_keypoints.json')
    source_final_keypoints = load_json('source_final_keypoints.json')

    if demo_data is None or warp_data is None or affine_data is None:
        print("Error: Missing trajectory data. Cannot visualize.")
        return

    # 2. Extract Trajectories
    demo_pos = np.array(demo_data['positions'])
    demo_ori = np.array(demo_data['orientations'])
    warp_pos = np.array(warp_data['positions'])
    warp_ori = np.array(warp_data['orientations'])
    affine_pos = np.array(affine_data['positions'])
    affine_ori = np.array(affine_data['orientations'])


    # 3. Extract Keypoints
    S_kp = get_keypoint_array(source_keypoints)
    T_kp = get_keypoint_array(target_keypoints)
    S_affine_kp = np.array(source_affine_keypoints)
    S_final_kp = np.array(source_final_keypoints)

    print(S_affine_kp)
    print(f"Final Keypoints: {len(S_final_kp)} points")
        # 4. Setup Plot
    fig = plt.figure(figsize=(14, 10))
    ax = fig.add_subplot(111, projection='3d')

    # --- PLOT TRAJECTORIES ---
    # ax.plot(demo_pos[:,0], demo_pos[:,1], demo_pos[:,2], 
    #         label='Original Demo', color='blue', linewidth=2, alpha=0.5)
    
    # ax.plot(affine_pos[:,0], affine_pos[:,1], affine_pos[:,2], 
    #         label='Affine Warped Policy', color='darkorange', linewidth=2)

    # --- PLOT KEYPOINTS ---
    # Source Keypoints (Cyan) - Correspond to Blue Line
    if S_kp.shape[0] > 0:
        ax.scatter(S_kp[:,0], S_kp[:,1], S_kp[:,2], 
                   c='cyan', marker='o', s=80, edgecolors='k', label='Source Keypoints')

    # Target Keypoints (Magenta) - Correspond to Orange Line
    if T_kp.shape[0] > 0:
        ax.scatter(T_kp[:,0], T_kp[:,1], T_kp[:,2], 
                   c='magenta', marker='^', s=100, edgecolors='k', label='Target Keypoints')
    
    if S_affine_kp.shape[0] > 0:
        ax.scatter(S_affine_kp[:,0], S_affine_kp[:,1], S_affine_kp[:,2], 
                   c='orange', marker='s', s=80, edgecolors='k', label='Source Affine Keypoints')
        
        # Optional: Draw lines connecting corresponding keypoints to visualize the shift
        # for s, t in zip(S_kp, T_kp):
        #     ax.plot([s[0], t[0]], [s[1], t[1]], [s[2], t[2]], color='gray', linestyle='--', alpha=0.3)

    # --- PLOT ORIENTATIONS ---
    print("Plotting frames... (Red=X, Green=Y, Blue=Z)")
    # plot_orientations(ax, demo_pos, demo_ori, step=25, scale=0.05, alpha=0.3)
    # plot_orientations(ax, warp_pos, warp_ori, step=25, scale=0.05, alpha=0.8)

    # Labels & Legend
    ax.set_xlabel('X (m)')
    ax.set_ylabel('Y (m)')
    ax.set_zlabel('Z (m)')
    ax.set_title("Policy Transportation Verification\n(Cyan=Old Shelf, Magenta=New Shelf)")
    ax.legend()
    
    plt.show()

    # 4. Setup Plot
    fig = plt.figure(figsize=(14, 10))
    ax = fig.add_subplot(111, projection='3d')

    # --- PLOT TRAJECTORIES ---
    ax.plot(affine_pos[:,0], affine_pos[:,1], affine_pos[:,2], 
            label='Original Demo', color='blue', linewidth=2, alpha=2)
    
    ax.plot(warp_pos[:,0], warp_pos[:,1], warp_pos[:,2], 
            label='Warped Policy', color='darkorange', linewidth=2)

    # --- PLOT KEYPOINTS ---
    # Source Keypoints (Cyan) - Correspond to Blue Line
    if S_kp.shape[0] > 0:
        ax.scatter(S_affine_kp[:,0], S_affine_kp[:,1], S_affine_kp[:,2], 
                   c='cyan', marker='o', s=80, edgecolors='k', label='Affine_Keypoints')

    # Target Keypoints (Magenta) - Correspond to Orange Line
    if T_kp.shape[0] > 0:
        ax.scatter(T_kp[:,0], T_kp[:,1], T_kp[:,2], 
                   c='magenta', marker='^', s=100, edgecolors='k', label='Target Keypoints')
        
    if S_final_kp.shape[0] > 0:
        ax.scatter(S_final_kp[:,0], S_final_kp[:,1], S_final_kp[:,2], 
                   c='green', marker='d', s=80, edgecolors='k', label='Source Final Keypoints')
        
        # Optional: Draw lines connecting corresponding keypoints to visualize the shift
        # for s, t in zip(S_kp, T_kp):
        #     ax.plot([s[0], t[0]], [s[1], t[1]], [s[2], t[2]], color='gray', linestyle='--', alpha=0.3)

    # --- PLOT ORIENTATIONS ---
    print("Plotting frames... (Red=X, Green=Y, Blue=Z)")
    plot_orientations(ax, affine_pos, affine_ori, step=100, scale=0.05, alpha=0.3)
    plot_orientations(ax, warp_pos, warp_ori, step=100, scale=0.05, alpha=0.8)

    # Labels & Legend
    ax.set_xlabel('X (m)')
    ax.set_ylabel('Y (m)')
    ax.set_zlabel('Z (m)')
    ax.set_title("Policy Transportation Verification\n(Cyan=Old Shelf, Magenta=New Shelf)")
    ax.legend()
    
    # # Auto-scaling logic
    # all_points = np.vstack((demo_pos, warp_pos, S_kp, T_kp))
    # max_range = (all_points.max(axis=0) - all_points.min(axis=0)).max() / 2.0
    # mid = (all_points.max(axis=0) + all_points.min(axis=0)) * 0.5
    # ax.set_xlim(mid[0] - max_range, mid[0] + max_range)
    # ax.set_ylim(mid[1] - max_range, mid[1] + max_range)
    # ax.set_zlim(mid[2] - max_range, mid[2] + max_range)

    plt.show()

if __name__ == "__main__":
    main()

# #!/usr/bin/env python3
# import json
# import numpy as np
# import matplotlib.pyplot as plt
# from mpl_toolkits.mplot3d import Axes3D
# from scipy.spatial.transform import Rotation as Rot
# import os

# # --- CONFIGURATION ---
# DATA_DIR = "/home/ravi/fr3_ws/src/reshelving_policy_transport/data"

# def load_json(filename):
#     path = os.path.join(DATA_DIR, filename)
#     if not os.path.exists(path):
#         print(f"Warning: {path} not found.")
#         return None
#     with open(path, 'r') as f:
#         return json.load(f)

# def get_keypoint_array(json_data):
#     """Extracts coordinate array from keypoint dictionary"""
#     if json_data is None or 'keypoints' not in json_data:
#         return np.empty((0, 3))
    
#     # If there is a specific order reference, follow it
#     if 'order_reference' in json_data:
#         kp_map = {kp['label']: kp['coords'] for kp in json_data['keypoints']}
#         try:
#             return np.array([kp_map[label] for label in json_data['order_reference']])
#         except KeyError:
#             pass # Fallback to default order

#     # Default: just take them in order
#     return np.array([kp['coords'] for kp in json_data['keypoints']])

# def plot_orientations(ax, positions, orientations, step=10, scale=0.05, alpha=0.6):
#     """Plots RGB coordinate frames at sampled points."""
#     if len(positions) != len(orientations): return

#     for i in range(0, len(positions), step):
#         p = positions[i]
#         q = orientations[i] # [x, y, z, w]
#         R = Rot.from_quat(q).as_matrix()
        
#         # Plot Quivers: X=Red, Y=Green, Z=Blue
#         ax.quiver(p[0], p[1], p[2], R[0,0], R[1,0], R[2,0], length=scale, color='red', alpha=alpha)
#         ax.quiver(p[0], p[1], p[2], R[0,1], R[1,1], R[2,1], length=scale, color='green', alpha=alpha)
#         ax.quiver(p[0], p[1], p[2], R[0,2], R[1,2], R[2,2], length=scale, color='blue', alpha=alpha)

# def plot_velocities(ax, positions, velocities, step=10, scale=1.0, color='black'):
#     """
#     Plots velocity vectors as arrows.
#     scale: Multiplier for arrow length (since velocities might be small in magnitude)
#     """
#     if len(positions) != len(velocities): return

#     # Subsample for plotting
#     indices = range(0, len(positions), step)
#     pos_sub = positions[indices]
#     vel_sub = velocities[indices]

#     # Quiver expects X, Y, Z, U, V, W
#     # We allow matplotlib to normalize the arrows, but we use length to indicate magnitude
#     ax.quiver(pos_sub[:,0], pos_sub[:,1], pos_sub[:,2], 
#               vel_sub[:,0], vel_sub[:,1], vel_sub[:,2], 
#               length=scale, color=color, alpha=0.8, arrow_length_ratio=0.3, normalize=False)

# def plot_speed_profile(velocities, timestamps=None, title="Speed Profile"):
#     """Plots the magnitude of velocity over time/index"""
#     speeds = np.linalg.norm(velocities, axis=1)
    
#     plt.figure(figsize=(10, 4))
#     if timestamps is not None and len(timestamps) == len(speeds):
#         plt.plot(timestamps, speeds, label='Linear Speed', color='black')
#         plt.xlabel('Time (s)')
#     else:
#         plt.plot(speeds, label='Linear Speed', color='black')
#         plt.xlabel('Sample Index')
        
#     plt.ylabel('Speed (m/s)')
#     plt.title(title)
#     plt.grid(True)
#     plt.legend()

# def main():
#     # 1. Load Data
#     demo_data = load_json('demo_trajectory.json')
#     warp_data = load_json('warped_trajectory.json')
#     source_data = load_json('source_keypoints.json')
#     target_data = load_json('target_keypoints.json')

#     if warp_data is None:
#         return

#     # 2. Extract Trajectories
#     warp_pos = np.array(warp_data['positions'])
#     warp_ori = np.array(warp_data['orientations'])
    
#     # Extract Velocities (Handle missing case)
#     if 'velocities_lin' in warp_data:
#         warp_vel = np.array(warp_data['velocities_lin'])
#     else:
#         print("Warning: 'velocities_lin' not found in warped trajectory!")
#         warp_vel = np.zeros_like(warp_pos)

#     # Extract Source/Target Keypoints
#     S_kp = get_keypoint_array(source_data)
#     T_kp = get_keypoint_array(target_data)

#     # 3. Setup 3D Plot
#     fig = plt.figure(figsize=(14, 10))
#     ax = fig.add_subplot(111, projection='3d')

#     # --- Plot Warped Path ---
#     ax.plot(warp_pos[:,0], warp_pos[:,1], warp_pos[:,2], 
#             label='Warped Policy', color='darkorange', linewidth=3)
    
#     # Plot Original Demo (Ghost) if available
#     if demo_data:
#         demo_pos = np.array(demo_data['positions'])
#         ax.plot(demo_pos[:,0], demo_pos[:,1], demo_pos[:,2], 
#                 label='Original Demo', color='blue', linewidth=1, alpha=0.3, linestyle='--')

#     # --- Plot Keypoints ---
#     if S_kp.shape[0] > 0:
#         ax.scatter(S_kp[:,0], S_kp[:,1], S_kp[:,2], c='cyan', marker='o', s=50, alpha=0.5, label='Source KP')
#     if T_kp.shape[0] > 0:
#         ax.scatter(T_kp[:,0], T_kp[:,1], T_kp[:,2], c='magenta', marker='^', s=100, edgecolors='k', label='Target KP')

#     # --- Plot Orientations (Frames) ---
#     # print("Plotting orientation frames...")
#     # plot_orientations(ax, warp_pos, warp_ori, step=30, scale=0.04)

#     # --- PLOT VELOCITIES (New Feature) ---
#     print("Plotting velocity vectors (Black Arrows)...")
#     # Scale factor: If typical velocity is 0.1 m/s, scale=0.5 makes arrows 5cm long
#     plot_velocities(ax, warp_pos, warp_vel, step=20, scale=0.5, color='black')

#     # Labels & Limits
#     ax.set_xlabel('X'); ax.set_ylabel('Y'); ax.set_zlabel('Z')
#     ax.set_title("Warped Trajectory with Velocity Vectors")
#     ax.legend()
    
#     # Auto-scaling
#     all_points = np.vstack([warp_pos, T_kp]) if T_kp.shape[0]>0 else warp_pos
#     max_range = (all_points.max(axis=0) - all_points.min(axis=0)).max() / 2.0
#     mid = (all_points.max(axis=0) + all_points.min(axis=0)) * 0.5
#     ax.set_xlim(mid[0] - max_range, mid[0] + max_range)
#     ax.set_ylim(mid[1] - max_range, mid[1] + max_range)
#     ax.set_zlim(mid[2] - max_range, mid[2] + max_range)

#     # 4. Show 2D Speed Profile
#     timestamps = warp_data.get('timestamps', None)
#     plot_speed_profile(warp_vel, timestamps, title="Warped Trajectory Speed Profile")

#     plt.show()

# if __name__ == "__main__":
#     main()