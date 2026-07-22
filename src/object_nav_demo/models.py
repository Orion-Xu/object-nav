from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class NavigationMode(str, Enum):
    APPROACH = "approach"
    DETECT_ONLY = "detect_only"
    DISABLED = "disabled"


class TaskState(str, Enum):
    IDLE = "IDLE"
    PARSE = "PARSE"
    LOCAL_SEARCH = "LOCAL_SEARCH"
    TARGET_CONFIRMED = "TARGET_CONFIRMED"
    LOCAL_PLAN = "LOCAL_PLAN"
    APPROACH = "APPROACH"
    ARRIVED = "ARRIVED"
    STOP = "STOP"
    FAILED = "FAILED"


class NavigationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ObjectPolicy:
    canonical_label: str
    aliases_zh: tuple[str, ...]
    prompt_en: str
    navigation_mode: NavigationMode
    min_confidence: float
    min_valid_depth_ratio: float
    standoff_m: Optional[float] = None


@dataclass(frozen=True)
class ParseResult:
    accepted: bool
    task_id: str
    raw_text: str
    timestamp: float
    vocabulary_version: str
    policy: Optional[ObjectPolicy] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class CameraIntrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass(frozen=True)
class RgbdFrame:
    rgb: Any
    depth_m: Any
    rgb_timestamp: float
    depth_timestamp: float
    frame_id: str
    intrinsics: Optional[CameraIntrinsics]
    received_at: float
    valid: bool = True
    error: Optional[str] = None


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    bbox_xyxy: tuple[int, int, int, int]
    timestamp: float
    model_version: str
    vocabulary_version: str


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    yaw: float = 0.0
    frame_id: str = "odom"
    timestamp: float = 0.0


@dataclass(frozen=True)
class LocalizedTarget:
    label: str
    point_camera: tuple[float, float, float]
    point_local: tuple[float, float, float]
    depth_m: float
    valid_depth_ratio: float
    timestamp: float
    frame_id: str = "odom"


@dataclass(frozen=True)
class SafetyInputs:
    estop_clear: Optional[bool]
    odometry_ok: bool
    navigation_healthy: bool
    camera_fresh: bool
    path_clear: bool


@dataclass(frozen=True)
class SafetyDecision:
    allow_motion: bool
    reason: str


def jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(item) for item in value]
    return value
