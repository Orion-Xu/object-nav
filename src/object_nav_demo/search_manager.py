from __future__ import annotations

import math
from collections import deque

from .models import LocalizedTarget


class SearchManager:
    """Confirm a target in the current local view; it never visits map waypoints."""

    def __init__(self, confirmation_frames: int, max_position_delta_m: float):
        if confirmation_frames < 1:
            raise ValueError("确认帧数必须大于零")
        self.confirmation_frames = confirmation_frames
        self.max_position_delta_m = max_position_delta_m
        self._candidates: deque[LocalizedTarget] = deque(maxlen=confirmation_frames)

    def reset(self) -> None:
        self._candidates.clear()

    def observe(self, candidate: LocalizedTarget | None) -> LocalizedTarget | None:
        if candidate is None:
            self._candidates.clear()
            return None
        if self._candidates:
            previous = self._candidates[-1]
            distance = math.dist(previous.point_local, candidate.point_local)
            if previous.label != candidate.label or distance > self.max_position_delta_m:
                self._candidates.clear()
        self._candidates.append(candidate)
        if len(self._candidates) == self.confirmation_frames:
            return candidate
        return None

    @property
    def confirmation_count(self) -> int:
        return len(self._candidates)
