from __future__ import annotations

import json
from pathlib import Path

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "tests" / "backtest" / "fixtures" / "calibration.json"
)


def load_calibration_fixtures() -> list[dict]:
    """Return the committed synthetic calibration cases (positives + negatives)."""
    return json.loads(_FIXTURE_PATH.read_text())
