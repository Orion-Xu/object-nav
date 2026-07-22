from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT


def _module(name: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(name)
        return {"ok": True, "version": str(getattr(module, "__version__", "unknown"))}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def collect_environment() -> dict[str, Any]:
    modules = {name: _module(name) for name in (
        "yaml", "numpy", "cv2", "torch", "torchvision", "ultralytics",
        "onnx", "onnxruntime", "open3d", "clip", "pytest",
    )}
    cuda = {"available": False}
    if modules["torch"]["ok"]:
        import torch
        cuda = {
            "available": bool(torch.cuda.is_available()),
            "runtime": str(torch.version.cuda),
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        }
    try:
        smi = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                             "--format=csv,noheader"], check=True, capture_output=True, text=True, timeout=10)
        nvidia = {"ok": True, "summary": smi.stdout.strip()}
    except Exception as exc:
        nvidia = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    models = {}
    for name in (
        "yolov8s-worldv2.pt", "yolov8s-worldv2-objectnav.pt",
        "yolov8n.pt", "yolov8n.onnx",
    ):
        path = PROJECT_ROOT / "models" / name
        models[name] = {"exists": path.is_file(), "bytes": path.stat().st_size if path.is_file() else 0}
    return {
        "python": sys.version.split()[0], "executable": sys.executable,
        "modules": modules, "cuda": cuda, "nvidia_smi": nvidia, "models": models,
        "ros_setup_exists": Path("/opt/ros/noetic/setup.zsh").is_file(),
    }


def main() -> int:
    report = collect_environment()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    required = ("yaml", "numpy", "cv2", "torch", "torchvision", "ultralytics", "onnxruntime", "pytest")
    return 0 if report["cuda"]["available"] and all(report["modules"][name]["ok"] for name in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
