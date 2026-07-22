from __future__ import annotations

import time

from .command_parser import CommandParser
from .detector import Detector
from .frame_source import MockRgbdSource
from .goal_builder import build_standoff_goal
from .local_mapping import RollingObstacleMap
from .models import NavigationMode, NavigationStatus, SafetyInputs, TaskState
from .navigation_adapter import NavigationAdapter
from .safety_arbiter import SafetyArbiter
from .search_manager import SearchManager
from .target_localizer import TargetLocalizer, TransformProvider
from .telemetry import JsonlTelemetry


class OfflineStateMachine:
    def __init__(self, parser: CommandParser, detector: Detector, frame_source: MockRgbdSource,
                 localizer: TargetLocalizer, transform: TransformProvider, search: SearchManager,
                 navigation: NavigationAdapter, obstacles: RollingObstacleMap,
                 safety: SafetyArbiter, telemetry: JsonlTelemetry, default_standoff_m: float = 1.0,
                 system_config_version: str = "unknown"):
        self.parser, self.detector, self.frame_source = parser, detector, frame_source
        self.localizer, self.transform, self.search = localizer, transform, search
        self.navigation, self.obstacles, self.safety = navigation, obstacles, safety
        self.telemetry, self.default_standoff_m = telemetry, default_standoff_m
        self.system_config_version = system_config_version
        self.state = TaskState.IDLE
        self.failure_reason: str | None = None

    def reset(self) -> None:
        self.state = TaskState.IDLE
        self.failure_reason = None
        self.search.reset()

    def _transition(self, state: TaskState, task_id: str, reason: str | None = None) -> None:
        previous = self.state
        self.state = state
        self.telemetry.record("state_transition", task_id, previous=previous, state=state, reason=reason)

    def _fail(self, task_id: str, reason: str, stop: bool = False) -> TaskState:
        self.failure_reason = reason
        if stop:
            self.navigation.request_stop(reason)
            self._transition(TaskState.STOP, task_id, reason)
        else:
            self._transition(TaskState.FAILED, task_id, reason)
        return self.state

    def run(self, command: str, max_search_frames: int = 6) -> TaskState:
        if self.state not in (TaskState.IDLE,):
            raise RuntimeError("任务未复位，不能开始新任务")
        parsed = self.parser.parse(command, self.detector.info.supported_labels)
        task_id = parsed.task_id
        self._transition(TaskState.PARSE, task_id)
        self.telemetry.record("command_parsed", task_id, result=parsed, detector=self.detector.info,
                              system_config_version=self.system_config_version)
        if not parsed.accepted or parsed.policy is None:
            return self._fail(task_id, parsed.reason or "解析失败")
        if parsed.policy.navigation_mode is NavigationMode.DETECT_ONLY:
            return self._fail(task_id, "目标策略为 detect_only，仅展示检测，不生成导航任务")
        self._transition(TaskState.LOCAL_SEARCH, task_id)
        confirmed = None
        for frame_index in range(max_search_frames):
            frame = self.frame_source.read()
            detections = self.detector.detect(frame, [parsed.policy.prompt_en], parsed.vocabulary_version)
            valid = [d for d in detections if d.label == parsed.policy.canonical_label
                     and d.confidence >= parsed.policy.min_confidence]
            valid.sort(key=lambda d: d.confidence, reverse=True)
            candidate = None if not valid else self.localizer.localize(
                frame, valid[0], parsed.policy.min_valid_depth_ratio, self.transform)
            confirmed = self.search.observe(candidate)
            self.telemetry.record("local_observation", task_id, frame_index=frame_index,
                                  frame_valid=frame.valid, detections=detections,
                                  localized=candidate, localization_error=self.localizer.last_error,
                                  confirmation_count=self.search.confirmation_count)
            if confirmed is not None:
                break
        if confirmed is None:
            return self._fail(task_id, "当前可见范围内未连续确认目标")
        self._transition(TaskState.TARGET_CONFIRMED, task_id)
        self._transition(TaskState.LOCAL_PLAN, task_id)
        robot = self.navigation.get_pose()
        if robot is None:
            return self._fail(task_id, "短时里程计不可用", stop=True)
        now = time.time()
        decision = self.safety.evaluate(SafetyInputs(True, True, True, True, self.obstacles.path_clear(now)))
        self.telemetry.record("safety_decision", task_id, decision=decision)
        if not decision.allow_motion:
            return self._fail(task_id, decision.reason, stop=True)
        goal = build_standoff_goal(robot, confirmed, parsed.policy.standoff_m or self.default_standoff_m, now)
        self.telemetry.record("approach_goal", task_id, target=confirmed, goal=goal)
        self._transition(TaskState.APPROACH, task_id)
        nav_id = self.navigation.navigate_to_pose(goal)
        status = self.navigation.get_navigation_status(nav_id)
        self.telemetry.record("navigation_result", task_id, navigation_task_id=nav_id, status=status)
        if status is not NavigationStatus.SUCCEEDED:
            return self._fail(task_id, "接近导航失败", stop=True)
        self._transition(TaskState.ARRIVED, task_id)
        return self.state

    def target_lost_during_approach(self, task_id: str = "active") -> TaskState:
        if self.state is not TaskState.APPROACH:
            raise RuntimeError("仅 APPROACH 状态可报告目标丢失")
        self.navigation.request_stop("接近期间目标丢失")
        self.search.reset()
        self._transition(TaskState.STOP, task_id, "接近期间目标丢失，必须重新确认")
        return self.state
