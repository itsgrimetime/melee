"""Tests for the `debug target score-simplify-order` CLI command.

This is the permuter-callable scorer that decomp-permuter invokes once
per candidate. The tests cover:

  * Happy path: a sidecar pcdump exists next to the .o, the function is
    present in both baseline and candidate, and the score is emitted as
    a single integer on stdout (permuter contract).
  * Failure modes that should degrade to PENALTY_INF on stdout (so
    permuter discards the iteration cleanly): missing .o, missing
    pcdump sidecar, function absent from candidate.
  * Failure modes that should exit non-zero with a stderr message
    (so a misconfigured campaign surfaces visibly rather than
    silently scoring everything as PENALTY_INF): spec/function name
    mismatch, malformed spec.
  * Output format variants: --json, --breakdown, default.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import app


runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_pcdump(
    function: str,
    *,
    simplify_iters: list[tuple[int, int]],  # (iter_idx, ig_idx)
    coalesce_mappings: list[tuple[int, int]] | None = None,
) -> str:
    """Build a minimal but parseable pcdump text for one function.

    `simplify_iters` is the (iter_idx, ig_idx) sequence that produces
    the SIMPLIFY GRAPH table. The first column is the
    `simplify_order` tuple the scorer reads, in order. Each row gets
    a stub degree/array_size/flags.
    """
    lines = [
        f"Starting function {function}",
        "COLORGRAPH DECISIONS (class=0, result=1, n_nodes=2)",
        "iter ig_idx assigned degree n_interferers flags",
        "  0  32  r30  0  0  0x0",
        "[COALESCE] enter class=0 n_virtuals=40",
    ]
    if coalesce_mappings:
        lines.append("[COALESCE] natural mappings (virt -> root):")
        for virt, root in coalesce_mappings:
            lines.append(f"  {virt} -> {root}")
    lines.append(
        "[COALESCE] exit class=0 n_virtuals=40 distinct_roots=40 forced=0"
    )
    lines.append(
        "SIMPLIFY GRAPH (class=0, n_colors=29, n_class_regs=40)"
    )
    lines.append("iter ig_idx degree array_size flags")
    for iter_idx, ig_idx in simplify_iters:
        lines.append(f"  {iter_idx}  {ig_idx}  1  1  0x0")
    return "\n".join(lines) + "\n"


def _write_spec(
    tmp_path: Path,
    *,
    function: str,
    target: list[int],
    baseline_pcdump: str,
    class_id: int = 0,
) -> Path:
    """Write a baseline pcdump + a matching target YAML; return the YAML path."""
    baseline_path = tmp_path / "baseline_pcdump.txt"
    baseline_path.write_text(baseline_pcdump, encoding="utf-8")
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        textwrap.dedent(
            f"""\
            function: {function}
            simplify_order_target: {target}
            class_id: {class_id}
            baseline_dump: {baseline_path}
            """
        ),
        encoding="utf-8",
    )
    return spec_path


def _write_candidate(
    tmp_path: Path,
    *,
    pcdump_text: str | None,
    object_name: str = "candidate.o",
) -> Path:
    """Write a candidate .o (plus optional sidecar pcdump) and return the .o path."""
    o_path = tmp_path / object_name
    o_path.write_bytes(b"\x00" * 16)
    if pcdump_text is not None:
        sidecar = tmp_path / f"{object_name}.pcdump.txt"
        sidecar.write_text(pcdump_text, encoding="utf-8")
    return o_path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_score_simplify_order_perfect_match_prints_zero(tmp_path: Path) -> None:
    """Baseline and candidate both hit target prefix exactly, no precolor
    disturbance -> score == 0."""
    function = "fn_test"
    baseline_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 42), (1, 32)]
    )
    candidate_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 42), (1, 32)]
    )
    spec = _write_spec(
        tmp_path,
        function=function,
        target=[42, 32],
        baseline_pcdump=baseline_pcdump,
    )
    o_path = _write_candidate(tmp_path, pcdump_text=candidate_pcdump)

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", function,
            "--target", str(spec),
            str(o_path),
        ],
    )
    assert result.exit_code == 0, result.stdout + "\n" + (result.stderr or "")
    assert result.stdout.strip() == "0"


def test_score_simplify_order_partial_progress_emits_lex_score(
    tmp_path: Path,
) -> None:
    """Baseline simplify-order missing the target entirely; candidate hits
    the full target. Score should be 0 (perfect hit, no distance)."""
    function = "fn_test"
    # Baseline: prefix=0/2
    baseline_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 99), (1, 99)]
    )
    # Candidate: prefix=2/2, zero distance (same coalesce shape)
    candidate_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 42), (1, 32)]
    )
    spec = _write_spec(
        tmp_path,
        function=function,
        target=[42, 32],
        baseline_pcdump=baseline_pcdump,
    )
    o_path = _write_candidate(tmp_path, pcdump_text=candidate_pcdump)

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", function,
            "--target", str(spec),
            str(o_path),
        ],
    )
    assert result.exit_code == 0, result.stdout + "\n" + (result.stderr or "")
    assert result.stdout.strip() == "0"


def test_score_simplify_order_missed_prefix_dominates(tmp_path: Path) -> None:
    """Candidate misses prefix entirely -> score >= LEX_BIG."""
    function = "fn_test"
    baseline_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 42), (1, 32)]
    )
    candidate_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 99), (1, 99)]
    )
    spec = _write_spec(
        tmp_path,
        function=function,
        target=[42, 32],
        baseline_pcdump=baseline_pcdump,
    )
    o_path = _write_candidate(tmp_path, pcdump_text=candidate_pcdump)

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", function,
            "--target", str(spec),
            str(o_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    # missed=2 -> 2 * 1_000_000 = 2_000_000
    assert result.stdout.strip() == "2000000"


# ---------------------------------------------------------------------------
# Failure modes that should map to PENALTY_INF stdout (iteration-level)
# ---------------------------------------------------------------------------


def test_score_simplify_order_missing_object_emits_penalty_inf(
    tmp_path: Path,
) -> None:
    function = "fn_test"
    baseline_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 42), (1, 32)]
    )
    spec = _write_spec(
        tmp_path,
        function=function,
        target=[42, 32],
        baseline_pcdump=baseline_pcdump,
    )
    bogus_o = tmp_path / "nonexistent.o"

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", function,
            "--target", str(spec),
            str(bogus_o),
        ],
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == str(10**9)


def test_score_simplify_order_missing_pcdump_sidecar_emits_penalty_inf(
    tmp_path: Path,
) -> None:
    function = "fn_test"
    baseline_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 42), (1, 32)]
    )
    spec = _write_spec(
        tmp_path,
        function=function,
        target=[42, 32],
        baseline_pcdump=baseline_pcdump,
    )
    o_path = _write_candidate(tmp_path, pcdump_text=None)  # no sidecar

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", function,
            "--target", str(spec),
            str(o_path),
        ],
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == str(10**9)


def test_score_simplify_order_function_missing_from_candidate(
    tmp_path: Path,
) -> None:
    function = "fn_test"
    baseline_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 42), (1, 32)]
    )
    # Candidate pcdump for a DIFFERENT function
    candidate_pcdump = _make_pcdump(
        "fn_other", simplify_iters=[(0, 1), (1, 2)]
    )
    spec = _write_spec(
        tmp_path,
        function=function,
        target=[42, 32],
        baseline_pcdump=baseline_pcdump,
    )
    o_path = _write_candidate(tmp_path, pcdump_text=candidate_pcdump)

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", function,
            "--target", str(spec),
            str(o_path),
        ],
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == str(10**9)


# ---------------------------------------------------------------------------
# Failure modes that should exit non-zero (campaign config error)
# ---------------------------------------------------------------------------


def test_score_simplify_order_function_name_mismatch_exits_nonzero(
    tmp_path: Path,
) -> None:
    function_in_spec = "fn_test"
    function_in_call = "fn_other"  # mismatch
    baseline_pcdump = _make_pcdump(
        function_in_spec, simplify_iters=[(0, 42)]
    )
    spec = _write_spec(
        tmp_path,
        function=function_in_spec,
        target=[42],
        baseline_pcdump=baseline_pcdump,
    )
    o_path = _write_candidate(
        tmp_path,
        pcdump_text=_make_pcdump(function_in_spec, simplify_iters=[(0, 42)]),
    )

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", function_in_call,
            "--target", str(spec),
            str(o_path),
        ],
    )
    assert result.exit_code == 2


def test_score_simplify_order_malformed_spec_exits_nonzero(
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        "this: is: bad: yaml\n", encoding="utf-8"
    )
    o_path = _write_candidate(tmp_path, pcdump_text=None)

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", "fn_test",
            "--target", str(spec_path),
            str(o_path),
        ],
    )
    assert result.exit_code == 2


def test_score_simplify_order_missing_target_exits_nonzero(
    tmp_path: Path,
) -> None:
    o_path = _write_candidate(tmp_path, pcdump_text=None)
    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", "fn_test",
            "--target", str(tmp_path / "no_such_spec.yaml"),
            str(o_path),
        ],
    )
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Output format variants
# ---------------------------------------------------------------------------


def test_score_simplify_order_json_output_shape(tmp_path: Path) -> None:
    function = "fn_test"
    baseline_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 42), (1, 32)]
    )
    candidate_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 42), (1, 32)]
    )
    spec = _write_spec(
        tmp_path,
        function=function,
        target=[42, 32],
        baseline_pcdump=baseline_pcdump,
    )
    o_path = _write_candidate(tmp_path, pcdump_text=candidate_pcdump)

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", function,
            "--target", str(spec),
            "--json",
            str(o_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["score"] == 0
    assert payload["function"] == function
    assert payload["target_len"] == 2
    assert payload["common_prefix_length"] == 2
    assert payload["missed_prefix"] == 0
    assert payload["precolor_distance"]["total"] == 0
    assert payload["observed_prefix"] == [42, 32]
    assert payload["target_prefix"] == [42, 32]


def test_score_simplify_order_breakdown_output_includes_components(
    tmp_path: Path,
) -> None:
    function = "fn_test"
    baseline_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 99), (1, 99)]
    )
    candidate_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 42), (1, 32)]
    )
    spec = _write_spec(
        tmp_path,
        function=function,
        target=[42, 32],
        baseline_pcdump=baseline_pcdump,
    )
    o_path = _write_candidate(tmp_path, pcdump_text=candidate_pcdump)

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", function,
            "--target", str(spec),
            "--breakdown",
            str(o_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "Function:" in out
    assert "Score:" in out
    assert "Target prefix:" in out
    assert "Observed prefix:" in out
    assert "Common prefix:" in out
    assert "Precolor distance:" in out


def test_score_simplify_order_json_includes_error_on_failure(
    tmp_path: Path,
) -> None:
    """--json with a missing pcdump sidecar should still emit JSON with
    score=PENALTY_INF and an error field."""
    function = "fn_test"
    baseline_pcdump = _make_pcdump(
        function, simplify_iters=[(0, 42)]
    )
    spec = _write_spec(
        tmp_path,
        function=function,
        target=[42],
        baseline_pcdump=baseline_pcdump,
    )
    o_path = _write_candidate(tmp_path, pcdump_text=None)

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "--function", function,
            "--target", str(spec),
            "--json",
            str(o_path),
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())
    assert payload["score"] == 10**9
    assert "error" in payload


# ---------------------------------------------------------------------------
# Polarity check in --breakdown output
# ---------------------------------------------------------------------------


def _build_target_spec(
    tmp_path: Path,
    *,
    simplify_order_target: list[int],
    force_phys: dict[int, int] | None = None,
    function: str | None = None,
) -> Path:
    """Build a minimal target.yaml file in tmp_path. Returns the path."""
    fn_name = function or "test_fn"
    # Baseline pcdump must contain the function so extract_signature passes.
    baseline_pcdump_text = _make_pcdump(fn_name, simplify_iters=[(0, 99)])
    baseline = tmp_path / "base.txt"
    baseline.write_text(baseline_pcdump_text, encoding="utf-8")
    lines = [
        f"function: {fn_name}",
        f"simplify_order_target: {simplify_order_target}",
        "class_id: 0",
        f"baseline_dump: {baseline}",
    ]
    if force_phys:
        lines.append("force_phys:")
        for k, v in sorted(force_phys.items()):
            lines.append(f"  {k}: {v}")
    spec_path = tmp_path / "target.yaml"
    spec_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return spec_path


def _build_candidate_obj(tmp_path: Path, function: str) -> Path:
    """Build a placeholder candidate .o + .pcdump.txt pair.

    The CLI reads the .o file, but the scorer logic only inspects the
    associated pcdump (looked up via the .pcdump.txt sibling convention).
    Tests just need both files to exist; the pcdump content can be a
    minimal pass-through that parses without error and contains the
    function name."""
    obj_path = tmp_path / "candidate.o"
    obj_path.write_bytes(b"\x00" * 16)
    pcdump = obj_path.with_suffix(obj_path.suffix + ".pcdump.txt")
    # Minimal pcdump: the scorer's prefix calculation will see an empty
    # observed order (no matching ig_idx), but the CLI runs to completion
    # and emits the breakdown sections we care about for these tests.
    pcdump.write_text(
        _make_pcdump(function, simplify_iters=[(0, 99)]),
        encoding="utf-8",
    )
    return obj_path


# ---------------------------------------------------------------------------
# Coalesce-preservation constraint: end-to-end CLI regression (Task 3 bug)
# ---------------------------------------------------------------------------


def _build_candidate_obj_with_coalesce(
    tmp_path: Path,
    *,
    function: str,
    coalesce_mappings: list[tuple[int, int]],
    simplify_iters: list[tuple[int, int]] | None = None,
) -> Path:
    """Build a candidate .o + .pcdump.txt where the pcdump has coalesce
    events for the given (virt, root) mappings.

    Uses _make_pcdump so the format is identical to what the rest of the
    test suite produces and parse_hook_events + find_function can parse it.
    """
    obj_path = tmp_path / "candidate.o"
    obj_path.write_bytes(b"\x00" * 16)
    pcdump = obj_path.with_suffix(obj_path.suffix + ".pcdump.txt")
    pcdump.write_text(
        _make_pcdump(
            function,
            simplify_iters=simplify_iters or [(0, 99)],
            coalesce_mappings=coalesce_mappings,
        ),
        encoding="utf-8",
    )
    return obj_path


def test_score_simplify_order_cli_rejects_coalescing_candidate(
    tmp_path: Path,
) -> None:
    """End-to-end: --breakdown CLI call against a candidate that coalesces
    a target ig_idx produces the structural rejection sentinel score.

    This regression-test exists because the Task 3 unit tests passed the
    new compute_lex_score kwargs explicitly, but the production CLI did
    not — leading to a silent bug where the constraint never fired in
    production. This test exercises the actual CLI dispatch path.
    """
    from src.mwcc_debug.simplify_order_scoring import STRUCTURAL_REJECTION_SCORE

    function = "test_fn"
    # Spec: ig_idx 42 is in simplify_order_target AND in force_phys, so the
    # coalesce-preservation constraint is armed (coalesce_preservation
    # defaults to True in the loaded spec).
    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[42],
        force_phys={42: 28},
        function=function,
    )
    # Candidate: ig_idx 42 appears as a coalesced virtual (virt=42 -> root=3).
    # The constraint must detect this and return STRUCTURAL_REJECTION_SCORE.
    candidate = _build_candidate_obj_with_coalesce(
        tmp_path,
        function=function,
        coalesce_mappings=[(42, 3)],
    )

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "-f", function,
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    # The score line must carry the structural rejection sentinel.
    assert str(STRUCTURAL_REJECTION_SCORE) in result.output


def test_score_simplify_order_cli_no_rejection_without_coalesce(
    tmp_path: Path,
) -> None:
    """Candidate with no coalesce events for the target ig_idx scores normally
    (not rejected), confirming the constraint is not over-firing."""
    from src.mwcc_debug.simplify_order_scoring import STRUCTURAL_REJECTION_SCORE

    function = "test_fn"
    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[42],
        force_phys={42: 28},
        function=function,
    )
    # Candidate: coalesce event exists but for a DIFFERENT ig_idx (virt=99).
    candidate = _build_candidate_obj_with_coalesce(
        tmp_path,
        function=function,
        coalesce_mappings=[(99, 3)],
        simplify_iters=[(0, 42)],
    )

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "-f", function,
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    # Must NOT see the rejection sentinel — this is a normal score.
    assert str(STRUCTURAL_REJECTION_SCORE) not in result.output


def test_breakdown_with_safe_polarity_no_warning(tmp_path: Path) -> None:
    """SAFE polarity (non-volatile targets) emits no polarity warning."""
    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[34, 37, 32],
        force_phys={34: 31, 37: 30, 32: 29},  # all non-volatile
        function="gm_test",
    )
    candidate = _build_candidate_obj(tmp_path, function="gm_test")

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "-f", "gm_test",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Polarity check:" in result.output
    assert "SAFE" in result.output
    assert "wrong polarity" not in result.output.lower()


def test_breakdown_with_wrong_polarity_emits_warning(tmp_path: Path) -> None:
    """WRONG_POLARITY (high-volatile target) emits a clear warning."""
    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[46, 44],
        force_phys={44: 10, 46: 12},  # high-volatile, lbDvd-style
        function="lbDvd_test",
    )
    candidate = _build_candidate_obj(tmp_path, function="lbDvd_test")

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "-f", "lbDvd_test",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output  # warn-only by default
    assert "WRONG POLARITY" in result.output or "wrong polarity" in result.output.lower()
    # Hint at the late-target syntax (deferred debt #20 full)
    assert "--want-late" in result.output or "want-late" in result.output


def test_breakdown_with_uncertain_polarity_emits_note(tmp_path: Path) -> None:
    """UNCERTAIN (mid-volatile targets r4-r9) emits a softer note."""
    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[46, 44],
        force_phys={44: 5, 46: 6},  # mid-volatile, uncertain
        function="x",
    )
    candidate = _build_candidate_obj(tmp_path, function="x")

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "-f", "x",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "uncertain" in result.output.lower()
    # NOT wrong polarity
    assert "wrong polarity" not in result.output.lower()


def test_breakdown_without_force_phys_no_polarity_section(tmp_path: Path) -> None:
    """Specs without force_phys skip the polarity check entirely."""
    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[1, 2],
        force_phys=None,
        function="x",
    )
    candidate = _build_candidate_obj(tmp_path, function="x")

    result = runner.invoke(
        app,
        [
            "debug", "target", "score-simplify-order",
            "-f", "x",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    # No polarity output at all when force_phys is absent
    assert "polarity" not in result.output.lower()


def test_strict_polarity_exits_nonzero_on_wrong(tmp_path: Path) -> None:
    """--strict-polarity exits non-zero when polarity is WRONG_POLARITY."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[46, 44],
        force_phys={44: 10, 46: 12},
        function="lbDvd_test",
    )
    candidate = _build_candidate_obj(tmp_path, function="lbDvd_test")

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "lbDvd_test",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
            "--strict-polarity",
        ],
    )

    assert result.exit_code != 0
    assert "WRONG POLARITY" in result.output or "wrong polarity" in result.output.lower()


