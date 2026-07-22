from __future__ import annotations

import math
from collections import deque


class RollingObstacleMap:
    def __init__(self, retention_s: float, stop_distance_m: float):
        self.retention_s = retention_s
        self.stop_distance_m = stop_distance_m
        self._observations: deque[tuple[float, tuple[tuple[float, float], ...]]] = deque()

    def update(self, timestamp: float, points_xy: list[tuple[float, float]]) -> None:
        self._observations.append((timestamp, tuple(points_xy)))
        self.prune(timestamp)

    def prune(self, now: float) -> None:
        while self._observations and now - self._observations[0][0] > self.retention_s:
            self._observations.popleft()

    def path_clear(self, now: float) -> bool:
        self.prune(now)
        return all(math.hypot(x, y) >= self.stop_distance_m
                   for _stamp, points in self._observations for x, y in points)
