from __future__ import annotations

import json
import math
import socket
import struct
import threading
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .models import CameraIntrinsics, RgbdFrame


MAGIC = b"PCRGBD1\0"
_PREFIX = struct.Struct("!8sIII")
MAX_HEADER_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class CameraPacket:
    sequence: int
    rgb_timestamp: float
    depth_timestamp: float
    frame_id: str
    intrinsics: CameraIntrinsics
    bgr: np.ndarray
    xyz_m: np.ndarray
    received_at: float = 0.0

    @property
    def depth_m(self) -> np.ndarray:
        return self.xyz_m[:, :, 2]

    @property
    def captured_at(self) -> float:
        return self.rgb_timestamp

    def to_rgbd_frame(self) -> RgbdFrame:
        return RgbdFrame(
            self.bgr,
            self.depth_m,
            self.rgb_timestamp,
            self.depth_timestamp,
            self.frame_id,
            self.intrinsics,
            self.received_at or time.time(),
        )


def encode_packet(packet: CameraPacket) -> bytes:
    bgr = np.ascontiguousarray(packet.bgr, dtype=np.uint8)
    xyz = np.ascontiguousarray(packet.xyz_m, dtype="<f4")
    if bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError("BGR image must have shape HxWx3")
    if xyz.shape != bgr.shape:
        raise ValueError("XYZ array must match BGR shape")
    _validate_metadata(
        packet.sequence,
        packet.rgb_timestamp,
        packet.depth_timestamp,
        packet.frame_id,
        packet.intrinsics,
        bgr.shape[1],
        bgr.shape[0],
    )
    header = {
        "sequence": packet.sequence,
        "rgb_timestamp": packet.rgb_timestamp,
        "depth_timestamp": packet.depth_timestamp,
        "frame_id": packet.frame_id,
        "width": packet.intrinsics.width,
        "height": packet.intrinsics.height,
        "fx": packet.intrinsics.fx,
        "fy": packet.intrinsics.fy,
        "cx": packet.intrinsics.cx,
        "cy": packet.intrinsics.cy,
        "bgr_bytes": bgr.nbytes,
        "xyz_bytes": xyz.nbytes,
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload = zlib.compress(bgr.tobytes() + xyz.tobytes(), level=1)
    return _PREFIX.pack(MAGIC, len(header_bytes), len(payload), 0) + header_bytes + payload


def decode_packet(data: bytes, received_at: float | None = None) -> CameraPacket:
    if len(data) < _PREFIX.size:
        raise ValueError("camera packet is truncated")
    magic, header_size, payload_size, _flags = _PREFIX.unpack_from(data)
    if magic != MAGIC:
        raise ValueError("invalid camera packet magic")
    if header_size > MAX_HEADER_BYTES or payload_size > MAX_PAYLOAD_BYTES:
        raise ValueError("camera packet exceeds configured limits")
    expected = _PREFIX.size + header_size + payload_size
    if len(data) != expected:
        raise ValueError("camera packet length mismatch")
    offset = _PREFIX.size
    header = json.loads(data[offset:offset + header_size])
    bgr_size = int(header["bgr_bytes"])
    xyz_size = int(header["xyz_bytes"])
    height, width = int(header["height"]), int(header["width"])
    if not (0 < width <= 10_000 and 0 < height <= 10_000):
        raise ValueError("camera dimensions are invalid")
    if bgr_size != width * height * 3 or xyz_size != width * height * 3 * 4:
        raise ValueError("camera array sizes do not match dimensions")
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(
        data[offset + header_size:], bgr_size + xyz_size + 1
    )
    if (
        len(raw) > bgr_size + xyz_size
        or not decompressor.eof
        or decompressor.unused_data
    ):
        raise ValueError("camera payload exceeds declared size")
    if len(raw) != bgr_size + xyz_size:
        raise ValueError("camera payload length mismatch")
    bgr = np.frombuffer(raw[:bgr_size], dtype=np.uint8).reshape(height, width, 3).copy()
    xyz = np.frombuffer(raw[bgr_size:], dtype="<f4").reshape(height, width, 3).copy()
    intrinsics = CameraIntrinsics(
        width, height, float(header["fx"]), float(header["fy"]),
        float(header["cx"]), float(header["cy"]),
    )
    sequence = int(header["sequence"])
    rgb_timestamp = float(header["rgb_timestamp"])
    depth_timestamp = float(header["depth_timestamp"])
    frame_id = str(header["frame_id"])
    _validate_metadata(
        sequence,
        rgb_timestamp,
        depth_timestamp,
        frame_id,
        intrinsics,
        width,
        height,
    )
    return CameraPacket(
        sequence,
        rgb_timestamp,
        depth_timestamp,
        frame_id,
        intrinsics,
        bgr,
        xyz,
        received_at if received_at is not None else time.time(),
    )


def _validate_metadata(
    sequence: int,
    rgb_timestamp: float,
    depth_timestamp: float,
    frame_id: str,
    intrinsics: CameraIntrinsics,
    width: int,
    height: int,
) -> None:
    if sequence < 0:
        raise ValueError("camera sequence must be non-negative")
    if not frame_id.strip():
        raise ValueError("camera frame_id must not be empty")
    if not all(math.isfinite(value) for value in (rgb_timestamp, depth_timestamp)):
        raise ValueError("camera timestamps must be finite")
    if intrinsics.width != width or intrinsics.height != height:
        raise ValueError("camera intrinsics dimensions do not match image")
    if not (
        math.isfinite(intrinsics.fx)
        and math.isfinite(intrinsics.fy)
        and intrinsics.fx > 0
        and intrinsics.fy > 0
        and math.isfinite(intrinsics.cx)
        and math.isfinite(intrinsics.cy)
        and 0 <= intrinsics.cx < width
        and 0 <= intrinsics.cy < height
    ):
        raise ValueError("camera intrinsics are invalid")


def recv_packet(sock: socket.socket) -> CameraPacket:
    prefix = _recv_exact(sock, _PREFIX.size)
    magic, header_size, payload_size, _flags = _PREFIX.unpack(prefix)
    if magic != MAGIC or header_size > MAX_HEADER_BYTES or payload_size > MAX_PAYLOAD_BYTES:
        raise ValueError("invalid camera packet prefix")
    rest = _recv_exact(sock, header_size + payload_size)
    return decode_packet(prefix + rest, time.time())


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise EOFError("camera bridge disconnected")
        chunks.extend(chunk)
    return bytes(chunks)


class PercipioRgbdSource:
    """Latest-frame TCP source for the read-only Camport ROS bridge."""

    def __init__(self, host: str = "127.0.0.1", port: int = 18765, timeout_s: float = 1.0):
        self.host, self.port, self.timeout_s = host, port, timeout_s
        self._socket: socket.socket | None = None
        self._latest: CameraPacket | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._finished = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
        self._socket.settimeout(self.timeout_s)
        self._stop.clear()
        self._finished.clear()
        self.error = None
        self._thread = threading.Thread(target=self._loop, daemon=True, name="percipio-rgbd-source")
        self._thread.start()

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    packet = recv_packet(self._socket)
                except socket.timeout:
                    continue
                with self._lock:
                    self._latest = packet
        except Exception as exc:
            if not self._stop.is_set():
                self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._finished.set()

    def latest_after(self, sequence: int) -> CameraPacket | None:
        with self._lock:
            if self._latest is None or self._latest.sequence <= sequence:
                return None
            return self._latest

    def read(self) -> RgbdFrame:
        with self._lock:
            packet = self._latest
        if packet is None:
            now = time.time()
            return RgbdFrame(None, None, now, now, "camera_link", None, now, False, self.error or "camera_not_ready")
        return packet.to_rgbd_frame()

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def stop(self) -> None:
        self._stop.set()
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


class PacketRecorder:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self._manifest = self.output_dir / "manifest.jsonl"

    def write(self, packet: CameraPacket) -> Path:
        frame_path = self.output_dir / f"{packet.sequence:08d}.rgbd"
        frame_path.write_bytes(encode_packet(packet))
        metadata: dict[str, Any] = {
            "sequence": packet.sequence,
            "rgb_timestamp": packet.rgb_timestamp,
            "depth_timestamp": packet.depth_timestamp,
            "file": frame_path.name,
        }
        with self._manifest.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(metadata, ensure_ascii=False) + "\n")
        return frame_path


class PacketReplaySource:
    def __init__(self, recording_dir: str | Path):
        folder = Path(recording_dir)
        self._paths = sorted(folder.glob("*.rgbd"))
        self._index = 0

    def read_packet(self) -> CameraPacket | None:
        if self._index >= len(self._paths):
            return None
        packet = decode_packet(self._paths[self._index].read_bytes())
        self._index += 1
        return packet
