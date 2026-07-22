from __future__ import annotations

from pathlib import Path

from .command_parser import CommandParser
from .config import default_config, load_yaml
from .detector import FakeDetector
from .frame_source import MockRgbdSource
from .local_mapping import RollingObstacleMap
from .navigation_adapter import MockNavigationAdapter
from .safety_arbiter import SafetyArbiter
from .search_manager import SearchManager
from .state_machine import OfflineStateMachine
from .target_localizer import StaticTransformProvider, TargetLocalizer
from .telemetry import JsonlTelemetry
from .vocabulary_manager import VocabularyManager


def build_offline_demo(target_label: str, log_path: str | Path | None = None) -> OfflineStateMachine:
    vocabulary = VocabularyManager(default_config("vocabulary.yaml"))
    system = load_yaml(default_config("system.yaml"))
    scripted = [[], [], [],
                [(target_label, 0.90, (20, 12, 44, 38))],
                [(target_label, 0.91, (20, 12, 44, 38))],
                [(target_label, 0.92, (20, 12, 44, 38))]]
    detector = FakeDetector([item.canonical_label for item in vocabulary.policies], scripted)
    depth = system["depth"]
    localizer = TargetLocalizer(float(depth["min_m"]), float(depth["max_m"]),
                                 float(depth["central_roi_fraction"]),
                                 float(depth["max_rgb_depth_delta_s"]), float(depth["max_frame_age_s"]))
    search_cfg = system["search"]
    search = SearchManager(int(search_cfg["confirmation_frames"]),
                           float(search_cfg["max_position_delta_m"]))
    mapping = system["local_mapping"]
    obstacles = RollingObstacleMap(float(mapping["retention_s"]), float(mapping["obstacle_stop_distance_m"]))
    return OfflineStateMachine(CommandParser(vocabulary), detector, MockRgbdSource(), localizer,
                               StaticTransformProvider((2.0, 1.0, 0.0)), search,
                               MockNavigationAdapter(), obstacles, SafetyArbiter(), JsonlTelemetry(log_path),
                               float(system["navigation"]["default_standoff_m"]),
                               str(system.get("version", "unknown")))
