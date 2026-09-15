import contextlib
from src.backtest.run import run_cheap_tiers
from src.backtest.store import BacktestStore
from src.backtest.types import Case


def make_case(cid_fn):
    return Case(function=cid_fn, c_sha="a"*40, cprev_sha="b"*40, unit="main/melee/gr/g",
                file="src/melee/gr/g.c", ground_truth_diff="@@", lever_locus="in_function",
                author="other", provenance="held_out", lever_class="retype",
                baseline_pct=99.0, baseline_ndl=4, target_pct=100.0, target_ndl=0)


def test_run_cheap_scores_and_stores(tmp_path):
    s = BacktestStore(tmp_path / "bt.db"); s.ensure_schema()
    s.insert_case(make_case("f1"))

    @contextlib.contextmanager
    def sandbox_factory(case):
        yield "/fake/sb"

    # advisory names the lever; generative reaches byte-match -> SOLVED
    summary = run_cheap_tiers(
        store=s,
        sandbox_factory=sandbox_factory,
        advisory_judge=lambda case, outputs: "names-lever",
        score_fn=lambda sb, fn: (100.0, 0),
        advisory_runner=lambda case, sandbox: {"t": {"rc": 0, "stdout": "x"}},
        generative_runner=lambda case, sandbox, score_fn: {"best_ndl": 0, "best_pct": 100.0, "ran": [], "timed_out": []},
    )
    assert summary["SOLVED-BY-TOOLING"] == 1
    assert s.results()[0]["rollup"] == "SOLVED-BY-TOOLING"
