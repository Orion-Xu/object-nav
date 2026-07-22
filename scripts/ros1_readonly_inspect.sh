#!/usr/bin/env bash
set -u

if [[ -f /opt/ros/noetic/setup.bash ]]; then
  source /opt/ros/noetic/setup.bash
else
  echo "ROS Noetic setup not found" >&2
  exit 1
fi

echo "ROS_DISTRO=${ROS_DISTRO:-unset}"
rosversion -d
echo "--- nodes (read-only) ---"
rosnode list
echo "--- topics (read-only) ---"
rostopic list
for topic in /odom /scan /tf /tf_static; do
  echo "--- rostopic info ${topic} ---"
  rostopic info "${topic}" || true
done
echo "--- services (read-only) ---"
rosservice list
echo "--- move_base_msgs package ---"
rospack find move_base_msgs

echo "NOTE: /map is intentionally not required by the mapless local-navigation scope."

# Deliberately contains no rostopic pub command and never writes /cmd_vel.
