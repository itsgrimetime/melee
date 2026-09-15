"""Tests for the Tier 3 orchestrator's seed generator + planner."""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

from src.mwcc_debug.symbol_bridge import Binding
from src.mwcc_debug.tier3_search import (
    CompileResult,
    PerSeedPermuteResult,
    SeedPlan,
    _extract_one_line_reason,
    find_best_candidate,
    materialize_seed,
    plan_seeds,
    plan_seeds_from_lifetime_layout_probes,
    rank_seed_results,
    run_per_seed_permute,
    smoke_compile,
)


def _local(name: str, type_str: str, virtual: int = 33) -> Binding:
    return Binding(
        var_name=name, virtual=virtual, decl_line=1,
        kind="local", type_str=type_str, confidence="best-guess",
    )


def test_plan_seeds_emits_type_widen_and_shrink_for_locals() -> None:
    """For an integer local, plan both widening and shrinking seeds
    (let the score sort)."""
    bindings = [_local("count", "u8")]
    plans = plan_seeds(bindings, budget=10)
    descriptions = [p.description for p in plans]
    assert any(
        "type-change" in d and "count" in d for d in descriptions
    )
    # u8 -> u32 widen AND u8 -> s8 shrink expected
    assert sum("u32" in d for d in descriptions) >= 1
    assert sum("s8" in d for d in descriptions) >= 1


def test_plan_seeds_emits_alias_split_for_pointer_locals() -> None:
    """For a pointer local, plan an alias-split seed."""
    bindings = [_local("data", "HSD_GObj*")]
    plans = plan_seeds(bindings, budget=5)
    assert any(p.mutator == "insert-alias" for p in plans)


def test_plan_seeds_respects_budget() -> None:
    """If candidates exceed budget, truncate by priority order."""
    bindings = [_local(f"v{i}", "u8") for i in range(10)]
    plans = plan_seeds(bindings, budget=3)
    assert len(plans) == 3


def test_plan_seeds_skips_unsupported_confidence() -> None:
    """Bindings with confidence='unsupported' or 'ambiguous' are skipped."""
    bindings = [
        _local("ok", "u8"),
        Binding(
            var_name="bad", virtual=-1, decl_line=1,
            kind="local", type_str="u8", confidence="ambiguous",
        ),
    ]
    plans = plan_seeds(bindings, budget=10)
    target_vars = {p.target_var for p in plans}
    assert "ok" in target_vars
    assert "bad" not in target_vars


def test_plan_seeds_skips_low_confidence_by_default() -> None:
    """low-confidence bindings are skipped unless explicitly opted in."""
    bindings = [
        Binding(
            var_name="weak", virtual=33, decl_line=1,
            kind="local", type_str="u8", confidence="low-confidence",
        ),
    ]
    plans = plan_seeds(bindings, budget=10)
    assert plans == []


def test_plan_seeds_includes_low_confidence_when_opted_in() -> None:
    """With include_low_confidence=True, low-confidence bindings ARE used."""
    bindings = [
        Binding(
            var_name="weak", virtual=33, decl_line=1,
            kind="local", type_str="u8", confidence="low-confidence",
        ),
    ]
    plans = plan_seeds(bindings, budget=10, include_low_confidence=True)
    assert plans  # at least one plan generated
    assert all(p.target_var == "weak" for p in plans)


def test_plan_seeds_skips_params() -> None:
    """v1 mutators don't operate on params - skip them in planning."""
    bindings = [
        Binding(
            var_name="gobj", virtual=32, decl_line=1, kind="param",
            type_str="HSD_GObj*", confidence="best-guess",
        ),
        _local("data", "HSD_GObj*"),
    ]
    plans = plan_seeds(bindings, budget=10)
    target_vars = {p.target_var for p in plans}
    assert "gobj" not in target_vars
    assert "data" in target_vars


def test_extract_one_line_reason_picks_mwcc_error_line() -> None:
    """The MWCC error block has '# Error: ...' as the most useful line."""
    stderr = textwrap.dedent("""\
        ### mwcceppc.exe Compiler:
        #    File: src/melee/mn/mnvibration.c
        # ----------------------------------
        # 1234:  bad code here
        # Error:   Illegal cast operation: cannot cast 'int' to 'HSD_JObj*'
        # The rest is noise.
    """)
    reason = _extract_one_line_reason(stderr, "")
    assert "Illegal cast" in reason
    # Leading '#' decoration is stripped.
    assert not reason.startswith("#")


