#!/usr/bin/env python3
"""Run one deterministic smoke test for every installed vision backend."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    args = parser.parse_args()

    import clip
    import cv2
    import numpy as np
    import onnxruntime as ort
    import open3d as o3d
    import torch
    from PIL import Image
    from ultralytics import YOLOWorld

    world_path = ROOT / "models/yolov8s-worldv2-objectnav.pt"
    onnx_path = ROOT / "models/yolov8n.onnx"
    if not args.image.is_file() or not world_path.is_file() or not onnx_path.is_file():
        raise FileNotFoundError("测试图片或离线模型缺失")

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    world = YOLOWorld(str(world_path))
    result = world.predict(str(args.image), device=device, verbose=False)[0]
    detections = [
        {
            "label": str(result.names[int(box.cls.item())]),
            "confidence": round(float(box.conf.item()), 4),
        }
        for box in result.boxes
    ]

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_info = session.get_inputs()[0]
    dummy = np.zeros(tuple(int(value) for value in input_info.shape), dtype=np.float32)
    onnx_outputs = session.run(None, {input_info.name: dummy})

    clip_model, preprocess = clip.load(
        "ViT-B/32", device="cpu", jit=False,
        download_root=str(ROOT / "models/clip"),
    )
    image_tensor = preprocess(Image.open(args.image).convert("RGB")).unsqueeze(0)
    text = clip.tokenize(["a photo of a bus", "a photo of a chair"])
    with torch.no_grad():
        logits, _ = clip_model(image_tensor, text)

    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.array([[0.0, 0.0, 1.0]]))
    report = {
        "cuda": {"available": torch.cuda.is_available(), "device": device},
        "yolo_world": {"model": world_path.name, "detections": detections},
        "onnx_cpu": {
            "model": onnx_path.name,
            "provider": session.get_providers()[0],
            "output_shapes": [list(value.shape) for value in onnx_outputs],
        },
        "clip_cpu": {"scores": logits.softmax(dim=-1)[0].tolist()},
        "open3d": {"point_count": len(cloud.points)},
        "opencv": cv2.__version__,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
