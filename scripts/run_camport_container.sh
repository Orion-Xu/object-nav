#!/usr/bin/env bash
set -euo pipefail
# GigE discovery requires host networking. This command only enumerates cameras.
docker run --rm --network host object-nav/camport-noetic:local
