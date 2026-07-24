from __future__ import annotations

import json
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from object_nav_demo.app_factory import build_offline_demo
from object_nav_demo.camera_protocol import CameraPacket, PacketRecorder, PacketReplaySource, decode_packet, encode_packet
from object_nav_demo.command_parser import CommandParser
from object_nav_demo.config import default_config, load_yaml
from object_nav_demo.detector import FakeDetector, UltralyticsDetector
from object_nav_demo.frame_source import MockFaults, MockRgbdSource
from object_nav_demo.goal_builder import build_standoff_goal
from object_nav_demo.local_mapping import RollingObstacleMap, pointcloud_to_obstacles
from object_nav_demo.models import CameraIntrinsics, Detection, LocalizedTarget, NavigationMode, Pose2D, SafetyInputs, TaskState
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

    def test_numpy_depth_and_configured_optical_frame_are_supported(self):
        localizer = TargetLocalizer(
            0.2, 8.0, 0.5, 0.05, 0.5,
            clock=lambda: self.now,
            accepted_camera_frames=("camera_rgb_optical_frame",),
        )
        frame = MockRgbdSource(seed=1, clock=lambda: self.now).read()
        frame = frame.__class__(
            frame.rgb,
            np.asarray(frame.depth_m, dtype=np.float32),
            frame.rgb_timestamp,
            frame.depth_timestamp,
            "camera_rgb_optical_frame",
            frame.intrinsics,
            frame.received_at,
        )
        self.assertIsNotNone(localizer.localize(
            frame, self.detection, 0.55, StaticTransformProvider()
        ))

    def test_missing_live_tf_never_produces_local_target(self):
        localizer = TargetLocalizer(
            0.2, 8.0, 0.5, 0.05, 0.5,
            clock=lambda: self.now,
            accepted_camera_frames=("camera_rgb_optical_frame",),
        )
        frame = MockRgbdSource(seed=1, clock=lambda: self.now).read()
        frame = frame.__class__(
            frame.rgb,
            np.asarray(frame.depth_m, dtype=np.float32),
            frame.rgb_timestamp,
            frame.depth_timestamp,
            "camera_rgb_optical_frame",
            frame.intrinsics,
            frame.received_at,
        )
        self.assertIsNone(localizer.localize(
            frame, self.detection, 0.55,
            StaticTransformProvider(available=False),
        ))
        self.assertEqual("missing_tf", localizer.last_error)

    def test_invalid_intrinsics_never_produce_target(self):
        frame = MockRgbdSource(seed=1, clock=lambda: self.now).read()
        frame = frame.__class__(
            frame.rgb,
            frame.depth_m,
            frame.rgb_timestamp,
            frame.depth_timestamp,
            frame.frame_id,
            CameraIntrinsics(64, 48, 0.0, 60.0, 32.0, 24.0),
            frame.received_at,
        )
        self.assertIsNone(self.localizer.localize(
            frame, self.detection, 0.55, StaticTransformProvider()
        ))
        self.assertEqual("invalid_intrinsics", self.localizer.last_error)


class CameraProtocolTests(unittest.TestCase):
    def packet(self):
        bgr = np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
        xyz = np.zeros((3, 4, 3), dtype=np.float32)
        xyz[:, :, 2] = 2.5
        return CameraPacket(
            7, 10.0, 10.01, "camera_rgb_optical_frame",
            CameraIntrinsics(4, 3, 100.0, 101.0, 1.5, 1.0),
            bgr, xyz,
        )

    def test_packet_round_trip_preserves_rgb_depth_and_intrinsics(self):
        restored = decode_packet(encode_packet(self.packet()))
        self.assertEqual(7, restored.sequence)
        self.assertEqual("camera_rgb_optical_frame", restored.frame_id)
        np.testing.assert_array_equal(self.packet().bgr, restored.bgr)
        np.testing.assert_allclose(self.packet().xyz_m, restored.xyz_m)
        self.assertAlmostEqual(2.5, restored.to_rgbd_frame().depth_m[0, 0])

    def test_recording_replays_without_camera(self):
        with tempfile.TemporaryDirectory() as folder:
            recording = PacketRecorder(Path(folder) / "sample")
            recording.write(self.packet())
            replay = PacketReplaySource(Path(folder) / "sample")
            self.assertEqual(7, replay.read_packet().sequence)
            self.assertIsNone(replay.read_packet())

    def test_corrupt_packet_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_packet(encode_packet(self.packet())[:-1])

    def test_invalid_packet_metadata_is_rejected(self):
        packet = self.packet()
        invalid = CameraPacket(
            packet.sequence,
            packet.rgb_timestamp,
            packet.depth_timestamp,
            packet.frame_id,
            CameraIntrinsics(4, 3, 0.0, 101.0, 1.5, 1.0),
            packet.bgr,
            packet.xyz_m,
        )
        with self.assertRaisesRegex(ValueError, "intrinsics"):
            encode_packet(invalid)


