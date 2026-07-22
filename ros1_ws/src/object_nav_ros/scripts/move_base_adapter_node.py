#!/usr/bin/env python3
"""Conservative move_base adapter smoke node.

It waits for and reports move_base availability. It submits no goal unless another
program explicitly calls MoveBaseNavigationAdapter.navigate_to_pose(). There is no
cmd_vel publisher in this package.
"""
import math
import threading
import uuid

import actionlib
import rospy
import tf2_ros
from actionlib_msgs.msg import GoalStatus
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal


class MoveBaseNavigationAdapter:
    STATUS = {
        GoalStatus.PENDING: "PENDING",
        GoalStatus.ACTIVE: "ACTIVE",
        GoalStatus.PREEMPTED: "CANCELED",
        GoalStatus.SUCCEEDED: "SUCCEEDED",
        GoalStatus.ABORTED: "FAILED",
        GoalStatus.REJECTED: "FAILED",
        GoalStatus.RECALLED: "CANCELED",
        GoalStatus.LOST: "UNKNOWN",
    }

    def __init__(self, action_name="move_base", local_frame="odom", base_frame="base_link"):
        self.action_name = action_name
        self.local_frame = local_frame
        self.base_frame = base_frame
        self.client = actionlib.SimpleActionClient(action_name, MoveBaseAction)
        self.tf_buffer = tf2_ros.Buffer(cache_time=rospy.Duration(10.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self._lock = threading.Lock()
        self._active_task = None
        self._statuses = {}

    def wait_until_available(self, timeout_s=2.0):
        return self.client.wait_for_server(rospy.Duration(timeout_s))

    def get_pose(self):
        try:
            transform = self.tf_buffer.lookup_transform(
                self.local_frame, self.base_frame, rospy.Time(0), rospy.Duration(0.2))
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException):
            return None
        translation = transform.transform.translation
        rotation = transform.transform.rotation
        yaw = math.atan2(2.0 * (rotation.w * rotation.z + rotation.x * rotation.y),
                         1.0 - 2.0 * (rotation.y ** 2 + rotation.z ** 2))
        return {"x": translation.x, "y": translation.y, "yaw": yaw,
                "frame_id": self.local_frame, "timestamp": transform.header.stamp.to_sec()}

    def navigate_to_pose(self, goal):
        if goal.frame_id != self.local_frame:
            raise ValueError("局部导航目标必须位于配置的 odom/局部坐标系")
        if goal.timestamp <= 0:
            raise ValueError("导航目标必须带有效时间戳")
        message = MoveBaseGoal()
        message.target_pose.header.frame_id = goal.frame_id
        message.target_pose.header.stamp = rospy.Time.from_sec(goal.timestamp)
        message.target_pose.pose.position.x = goal.x
        message.target_pose.pose.position.y = goal.y
        message.target_pose.pose.orientation.z = math.sin(goal.yaw / 2.0)
        message.target_pose.pose.orientation.w = math.cos(goal.yaw / 2.0)
        task_id = uuid.uuid4().hex

        def done_cb(status, _result):
            with self._lock:
                self._statuses[task_id] = self.STATUS.get(status, "UNKNOWN")

        with self._lock:
            if self._active_task is not None:
                raise RuntimeError("已有导航任务，必须先取消或等待完成")
            self._active_task = task_id
            self._statuses[task_id] = "PENDING"
        self.client.send_goal(message, done_cb=done_cb)
        return task_id

    def get_navigation_status(self, task_id):
        with self._lock:
            if task_id != self._active_task and task_id not in self._statuses:
                return "UNKNOWN"
            status = self.STATUS.get(self.client.get_state(), self._statuses.get(task_id, "UNKNOWN"))
            self._statuses[task_id] = status
            if status in ("SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN") and task_id == self._active_task:
                self._active_task = None
            return status

    def request_stop(self, reason):
        rospy.logwarn("ObjectNav navigation cancel requested: %s", reason)
        self.client.cancel_all_goals()
        with self._lock:
            if self._active_task:
                self._statuses[self._active_task] = "CANCELED"
                self._active_task = None


def main():
    rospy.init_node("object_nav_move_base_adapter")
    adapter = MoveBaseNavigationAdapter(
        rospy.get_param("~action_name", "move_base"),
        rospy.get_param("~local_frame", "odom"),
        rospy.get_param("~base_frame", "base_link"),
    )
    if not adapter.wait_until_available(rospy.get_param("~wait_timeout_s", 2.0)):
        rospy.logerr("move_base action unavailable; staying read-only and sending no goal")
        return
    rospy.loginfo("move_base is available; adapter is idle and sends no goal by itself")
    rospy.spin()


if __name__ == "__main__":
    main()
