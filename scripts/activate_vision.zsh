#!/usr/bin/env zsh
SCRIPT_DIR=${0:A:h}
PROJECT_ROOT=${SCRIPT_DIR:h}
source "${PROJECT_ROOT}/.venv/bin/activate"
export OBJECT_NAV_ROOT="${PROJECT_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export YOLO_CONFIG_DIR="${PROJECT_ROOT}/.cache/ultralytics"
export XDG_CACHE_HOME="${PROJECT_ROOT}/.cache"
echo "ObjectNav vision environment: ${VIRTUAL_ENV}"