class DetectorAdapterTests(unittest.TestCase):
    def test_world_prompt_is_mapped_back_to_canonical_label(self):
        box = types.SimpleNamespace(
            cls=np.asarray(0),
            conf=np.asarray(0.9),
            xyxy=np.asarray([[1.0, 2.0, 3.0, 4.0]]),
        )
        result = types.SimpleNamespace(
            names={0: "potted plant"},
            boxes=[box],
        )

        class Model:
            def set_classes(self, prompts):
                self.prompts = prompts

            def predict(self, *_args, **_kwargs):
                return [result]

        model = Model()
        module = types.SimpleNamespace(
            YOLO=lambda _path: model,
            YOLOWorld=lambda _path: model,
        )
        with tempfile.TemporaryDirectory() as folder:
            weights = Path(folder) / "world.pt"
            weights.touch()
            with patch.dict("sys.modules", {"ultralytics": module}):
                detector = UltralyticsDetector(
                    weights,
                    {"potted plant": "potted_plant"},
                )
                detections = detector.detect(
                    MockRgbdSource(seed=1).read(), (), "test-vocab"
                )

        self.assertEqual(["potted plant"], model.prompts)
        self.assertEqual(frozenset({"potted_plant"}), detector.info.supported_labels)
        self.assertEqual("potted_plant", detections[0].label)


class RollingGridTests(unittest.TestCase):
    def test_ray_clearing_decay_inflation_and_path_corridor(self):
        grid = RollingObstacleMap(
            retention_s=0.8,
            stop_distance_m=0.5,
            width_m=4.0,
            height_m=4.0,
            resolution_m=0.1,
            inflation_radius_m=0.2,
        )
        grid.update(1.0, [(1.0, 0.0)])
        self.assertFalse(grid.path_clear(1.0, [(0.0, 0.0), (1.5, 0.0)]))
        self.assertTrue(grid.path_clear(1.0, [(0.0, 0.8), (1.5, 0.8)]))
        grid.update(1.1, [(1.5, 0.0)])
        uninflated = grid.snapshot(1.1, inflated=False)
        occupied = uninflated.data.count(100)
        self.assertEqual(1, occupied)
        self.assertEqual(0, grid.snapshot(2.0).data.count(100))

    def test_window_motion_retains_overlap_and_drops_outside(self):
        grid = RollingObstacleMap(10.0, 0.2, 2.0, 2.0, 0.1, 0.0)
        grid.update(1.0, [(0.4, 0.0), (-0.8, 0.0)])
        grid.move_center((0.5, 0.0))
        self.assertEqual(1, grid.snapshot(1.0, inflated=False).data.count(100))

    def test_metric_pointcloud_transform_and_height_filter(self):
        xyz = np.array([[[1.0, 0.0, 0.2], [2.0, 0.0, 2.0]]], dtype=np.float32)
        points = pointcloud_to_obstacles(
            xyz, np.eye(4), 0.1, 1.0, min_range_m=0.0, max_range_m=4.0, stride=1
        )
        self.assertEqual([(1.0, 0.0)], points)


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
        self.assertFalse(Path(system["camera"]["recording_root"]).is_absolute())

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
