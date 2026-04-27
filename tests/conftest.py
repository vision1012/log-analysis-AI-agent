"""Ensure repo root is on ``sys.path`` so ``pytest`` works without ``PYTHONPATH``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("DISABLE_LLM", "true")
