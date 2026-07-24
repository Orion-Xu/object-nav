#!/usr/bin/env python3
"""Read-only RGB/registered-point-cloud bridge for the host vision process."""

import json
import math
import socket
import struct
import threading
import zlib

import message_filters
import numpy as np
import rospy
from cv_bridge import CvBridge
from sensor_msgs.msg import CameraInfo, Image, PointCloud2


MAGIC = b"PCRGBD1\0"
PREFIX = struct.Struct("!8sIII")


def pointcloud_xyz(message):
    if message.height <= 1:
        raise ValueError("PointCloud2 must be organized")
    fields = {field.name: field for field in message.fields}
    if not all(name in fields for name in ("x", "y", "z")):
        raise ValueError("PointCloud2 is missing x/y/z fields")
    byte_order = ">" if message.is_bigendian else "<"
    dtype = np.dtype({
        "names": ["x", "y", "z"],
        "formats": [byte_order + "f4"] * 3,
        "offsets": [fields[name].offset for name in ("x", "y", "z")],
        "itemsize": message.point_step,
    })
    rows = np.ndarray(
        shape=(message.height, message.width),
        dtype=dtype,
        buffer=message.data,
        strides=(message.row_step, message.point_step),
    )
    return np.stack((rows["x"], rows["y"], rows["z"]), axis=-1).astype("<f4", copy=False)


def encode(sequence, rgb_message, info_message, cloud_message, bgr, xyz):
    bgr = np.ascontiguousarray(bgr, dtype=np.uint8)
    xyz = np.ascontiguousarray(xyz, dtype="<f4")
    if bgr.shape != xyz.shape:
        raise ValueError("registered point cloud dimensions do not match RGB")
    height, width = bgr.shape[:2]
    if info_message.width != width or info_message.height != height:
        raise ValueError("CameraInfo dimensions do not match RGB")
    frame_ids = {
        rgb_message.header.frame_id,
        info_message.header.frame_id,
        cloud_message.header.frame_id,
    }
    if len(frame_ids) != 1 or not next(iter(frame_ids)).strip():
        raise ValueError("RGB, CameraInfo and point cloud frame IDs must match")
    metadata_values = (
        rgb_message.header.stamp.to_sec(),
        cloud_message.header.stamp.to_sec(),
        info_message.K[0],
        info_message.K[4],
        info_message.K[2],
        info_message.K[5],
    )
    if not all(math.isfinite(value) for value in metadata_values):
        raise ValueError("camera timestamps and intrinsics must be finite")
    if info_message.K[0] <= 0 or info_message.K[4] <= 0:
        raise ValueError("camera focal lengths must be positive")
    if not (0 <= info_message.K[2] < width and 0 <= info_message.K[5] < height):
        raise ValueError("camera principal point is outside the image")
    header = {
        "sequence": sequence,
        "rgb_timestamp": rgb_message.header.stamp.to_sec(),
        "depth_timestamp": cloud_message.header.stamp.to_sec(),
        "frame_id": cloud_message.header.frame_id,
        "width": bgr.shape[1],
        "height": bgr.shape[0],
        "fx": info_message.K[0],
        "fy": info_message.K[4],
        "cx": info_message.K[2],
        "cy": info_message.K[5],
        "bgr_bytes": bgr.nbytes,
        "xyz_bytes": xyz.nbytes,
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload = zlib.compress(bgr.tobytes() + xyz.tobytes(), level=1)
    return PREFIX.pack(MAGIC, len(header_bytes), len(payload), 0) + header_bytes + payload


class LatestPacketServer:
    def __init__(self, host, port):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._server.listen(4)
        self._clients = set()
        self._lock = threading.Lock()
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while not rospy.is_shutdown():
            try:
                client, address = self._server.accept()
                client.settimeout(1.0)
                with self._lock:
                    self._clients.add(client)
                rospy.loginfo("RGB-D bridge client connected: %s:%s", *address)
            except OSError:
                return

    def publish(self, packet):
        with self._lock:
            clients = tuple(self._clients)
        failed = []
        for client in clients:
            try:
                client.sendall(packet)
            except OSError:
                failed.append(client)
        if failed:
            with self._lock:
                for client in failed:
                    self._clients.discard(client)
                    client.close()

    def close(self):
        self._server.close()
        with self._lock:
            for client in self._clients:
                client.close()
            self._clients.clear()


class RgbdBridge:
    def __init__(self):
        host = rospy.get_param("~host", "127.0.0.1")
        port = int(rospy.get_param("~port", 18765))
        queue_size = int(rospy.get_param("~queue_size", 5))
        slop = float(rospy.get_param("~sync_slop_s", 0.05))
        self._cv = CvBridge()
        self._server = LatestPacketServer(host, port)
        self._sequence = 0
        subscribers = [
            message_filters.Subscriber(
                rospy.get_param("~rgb_topic", "/camera/rgb/image"), Image
            ),
            message_filters.Subscriber(
                rospy.get_param("~camera_info_topic", "/camera/rgb/camera_info"), CameraInfo
            ),
            message_filters.Subscriber(
                rospy.get_param("~pointcloud_topic", "/camera/PointCloud2"), PointCloud2
            ),
        ]
        self._sync = message_filters.ApproximateTimeSynchronizer(
            subscribers, queue_size=queue_size, slop=slop, allow_headerless=False
        )
        self._sync.registerCallback(self._callback)
        rospy.on_shutdown(self._server.close)
        rospy.loginfo("RGB-D TCP bridge listening on %s:%d", host, port)

    def _callback(self, rgb_message, info_message, cloud_message):
        try:
            bgr = self._cv.imgmsg_to_cv2(rgb_message, desired_encoding="bgr8")
            xyz = pointcloud_xyz(cloud_message)
            self._sequence += 1
            self._server.publish(encode(
                self._sequence, rgb_message, info_message, cloud_message, bgr, xyz
            ))
        except Exception as exc:
            rospy.logerr_throttle(2.0, "RGB-D bridge rejected frame: %s", exc)


def main():
    rospy.init_node("percipio_rgbd_tcp_bridge")
    RgbdBridge()
    rospy.spin()


if __name__ == "__main__":
    main()