def test_extract_one_line_reason_syntax_error() -> None:
    """'syntax error' should be caught when 'error:' isn't there."""
    stderr = "Something benign\nfile:1: syntax error before token foo\n"
    reason = _extract_one_line_reason(stderr, "")
    assert "syntax error" in reason


def test_extract_one_line_reason_fallback_on_no_keyword() -> None:
    """If no error keyword appears, fall back to first non-blank line."""
    stderr = "\n\nweird output not matching keywords\n"
    reason = _extract_one_line_reason(stderr, "")
    assert "weird output" in reason


def test_extract_one_line_reason_empty_returns_placeholder() -> None:
    """Empty input returns the explicit no-diagnostic placeholder."""
    reason = _extract_one_line_reason("", "")
    assert "no compiler diagnostic" in reason


def test_compile_result_dataclass_default_ok_state() -> None:
    """Sanity check: a fresh ok=True result has empty error fields."""
    r = CompileResult(ok=True, stderr="", stdout="", one_line_reason="")
    assert r.ok is True
    assert r.one_line_reason == ""


def test_smoke_compile_redirects_pcdump_out_of_repo_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Smoke compiles should not leak the DLL's default root pcdump.txt."""
    seed = tmp_path / "seed.c"
    seed.write_text("void fn(void) {}\n")
    wibo = tmp_path / "wibo"
    compiler = tmp_path / "mwcceppc_debug.exe"
    wibo.write_text("")
    compiler.write_text("")
    captured: dict[str, object] = {}

    def fake_run(args, cwd, capture_output, text, timeout, env=None):
        captured["cwd"] = cwd
        captured["env"] = env
        Path(args[-1]).write_bytes(b"obj")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("src.mwcc_debug.tier3_search.subprocess.run", fake_run)

    result = smoke_compile(
        seed_source_path=seed,
        wibo=wibo,
        debug_compiler=compiler,
        cflags="",
        cwd=tmp_path,
    )

    assert result.ok is True
    env = captured["env"]
    assert isinstance(env, dict)
    redirected = env.get("MWCC_DEBUG_PCDUMP_PATH")
    assert redirected
    assert Path(str(redirected)).name != "pcdump.txt"
    assert not (tmp_path / "pcdump.txt").exists()


# --- Per-seed permuter orchestration tests --------------------------------
#
# These tests cover the v2 wiring: for each compiling seed, run `debug
# permute` for a bounded time, capture the best candidate, rank seeds by
# post-permute delta. We inject a fake `runner` callable so tests stay
# fast and don't actually shell out to the permuter binary.


def _seed_plan(idx: int) -> SeedPlan:
    """Helper: minimal SeedPlan for tests."""
    return SeedPlan(
        mutator="type-change",
        target_var=f"v{idx}",
        args={"new_type": "u32"},
        description=f"seed{idx}: type-change v{idx}: u8 -> u32",
    )


def test_find_best_candidate_returns_lowest_score_dir(tmp_path: Path) -> None:
    """find_best_candidate scans output-N-M/ subdirs and returns the
    source.c with the lowest score (lower score = closer to target)."""
    perm_dir = tmp_path / "fn"
    perm_dir.mkdir()
    # output dirs use permuter's naming: output-{score}-{ctr}
    for score, ctr in [(500, 1), (300, 1), (300, 2), (1000, 1)]:
        d = perm_dir / f"output-{score}-{ctr}"
        d.mkdir()
        (d / "source.c").write_text(f"// score {score} ctr {ctr}\n")
        (d / "score.txt").write_text(f"{score}\n")

    best = find_best_candidate(perm_dir)
    assert best is not None
    assert best.parent.name in ("output-300-1", "output-300-2")
    assert best.name == "source.c"


def test_find_best_candidate_no_outputs_returns_none(tmp_path: Path) -> None:
    """If permuter produced no improvements, return None."""
    perm_dir = tmp_path / "fn"
    perm_dir.mkdir()
    # Only base.c and target.o — no output dirs
    (perm_dir / "base.c").write_text("void fn() {}\n")
    (perm_dir / "target.o").write_bytes(b"")
    assert find_best_candidate(perm_dir) is None


