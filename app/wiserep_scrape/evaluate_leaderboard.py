#!/usr/bin/env python3
"""Score listed models on a monthly WISeREP challenge (see leaderboard.evaluate)."""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from astrodash.infrastructure.ml.leaderboard.evaluate import main

if __name__ == "__main__":
    raise SystemExit(main())
