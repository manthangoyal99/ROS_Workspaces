#!/usr/bin/env python3
"""
Visualize the cleaning_keypoints mesh as a 3D wireframe grid
with labeled keypoints.
"""
import json
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
import os

DATA_DIR = "/home/ravi/fr3_ws/src/cleaning_adaptive/data"


def load_json(filename):
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, "r") as f:
        return json.load(f)


def main():
    data = load_json("target_keypoints.json")

    # --- Extract grid info ---
    rows, cols = data["grid_shape"]  # 4 x 4
    order = data["order_reference"]
    kp_map = {kp["label"]: np.array(kp["coords"]) for kp in data["keypoints"]}

    # Build the grid matrix (rows x cols x 3)
    grid = np.zeros((rows, cols, 3))
    for idx, label in enumerate(order):
        r = idx // cols
        c = idx % cols
        grid[r, c] = kp_map[label]

    # --- Plot ---
    fig = plt.figure(figsize=(12, 9))
    ax = fig.add_subplot(111, projection="3d")

    # Draw wireframe lines along rows
    for r in range(rows):
        ax.plot(
            grid[r, :, 0], grid[r, :, 1], grid[r, :, 2],
            color="steelblue", linewidth=2, zorder=2,
        )

    # Draw wireframe lines along columns
    for c in range(cols):
        ax.plot(
            grid[:, c, 0], grid[:, c, 1], grid[:, c, 2],
            color="steelblue", linewidth=2, zorder=2,
        )

    # Scatter the keypoints
    all_pts = grid.reshape(-1, 3)
    ax.scatter(
        all_pts[:, 0], all_pts[:, 1], all_pts[:, 2],
        color="crimson", s=60, depthshade=False, zorder=3,
    )

    # Label each keypoint
    for idx, label in enumerate(order):
        pt = kp_map[label]
        ax.text(
            pt[0], pt[1], pt[2], f"  {label}",
            fontsize=7, color="black", ha="left",
        )

    # --- Formatting ---
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_zlabel("Z (m)")
    ax.set_title(f"Cleaning Keypoints Mesh  ({rows}×{cols})  —  frame: {data['frame']}")

    # Equal aspect ratio
    max_range = (all_pts.max(axis=0) - all_pts.min(axis=0)).max() / 2.0
    mid = (all_pts.max(axis=0) + all_pts.min(axis=0)) * 0.5
    ax.set_xlim(mid[0] - max_range, mid[0] + max_range)
    ax.set_ylim(mid[1] - max_range, mid[1] + max_range)
    ax.set_zlim(mid[2] - max_range, mid[2] + max_range)

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
