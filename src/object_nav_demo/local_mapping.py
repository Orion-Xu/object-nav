from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence


Cell = tuple[int, int]


@dataclass(frozen=True)
class GridSnapshot:
    width: int
    height: int
    resolution_m: float
    origin_x_m: float
    origin_y_m: float
    frame_id: str
    timestamp: float
    data: tuple[int, ...]


class RollingObstacleMap:
    """Short-range rolling occupancy grid with ray clearing and time decay.

    Occupancy is stored in world-aligned integer cells. Moving the grid center
    discards cells outside the rolling window while retaining its overlap.
    """

    def __init__(
        self,
        retention_s: float,
        stop_distance_m: float,
        width_m: float = 8.0,
        height_m: float = 8.0,
        resolution_m: float = 0.05,
        inflation_radius_m: float | None = None,
        frame_id: str = "base_link",
    ):
        for name, value in (
            ("retention_s", retention_s),
            ("stop_distance_m", stop_distance_m),
            ("width_m", width_m),
            ("height_m", height_m),
            ("resolution_m", resolution_m),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        self.retention_s = retention_s
        self.stop_distance_m = stop_distance_m
        self.width_m = width_m
        self.height_m = height_m
        self.resolution_m = resolution_m
        self.inflation_radius_m = (
            stop_distance_m if inflation_radius_m is None else inflation_radius_m
        )
        self.frame_id = frame_id
        self.center_xy = (0.0, 0.0)
        self._occupied: dict[Cell, float] = {}
        self._free: dict[Cell, float] = {}

    @property
    def width_cells(self) -> int:
        return max(1, int(round(self.width_m / self.resolution_m)))

    @property
    def height_cells(self) -> int:
        return max(1, int(round(self.height_m / self.resolution_m)))

    def update(
        self,
        timestamp: float,
        points_xy: Iterable[tuple[float, float]],
        sensor_xy: tuple[float, float] | None = None,
        center_xy: tuple[float, float] | None = None,
    ) -> None:
        if center_xy is not None:
            self.move_center(center_xy)
        self.prune(timestamp)
        if sensor_xy is None:
            sensor_xy = self.center_xy
        sensor_cell = self._cell(sensor_xy)
        cleared: set[Cell] = set()
        hits: set[Cell] = set()
        for point in points_xy:
            if not all(math.isfinite(value) for value in point):
                continue
            hit_cell = self._cell(point)
            if not self._in_bounds(hit_cell):
                continue
            ray = self._ray_cells(sensor_cell, hit_cell)
            for cell in ray[:-1]:
                if self._in_bounds(cell):
                    cleared.add(cell)
            hits.add(hit_cell)
        for cell in cleared - hits:
            self._free[cell] = timestamp
            self._occupied.pop(cell, None)
        for cell in hits:
            self._occupied[cell] = timestamp
            self._free.pop(cell, None)

    def move_center(self, center_xy: tuple[float, float]) -> None:
        if not all(math.isfinite(value) for value in center_xy):
            raise ValueError("grid center must be finite")
        self.center_xy = center_xy
        self._occupied = {
            cell: stamp for cell, stamp in self._occupied.items() if self._in_bounds(cell)
        }
        self._free = {
            cell: stamp for cell, stamp in self._free.items() if self._in_bounds(cell)
        }

    def prune(self, now: float) -> None:
        cutoff = now - self.retention_s
        self._occupied = {
            cell: stamp for cell, stamp in self._occupied.items()
            if stamp >= cutoff and self._in_bounds(cell)
        }
        self._free = {
            cell: stamp for cell, stamp in self._free.items()
            if stamp >= cutoff and self._in_bounds(cell)
        }

    def path_clear(
        self,
        now: float,
        path_xy: Sequence[tuple[float, float]] | None = None,
    ) -> bool:
        self.prune(now)
        inflated = self._inflated_cells()
        if path_xy is None:
            center = self.center_xy
            return all(
                math.hypot(x - center[0], y - center[1]) >= self.stop_distance_m
                for x, y in (self._point(cell) for cell in self._occupied)
            )
        if not path_xy:
            return True
        cells: set[Cell] = {self._cell(path_xy[0])}
        for start, end in zip(path_xy, path_xy[1:]):
            cells.update(self._ray_cells(self._cell(start), self._cell(end)))
        return not bool(cells & inflated)

    def snapshot(self, now: float, inflated: bool = True) -> GridSnapshot:
        self.prune(now)
        min_ix, min_iy = self._minimum_cell()
        data = [-1] * (self.width_cells * self.height_cells)
        for ix, iy in self._free:
            index = (iy - min_iy) * self.width_cells + ix - min_ix
            if 0 <= index < len(data):
                data[index] = 0
        occupied = self._inflated_cells() if inflated else set(self._occupied)
        for ix, iy in occupied:
            if not self._in_bounds((ix, iy)):
                continue
            index = (iy - min_iy) * self.width_cells + ix - min_ix
            if 0 <= index < len(data):
                data[index] = 100
        return GridSnapshot(
            self.width_cells,
            self.height_cells,
            self.resolution_m,
            min_ix * self.resolution_m,
            min_iy * self.resolution_m,
            self.frame_id,
            now,
            tuple(data),
        )

    def _inflated_cells(self) -> set[Cell]:
        radius = max(0, int(math.ceil(self.inflation_radius_m / self.resolution_m)))
        offsets = [
            (dx, dy)
            for dx in range(-radius, radius + 1)
            for dy in range(-radius, radius + 1)
            if math.hypot(dx, dy) * self.resolution_m <= self.inflation_radius_m
        ]
        return {
            (cell[0] + dx, cell[1] + dy)
            for cell in self._occupied
            for dx, dy in offsets
            if self._in_bounds((cell[0] + dx, cell[1] + dy))
        }

    def _cell(self, point: tuple[float, float]) -> Cell:
        return (
            math.floor(point[0] / self.resolution_m),
            math.floor(point[1] / self.resolution_m),
        )

    def _point(self, cell: Cell) -> tuple[float, float]:
        return (
            (cell[0] + 0.5) * self.resolution_m,
            (cell[1] + 0.5) * self.resolution_m,
        )

    def _minimum_cell(self) -> Cell:
        center = self._cell(self.center_xy)
        return center[0] - self.width_cells // 2, center[1] - self.height_cells // 2

    def _in_bounds(self, cell: Cell) -> bool:
        minimum = self._minimum_cell()
        return (
            minimum[0] <= cell[0] < minimum[0] + self.width_cells
            and minimum[1] <= cell[1] < minimum[1] + self.height_cells
        )

    @staticmethod
    def _ray_cells(start: Cell, end: Cell) -> list[Cell]:
        x0, y0 = start
        x1, y1 = end
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        error = dx - dy
        cells: list[Cell] = []
        while True:
            cells.append((x0, y0))
            if x0 == x1 and y0 == y1:
                return cells
            twice = 2 * error
            if twice > -dy:
                error -= dy
                x0 += sx
            if twice < dx:
                error += dx
                y0 += sy


def pointcloud_to_obstacles(
    xyz_camera,
    camera_to_base,
    min_height_m: float,
    max_height_m: float,
    min_range_m: float = 0.2,
    max_range_m: float = 8.0,
    stride: int = 4,
) -> list[tuple[float, float]]:
    """Transform organized metric XYZ into filtered base-frame XY hits."""
    import numpy as np

    xyz = np.asarray(xyz_camera, dtype=np.float32)
    transform = np.asarray(camera_to_base, dtype=np.float64)
    if xyz.ndim != 3 or xyz.shape[2] != 3:
        raise ValueError("xyz_camera must have shape HxWx3")
    if transform.shape != (4, 4):
        raise ValueError("camera_to_base must be a 4x4 matrix")
    sampled = xyz[::max(1, stride), ::max(1, stride)].reshape(-1, 3)
    finite = np.isfinite(sampled).all(axis=1)
    distances = np.linalg.norm(sampled, axis=1)
    valid = finite & (distances >= min_range_m) & (distances <= max_range_m)
    if not np.any(valid):
        return []
    homogeneous = np.column_stack((sampled[valid], np.ones(np.count_nonzero(valid))))
    base = homogeneous @ transform.T
    height_ok = (base[:, 2] >= min_height_m) & (base[:, 2] <= max_height_m)
    return [tuple(row) for row in base[height_ok, :2].tolist()]
