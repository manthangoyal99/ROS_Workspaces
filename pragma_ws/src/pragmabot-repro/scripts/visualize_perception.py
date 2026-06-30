#!/usr/bin/env python3
"""Visualize each perception stage on a real frame.

For every detection produced by the configured perception backend, this
script writes a 4-panel composite PNG showing:

    Panel 1  RGB + GroundingDINO 2D bbox + label
    Panel 2  RGB + SAM mask overlay (alpha-blended)
    Panel 3  Depth (colormapped) + mask outline; depth holes inside the
             mask are flagged in red (these are the points the OBB
             algorithm silently drops)
    Panel 4  RGB + reprojected OBB:
                - bottom face: thin dashed lines
                - top face:    thick solid lines
                - 8 corners labeled with their canonical indices
                - centroid as a yellow dot

Output: one PNG per detection at ``--out-dir`` (default ``/tmp/perception_viz/``)
plus an index ``index.html`` linking them all.

This script is fully decoupled from the runtime pipeline.

Usage (Ubuntu)::

    python3 scripts/visualize_perception.py \\
        --queries "apple, plate" \\
        --out-dir /tmp/perception_viz

    # Visualize only the lowest-confidence detection (debug junk):
    python3 scripts/visualize_perception.py --queries "plate" --max-detections 99
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# --- ROS guard ---------------------------------------------------------------
try:
    import rospy  # type: ignore
    import tf2_ros  # type: ignore
    from sensor_msgs.msg import CameraInfo  # type: ignore
    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
# -----------------------------------------------------------------------------

# Make ``pragmabot`` importable from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "pragmabot" / "src"))

from pragmabot.perception import (  # noqa: E402
    CameraIntrinsics,
    auto_fit_primitive,
    class_to_primitive,
    clean_object_cloud,
    compute_aabb_from_mask_depth,
    compute_aabb_from_points,
    compute_obb_from_mask_depth,
    compute_obb_from_points,
    get_perception,
)
from pragmabot.perception.aabb import AxisAlignedBoundingBox  # noqa: E402
from pragmabot.perception.obb import OrientedBoundingBox  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


# ---------------------------------------------------------------------------
# Rendering helpers (matplotlib only used for figure layout)
# ---------------------------------------------------------------------------


def _project_points_camera(points_cam: np.ndarray, intr: CameraIntrinsics) -> np.ndarray:
    """Project (N, 3) camera-frame points to (N, 2) pixel coordinates.

    Z<=0 points are returned with NaN pixels so the caller can skip them.
    """
    pts = np.asarray(points_cam, dtype=float).reshape(-1, 3)
    out = np.full((pts.shape[0], 2), np.nan, dtype=float)
    z = pts[:, 2]
    valid = z > 1e-6
    out[valid, 0] = intr.fx * pts[valid, 0] / z[valid] + intr.cx
    out[valid, 1] = intr.fy * pts[valid, 1] / z[valid] + intr.cy
    return out


def _render_one_detection(
    rgb: np.ndarray,
    depth: np.ndarray,
    detection: Any,
    intr: CameraIntrinsics,
    obb_cam: Optional[OrientedBoundingBox],
    obb_base: Optional[OrientedBoundingBox],
    aabb_cam: Optional[AxisAlignedBoundingBox],
    aabb_base: Optional[AxisAlignedBoundingBox],
    cleaned_cloud_cam: Optional[np.ndarray] = None,
    eroded_mask: Optional[np.ndarray] = None,
    primitive_cam: Optional[Any] = None,
    out_path: Path = Path("/tmp/_viz.png"),
    title_prefix: str = "",
) -> None:
    """Write a 4-panel PNG for one detection."""
    import matplotlib
    matplotlib.use("Agg")  # safe on headless Ubuntu
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # -- Panel 1: RGB + DINO bbox -----------------------------------------
    ax = axes[0, 0]
    ax.imshow(rgb)
    x1, y1, x2, y2 = detection.bbox_2d
    ax.add_patch(Rectangle((x1, y1), x2 - x1, y2 - y1,
                            fill=False, edgecolor="cyan", linewidth=2.5))
    ax.text(x1, max(y1 - 6, 6),
            f"{detection.name}  conf={detection.confidence:.2f}",
            color="cyan", fontsize=11, weight="bold",
            bbox=dict(facecolor="black", alpha=0.5, pad=2))
    ax.set_title("1. GroundingDINO 2D bbox")
    ax.axis("off")

    # -- Panel 2: RGB + SAM mask + eroded mask outline -------------------
    ax = axes[0, 1]
    ax.imshow(rgb)
    if detection.mask is not None:
        overlay = np.zeros((*detection.mask.shape, 4), dtype=np.float32)
        overlay[detection.mask] = [1.0, 0.4, 0.0, 0.45]  # orange, alpha 0.45
        ax.imshow(overlay)
        n_mask = int(detection.mask.sum())
        title2 = f"2. SAM mask  ({n_mask} px)"
        if eroded_mask is not None and eroded_mask.shape == detection.mask.shape:
            ax.contour(eroded_mask.astype(np.uint8), levels=[0.5],
                       colors="lime", linewidths=1.5)
            n_used = int(eroded_mask.sum())
            title2 += f"   |   eroded (used): {n_used} px"
        ax.set_title(title2)
    else:
        ax.set_title("2. SAM mask  (none)")
    ax.axis("off")

    # -- Panel 3: depth + mask outline + invalid-depth holes --------------
    ax = axes[1, 0]
    depth_m = depth.astype(np.float64) * float(intr.depth_scale)
    valid_global = np.isfinite(depth_m) & (depth_m > 0)
    # Color-map depth (clip to a reasonable robot workspace range).
    vis = np.full_like(depth_m, np.nan, dtype=np.float64)
    vis[valid_global] = np.clip(depth_m[valid_global], 0.3, 1.5)
    ax.imshow(vis, cmap="viridis")
    if detection.mask is not None:
        # Outline of the mask.
        ax.contour(detection.mask.astype(np.uint8), levels=[0.5],
                   colors="white", linewidths=1.5)
        # Highlight invalid-depth pixels INSIDE the mask.
        holes = detection.mask & (~valid_global)
        n_total = int(detection.mask.sum())
        n_holes = int(holes.sum())
        if n_holes > 0:
            holes_rgba = np.zeros((*holes.shape, 4), dtype=np.float32)
            holes_rgba[holes] = [1.0, 0.0, 0.0, 0.85]
            ax.imshow(holes_rgba)
        pct = (n_holes / max(n_total, 1)) * 100.0
        ax.set_title(
            f"3. Depth + mask  (holes: {n_holes}/{n_total} = {pct:.1f}% red)"
        )
    else:
        ax.set_title("3. Depth (no mask)")
    ax.axis("off")

    # -- Panel 4: RGB + reprojected OBB corners ---------------------------
    ax = axes[1, 1]
    ax.imshow(rgb)
    title4 = "4. OBB (camera frame) reprojected"
    if obb_cam is not None:
        pix = _project_points_camera(obb_cam.corners, intr)
        # Bottom face = indices 0..3, top = 4..7
        def _draw_face(idxs, color, lw, ls):
            n = len(idxs)
            for i in range(n):
                a = pix[idxs[i]]
                b = pix[idxs[(i + 1) % n]]
                if np.any(np.isnan(a)) or np.any(np.isnan(b)):
                    continue
                ax.plot([a[0], b[0]], [a[1], b[1]],
                        color=color, linewidth=lw, linestyle=ls)
        # Vertical edges
        for i in range(4):
            a, b = pix[i], pix[i + 4]
            if np.any(np.isnan(a)) or np.any(np.isnan(b)):
                continue
            ax.plot([a[0], b[0]], [a[1], b[1]],
                    color="white", linewidth=1.0, linestyle=":")
        _draw_face([0, 1, 2, 3], "magenta", 1.2, "--")
        _draw_face([4, 5, 6, 7], "yellow",  2.4, "-")
        # Corner index labels.
        for i in range(8):
            p = pix[i]
            if np.any(np.isnan(p)):
                continue
            ax.text(p[0] + 3, p[1] - 3, str(i),
                    color="yellow", fontsize=9, weight="bold",
                    bbox=dict(facecolor="black", alpha=0.5, pad=1))

    # --- AABB (camera frame) overlay, cyan ------------------------------
    if aabb_cam is not None:
        apix = _project_points_camera(aabb_cam.corners, intr)

        def _draw_aabb_face(idxs, color, lw, ls):
            n = len(idxs)
            for i in range(n):
                a = apix[idxs[i]]
                b = apix[idxs[(i + 1) % n]]
                if np.any(np.isnan(a)) or np.any(np.isnan(b)):
                    continue
                ax.plot([a[0], b[0]], [a[1], b[1]],
                        color=color, linewidth=lw, linestyle=ls)
        # Vertical edges
        for i in range(4):
            a, b = apix[i], apix[i + 4]
            if np.any(np.isnan(a)) or np.any(np.isnan(b)):
                continue
            ax.plot([a[0], b[0]], [a[1], b[1]],
                    color="cyan", linewidth=0.8, linestyle=":")
        _draw_aabb_face([0, 1, 2, 3], "cyan", 0.9, "--")
        _draw_aabb_face([4, 5, 6, 7], "cyan", 1.6, "-")

    # --- Cleaned cloud overlay (tiny white dots, only every Nth point) ---
    if cleaned_cloud_cam is not None and cleaned_cloud_cam.shape[0] > 0:
        n = cleaned_cloud_cam.shape[0]
        stride = max(1, n // 800)  # cap at ~800 dots for speed
        pix_pts = _project_points_camera(cleaned_cloud_cam[::stride], intr)
        valid = ~np.any(np.isnan(pix_pts), axis=1)
        ax.scatter(pix_pts[valid, 0], pix_pts[valid, 1],
                   s=1, c="white", alpha=0.5)

    # --- Primitive overlay (lime green wireframe in CAMERA frame) -------
    if primitive_cam is not None:
        wire = primitive_cam.wireframe_points() if hasattr(primitive_cam, "wireframe_points") else []
        for poly in wire:
            ppix = _project_points_camera(poly, intr)
            valid = ~np.any(np.isnan(ppix), axis=1)
            if valid.sum() < 2:
                continue
            ax.plot(ppix[valid, 0], ppix[valid, 1],
                    color="#33ff66", linewidth=2.0)
        # Center marker.
        if hasattr(primitive_cam, "center"):
            cp = _project_points_camera(
                np.asarray(primitive_cam.center).reshape(1, 3), intr,
            )[0]
            if not np.any(np.isnan(cp)):
                ax.plot(cp[0], cp[1], "o", color="#33ff66",
                        markersize=10, markeredgecolor="black")

    # OBB-only details after AABB block so they stay on top.
    if obb_cam is not None:
        # Centroid (centroid_3d_camera_m may differ from OBB center; show both).
        cen = _project_points_camera(obb_cam.center.reshape(1, 3), intr)[0]
        if not np.any(np.isnan(cen)):
            ax.plot(cen[0], cen[1], "o", color="yellow",
                    markersize=10, markeredgecolor="black")
        if detection.centroid_3d is not None:
            cd = _project_points_camera(
                np.asarray(detection.centroid_3d).reshape(1, 3), intr,
            )[0]
            if not np.any(np.isnan(cd)):
                ax.plot(cd[0], cd[1], "x", color="cyan",
                        markersize=10, markeredgewidth=2.5)
        dims = obb_cam.dimensions
        title4 = (
            f"4. OBB[cam] (yellow=top, magenta=bot) dims=({dims[0]:.3f},{dims[1]:.3f},{dims[2]:.3f})m"
            f"  yaw={np.degrees(obb_cam.yaw_rad):+.1f}°"
        )
    if aabb_cam is not None:
        e = aabb_cam.extents
        title4 += f"   |   AABB[cam] (cyan) extents=({e[0]:.3f},{e[1]:.3f},{e[2]:.3f})m"
    if primitive_cam is not None:
        p = primitive_cam.to_dict()
        if p["type"] == "sphere":
            title4 += f"   |   SPHERE r={p['radius_m']:.3f}m (lime)"
        elif p["type"] in ("upright_cylinder", "flat_disk"):
            h = p.get("height_m") or p.get("thickness_m", 0.0)
            title4 += f"   |   {p['type'].upper()} r={p['radius_m']:.3f}m h={h:.3f}m (lime)"
    ax.set_title(title4, fontsize=9)
    ax.axis("off")

    # Top-of-figure summary including base-frame OBB + AABB.
    summary_lines = [title_prefix]
    if obb_base is not None:
        d = obb_base.dimensions
        summary_lines.append(
            f"OBB[base]:  long(x_local)={d[0] * 100:.1f}cm  "
            f"short(y_local)={d[1] * 100:.1f}cm  "
            f"height(z)={d[2] * 100:.1f}cm  "
            f"yaw={np.degrees(obb_base.yaw_rad):+.1f}°  "
            f"top_z={obb_base.corners[4:8, 2].mean():.3f}m"
        )
    if aabb_base is not None:
        summary_lines.append(
            f"AABB[base]: depth(x)={aabb_base.depth_x_m * 100:.1f}cm  "
            f"width(y)={aabb_base.width_y_m * 100:.1f}cm  "
            f"height(z)={aabb_base.height_z_m * 100:.1f}cm  "
            f"length_horiz={aabb_base.length_horiz_m * 100:.1f}cm  "
            f"top_z={aabb_base.max_xyz[2]:.3f}m"
        )
    if primitive_cam is not None:
        p = primitive_cam.to_dict()
        if p["type"] == "sphere":
            summary_lines.append(
                f"primitive[cam]: SPHERE  diameter={p['diameter_m'] * 100:.1f}cm  "
                f"radius={p['radius_m'] * 100:.1f}cm  inliers={p['n_inliers']}  "
                f"rmse={p['rmse_m'] * 1000:.1f}mm"
            )
        else:
            h = p.get("height_m") or p.get("thickness_m", 0.0)
            summary_lines.append(
                f"primitive[cam]: {p['type'].upper()}  "
                f"diameter={p['diameter_m'] * 100:.1f}cm  "
                f"height={h * 100:.1f}cm  inliers={p['n_inliers']}  "
                f"rmse={p['rmse_m'] * 1000:.1f}mm"
            )
    fig.suptitle("\n".join(summary_lines), fontsize=11, y=0.995,
                 fontfamily="monospace")
    plt.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def _fmt_cm(m: Optional[float]) -> str:
    return "—" if m is None else f"{m * 100:.1f}"


def _fmt_m(m: Optional[float]) -> str:
    return "—" if m is None else f"{m:.3f}"


def _dims_table_html(entry: Dict[str, Any]) -> str:
    """Render a per-detection dims table (AABB + OBB, both frames) as HTML."""
    a_cam_raw  = entry.get("aabb_cam_raw")  or {}
    a_cam = entry.get("aabb_cam") or {}
    a_base = entry.get("aabb_base") or {}
    o_cam_raw  = entry.get("obb_cam_raw")  or {}
    o_cam = entry.get("obb_cam") or {}
    o_base = entry.get("obb_base") or {}
    primitive = entry.get("primitive") or {}

    def _g(d, k):
        return d.get(k) if d else None

    rows: List[Tuple[str, Optional[float]]] = []

    if primitive:
        rows.append(("=== PRIMITIVE FIT ===", None))
        rows.append((f"  type",                                       None))
        # We use 'rmse' field as a sentinel to show non-cm formatting in the row builder.
        if primitive.get("type") == "sphere":
            rows.append(("  diameter",                                primitive.get("diameter_m")))
            rows.append(("  radius",                                  primitive.get("radius_m")))
        else:
            rows.append(("  diameter",                                primitive.get("diameter_m")))
            rows.append(("  height/thickness",
                          primitive.get("height_m") or primitive.get("thickness_m")))
        rows.append(("  inlier_ratio (—%)",                          primitive.get("inlier_ratio")))
        rows.append(("  rmse (mm — see right col)",                  primitive.get("rmse_m")))

    rows.extend([
        ("=== AABB[base]  (use this for TP-GPT) ===", None),
        ("  depth (x = robot forward)",  _g(a_base, "depth_x_m")),
        ("  width (y = robot left)",     _g(a_base, "width_y_m")),
        ("  height (z = up)",            _g(a_base, "height_z_m")),
        ("  length (max of x, y)",       _g(a_base, "length_horiz_m")),
        ("  top z (max_xyz[2])",
         (None if not a_base else a_base["max_xyz_m"][2])),
        ("=== AABB[cam] cleaned vs raw ===", None),
        ("  extent_x  raw -> cleaned",
         (None if not a_cam else a_cam["extents_m"][0])),
        ("  extent_y  raw -> cleaned",
         (None if not a_cam else a_cam["extents_m"][1])),
        ("  extent_z (depth from cam)  raw -> cleaned",
         (None if not a_cam else a_cam["extents_m"][2])),
        ("=== OBB[base] (cleaned) ===", None),
        ("  long (x_local)",             (None if not o_base else o_base["dimensions_m"][0])),
        ("  short (y_local)",            (None if not o_base else o_base["dimensions_m"][1])),
        ("  height (z = up)",            (None if not o_base else o_base["dimensions_m"][2])),
        ("  yaw (deg, around world z)",
         (None if not o_base else float(np.degrees(o_base["yaw_rad"])))),
    ])

    if a_cam_raw or o_cam_raw:
        rows.append(("=== RAW (no cleaning, for comparison) ===", None))
        if a_cam_raw:
            rows.append(("  AABB[cam,raw] extent_x", a_cam_raw["extents_m"][0]))
            rows.append(("  AABB[cam,raw] extent_y", a_cam_raw["extents_m"][1]))
            rows.append(("  AABB[cam,raw] extent_z", a_cam_raw["extents_m"][2]))
        if o_cam_raw:
            rows.append(("  OBB[cam,raw] dim_x", o_cam_raw["dimensions_m"][0]))
            rows.append(("  OBB[cam,raw] dim_y", o_cam_raw["dimensions_m"][1]))
            rows.append(("  OBB[cam,raw] dim_z", o_cam_raw["dimensions_m"][2]))

    rep = entry.get("cleaning_report")
    if rep:
        rows.append(("=== CLEANING REPORT ===", None))
        for k in ("n_pixels_in_mask", "n_pixels_after_erosion",
                   "n_pixels_with_valid_depth", "n_pixels_after_depth_jump",
                   "n_points_after_statistical"):
            v = rep.get(k)
            if v is not None:
                rows.append((f"  {k}", float(v)))  # cm column will show count, m col blank

    tr_rows = []
    for label, val in rows:
        # Section header rows
        if label.startswith("==="):
            tr_rows.append(
                f'<tr><td colspan="3" style="padding:8px 12px 4px 12px;'
                f'color:#ffaa55;font-weight:bold;background:#222;">'
                f"{label}</td></tr>"
            )
            continue
        # Special formatting cases
        if "deg" in label:
            cell_cm = "—"
            cell_m = "—" if val is None else f"{val:+.1f}°"
        elif "inlier_ratio" in label:
            cell_cm = "—" if val is None else f"{val * 100:.1f}%"
            cell_m = "—"
        elif "rmse" in label.lower():
            cell_cm = "—" if val is None else f"{val * 1000:.2f}"
            cell_m = "—" if val is None else f"{val:.4f}"
        elif "n_pixels" in label or "n_points" in label:
            # raw counts, no unit
            cell_cm = "—" if val is None else f"{int(val)}"
            cell_m = "—"
        elif label.strip() in ("type",):
            cell_cm = "—"
            cell_m = "—"
        else:
            cell_cm = _fmt_cm(val)
            cell_m = _fmt_m(val)
        tr_rows.append(
            f"<tr>"
            f'<td style="padding:2px 12px;">{label}</td>'
            f'<td style="padding:2px 12px;text-align:right;font-family:monospace;">{cell_cm}</td>'
            f'<td style="padding:2px 12px;text-align:right;font-family:monospace;color:#bbb;">{cell_m}</td>'
            f"</tr>"
        )
    return (
        '<table style="border-collapse:collapse;margin:8px 0;'
        'background:#1a1a1a;border:1px solid #333;font-size:13px;">'
        '<thead><tr style="background:#222;color:#9cf;">'
        '<th style="padding:4px 12px;text-align:left;">Quantity</th>'
        '<th style="padding:4px 12px;text-align:right;">cm</th>'
        '<th style="padding:4px 12px;text-align:right;">m</th>'
        "</tr></thead><tbody>"
        + "\n".join(tr_rows)
        + "</tbody></table>"
    )


def _write_index_html(out_dir: Path, entries: List[Dict[str, Any]]) -> Path:
    """Create an index.html that links every rendered PNG and dims table."""
    rows = []
    for e in entries:
        rows.append(
            f'<div style="margin:24px 0;padding:14px;background:#181818;'
            f'border:1px solid #333;border-radius:6px;">'
            f'<h3 style="margin:0 0 8px 0;">[{e["idx"]}] {e["name"]} '
            f'<span style="color:#888;font-weight:normal;">(conf={e["conf"]:.2f})</span></h3>'
            f"{_dims_table_html(e)}"
            f'<img src="{e["file"]}" style="max-width:1400px;width:100%;border:1px solid #444"/>'
            f"</div>"
        )
    html = (
        "<!doctype html><meta charset='utf-8'><title>perception viz</title>"
        "<body style='background:#111;color:#eee;font-family:sans-serif;padding:20px;'>"
        f"<h1>perception viz  ({len(entries)} detections)</h1>"
        '<p style="color:#aaa;max-width:900px;">'
        "Each detection shows AABB (axis-aligned in <em>base frame</em>: "
        "x=robot forward / y=robot left / z=up) and OBB (ground-aligned, "
        "yaw=rotation of the OBB's long horizontal axis around world z). "
        "AABB is conservative and gravity-aligned — use it for collision / "
        "approach planning. OBB is tighter when the object has a clear "
        "long axis (boxes, plates, bottles) — use yaw for grasp orientation."
        "</p>"
        + "\n".join(rows)
        + "</body>"
    )
    path = out_dir / "index.html"
    path.write_text(html)
    return path


# ---------------------------------------------------------------------------
# TF lookup (camera -> base)
# ---------------------------------------------------------------------------


def _lookup_tf(
    tf_buffer: "tf2_ros.Buffer",
    source: str,
    target: str,
    timeout_s: float = 3.0,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    try:
        ts = tf_buffer.lookup_transform(target, source, rospy.Time(0), rospy.Duration(timeout_s))
    except Exception as exc:
        print(f"[tf] lookup {source} -> {target} failed: {exc}", file=sys.stderr)
        return None
    q = ts.transform.rotation
    t = ts.transform.translation
    x, y, z, w = float(q.x), float(q.y), float(q.z), float(q.w)
    R = np.array([
        [1 - 2 * (y * y + z * z),     2 * (x * y - z * w),     2 * (x * z + y * w)],
        [    2 * (x * y + z * w), 1 - 2 * (x * x + z * z),     2 * (y * z - x * w)],
        [    2 * (x * z - y * w),     2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=float)
    return R, np.array([float(t.x), float(t.y), float(t.z)], dtype=float)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    if not ROS_AVAILABLE:
        print("ROS not available — this script must run on Ubuntu with rospy.",
              file=sys.stderr)
        return 1

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config",
                    default=str(_REPO_ROOT / "pragmabot" / "config" / "config.yaml"))
    ap.add_argument("--queries", required=True,
                    help="Comma-separated text queries, e.g. 'apple, plate'.")
    ap.add_argument("--out-dir", default="/tmp/perception_viz")
    ap.add_argument("--wait-s", type=float, default=5.0)
    ap.add_argument("--max-detections", type=int, default=99,
                    help="Cap on how many detections to render (sorted by confidence desc).")
    ap.add_argument("--no-base-tf", action="store_true")
    args = ap.parse_args()

    queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    if not queries:
        print("[err] no queries parsed", file=sys.stderr)
        return 2

    rospy.init_node("pragmabot_perception_viz", anonymous=True, disable_signals=True)
    cfg = load_config(args.config)

    # Intrinsics
    info_topic = str(cfg.ros.camera_info_topic)
    print(f"[init] waiting for {info_topic} ...")
    info = rospy.wait_for_message(info_topic, CameraInfo, timeout=args.wait_s)
    intr = CameraIntrinsics.from_ros_camera_info(info)
    intr.depth_scale = float(cfg.camera.get("depth_scale", 1.0))
    print(f"[init] intrinsics fx={intr.fx:.1f} fy={intr.fy:.1f} "
          f"cx={intr.cx:.1f} cy={intr.cy:.1f} ({intr.width}x{intr.height})")

    # One-shot scene observer
    from pragmabot.ros.scene_observer import SceneObserver
    observer = SceneObserver(cfg)
    deadline = time.time() + args.wait_s
    while time.time() < deadline and not observer.is_receiving():
        time.sleep(0.05)
    rgb = observer.get_latest_rgb(timeout=args.wait_s)
    depth = observer.get_latest_depth(timeout=args.wait_s)
    if depth is None:
        print("[err] no depth received", file=sys.stderr)
        return 2
    print(f"[init] rgb={rgb.shape} depth={depth.shape} dtype={depth.dtype}")

    # Perception
    perception = get_perception(cfg)
    print(f"[detect] backend={perception.backend_name}  queries={queries}")
    t0 = time.time()
    result = perception.detect(rgb, queries=queries, depth=depth)
    print(f"[detect] {len(result.objects)} object(s) in {time.time() - t0:.2f}s")

    # TF
    R_cb: Optional[np.ndarray] = None
    t_cb: Optional[np.ndarray] = None
    if not args.no_base_tf:
        tf_buf = tf2_ros.Buffer()
        _listener = tf2_ros.TransformListener(tf_buf)  # noqa: F841 — kept alive
        time.sleep(0.5)
        tf = _lookup_tf(tf_buf, str(cfg.robot.camera_frame),
                        str(cfg.robot.robot_base_frame), timeout_s=args.wait_s)
        if tf is not None:
            R_cb, t_cb = tf
            print(f"[tf] camera->base t={t_cb.tolist()}")

    base_offset = None
    try:
        offset = cfg.robot.get("perception_offset_base", None)
    except Exception:
        offset = None
    if offset is not None:
        base_offset = np.asarray([float(v) for v in offset], dtype=float).reshape(3)

    # Render
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    detections_sorted = sorted(
        enumerate(result.objects), key=lambda kv: -kv[1].confidence,
    )[: args.max_detections]

    entries: List[Dict[str, Any]] = []
    for idx, det in detections_sorted:
        # ---- Raw boxes (no cleaning) for the comparison column ------------
        obb_cam_raw = compute_obb_from_mask_depth(
            mask=det.mask, depth=depth, intrinsics=intr,
            R_cam_to_base=None, t_cam_to_base=None, frame="camera",
        )
        aabb_cam_raw = compute_aabb_from_mask_depth(
            mask=det.mask, depth=depth, intrinsics=intr,
            R_cam_to_base=None, t_cam_to_base=None, frame="camera",
        )

        # ---- Clean the cloud (camera frame) -------------------------------
        cleaned_cam, eroded_mask, report = clean_object_cloud(
            mask=det.mask, depth=depth, intrinsics=intr,
            erosion_px=1, depth_jump_threshold_m=0.03,
            statistical_k=10, statistical_std_ratio=2.0,
        )
        print(f"  [{idx}] {det.name}: clean {report.n_pixels_in_mask} -> {report.n_points_after_statistical} pts")

        # ---- Cleaned OBB/AABB in camera & base frames ---------------------
        obb_cam = None
        aabb_cam = None
        obb_base = None
        aabb_base = None
        if cleaned_cam.shape[0] >= 30:
            try:
                obb_cam = compute_obb_from_points(cleaned_cam, frame="camera")
                aabb_cam = compute_aabb_from_points(cleaned_cam, frame="camera",
                                                     percentile_clip=None)
            except Exception as exc:
                print(f"    [warn] obb/aabb cam failed: {exc}")
            if R_cb is not None and t_cb is not None:
                cleaned_base = cleaned_cam @ R_cb.T + t_cb
                if base_offset is not None:
                    cleaned_base = cleaned_base + base_offset
                try:
                    obb_base = compute_obb_from_points(
                        cleaned_base, frame=str(cfg.robot.robot_base_frame),
                    )
                    aabb_base = compute_aabb_from_points(
                        cleaned_base, frame=str(cfg.robot.robot_base_frame),
                        percentile_clip=None,
                    )
                except Exception as exc:
                    print(f"    [warn] obb/aabb base failed: {exc}")

        # ---- Class-aware primitive fit -----------------------------------
        # Sphere works in any frame; cylinder/disk need +z=up (base frame).
        primitive_cam = None
        primitive_base = None
        kind = class_to_primitive(det.name)
        if kind == "sphere" and cleaned_cam.shape[0] >= 30:
            primitive_cam = auto_fit_primitive(
                cleaned_cam, det.name, frame="camera",
            )
            # If we have a base TF, ALSO fit a sphere in base (so we can compare).
            if R_cb is not None and t_cb is not None:
                cleaned_base = cleaned_cam @ R_cb.T + t_cb
                if base_offset is not None:
                    cleaned_base = cleaned_base + base_offset
                primitive_base = auto_fit_primitive(
                    cleaned_base, det.name,
                    frame=str(cfg.robot.robot_base_frame),
                )
        elif kind in ("upright_cylinder", "flat_disk"):
            # Only fit in base frame (z=up).
            if R_cb is not None and t_cb is not None and cleaned_cam.shape[0] >= 30:
                cleaned_base = cleaned_cam @ R_cb.T + t_cb
                if base_offset is not None:
                    cleaned_base = cleaned_base + base_offset
                primitive_base = auto_fit_primitive(
                    cleaned_base, det.name,
                    frame=str(cfg.robot.robot_base_frame),
                )

        safe_name = "".join(c if c.isalnum() else "_" for c in det.name)[:30]
        fname = f"{idx:02d}_{safe_name}.png"
        out_path = out_dir / fname
        title = (
            f"[{idx}] {det.name}  conf={det.confidence:.2f}  "
            f"bbox=[{det.bbox_2d[0]},{det.bbox_2d[1]},{det.bbox_2d[2]},{det.bbox_2d[3]}]  "
            f"primitive={kind or 'none'}"
        )
        _render_one_detection(
            rgb=rgb, depth=depth, detection=det, intr=intr,
            obb_cam=obb_cam, obb_base=obb_base,
            aabb_cam=aabb_cam, aabb_base=aabb_base,
            cleaned_cloud_cam=cleaned_cam,
            eroded_mask=eroded_mask,
            primitive_cam=primitive_cam,
            out_path=out_path, title_prefix=title,
        )
        print(f"  -> {out_path}")
        # Pick the "primitive" entry for the HTML: prefer base, fall back to camera.
        primitive_entry = primitive_base or primitive_cam
        entries.append({
            "idx": idx, "name": det.name,
            "conf": float(det.confidence), "file": fname,
            "obb_cam":      None if obb_cam      is None else obb_cam.to_dict(),
            "obb_base":     None if obb_base     is None else obb_base.to_dict(),
            "aabb_cam":     None if aabb_cam     is None else aabb_cam.to_dict(),
            "aabb_base":    None if aabb_base    is None else aabb_base.to_dict(),
            "obb_cam_raw":  None if obb_cam_raw  is None else obb_cam_raw.to_dict(),
            "aabb_cam_raw": None if aabb_cam_raw is None else aabb_cam_raw.to_dict(),
            "primitive":    None if primitive_entry is None else primitive_entry.to_dict(),
            "cleaning_report": report.to_dict(),
        })

    index_path = _write_index_html(out_dir, entries)
    print(f"\n[ok] wrote {len(entries)} viz PNG(s) + {index_path}")
    print(f"     open: file://{index_path.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"[fatal] {exc}", file=sys.stderr)
        raise SystemExit(3)
