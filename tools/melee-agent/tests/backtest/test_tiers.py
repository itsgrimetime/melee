import subprocess
from pathlib import Path

from src.backtest.tiers import run_advisory, run_generative, ADVISORY_TOOLS, MELEE_AGENT_DIR
from src.backtest.types import Case


def make_case():
    return Case(function="grIceMt_801F9ACC", c_sha="a"*40, cprev_sha="b"*40,
                unit="main/melee/gr/gricemt", file="src/melee/gr/gricemt.c",
                ground_truth_diff="@@", lever_locus="in_function", author="other",
                provenance="held_out", lever_class="retype",
                baseline_pct=99.98, baseline_ndl=4, target_pct=100.0, target_ndl=0)


def test_melee_agent_dir_resolves():
    p = Path(MELEE_AGENT_DIR)
    assert p.name == "melee-agent", f"Expected name 'melee-agent', got {p.name!r}"
    assert p.exists(), f"MELEE_AGENT_DIR does not exist: {p}"


def test_run_advisory_captures_each_tool():
    calls = []
    def fake_cli(args, *, cwd, timeout):
        calls.append(args); return (0, "Found 1 pattern: u8-mask", "")
    out = run_advisory(make_case(), sandbox="/sb", cli_runner=fake_cli)
    assert len(out) == len(ADVISORY_TOOLS)
    assert all(v["rc"] == 0 for v in out.values())


def test_run_generative_threads_max_iters():
    seen = []
    def fake_cli(args, *, cwd, timeout):
        seen.append(args)
        return (0, "{}", "")
    def score_fn(sb, fn):
        return (99.5, 3)
    run_generative(make_case(), sandbox="/sb", cli_runner=fake_cli, score_fn=score_fn, max_iters=3)
    directed = next(a for a in seen if any("directed" in t for t in a))
    assert "--max-iters" in directed
    i = directed.index("--max-iters")
    assert directed[i + 1] == "3"


def test_run_generative_records_timeout_and_best():
    seq = iter([4, 2])  # ndl after tool 1, then tool 2
    def fake_cli(args, *, cwd, timeout):
        if "directed" in " ".join(args):
            raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)
        return (0, "{}", "")
    def score_fn(sb, fn):
        return (99.5, next(seq, 2))
    out = run_generative(make_case(), sandbox="/sb", cli_runner=fake_cli, score_fn=score_fn)
    assert out["best_ndl"] == 2
    assert any("directed" in " ".join(t) for t in out["timed_out"])
