#!/usr/bin/env bash
set -euo pipefail

camera_device_id="${1:-#1}"
bridge_port="${PERCIPIO_BRIDGE_PORT:-18765}"

exec docker run --rm --network host \
  object-nav/camport-noetic:local \
  bash -lc "source /camera_ws/devel/setup.bash && exec roslaunch percipio_object_bridge object_nav_bridge.launch device_id:=${camera_device_id} port:=${bridge_port}"