def test_find_best_candidate_skips_dirs_without_source(tmp_path: Path) -> None:
    """A malformed output dir without source.c is skipped, not crashed on."""
    perm_dir = tmp_path / "fn"
    perm_dir.mkdir()
    bad = perm_dir / "output-100-1"
    bad.mkdir()
    # No source.c written
    good = perm_dir / "output-200-1"
    good.mkdir()
    (good / "source.c").write_text("// ok\n")

    best = find_best_candidate(perm_dir)
    assert best is not None
    assert best.parent.name == "output-200-1"


def test_run_per_seed_permute_invokes_runner_and_captures_best(
    tmp_path: Path,
) -> None:
    """run_per_seed_permute calls the injected runner with the seed_dir,
    then finds the best candidate produced inside that seed_dir."""
    seed_dir = tmp_path / "tier3_seed_0"
    seed_dir.mkdir()
    (seed_dir / "base.c").write_text("void fn() {}\n")

    runner_calls: list[dict] = []

    def fake_runner(seed_dir_arg: Path, fn_name: str, time_seconds: int) -> None:
        runner_calls.append({
            "seed_dir": seed_dir_arg,
            "fn_name": fn_name,
            "time_seconds": time_seconds,
        })
        # Simulate permuter producing one improvement
        out = seed_dir_arg / "output-150-1"
        out.mkdir()
        (out / "source.c").write_text("// better candidate\n")
        (out / "score.txt").write_text("150\n")

    plan = _seed_plan(0)
    result = run_per_seed_permute(
        seed_idx=0,
        plan=plan,
        seed_dir=seed_dir,
        fn_name="fn_test",
        per_seed_time=42,
        runner=fake_runner,
        baseline_score=200,
    )

    assert len(runner_calls) == 1
    assert runner_calls[0]["seed_dir"] == seed_dir
    assert runner_calls[0]["fn_name"] == "fn_test"
    assert runner_calls[0]["time_seconds"] == 42

    assert isinstance(result, PerSeedPermuteResult)
    assert result.seed_idx == 0
    assert result.plan is plan
    assert result.best_score == 150
    assert result.baseline_score == 200
    assert result.delta == 50  # baseline - best (lower is better)
    assert result.best_candidate is not None
    assert result.best_candidate.name == "source.c"


def test_run_per_seed_permute_no_improvement_records_zero_delta(
    tmp_path: Path,
) -> None:
    """A seed where permuter produced no output gets delta=0 and
    best_candidate=None — recorded as 'ran but didn't improve'."""
    seed_dir = tmp_path / "tier3_seed_0"
    seed_dir.mkdir()
    (seed_dir / "base.c").write_text("void fn() {}\n")

    def no_op_runner(seed_dir_arg: Path, fn_name: str, time_seconds: int) -> None:
        # Permuter ran but produced no improvements
        pass

    result = run_per_seed_permute(
        seed_idx=2,
        plan=_seed_plan(2),
        seed_dir=seed_dir,
        fn_name="fn_test",
        per_seed_time=10,
        runner=no_op_runner,
        baseline_score=200,
    )

    assert result.best_candidate is None
    assert result.delta == 0
    assert result.best_score is None


def test_run_per_seed_permute_keeps_seed_score_improvement(
    tmp_path: Path,
) -> None:
    """A frame-directed seed can improve target score before the permuter
    creates output dirs; keep that seed as the best candidate."""
    seed_dir = tmp_path / "tier3_seed_0"
    seed_dir.mkdir()
    base = seed_dir / "base.c"
    base.write_text("void fn() {}\n")

    def no_output_runner(seed_dir_arg: Path, fn_name: str, time_seconds: int) -> None:
        pass

    result = run_per_seed_permute(
        seed_idx=0,
        plan=_seed_plan(0),
        seed_dir=seed_dir,
        fn_name="fn_test",
        per_seed_time=10,
        runner=no_output_runner,
        baseline_score=34,
        seed_score=8,
    )

    assert result.best_candidate == base
    assert result.best_score == 8
    assert result.baseline_score == 34
    assert result.seed_score == 8
    assert result.delta == 26


