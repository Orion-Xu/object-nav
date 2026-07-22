#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
docker build -f "${PROJECT_ROOT}/docker/camport-noetic/Dockerfile" -t object-nav/camport-noetic:local "${PROJECT_ROOT}"
