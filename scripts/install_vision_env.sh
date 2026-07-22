#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "${PROJECT_ROOT}"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip 'setuptools==80.9.0' wheel
.venv/bin/python -m pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
.venv/bin/python -m pip install -r requirements-vision.txt
.venv/bin/python -m pip install --no-build-isolation \
  'git+https://github.com/openai/CLIP.git@d50d76daa670286dd6cacf3bcd80b5e4823fc8e1'
.venv/bin/python -m pip install -e . --no-deps
.venv/bin/python -m pip freeze > environment.lock.txt
