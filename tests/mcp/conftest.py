"""Prevent ``tests/mcp`` from shadowing the project ``mcp`` package on ``sys.path``."""

from __future__ import annotations

import sys
from pathlib import Path

_shadow = str(Path(__file__).resolve().parent)
while _shadow in sys.path:
    sys.path.remove(_shadow)
