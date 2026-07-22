from __future__ import annotations

import itertools
import time
from typing import Protocol

from .models import NavigationStatus, Pose2D


class NavigationAdapter(Protocol):
    def get_pose(self) -> Pose2D | None: ...
    def navigate_to_pose(self, goal: Pose2D) -> str: ...
    def get_navigation_status(self, task_id: str) -> NavigationStatus: ...
    def request_stop(self, reason: str) -> None: ...


class MockNavigationAdapter:
    """Goal-level simulator; deliberately has no velocity publishing method."""

    def __init__(self, initial_pose: Pose2D | None = None, succeed: bool = True):
        self._pose = initial_pose or Pose2D(0.0, 0.0)
        self._succeed = succeed
        self._ids = itertools.count(1)
        self._tasks: dict[str, NavigationStatus] = {}
        self._goals: dict[str, Pose2D] = {}
        self.stop_reasons: list[str] = []

    def get_pose(self) -> Pose2D | None:
        return self._pose

    def navigate_to_pose(self, goal: Pose2D) -> str:
        task_id = f"mock-nav-{next(self._ids)}"
        self._tasks[task_id] = NavigationStatus.SUCCEEDED if self._succeed else NavigationStatus.FAILED
        self._goals[task_id] = goal
        if self._succeed:
            self._pose = Pose2D(goal.x, goal.y, goal.yaw, goal.frame_id, time.time())
        return task_id

    def get_navigation_status(self, task_id: str) -> NavigationStatus:
        return self._tasks.get(task_id, NavigationStatus.UNKNOWN)

    def request_stop(self, reason: str) -> None:
        self.stop_reasons.append(reason)
        for task_id, status in list(self._tasks.items()):
            if status in (NavigationStatus.PENDING, NavigationStatus.ACTIVE):
                self._tasks[task_id] = NavigationStatus.CANCELED