def test_strict_polarity_succeeds_on_safe(tmp_path: Path) -> None:
    """--strict-polarity succeeds when polarity is SAFE."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[34, 37],
        force_phys={34: 31, 37: 30},
        function="gm_test",
    )
    candidate = _build_candidate_obj(tmp_path, function="gm_test")

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "gm_test",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
            "--strict-polarity",
        ],
    )

    assert result.exit_code == 0


def test_strict_polarity_does_not_error_on_uncertain(tmp_path: Path) -> None:
    """UNCERTAIN doesn't trigger --strict-polarity exit — only WRONG does.

    Reason: UNCERTAIN means 'might work, might not'. Refusing it
    would block legitimate experiments. Only WRONG_POLARITY
    (structurally impossible) gets the hard refusal."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[46, 44],
        force_phys={44: 5, 46: 6},
        function="x",
    )
    candidate = _build_candidate_obj(tmp_path, function="x")

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "x",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
            "--strict-polarity",
        ],
    )

    assert result.exit_code == 0


def test_strict_polarity_without_force_phys_succeeds(tmp_path: Path) -> None:
    """--strict-polarity on a spec without force_phys is a no-op."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[1],
        force_phys=None,
        function="x",
    )
    candidate = _build_candidate_obj(tmp_path, function="x")

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "x",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
            "--strict-polarity",
        ],
    )

    assert result.exit_code == 0


def test_strict_polarity_implies_breakdown(tmp_path: Path) -> None:
    """--strict-polarity without --breakdown still triggers the check.

    Without this implication, passing --strict-polarity alone is a silent
    no-op: the polarity block is gated by --breakdown, so a screening
    script that only sets --strict-polarity gets no protection. Fix is
    to imply --breakdown when --strict-polarity is set.
    """
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[46, 44],
        force_phys={44: 10, 46: 12},
        function="lbDvd_test",
    )
    candidate = _build_candidate_obj(tmp_path, function="lbDvd_test")

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "lbDvd_test",
            "--target", str(spec_path),
            str(candidate),
            "--strict-polarity",
            # NOTE: no --breakdown flag here
        ],
    )

    assert result.exit_code != 0
    assert "WRONG POLARITY" in result.output or "wrong polarity" in result.output.lower()


# ---------------------------------------------------------------------------
# Coalesce-preservation diagnostic in --breakdown (Task 5)
# ---------------------------------------------------------------------------


def test_breakdown_coalesce_preservation_safe(tmp_path: Path) -> None:
    """When no target ig_idx is coalesced, --breakdown reports
    'Coalesce preservation: ALL TARGETS INDEPENDENT'."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[34],
        force_phys={34: 31},
        function="test_fn",
    )
    candidate = _build_candidate_obj(tmp_path, function="test_fn")

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "test_fn",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Coalesce preservation:" in result.output
    assert "ALL TARGETS INDEPENDENT" in result.output


