from __future__ import annotations

from src.cli.debug.mutate import _lifetime_layout_force_phys_target_score


def test_lifetime_layout_force_phys_target_score_reads_colorgraph_decisions() -> None:
    pcdump = """
Starting function fn_test

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=3)
iter  ig_idx  reg  degree  nIntfr  flags
0     97      r4   0       0       0x00
1     96      r7   0       0       0x00
2     42      r6   0       0       0x00
""".strip()

    score = _lifetime_layout_force_phys_target_score(
        pcdump,
        function="fn_test",
        class_id=0,
        force_phys={97: 4, 96: 6},
    )

    assert score == {
        "virtuals": {
            "96": {
                "expected": 6,
                "actual": 7,
                "hit": False,
                "matched": False,
                "distance": 1,
            },
            "97": {
                "expected": 4,
                "actual": 4,
                "hit": True,
                "matched": True,
                "distance": 0,
            },
        },
        "hits": 1,
        "matched": 1,
        "targeted": 2,
        "observed_targets": 2,
        "observed_distance_total": 1,
        "all_targets_observed": True,
        "distance_total": 1,
    }


def test_lifetime_layout_force_phys_target_score_reports_missing_virtual() -> None:
    pcdump = """
Starting function fn_test

COLORGRAPH DECISIONS (class=0, result=1, n_nodes=1)
iter  ig_idx  reg  degree  nIntfr  flags
0     97      r28  0       0       0x00
""".strip()

    score = _lifetime_layout_force_phys_target_score(
        pcdump,
        function="fn_test",
        class_id=0,
        force_phys={97: 4, 96: 6},
    )

    assert score["virtuals"]["96"] == {
        "expected": 6,
        "actual": None,
        "hit": False,
        "matched": False,
        "distance": None,
    }
    assert score["observed_targets"] == 1
    assert score["observed_distance_total"] == 24
    assert score["all_targets_observed"] is False
    assert score["distance_total"] is None
