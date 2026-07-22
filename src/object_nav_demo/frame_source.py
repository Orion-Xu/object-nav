from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from .models import CameraIntrinsics, RgbdFrame


@dataclass
class MockFaults:
    hole_ratio: float = 0.0
    outlier_ratio: float = 0.0
    unsynced: bool = False
    stale: bool = False
    missing_intrinsics: bool = False
    interrupted: bool = False


class MockRgbdSource:
    def __init__(self, seed: int = 7, width: int = 64, height: int = 48, depth_m: float = 2.5,
                 faults: MockFaults | None = None, clock=time.time):
        self._random = random.Random(seed)
        self.width = width
        self.height = height
        self.nominal_depth_m = depth_m
        self.faults = faults or MockFaults()
        self.clock = clock

    def read(self) -> RgbdFrame:
        now = self.clock()
        if self.faults.interrupted:
            return RgbdFrame(None, None, now, now, "camera_link", None, now, False, "camera_interrupted")
        rgb = [[[0, 0, 0] for _ in range(self.width)] for _ in range(self.height)]
        depth = []
        for _y in range(self.height):
            row = []
            for _x in range(self.width):
                value = self.nominal_depth_m + self._random.uniform(-0.015, 0.015)
                draw = self._random.random()
                if draw < self.faults.hole_ratio:
                    value = 0.0
                elif draw < self.faults.hole_ratio + self.faults.outlier_ratio:
                    value = math.nan if draw % 0.02 < 0.01 else 99.0
                row.append(value)
            depth.append(row)
        stamp = now - 2.0 if self.faults.stale else now
        depth_stamp = stamp + (0.2 if self.faults.unsynced else 0.0)
        intrinsics = None if self.faults.missing_intrinsics else CameraIntrinsics(
            self.width, self.height, 60.0, 60.0, (self.width - 1) / 2.0, (self.height - 1) / 2.0)
        return RgbdFrame(rgb, depth, stamp, depth_stamp, "camera_link", intrinsics, now)