def test_breakdown_coalesce_preservation_rejected(tmp_path: Path) -> None:
    """When a target ig_idx IS coalesced, --breakdown reports REJECTED
    and lists the coalesced ig_idx values."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[42],
        force_phys={42: 28},
        function="test_fn",
    )
    candidate = _build_candidate_obj_with_coalesce(
        tmp_path, function="test_fn", coalesce_mappings=[(42, 3)]
    )

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "test_fn",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output  # warn-only
    assert "Coalesce preservation:" in result.output
    assert "REJECTED" in result.output
    assert "42" in result.output  # the coalesced ig_idx


def test_breakdown_without_force_phys_no_coalesce_line(tmp_path: Path) -> None:
    """Specs without force_phys -> no coalesce line in --breakdown."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    spec_path = _build_target_spec(
        tmp_path,
        simplify_order_target=[1, 2],
        force_phys=None,
        function="test_fn",
    )
    candidate = _build_candidate_obj(tmp_path, function="test_fn")

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "test_fn",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    # Case-insensitive check that "coalesce preservation" doesn't appear
    assert "coalesce preservation" not in result.output.lower()


def test_breakdown_coalesce_preservation_disabled(tmp_path: Path) -> None:
    """When coalesce_preservation is explicitly false, --breakdown emits
    DISABLED even if a target would be coalesced."""
    # Build a target.yaml that has force_phys + coalesce_preservation: false
    baseline = tmp_path / "base.txt"
    baseline.write_text(
        _make_pcdump("test_fn", simplify_iters=[(0, 99)]),
        encoding="utf-8",
    )
    spec_path = tmp_path / "target.yaml"
    spec_path.write_text(
        f"""function: test_fn
simplify_order_target: [42]
class_id: 0
baseline_dump: {baseline}
force_phys:
  42: 28
coalesce_preservation: false
""",
        encoding="utf-8",
    )
    candidate = _build_candidate_obj_with_coalesce(
        tmp_path, function="test_fn", coalesce_mappings=[(42, 3)]
    )

    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "test_fn",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Coalesce preservation:" in result.output
    assert "DISABLED" in result.output


