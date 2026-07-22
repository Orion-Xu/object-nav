#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    from ultralytics import YOLO, YOLOWorld
    import clip

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    world = YOLOWorld("yolov8s-worldv2.pt")
    world_source = Path("yolov8s-worldv2.pt").resolve()
    if world_source.exists():
        world_source.replace(MODEL_DIR / world_source.name)
        world = YOLOWorld(str(MODEL_DIR / world_source.name))
    fallback = YOLO("yolov8n.pt")
    fallback_source = Path("yolov8n.pt").resolve()
    if fallback_source.exists():
        fallback_source.replace(MODEL_DIR / fallback_source.name)
        fallback = YOLO(str(MODEL_DIR / fallback_source.name))

    # Keep a CPU-only fallback artifact beside the PyTorch checkpoint.  The
    # fixed input size makes replay benchmarks deterministic and avoids any
    # implicit export/download at demo time.
    exported = Path(fallback.export(
        format="onnx", imgsz=640, opset=17, simplify=False, dynamic=False,
    ))
    fallback_onnx = MODEL_DIR / "yolov8n.onnx"
    if exported.resolve() != fallback_onnx.resolve():
        exported.replace(fallback_onnx)

    prompts = [
        "chair", "table", "sofa", "potted plant", "backpack", "suitcase",
        "cardboard box", "trash can", "bottle", "cup", "book", "laptop",
        "keyboard", "computer mouse", "cell phone", "clock", "vase",
        "teddy bear", "person",
    ]
    world.set_classes(prompts)
    offline_path = MODEL_DIR / "yolov8s-worldv2-objectnav.pt"
    world.save(str(offline_path))
    clip.load("ViT-B/32", device="cpu", jit=False, download_root=str(MODEL_DIR / "clip"))

    paths = [
        MODEL_DIR / "yolov8s-worldv2.pt",
        MODEL_DIR / "yolov8n.pt",
        fallback_onnx,
        offline_path,
    ]
    paths.extend((MODEL_DIR / "clip").glob("*"))
    manifest = {
        "models": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path), "bytes": path.stat().st_size}
                   for path in paths if path.is_file()]
    }
    (MODEL_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
