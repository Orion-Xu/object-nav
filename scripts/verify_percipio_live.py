#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import time

import numpy as np

from object_nav_demo.camera_protocol import PacketRecorder, PercipioRgbdSource
from object_nav_demo.config import PROJECT_ROOT, default_config, load_yaml
from object_nav_demo.detector import UltralyticsDetector
from object_nav_demo.local_mapping import RollingObstacleMap, pointcloud_to_obstacles
from object_nav_demo.target_localizer import StaticTransformProvider, TargetLocalizer
from object_nav_demo.vocabulary_manager import VocabularyManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only GM461 RGB-D/YOLO/map acceptance")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--skip-yolo", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    system = load_yaml(default_config("system.yaml"))
    camera = system["camera"]
    mapping = system["local_mapping"]
    bridge = camera["bridge"]
    source = PercipioRgbdSource(bridge["host"], int(bridge["port"]), timeout_s=2.0)
    recording = None
    recording_dir = None
    if not args.no_record:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        recording_root = Path(camera["recording_root"]).expanduser()
        if not recording_root.is_absolute():
            recording_root = PROJECT_ROOT / recording_root
        recording_dir = recording_root / stamp
        recording = PacketRecorder(recording_dir)

    detector = None
    if not args.skip_yolo:
        vocabulary = VocabularyManager(default_config("vocabulary.yaml"))
        policies = {policy.canonical_label: policy for policy in vocabulary.policies}
        detector = UltralyticsDetector(
            PROJECT_ROOT / system["detector"]["preferred_weights"],
            {
                policy.prompt_en: policy.canonical_label
                for policy in vocabulary.policies
            },
            world_model=True,
            device=system["detector"]["device"],
            image_size=int(system["realtime_detection"]["image_size"]),
            confidence=float(system["realtime_detection"]["confidence"]),
        )

    grid = RollingObstacleMap(
        float(mapping["retention_s"]),
        float(mapping["obstacle_stop_distance_m"]),
        float(mapping["width_m"]),
        float(mapping["height_m"]),
        float(mapping["resolution_m"]),
        float(mapping["inflation_radius_m"]),
        mapping["frame_id"],
    )
    extrinsics = camera["extrinsics"]
    transform = np.asarray(extrinsics["camera_to_base_matrix"], dtype=np.float64)
    calibrated = bool(extrinsics["calibrated"])
    stats = {
        "frames": 0,
        "sync_delta_max_s": 0.0,
        "valid_depth_ratio_sum": 0.0,
        "detections": Counter(),
        "localized_detections": 0,
        "localization_failures": Counter(),
        "frame_ids": Counter(),
        "calibrated_extrinsics": calibrated,
        "mapping_frame": mapping["frame_id"] if calibrated else "camera_optical_xz_diagnostic",
        "navigation_commands": 0,
    }
    last_sequence = 0
    last_depth_timestamp = 0.0
    source.start()
    deadline = time.monotonic() + args.duration
    try:
        while time.monotonic() < deadline:
            packet = source.latest_after(last_sequence)
            if packet is None:
                if source.finished:
                    raise RuntimeError(source.error or "camera bridge stopped")
                time.sleep(0.01)
                continue
            last_sequence = packet.sequence
            last_depth_timestamp = packet.depth_timestamp
            stats["frames"] += 1
            stats["frame_ids"][packet.frame_id] += 1
            stats["resolution"] = [packet.intrinsics.width, packet.intrinsics.height]
            stats["intrinsics"] = {
                "fx": packet.intrinsics.fx,
                "fy": packet.intrinsics.fy,
                "cx": packet.intrinsics.cx,
                "cy": packet.intrinsics.cy,
            }
            stats["sync_delta_max_s"] = max(
                stats["sync_delta_max_s"],
                abs(packet.rgb_timestamp - packet.depth_timestamp),
            )
            valid = np.isfinite(packet.depth_m) & (packet.depth_m > 0)
            stats["valid_depth_ratio_sum"] += float(np.mean(valid))
            if recording:
                recording.write(packet)
            if detector:
                for detection in detector.detect(packet.to_rgbd_frame(), (), "live"):
                    stats["detections"][detection.label] += 1
                    policy = policies[detection.label]
                    localizer = TargetLocalizer(
                        float(system["depth"]["min_m"]),
                        float(system["depth"]["max_m"]),
                        float(system["depth"]["central_roi_fraction"]),
                        float(system["depth"]["max_rgb_depth_delta_s"]),
                        float(system["depth"]["max_frame_age_s"]),
                        accepted_camera_frames=(packet.frame_id,),
                    )
                    if localizer.localize(
                        packet.to_rgbd_frame(),
                        detection,
                        float(policy.min_valid_depth_ratio),
                        # The camera-to-base extrinsic and odom TF are not yet
                        # confirmed, so camera data must not yield a local goal.
                        StaticTransformProvider(available=False),
                    ):
                        stats["localized_detections"] += 1
                    else:
                        stats["localization_failures"][localizer.last_error] += 1
            if calibrated:
                points = pointcloud_to_obstacles(
                    packet.xyz_m,
                    transform,
                    float(mapping["min_obstacle_height_m"]),
                    float(mapping["max_obstacle_height_m"]),
                    float(system["depth"]["min_m"]),
                    float(system["depth"]["max_m"]),
                    int(mapping["point_stride"]),
                )
            else:
                stride = int(mapping["point_stride"])
                xyz = packet.xyz_m[::stride, ::stride]
                finite = np.isfinite(xyz).all(axis=2) & (xyz[:, :, 2] > 0)
                points = [(float(x), float(z)) for x, _y, z in xyz[finite]]
            grid.update(packet.depth_timestamp, points)
    finally:
        source.stop()

    frames = int(stats["frames"])
    stats["valid_depth_ratio_mean"] = (
        stats.pop("valid_depth_ratio_sum") / frames if frames else 0.0
    )
    stats["detections"] = dict(stats["detections"])
    stats["frame_ids"] = dict(stats["frame_ids"])
    stats["localization_failures"] = dict(stats["localization_failures"])
    stats["recording_dir"] = str(recording_dir) if recording_dir else None
    stats["grid_occupied_cells"] = grid.snapshot(last_depth_timestamp).data.count(100)
    stats["passed"] = (
        frames > 0
        and stats["sync_delta_max_s"] <= float(system["depth"]["max_rgb_depth_delta_s"])
        and stats["valid_depth_ratio_mean"] > 0.0
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if stats["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