# ---------------------------------------------------------------------------
# Late-mode --breakdown rendering (Task 6)
# ---------------------------------------------------------------------------


def test_breakdown_late_mode_shows_observed_suffix(tmp_path: Path) -> None:
    """Late-mode target → --breakdown shows the observed suffix and the
    target suffix instead of prefix."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    # Build a spec with simplify_order_target_late
    baseline = tmp_path / "base.txt"
    baseline.write_text(
        _make_pcdump("test_fn", simplify_iters=[(0, 99)]),
        encoding="utf-8",
    )
    spec_path = tmp_path / "target.yaml"
    spec_path.write_text(
        f"""function: test_fn
simplify_order_target_late: [46, 44]
class_id: 0
baseline_dump: {baseline}
""",
        encoding="utf-8",
    )
    candidate = _build_candidate_obj(tmp_path, function="test_fn")

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "test_fn",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    # Late-mode renders "Target suffix" / "Observed suffix" / "Common suffix"
    assert "Target suffix:" in result.output
    assert "Observed suffix:" in result.output
    assert "Common suffix:" in result.output
    # Late-mode should NOT render the prefix variants
    assert "Target prefix:" not in result.output
    assert "Common prefix:" not in result.output


def test_breakdown_late_mode_polarity_safe_for_high_volatile(tmp_path: Path) -> None:
    """Late-mode + high-volatile target → polarity SAFE."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    baseline = tmp_path / "base.txt"
    baseline.write_text(
        _make_pcdump("test_fn", simplify_iters=[(0, 99)]),
        encoding="utf-8",
    )
    spec_path = tmp_path / "target.yaml"
    spec_path.write_text(
        f"""function: test_fn
simplify_order_target_late: [46, 44]
class_id: 0
baseline_dump: {baseline}
force_phys:
  44: 10
  46: 12
""",
        encoding="utf-8",
    )
    candidate = _build_candidate_obj(tmp_path, function="test_fn")

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "test_fn",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Polarity check:" in result.output
    assert "SAFE" in result.output
    # NOT wrong polarity for high-volatile + late
    assert "WRONG POLARITY" not in result.output


