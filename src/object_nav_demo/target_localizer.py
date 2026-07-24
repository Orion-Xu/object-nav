from __future__ import annotations

import math
from numbers import Real
import statistics
import time
from typing import Protocol

from .models import Detection, LocalizedTarget, RgbdFrame


class TransformProvider(Protocol):
    def camera_to_local(self, point: tuple[float, float, float], timestamp: float) -> tuple[float, float, float] | None: ...


class StaticTransformProvider:
    def __init__(self, translation=(0.0, 0.0, 0.0), yaw: float = 0.0, available: bool = True):
        self.translation = translation
        self.yaw = yaw
        self.available = available

    def camera_to_local(self, point: tuple[float, float, float], timestamp: float) -> tuple[float, float, float] | None:
        if not self.available:
            return None
        x, y, z = point
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        tx, ty, tz = self.translation
        return (c * x - s * y + tx, s * x + c * y + ty, z + tz)


class TargetLocalizer:
    def __init__(self, min_depth_m: float, max_depth_m: float, roi_fraction: float,
                 max_sync_delta_s: float, max_frame_age_s: float, clock=time.time,
                 accepted_camera_frames: tuple[str, ...] = ("camera_link",)):
        if not 0 < roi_fraction <= 1:
            raise ValueError("roi_fraction 必须在 (0,1]")
        self.min_depth_m = min_depth_m
        self.max_depth_m = max_depth_m
        self.roi_fraction = roi_fraction
        self.max_sync_delta_s = max_sync_delta_s
        self.max_frame_age_s = max_frame_age_s
        self.clock = clock
        self.accepted_camera_frames = frozenset(accepted_camera_frames)
        self.last_error: str | None = None

    def localize(self, frame: RgbdFrame, detection: Detection, min_valid_ratio: float,
                 transform: TransformProvider) -> LocalizedTarget | None:
        self.last_error = None
        if not frame.valid or frame.depth_m is None:
            return self._fail(frame.error or "invalid_frame")
        if frame.intrinsics is None:
            return self._fail("missing_intrinsics")
        intr = frame.intrinsics
        if not (
            intr.width > 0
            and intr.height > 0
            and math.isfinite(intr.fx)
            and math.isfinite(intr.fy)
            and intr.fx > 0
            and intr.fy > 0
            and math.isfinite(intr.cx)
            and math.isfinite(intr.cy)
        ):
            return self._fail("invalid_intrinsics")
        if frame.frame_id not in self.accepted_camera_frames:
            return self._fail("unexpected_camera_frame")
        if abs(frame.rgb_timestamp - frame.depth_timestamp) > self.max_sync_delta_s:
            return self._fail("rgb_depth_unsynchronized")
        if self.clock() - max(frame.rgb_timestamp, frame.depth_timestamp) > self.max_frame_age_s:
            return self._fail("stale_frame")
        x1, y1, x2, y2 = detection.bbox_xyxy
        width, height = x2 - x1, y2 - y1
        if width <= 0 or height <= 0:
            return self._fail("invalid_bbox")
        margin_x = width * (1.0 - self.roi_fraction) / 2.0
        margin_y = height * (1.0 - self.roi_fraction) / 2.0
        left = max(0, int(math.floor(x1 + margin_x)))
        right = min(frame.intrinsics.width, int(math.ceil(x2 - margin_x)))
        top = max(0, int(math.floor(y1 + margin_y)))
        bottom = min(frame.intrinsics.height, int(math.ceil(y2 - margin_y)))
        try:
            samples = [
                frame.depth_m[y][x]
                for y in range(top, bottom)
                for x in range(left, right)
            ]
        except (IndexError, TypeError):
            return self._fail("invalid_depth_shape")
        if not samples:
            return self._fail("empty_depth_roi")
        valid = [float(v) for v in samples if isinstance(v, Real) and math.isfinite(v)
                 and self.min_depth_m <= float(v) <= self.max_depth_m]
        ratio = len(valid) / len(samples)
        if ratio < min_valid_ratio:
            return self._fail("insufficient_valid_depth")
        median = statistics.median(valid)
        u, v = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        point_camera = ((u - intr.cx) * median / intr.fx, (v - intr.cy) * median / intr.fy, median)
        point_local = transform.camera_to_local(point_camera, detection.timestamp)
        if point_local is None:
            return self._fail("missing_tf")
        return LocalizedTarget(detection.label, point_camera, point_local, median, ratio,
                               detection.timestamp, "odom")

    def _fail(self, reason: str):
        self.last_error = reason
        return None
