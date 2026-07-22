from __future__ import annotations

import math

from .models import LocalizedTarget, Pose2D


def build_standoff_goal(robot: Pose2D, target: LocalizedTarget, standoff_m: float, timestamp: float) -> Pose2D:
    if robot.frame_id != target.frame_id:
        raise ValueError("机器人和目标必须位于同一局部坐标系")
    tx, ty, _ = target.point_local
    dx, dy = tx - robot.x, ty - robot.y
    distance = math.hypot(dx, dy)
    if distance <= 1e-9:
        raise ValueError("目标与机器人位置重合，无法生成停靠位姿")
    travel = max(0.0, distance - standoff_m)
    yaw = math.atan2(dy, dx)
    return Pose2D(robot.x + dx / distance * travel, robot.y + dy / distance * travel,
                  yaw, robot.frame_id, timestamp)