def test_rank_seed_results_orders_by_delta_descending() -> None:
    """rank_seed_results sorts so the largest improvement comes first."""
    r1 = PerSeedPermuteResult(
        seed_idx=0, plan=_seed_plan(0), seed_dir=Path("/x/0"),
        best_candidate=None, best_score=180, baseline_score=200,
        delta=20, ran_seconds=10,
    )
    r2 = PerSeedPermuteResult(
        seed_idx=1, plan=_seed_plan(1), seed_dir=Path("/x/1"),
        best_candidate=None, best_score=100, baseline_score=200,
        delta=100, ran_seconds=10,
    )
    r3 = PerSeedPermuteResult(
        seed_idx=2, plan=_seed_plan(2), seed_dir=Path("/x/2"),
        best_candidate=None, best_score=None, baseline_score=200,
        delta=0, ran_seconds=10,
    )

    ranked = rank_seed_results([r1, r2, r3])
    assert [r.seed_idx for r in ranked] == [1, 0, 2]


def test_rank_seed_results_empty_list_returns_empty() -> None:
    """Empty input -> empty output (no crash on no seeds)."""
    assert rank_seed_results([]) == []


def test_run_per_seed_permute_runner_exception_is_caught(
    tmp_path: Path,
) -> None:
    """A runner that raises (e.g. subprocess timeout) is caught — the
    seed still gets a result with delta=0 and an error recorded, so we
    don't crash the whole orchestration."""
    seed_dir = tmp_path / "tier3_seed_5"
    seed_dir.mkdir()

    def crashing_runner(
        seed_dir_arg: Path, fn_name: str, time_seconds: int,
    ) -> None:
        raise RuntimeError("permuter subprocess timed out")

    result = run_per_seed_permute(
        seed_idx=5,
        plan=_seed_plan(5),
        seed_dir=seed_dir,
        fn_name="fn_test",
        per_seed_time=5,
        runner=crashing_runner,
        baseline_score=200,
    )

    assert result.best_candidate is None
    assert result.delta == 0
    assert result.error is not None
    assert "timed out" in result.error


def test_per_seed_result_dataclass_defaults() -> None:
    """PerSeedPermuteResult has sane defaults for unset fields."""
    r = PerSeedPermuteResult(
        seed_idx=0, plan=_seed_plan(0), seed_dir=Path("/x"),
        best_candidate=None, best_score=None, baseline_score=100,
        delta=0, ran_seconds=0,
    )
    assert r.error is None


def test_plan_seeds_from_source_anchors_adds_arg_temp_seed() -> None:
    from src.mwcc_debug.source_shape import SourceAnchor
    from src.mwcc_debug.tier3_search import plan_seeds_from_source_anchors

    anchors = [
        SourceAnchor(
            function="fn_test",
            scope_path=("fn_test", "block@l10c4"),
            byte_range=(100, 130),
            line_range=(10, 12),
            kind="coalesce",
            reason="compiler temp r46 repeated load near call argument",
            virtuals=(46, 50),
        )
    ]
    plans = plan_seeds_from_source_anchors(anchors, budget=5)
    assert len(plans) == 1
    assert plans[0].mutator == "source-shape"
    assert plans[0].target_var == "r46_r50"
    assert "compiler temp" in plans[0].description


def test_plan_seeds_from_lifetime_layout_probes_preserves_source_text() -> None:
    from src.mwcc_debug.pressure_explorer import LifetimeLayoutProbe

    probe = LifetimeLayoutProbe(
        label="case-c2-loop-cursor",
        operator="temp-introduction",
        description="rebind loop cursor temp",
        source_text="void fn_test(void) { int tmp; tmp = 1; }\n",
    )

    plans = plan_seeds_from_lifetime_layout_probes([probe], budget=5)

    assert len(plans) == 1
    assert plans[0].mutator == "source-shape"
    assert plans[0].target_var == "case-c2-loop-cursor"
    assert plans[0].args["source_text"] == probe.source_text
    assert "rebind loop cursor temp" in plans[0].description


def test_materialize_seed_writes_source_shape_probe(tmp_path: Path) -> None:
    mutated = "void fn_test(void) { int tmp; tmp = 1; }\n"
    plan = SeedPlan(
        mutator="source-shape",
        target_var="case-c2-loop-cursor",
        args={"source_text": mutated},
        description="source-shape temp introduction",
    )

    out = materialize_seed(
        "void fn_test(void) {}\n",
        "fn_test",
        plan,
        tmp_path / "tier3_seed_0",
    )

    assert out is not None
    assert out.read_text() == mutated
