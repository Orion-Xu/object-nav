from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from .models import Detection, RgbdFrame


@dataclass(frozen=True)
class DetectorInfo:
    backend: str
    model_version: str
    supported_labels: frozenset[str]
    fallback_active: bool = False


class Detector(Protocol):
    @property
    def info(self) -> DetectorInfo: ...

    def detect(self, frame: RgbdFrame, prompts: Sequence[str], vocabulary_version: str) -> list[Detection]: ...


class FakeDetector:
    """Deterministic detector used by tests and the offline acceptance demo."""

    def __init__(self, labels: Sequence[str], scripted: Sequence[Sequence[tuple[str, float, tuple[int, int, int, int]]]] | None = None):
        self._info = DetectorInfo("fake", "fake-detector-v1", frozenset(labels))
        self._scripted = list(scripted or [])
        self._index = 0

    @property
    def info(self) -> DetectorInfo:
        return self._info

    def detect(self, frame: RgbdFrame, prompts: Sequence[str], vocabulary_version: str) -> list[Detection]:
        rows = self._scripted[self._index] if self._index < len(self._scripted) else []
        self._index += 1
        return [Detection(label, confidence, bbox, frame.rgb_timestamp, self.info.model_version, vocabulary_version)
                for label, confidence, bbox in rows if label in self.info.supported_labels]


class UltralyticsDetector:
    """Optional local-weight adapter. It never downloads a model implicitly."""

    def __init__(
        self,
        weights: str | Path,
        labels: Sequence[str] | Mapping[str, str],
        world_model: bool = True,
        device: str | int | None = None,
        image_size: int = 640,
        confidence: float = 0.25,
    ):
        path = Path(weights)
        if not path.is_file():
            raise FileNotFoundError(f"本地模型权重不存在: {path}")
        try:
            from ultralytics import YOLO, YOLOWorld
        except ImportError as exc:
            raise RuntimeError("未安装可选依赖 ultralytics") from exc
        self._model = (YOLOWorld if world_model else YOLO)(str(path))
        if isinstance(labels, Mapping):
            self._prompt_to_label = dict(labels)
        else:
            self._prompt_to_label = {label: label for label in labels}
        self._prompts = tuple(self._prompt_to_label)
        self._device = device
        self._image_size = image_size
        self._confidence = confidence
        if world_model:
            self._model.set_classes(list(self._prompts))
        self._info = DetectorInfo(
            "yolo_world" if world_model else "yolov8n",
            path.name,
            frozenset(self._prompt_to_label.values()),
            not world_model,
        )

    @property
    def info(self) -> DetectorInfo:
        return self._info

    def detect(self, frame: RgbdFrame, prompts: Sequence[str], vocabulary_version: str) -> list[Detection]:
        results = self._model.predict(
            frame.rgb,
            device=self._device,
            imgsz=self._image_size,
            conf=self._confidence,
            verbose=False,
        )
        detections: list[Detection] = []
        for result in results:
            names = result.names
            for box in result.boxes:
                cls_id = int(box.cls.item())
                prompt = str(names[cls_id])
                label = self._prompt_to_label.get(prompt)
                if label is None:
                    continue
                if label not in self.info.supported_labels:
                    continue
                xyxy = tuple(int(round(value)) for value in box.xyxy[0].tolist())
                detections.append(Detection(label, float(box.conf.item()), xyxy, frame.rgb_timestamp,
                                            self.info.model_version, vocabulary_version))
        return detections


def choose_backend(preferred_factory, fallback_factory):
    """Try the preferred backend and explicitly mark/return the configured fallback."""
    try:
        return preferred_factory()
    except Exception:
        detector = fallback_factory()
        return detector
