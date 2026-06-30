#!/usr/bin/env python3
"""Standalone perception manifest dumper.

Grabs ONE RGB+depth frame, runs the configured perception backend on a
caller-supplied text query, computes a ground-aligned OBB per detected
object (camera frame + optional base frame), and writes the result to
``/tmp/perception_manifest.json`` while pretty-printing a summary to
stdout.

This script is intentionally decoupled from the live pipeline — it does
NOT instantiate MoveIt, NOT call the VLM, NOT touch LTM. Safe to run
alongside the main pragmabot node on the same machine.

Usage (Ubuntu)::

    # roscore + camera + (optional) eye_hand_tf publisher must be running.
    python3 scripts/dump_perception_manifest.py \\
        --queries "apple, plate, mug" \\
        --out /tmp/perception_manifest.json

    # Camera-frame only (skip TF lookup):
    python3 scripts/dump_perception_manifest.py \\
        --queries "apple" --no-base-tf

Exit codes:
    0  success
    1  ROS not available
    2  no image / no detections
    3  unexpected failure
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# --- ROS import guard --------------------------------------------------------
try:
    import rospy  # type: ignore
    import tf2_ros  # type: ignore
    from sensor_msgs.msg import CameraInfo  # type: ignore
    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
# -----------------------------------------------------------------------------


# Make ``pragmabot`` importable when run directly from the repo root.
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
from pragmabot.simple_config import load_config  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_queries(arg: str) -> List[str]:
    return [q.strip() for q in arg.split(",") if q.strip()]


def _lookup_tf(
    tf_buffer: "tf2_ros.Buffer",
    source: str,
    target: str,
    timeout_s: float = 3.0,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Returns (R 3x3, t 3) for ``source -> target``, or None on failure."""
    try:
        ts = tf_buffer.lookup_transform(target, source, rospy.Time(0), rospy.Duration(timeout_s))
    except Exception as exc:  # pragma: no cover - runtime defensive
        print(f"[tf] lookup {source} -> {target} failed: {exc}", file=sys.stderr)
        return None
    q = ts.transform.rotation
    t = ts.transform.translation
    # Quaternion -> rotation matrix (xyzw convention).
    x, y, z, w = float(q.x), float(q.y), float(q.z), float(q.w)
    R = np.array([
        [1 - 2 * (y * y + z * z),     2 * (x * y - z * w),     2 * (x * z + y * w)],
        [    2 * (x * y + z * w), 1 - 2 * (x * x + z * z),     2 * (y * z - x * w)],
        [    2 * (x * z - y * w),     2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=float)
    return R, np.array([float(t.x), float(t.y), float(t.z)], dtype=float)


def _mask_to_png_b64(mask: np.ndarray) -> str:
    """Pack a boolean mask as a base64 PNG (1-bit) for easy round-trip."""
    try:
        from PIL import Image  # local import to keep top-level fast
    except ImportError:
        return ""
    img = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _depth_stats(depth: Optional[np.ndarray], scale: float) -> Dict[str, float]:
    if depth is None:
        return {}
    finite = np.isfinite(depth) & (depth > 0)
    if not finite.any():
        return {"min_m": 0.0, "max_m": 0.0, "median_m": 0.0, "valid_frac": 0.0}
    vals = depth[finite].astype(np.float64) * float(scale)
    return {
        "min_m": float(vals.min()),
        "max_m": float(vals.max()),
        "median_m": float(np.median(vals)),
        "valid_frac": float(finite.sum() / depth.size),
    }


def _summarize_obb(obb_dict: Dict[str, Any]) -> str:
    """Compact one-line summary for stdout."""
    if not obb_dict:
        return "  obb: (none)"
    c = obb_dict["center_m"]
    d = obb_dict["dimensions_m"]
    yaw_deg = np.degrees(obb_dict["yaw_rad"])
    return (
        f"  obb[{obb_dict['frame']}]: "
        f"center=({c[0]:+.3f},{c[1]:+.3f},{c[2]:+.3f})m "
        f"dims=({d[0]:.3f},{d[1]:.3f},{d[2]:.3f})m "
        f"yaw={yaw_deg:+.1f}deg "
        f"n_pts={obb_dict['n_points_used']}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    if not ROS_AVAILABLE:
        print("ROS not available — this script must run on Ubuntu with rospy.", file=sys.stderr)
        return 1

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--config",
        default=str(_REPO_ROOT / "pragmabot" / "config" / "config.yaml"),
        help="Path to config.yaml (default: pragmabot/config/config.yaml)",
    )
    ap.add_argument(
        "--queries",
        required=True,
        help="Comma-separated text queries for the perception backend, e.g. 'apple, plate, mug'.",
    )
    ap.add_argument(
        "--out",
        default="/tmp/perception_manifest.json",
        help="Output JSON path.",
    )
    ap.add_argument(
        "--no-base-tf",
        action="store_true",
        help="Skip camera->base TF lookup and report OBBs in camera frame only.",
    )
    ap.add_argument(
        "--include-masks",
        action="store_true",
        help="Embed base64 PNG masks in the manifest (large; off by default).",
    )
    ap.add_argument(
        "--wait-s",
        type=float,
        default=5.0,
        help="How long to wait for an RGB/depth frame (seconds).",
    )
    args = ap.parse_args()

    queries = _parse_queries(args.queries)
    if not queries:
        print("[err] no queries parsed from --queries", file=sys.stderr)
        return 2

    # --- ROS init ------------------------------------------------------------
    rospy.init_node("pragmabot_perception_dump", anonymous=True, disable_signals=True)
    cfg = load_config(args.config)

    # --- Intrinsics from /camera_info ---------------------------------------
    info_topic = str(cfg.ros.camera_info_topic)
    print(f"[init] waiting for {info_topic} ...")
    info = rospy.wait_for_message(info_topic, CameraInfo, timeout=args.wait_s)
    intrinsics = CameraIntrinsics.from_ros_camera_info(info)
    intrinsics.depth_scale = float(cfg.camera.get("depth_scale", 1.0))
    print(
        f"[init] intrinsics fx={intrinsics.fx:.1f} fy={intrinsics.fy:.1f} "
        f"cx={intrinsics.cx:.1f} cy={intrinsics.cy:.1f} "
        f"size=({intrinsics.width}x{intrinsics.height}) "
        f"depth_scale={intrinsics.depth_scale}"
    )

    # --- Scene observer: one shot --------------------------------------------
    # Imported late so the ROS guard inside still applies.
    from pragmabot.ros.scene_observer import SceneObserver  # type: ignore

    observer = SceneObserver(cfg)
    # Give callbacks a moment to fire.
    deadline = time.time() + args.wait_s
    while time.time() < deadline and not observer.is_receiving():
        time.sleep(0.05)
    rgb = observer.get_latest_rgb(timeout=args.wait_s)
    depth = observer.get_latest_depth(timeout=args.wait_s)
    if depth is None:
        print("[err] no depth image received", file=sys.stderr)
        return 2
    print(f"[init] rgb={rgb.shape} depth={depth.shape} dtype={depth.dtype}")

    # --- Perception ----------------------------------------------------------
    perception = get_perception(cfg)
    print(f"[init] perception backend = {perception.backend_name}")
    print(f"[detect] queries = {queries}")
    t0 = time.time()
    result = perception.detect(rgb, queries=queries, depth=depth)
    print(f"[detect] {len(result.objects)} object(s) in {time.time() - t0:.2f}s")

    # --- TF camera -> base ---------------------------------------------------
    R_cb: Optional[np.ndarray] = None
    t_cb: Optional[np.ndarray] = None
    if not args.no_base_tf:
        tf_buffer = tf2_ros.Buffer()
        _listener = tf2_ros.TransformListener(tf_buffer)  # noqa: F841 — keep alive
        cam_frame = str(cfg.robot.camera_frame)
        base_frame = str(cfg.robot.robot_base_frame)
        # Give TF some time to populate.
        time.sleep(0.5)
        tf = _lookup_tf(tf_buffer, cam_frame, base_frame, timeout_s=args.wait_s)
        if tf is None:
            print(
                f"[warn] TF {cam_frame} -> {base_frame} unavailable; "
                "falling back to camera-frame OBBs only."
            )
        else:
            R_cb, t_cb = tf
            print(f"[tf] {cam_frame} -> {base_frame}: t={t_cb.tolist()}")

    # Optional eye-hand calibration nudge.
    base_offset = None
    try:
        offset = cfg.robot.get("perception_offset_base", None)
    except Exception:
        offset = None
    if offset is not None:
        base_offset = np.asarray([float(v) for v in offset], dtype=float).reshape(3)
        print(f"[tf] perception_offset_base = {base_offset.tolist()}")

    # --- Build manifest ------------------------------------------------------
    manifest_objects: List[Dict[str, Any]] = []
    for obj in result.objects:
        # ---- Raw OBB/AABB (no cleaning) for comparison ------------------
        obb_cam_raw = compute_obb_from_mask_depth(
            mask=obj.mask, depth=depth, intrinsics=intrinsics,
            R_cam_to_base=None, t_cam_to_base=None,
            frame="camera",
        )
        aabb_cam_raw = compute_aabb_from_mask_depth(
            mask=obj.mask, depth=depth, intrinsics=intrinsics,
            R_cam_to_base=None, t_cam_to_base=None,
            frame="camera",
        )

        # ---- Clean the cloud ------------------------------------------------
        cleaned_cam, eroded_mask, report = clean_object_cloud(
            mask=obj.mask, depth=depth, intrinsics=intrinsics,
            erosion_px=1, depth_jump_threshold_m=0.03,
            statistical_k=10, statistical_std_ratio=2.0,
        )

        # ---- Cleaned OBB/AABB ----------------------------------------------
        obb_cam = None
        aabb_cam = None
        obb_base: Optional[Dict[str, Any]] = None
        aabb_base: Optional[Dict[str, Any]] = None
        cleaned_base = None
        if cleaned_cam.shape[0] >= 30:
            try:
                obb_cam = compute_obb_from_points(cleaned_cam, frame="camera")
            except Exception:
                pass
            try:
                aabb_cam = compute_aabb_from_points(cleaned_cam, frame="camera",
                                                    percentile_clip=None)
            except Exception:
                pass
            if R_cb is not None and t_cb is not None:
                cleaned_base = cleaned_cam @ R_cb.T + t_cb
                if base_offset is not None:
                    cleaned_base = cleaned_base + base_offset
                try:
                    obb_base = compute_obb_from_points(
                        cleaned_base, frame=str(cfg.robot.robot_base_frame),
                    ).to_dict()
                except Exception:
                    pass
                try:
                    aabb_base = compute_aabb_from_points(
                        cleaned_base, frame=str(cfg.robot.robot_base_frame),
                        percentile_clip=None,
                    ).to_dict()
                except Exception:
                    pass

        # ---- Class-aware primitive fit -------------------------------------
        primitive: Optional[Dict[str, Any]] = None
        primitive_kind = class_to_primitive(obj.name)
        if cleaned_cam.shape[0] >= 30:
            if primitive_kind == "sphere":
                # Sphere is frame-invariant; prefer base frame if available.
                target = cleaned_base if cleaned_base is not None else cleaned_cam
                frame_label = (str(cfg.robot.robot_base_frame)
                               if cleaned_base is not None else "camera")
                fit = auto_fit_primitive(target, obj.name, frame=frame_label)
                if fit is not None:
                    primitive = fit.to_dict()
            elif primitive_kind in ("upright_cylinder", "flat_disk"):
                if cleaned_base is not None:
                    fit = auto_fit_primitive(
                        cleaned_base, obj.name,
                        frame=str(cfg.robot.robot_base_frame),
                    )
                    if fit is not None:
                        primitive = fit.to_dict()

        entry: Dict[str, Any] = {
            "name": obj.name,
            "confidence": float(obj.confidence),
            "bbox_2d_xyxy_px": list(obj.bbox_2d),
            "centroid_2d_uv_px": list(obj.centroid_2d),
            "centroid_3d_camera_m": (
                None if obj.centroid_3d is None else [float(c) for c in obj.centroid_3d]
            ),
            "obb_camera": obb_cam.to_dict() if obb_cam is not None else None,
            "obb_base": obb_base,
            "aabb_camera": aabb_cam.to_dict() if aabb_cam is not None else None,
            "aabb_base": aabb_base,
            "obb_camera_raw":  None if obb_cam_raw  is None else obb_cam_raw.to_dict(),
            "aabb_camera_raw": None if aabb_cam_raw is None else aabb_cam_raw.to_dict(),
            "cleaning_report": report.to_dict(),
            "primitive_kind": primitive_kind,
            "primitive": primitive,
        }
        if args.include_masks and obj.mask is not None:
            entry["mask_png_b64"] = _mask_to_png_b64(obj.mask)
        manifest_objects.append(entry)

    manifest = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "frames": {
            "camera": str(cfg.robot.camera_frame),
            "base": str(cfg.robot.robot_base_frame),
        },
        "image_size": [int(intrinsics.width), int(intrinsics.height)],
        "intrinsics": {
            "fx": intrinsics.fx, "fy": intrinsics.fy,
            "cx": intrinsics.cx, "cy": intrinsics.cy,
            "depth_scale": intrinsics.depth_scale,
        },
        "tf_camera_to_base": (
            None if R_cb is None
            else {"R": [[float(v) for v in row] for row in R_cb], "t": t_cb.tolist()}
        ),
        "perception_offset_base": (None if base_offset is None else base_offset.tolist()),
        "depth_stats_m": _depth_stats(depth, intrinsics.depth_scale),
        "obb_conventions": {
            "corner_order": [
                "bot_-x-y", "bot_+x-y", "bot_+x+y", "bot_-x+y",
                "top_-x-y", "top_+x-y", "top_+x+y", "top_-x+y",
            ],
            "face_order": ["bottom", "top", "-y", "+y", "-x", "+x"],
            "z_axis": "world up (gravity); ground_aligned PCA on (x,y)",
            "top_face_corners": "corners[4:8], CCW from above",
        },
        "aabb_conventions": {
            "axes_base_frame": {
                "x": "robot forward",
                "y": "robot left",
                "z": "world up (gravity)",
            },
            "extents": "(depth_x_m, width_y_m, height_z_m)",
            "length_horiz_m": "max(depth_x_m, width_y_m) — longest horizontal extent",
            "corner_order": [
                "(xmin,ymin,zmin)", "(xmax,ymin,zmin)",
                "(xmax,ymax,zmin)", "(xmin,ymax,zmin)",
                "(xmin,ymin,zmax)", "(xmax,ymin,zmax)",
                "(xmax,ymax,zmax)", "(xmin,ymax,zmax)",
            ],
        },
        "queries": queries,
        "objects": manifest_objects,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    print(f"\n[ok] wrote {out_path}\n")

    # --- Pretty stdout summary ----------------------------------------------
    print("=" * 72)
    print(f"PERCEPTION MANIFEST  ({len(manifest_objects)} objects)")
    print("=" * 72)
    for i, entry in enumerate(manifest_objects):
        print(f"\n[{i}] {entry['name']!r}  conf={entry['confidence']:.2f}")
        print(f"  bbox_2d_xyxy_px = {entry['bbox_2d_xyxy_px']}")
        print(f"  centroid_3d_camera_m = {entry['centroid_3d_camera_m']}")
        print(_summarize_obb(entry["obb_camera"]) if entry["obb_camera"] else "  obb[camera]: (insufficient depth points)")
        if entry["obb_base"]:
            print(_summarize_obb(entry["obb_base"]))
        if entry.get("aabb_base"):
            a = entry["aabb_base"]
            print(
                f"  aabb[base]: depth_x={a['depth_x_m'] * 100:.1f}cm  "
                f"width_y={a['width_y_m'] * 100:.1f}cm  "
                f"height_z={a['height_z_m'] * 100:.1f}cm  "
                f"length_horiz={a['length_horiz_m'] * 100:.1f}cm  "
                f"top_z={a['max_xyz_m'][2]:+.3f}m"
            )
        elif entry.get("aabb_camera"):
            a = entry["aabb_camera"]
            e = a["extents_m"]
            print(
                f"  aabb[camera]: extents=({e[0]:.3f},{e[1]:.3f},{e[2]:.3f})m  "
                f"top_z={a['max_xyz_m'][2]:+.3f}m"
            )
        if entry.get("obb_base"):
            top = entry["obb_base"]["top_face_corners_m"]
            print(f"  top_face_corners[base] = ")
            for j, p in enumerate(top):
                print(f"    {j}: ({p[0]:+.3f}, {p[1]:+.3f}, {p[2]:+.3f}) m")
        rep = entry.get("cleaning_report") or {}
        if rep:
            print(
                f"  cleaning: in_mask={rep['n_pixels_in_mask']}  "
                f"eroded={rep['n_pixels_after_erosion']}  "
                f"valid_depth={rep['n_pixels_with_valid_depth']}  "
                f"after_jump={rep['n_pixels_after_depth_jump']}  "
                f"after_stat={rep['n_points_after_statistical']}"
            )
        prim = entry.get("primitive")
        if prim:
            if prim.get("type") == "sphere":
                print(
                    f"  primitive: SPHERE  d={prim['diameter_m'] * 100:.1f}cm  "
                    f"r={prim['radius_m'] * 100:.1f}cm  "
                    f"center={[round(c, 3) for c in prim['center_m']]}  "
                    f"inliers={prim['n_inliers']}  "
                    f"rmse={prim['rmse_m'] * 1000:.1f}mm"
                )
            else:
                h = prim.get("height_m") or prim.get("thickness_m", 0.0)
                print(
                    f"  primitive: {prim['type'].upper()}  "
                    f"d={prim['diameter_m'] * 100:.1f}cm  "
                    f"h={h * 100:.1f}cm  "
                    f"center={[round(c, 3) for c in prim['center_m']]}  "
                    f"inliers={prim['n_inliers']}  "
                    f"rmse={prim['rmse_m'] * 1000:.1f}mm"
                )
        else:
            print("  obb[base]: (n/a)")

    if not manifest_objects:
        print("\n[warn] no detections.")
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:  # pragma: no cover
        raise SystemExit(130)
    except Exception as exc:  # pragma: no cover
        import traceback
        traceback.print_exc()
        print(f"[fatal] {exc}", file=sys.stderr)
        raise SystemExit(3)
