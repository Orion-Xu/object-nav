from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable


@dataclass(frozen=True)
class CapturedFrame:
    sequence: int
    captured_at: float
    bgr: Any


class ConsecutiveLabelConfirmer:
    """Small display-only confirmer; it never creates a navigation request."""

    def __init__(self, required_frames: int = 3):
        if required_frames < 1:
            raise ValueError("required_frames must be positive")
        self.required_frames = required_frames
        self.count = 0

    def observe(self, present: bool) -> bool:
        self.count = min(self.required_frames, self.count + 1) if present else 0
        return self.count >= self.required_frames

    def reset(self) -> None:
        self.count = 0


class OpenCvLatestFrameSource:
    """Continuously captures frames and retains only the newest one."""

    def __init__(self, source: int | str, capture_factory: Callable[[int | str], Any] | None = None):
        self.source = source
        self._capture_factory = capture_factory
        self._capture = None
        self._latest: CapturedFrame | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._finished = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_interval_s = 0.0
        self.error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if self._capture_factory is None:
            import cv2
            self._capture_factory = cv2.VideoCapture
        self._capture = self._capture_factory(self.source)
        if not self._capture or not self._capture.isOpened():
            if self._capture:
                self._capture.release()
            raise RuntimeError(f"无法打开实时数据源: {self.source}")
        # Cameras provide frames at their own rate. Video files do not, so pace
        # them by their encoded FPS instead of consuming the whole file at once.
        if isinstance(self.source, str):
            try:
                import cv2
                fps = float(self._capture.get(cv2.CAP_PROP_FPS))
                self._frame_interval_s = 1.0 / fps if 0.5 <= fps <= 240.0 else 0.0
            except (AttributeError, TypeError, ValueError):
                self._frame_interval_s = 0.0
        self._stop.clear()
        self._finished.clear()
        self.error = None
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="opencv-frame-source")
        self._thread.start()

    def _capture_loop(self) -> None:
        sequence = 0
        next_frame_at = time.monotonic()
        try:
            while not self._stop.is_set():
                ok, frame = self._capture.read()
                if not ok:
                    self.error = "数据源结束或相机断流"
                    break
                sequence += 1
                captured = CapturedFrame(sequence, time.time(), frame)
                with self._lock:
                    self._latest = captured
                if self._frame_interval_s:
                    next_frame_at += self._frame_interval_s
                    self._stop.wait(max(0.0, next_frame_at - time.monotonic()))
        except Exception as exc:
            self.error = f"采集异常: {type(exc).__name__}: {exc}"
        finally:
            if self._capture:
                self._capture.release()
            self._finished.set()

    def latest_after(self, sequence: int) -> CapturedFrame | None:
        with self._lock:
            if self._latest is None or self._latest.sequence <= sequence:
                return None
            return self._latest

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.25)
        if thread and thread.is_alive() and self._capture:
            self._capture.release()
            if thread is not threading.current_thread():
                thread.join(timeout=0.75)
