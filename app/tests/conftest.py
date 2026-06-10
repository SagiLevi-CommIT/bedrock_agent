"""Test config: make the ``src`` package importable when running pytest from app/."""

from __future__ import annotations

import sys
from pathlib import Path

# tests/ is app/tests -> add app/ so ``import src.*`` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
