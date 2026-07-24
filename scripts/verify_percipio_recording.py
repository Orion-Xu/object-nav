#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import cv2
import numpy as np

from object_nav_demo.camera_protocol import PacketReplaySource
from object_nav_demo.config import PROJECT_ROOT, default_config, load_yaml
from object_nav_demo.detector import UltralyticsDetector
from object_nav_demo.local_mapping import RollingObstacleMap
from object_nav_demo.vocabulary_manager import VocabularyManager


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a local GM461 recording")
    parser.add_argument("recording_dir")
    parser.add_argument("--skip-yolo", action="store_true")
    args = parser.parse_args()
    system = load_yaml(default_config("system.yaml"))
    mapping = system["local_mapping"]
    detector = None
    if not args.skip_yolo:
        vocabulary = VocabularyManager(default_config("vocabulary.yaml"))
        detector = UltralyticsDetector(
            PROJECT_ROOT / system["detector"]["preferred_weights"],
            {
                policy.prompt_en: policy.canonical_label
                for policy in vocabulary.policies
            },
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
        "camera_optical_xz_diagnostic",
    )
    replay = PacketReplaySource(args.recording_dir)
    frames = 0
    detections = Counter()
    last_stamp = 0.0
    while True:
        packet = replay.read_packet()
        if packet is None:
            break
        frames += 1
        last_stamp = packet.depth_timestamp
        if detector:
            for detection in detector.detect(packet.to_rgbd_frame(), (), "replay"):
                detections[detection.label] += 1
        stride = int(mapping["point_stride"])
        xyz = packet.xyz_m[::stride, ::stride]
        valid = np.isfinite(xyz).all(axis=2) & (xyz[:, :, 2] > 0)
        grid.update(last_stamp, [(float(x), float(z)) for x, _y, z in xyz[valid]])
    result = {
        "frames": frames,
        "detections": dict(detections),
        "grid_occupied_cells": grid.snapshot(last_stamp).data.count(100),
        "navigation_commands": 0,
        "passed": frames > 0,
    }
    snapshot = grid.snapshot(last_stamp)
    image = np.asarray(snapshot.data, dtype=np.int16).reshape(snapshot.height, snapshot.width)
    rendered = np.full(image.shape, 127, dtype=np.uint8)
    rendered[image == 0] = 255
    rendered[image == 100] = 0
    map_path = Path(args.recording_dir) / "rolling_grid.png"
    cv2.imwrite(str(map_path), cv2.resize(
        rendered, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST
    ))
    result["map_visualization"] = str(map_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