def test_breakdown_late_mode_polarity_wrong_for_top_non_volatile(
    tmp_path: Path,
) -> None:
    """Late-mode + r28-r31 target → WRONG POLARITY (wrong direction)."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    baseline = tmp_path / "base.txt"
    baseline.write_text(
        _make_pcdump("test_fn", simplify_iters=[(0, 99)]),
        encoding="utf-8",
    )
    spec_path = tmp_path / "target.yaml"
    spec_path.write_text(
        f"""function: test_fn
simplify_order_target_late: [34, 37]
class_id: 0
baseline_dump: {baseline}
force_phys:
  34: 31
  37: 30
""",
        encoding="utf-8",
    )
    candidate = _build_candidate_obj(tmp_path, function="test_fn")

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "test_fn",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "WRONG POLARITY" in result.output
    # The hint should mention --want-first (since target wants front-mode)
    assert "--want-first" in result.output


def test_breakdown_first_mode_polarity_wrong_hint_mentions_want_late(
    tmp_path: Path,
) -> None:
    """Phase 1's hint said --want-late was 'future work'; Phase 3 ships
    it, so the hint should now actively recommend it."""
    from typer.testing import CliRunner
    from src.cli.debug import debug_app

    baseline = tmp_path / "base.txt"
    baseline.write_text(
        _make_pcdump("test_fn", simplify_iters=[(0, 99)]),
        encoding="utf-8",
    )
    spec_path = tmp_path / "target.yaml"
    spec_path.write_text(
        f"""function: test_fn
simplify_order_target: [46, 44]
class_id: 0
baseline_dump: {baseline}
force_phys:
  44: 10
  46: 12
""",
        encoding="utf-8",
    )
    candidate = _build_candidate_obj(tmp_path, function="test_fn")

    runner = CliRunner()
    result = runner.invoke(
        debug_app,
        [
            "target",
            "score-simplify-order",
            "-f", "test_fn",
            "--target", str(spec_path),
            str(candidate),
            "--breakdown",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "WRONG POLARITY" in result.output
    # The hint should actively recommend --want-late (not say "future work")
    assert "--want-late" in result.output
    # And the stale "deferred debt #20 full" language should be GONE
    assert "deferred debt #20 full" not in result.output
