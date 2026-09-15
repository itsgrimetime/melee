"""Slow smoke test for cheap_tiers_with_real_judge. Gated by BACKTEST_SLOW=1."""
import os
import pytest


@pytest.mark.skipif(
    os.environ.get("BACKTEST_SLOW") != "1",
    reason="Set BACKTEST_SLOW=1 to run slow sandbox/build smoke tests",
)
def test_cheap_tiers_with_real_judge_smoke(tmp_path):
    from src.backtest.run import cheap_tiers_with_real_judge
    result = cheap_tiers_with_real_judge(limit=1, db=tmp_path / "bt.db")
    assert set(result.keys()) == {"SOLVED-BY-TOOLING", "PARTIAL", "GAP"}
