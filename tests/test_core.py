from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from object_nav_demo.app_factory import build_offline_demo
from object_nav_demo.command_parser import CommandParser
from object_nav_demo.config import default_config, load_yaml
from object_nav_demo.detector import FakeDetector
from object_nav_demo.frame_source import MockFaults, MockRgbdSource
from object_nav_demo.goal_builder import build_standoff_goal
from object_nav_demo.local_mapping import RollingObstacleMap
from object_nav_demo.models import Detection, LocalizedTarget, NavigationMode, Pose2D, SafetyInputs, TaskState
from object_nav_demo.realtime_detection import ConsecutiveLabelConfirmer
from object_nav_demo.safety_arbiter import SafetyArbiter
from object_nav_demo.search_manager import SearchManager
from object_nav_demo.target_localizer import StaticTransformProvider, TargetLocalizer
from object_nav_demo.vocabulary_manager import VocabularyManager


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.vocab = VocabularyManager(default_config("vocabulary.yaml"))
        self.parser = CommandParser(self.vocab)
        self.world = {p.canonical_label for p in self.vocab.policies}

    def test_ten_configured_expressions(self):
        cases = {
            "寻找椅子": "chair", "找一下桌子": "table", "帮我找沙发": "sofa",
            "去找盆栽": "potted_plant", "找一找背包": "backpack", "寻找行李箱": "suitcase",
            "麻烦你帮我找纸箱": "box", "定位垃圾桶": "trash_can", "找水瓶": "bottle",
            "带我去找笔记本电脑": "laptop",
        }
        for command, label in cases.items():
            with self.subTest(command=command):
                result = self.parser.parse(command, self.world)
                self.assertTrue(result.accepted, result.reason)
                self.assertEqual(label, result.policy.canonical_label)

    def test_unknown_free_text_and_person_rejected(self):
        for command in ("随便走走", "寻找火箭", "寻找人", "椅子"):
            with self.subTest(command=command):
                self.assertFalse(self.parser.parse(command, self.world).accepted)

    def test_fallback_support_is_enforced(self):
        result = self.parser.parse("寻找垃圾桶", {"chair", "person"})
        self.assertFalse(result.accepted)
        self.assertIn("后端不支持", result.reason)

    def test_configuration_only_extension(self):
        text = """version: test\nobjects:\n  - canonical_label: umbrella\n    aliases_zh: [雨伞]\n    prompt_en: umbrella\n    navigation_mode: detect_only\n    min_confidence: 0.5\n    min_valid_depth_ratio: 0.6\n"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "vocab.yaml"
            path.write_text(text, encoding="utf-8")
            manager = VocabularyManager(path)
            result = CommandParser(manager).parse("帮我找雨伞", {"umbrella"})
            self.assertTrue(result.accepted)
            self.assertEqual(NavigationMode.DETECT_ONLY, result.policy.navigation_mode)


class LocalizerTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.localizer = TargetLocalizer(0.2, 8.0, 0.5, 0.05, 0.5, clock=lambda: self.now)
        self.detection = Detection("chair", 0.9, (20, 12, 44, 38), self.now, "fake", "v1")

    def localize(self, faults=MockFaults(), transform=None):
        frame = MockRgbdSource(seed=1, faults=faults, clock=lambda: self.now).read()
        return self.localizer.localize(frame, self.detection, 0.55,
                                       transform or StaticTransformProvider((1, 2, 0)))

    def test_valid_depth_localizes_deterministically(self):
        target = self.localize()
        self.assertIsNotNone(target)
        self.assertAlmostEqual(2.5, target.depth_m, places=2)
        self.assertEqual("odom", target.frame_id)

    def test_invalid_inputs_never_produce_pose(self):
        cases = [
            (MockFaults(unsynced=True), StaticTransformProvider()),
            (MockFaults(stale=True), StaticTransformProvider()),
            (MockFaults(missing_intrinsics=True), StaticTransformProvider()),
            (MockFaults(hole_ratio=0.9), StaticTransformProvider()),
            (MockFaults(), StaticTransformProvider(available=False)),
            (MockFaults(interrupted=True), StaticTransformProvider()),
        ]
        for faults, transform in cases:
            with self.subTest(faults=faults, transform=transform.available):
                self.assertIsNone(self.localize(faults, transform))


class SearchSafetyNavigationTests(unittest.TestCase):
    def test_realtime_confirmation_resets_on_missing_frame(self):
        confirmer = ConsecutiveLabelConfirmer(3)
        self.assertFalse(confirmer.observe(True))
        self.assertFalse(confirmer.observe(True))
        self.assertFalse(confirmer.observe(False))
        self.assertEqual(0, confirmer.count)
        self.assertFalse(confirmer.observe(True))
        self.assertFalse(confirmer.observe(True))
        self.assertTrue(confirmer.observe(True))

    def test_scope_requires_visible_target_and_no_global_map(self):
        system = load_yaml(default_config("system.yaml"))
        self.assertFalse(system["project_scope"]["global_map_required"])
        self.assertTrue(system["project_scope"]["target_must_be_visible_before_motion"])
        self.assertFalse(system["navigation"]["global_planner_enabled"])
        self.assertNotIn("waypoints", system["search"])

    def target(self, label="chair", x=1.0):
        return LocalizedTarget(label, (0, 0, 1), (x, 1, 0), 1.0, 1.0, time.time())

    def test_three_consecutive_stable_frames_required(self):
        search = SearchManager(3, 0.25)
        self.assertIsNone(search.observe(self.target()))
        self.assertIsNone(search.observe(self.target(x=1.1)))
        self.assertIsNotNone(search.observe(self.target(x=1.05)))
        search.reset()
        search.observe(self.target())
        self.assertIsNone(search.observe(self.target(label="table")))
        self.assertEqual(1, search.confirmation_count)

    def test_local_search_has_no_waypoint_navigation(self):
        manager = SearchManager(3, 0.2)
        self.assertFalse(hasattr(manager, "next_waypoint"))

    def test_safety_unknown_and_obstacle_stop(self):
        arbiter = SafetyArbiter()
        self.assertFalse(arbiter.evaluate(SafetyInputs(None, True, True, True, True)).allow_motion)
        self.assertFalse(arbiter.evaluate(SafetyInputs(True, True, True, True, False)).allow_motion)
        self.assertTrue(arbiter.evaluate(SafetyInputs(True, True, True, True, True)).allow_motion)
        grid = RollingObstacleMap(0.8, 0.5)
        grid.update(10.0, [(0.2, 0.1)])
        self.assertFalse(grid.path_clear(10.1))
        self.assertTrue(grid.path_clear(11.0))

    def test_standoff_goal_faces_target(self):
        goal = build_standoff_goal(Pose2D(0, 0), self.target(x=3), 1.0, 10.0)
        self.assertAlmostEqual(((3 ** 2 + 1) ** 0.5) - 1.0,
                               (goal.x ** 2 + goal.y ** 2) ** 0.5)


class StateMachineTests(unittest.TestCase):
    def test_complete_deterministic_closed_loop_and_log(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "demo.jsonl"
            first = build_offline_demo("chair", log)
            self.assertEqual(TaskState.ARRIVED, first.run("寻找椅子"))
            events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            states = [event["state"] for event in events if event["event"] == "state_transition"]
            self.assertEqual(["PARSE", "LOCAL_SEARCH", "TARGET_CONFIRMED", "LOCAL_PLAN", "APPROACH", "ARRIVED"], states)
            self.assertTrue(any(event["event"] == "safety_decision" for event in events))
            second = build_offline_demo("chair")
            self.assertEqual(TaskState.ARRIVED, second.run("寻找椅子"))

    def test_detect_only_never_navigates(self):
        machine = build_offline_demo("bottle")
        self.assertEqual(TaskState.FAILED, machine.run("寻找瓶子"))
        self.assertIn("detect_only", machine.failure_reason)
        self.assertEqual({}, machine.navigation._goals)

    def test_search_exhaustion(self):
        machine = build_offline_demo("chair")
        machine.detector = FakeDetector(["chair"], [])
        self.assertEqual(TaskState.FAILED, machine.run("寻找椅子", max_search_frames=3))
        self.assertEqual({}, machine.navigation._goals)

    def test_navigation_failure_stops(self):
        machine = build_offline_demo("chair")
        machine.navigation._succeed = False
        self.assertEqual(TaskState.STOP, machine.run("寻找椅子"))
        self.assertIn("接近导航失败", machine.navigation.stop_reasons)

    def test_reset_is_required_after_terminal_state(self):
        machine = build_offline_demo("chair")
        self.assertEqual(TaskState.ARRIVED, machine.run("寻找椅子"))
        with self.assertRaises(RuntimeError):
            machine.run("寻找椅子")
        machine.reset()
        self.assertEqual(TaskState.IDLE, machine.state)


if __name__ == "__main__":
    unittest.main()
