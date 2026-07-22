#!/usr/bin/env zsh
SCRIPT_DIR=${0:A:h}
PROJECT_ROOT=${SCRIPT_DIR:h}
source /opt/ros/noetic/setup.zsh
[[ -f "${PROJECT_ROOT}/ros1_ws/devel/setup.zsh" ]] && source "${PROJECT_ROOT}/ros1_ws/devel/setup.zsh"
export PYTHONPATH="${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
echo "ObjectNav ROS environment: ${ROS_DISTRO:-unavailable}"
