"""Smoke test for run_directed dry path (Task 12).

No mwcc compilation occurs — the dry=True flag substitutes in-memory fakes
so this test is fast, deterministic, and safe for CI.
"""
from __future__ import annotations

import pytest


def test_run_directed_dry(tmp_path):
    """run_directed(dry=True) returns the required top-level keys and a valid
    gate reason token without any mwcc invocation."""
    from src.search.directed.run import run_directed

    res = run_directed(
        function="grIceMt_801F9ACC",
        unit="melee/gr/gricemt",
        melee_root=tmp_path,
        store_dir=tmp_path / "store",
        dry=True,
    )

    # Top-level shape
    assert "gate" in res, f"missing 'gate' key: {res}"
    assert "directed_telemetry" in res, f"missing 'directed_telemetry' key: {res}"
    assert "accounting" in res, f"missing 'accounting' key: {res}"

    # Gate sub-keys
    gate = res["gate"]
    assert "passed" in gate, f"gate missing 'passed': {gate}"
    assert "reason" in gate, f"gate missing 'reason': {gate}"
    assert "evidence" in gate, f"gate missing 'evidence': {gate}"

    # Reason must be a known token
    valid_reasons = {
        "attributable_progress",
        "no_smooth_gradient",
        "void_no_treatment",
        "unattributed_or_regressing",
        "not_preflight",
    }
    assert gate["reason"] in valid_reasons, (
        f"unexpected gate reason: {gate['reason']!r}; expected one of {valid_reasons}"
    )

    # passed must be a bool
    assert isinstance(gate["passed"], bool), f"gate['passed'] must be bool: {gate}"


def test_run_directed_dry_returns_telemetry(tmp_path):
    """Dry run should produce at least one directed_telemetry entry."""
    from src.search.directed.run import run_directed

    res = run_directed(
        function="grIceMt_801F9ACC",
        unit="melee/gr/gricemt",
        melee_root=tmp_path,
        store_dir=tmp_path / "store",
        dry=True,
    )

    telemetry = res["directed_telemetry"]
    assert isinstance(telemetry, list), "directed_telemetry must be a list"
    # Dry mode vends 2 batches → at least 1 entry
    assert len(telemetry) >= 1, (
        f"expected at least 1 telemetry entry in dry mode, got {len(telemetry)}"
    )

    # Each entry must have the DirectedMeta fields
    for entry in telemetry:
        assert "valid" in entry, f"telemetry entry missing 'valid': {entry}"
        assert "displacement" in entry, f"telemetry entry missing 'displacement': {entry}"
        assert "case" in entry, f"telemetry entry missing 'case': {entry}"


def test_run_directed_dry_accounting(tmp_path):
    """Dry run accounting dict must be present and non-empty."""
    from src.search.directed.run import run_directed

    res = run_directed(
        function="grIceMt_801F9ACC",
        unit="melee/gr/gricemt",
        melee_root=tmp_path,
        store_dir=tmp_path / "store",
        dry=True,
    )

    accounting = res["accounting"]
    assert isinstance(accounting, dict), "accounting must be a dict"
    assert "compiled" in accounting, f"accounting missing 'compiled': {accounting}"


def test_run_directed_live_case_abstained_scores_seed_fallback(
    tmp_path,
    monkeypatch,
):
    from src.search.directed.contracts import DirectedMeta, DirectedObjective
    from src.search.directed.objective import PreflightError
    from src.search.types import SearchResult

    repo = tmp_path / "repo"
    source_path = repo / "src" / "melee" / "ft" / "ftdynamics.c"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("int ftCo_8009E7B4(void){return 7;}\n")
    seed_texts = []

    class _Roles:
        function = "ftCo_8009E7B4"
        roles = [object()]

    class _FakePcdumpBackend:
        def __init__(self, **kwargs):
            pass

    class _FakeScheduler:
        def __init__(self, **kwargs):
            pass

        def run(self, *, sources, **kwargs):
            for source in sources:
                if source.name() == "seed-list":
                    batch = source.next_batch(1)
                    seed_texts.extend(variant.source_text for variant in batch)
                    break
            return SearchResult(
                accounting={"compiled": 1},
                directed_telemetry=[
                    DirectedMeta(
                        candidate_id="seed",
                        source_hash="hash",
                        iteration=1,
                        parent_id=None,
                        parent_state_id="root",
                        valid=True,
                        invalid_reason=None,
                        case="force_phys_assignment",
                        label="assignment_fallback",
                        order_distance=0,
                        displacement=1.0,
                        displacement_delta=1.0,
                        reanchor_matched=1,
                        reanchor_total=1,
                        diagnosis_chars=21,
                        applied_mutator="seed#1",
                        directed_scalar=1.0,
                    )
                ],
            )

    def fake_objective(**kwargs):
        return DirectedObjective(
            search_target=kwargs["search_target"],
            role_target=_Roles(),
            baseline_compile=object(),
            baseline_pcdump_path=tmp_path / "baseline.pcdump.txt",
            baseline_source_hash="baseline",
            class_id=kwargs["class_id"],
            objective_iter_by_original_ig={58: 1},
            proof_force_phys=kwargs["proof_force_phys"],
        )

    def abstain_preflight(_objective):
        raise PreflightError("case_abstained")

    monkeypatch.setattr(
        "src.search.directed.pcdump_backend.PcdumpLocalBackend",
        _FakePcdumpBackend,
    )
    monkeypatch.setattr(
        "src.search.directed.objective.build_directed_objective",
        fake_objective,
    )
    monkeypatch.setattr(
        "src.search.directed.objective.preflight_objective",
        abstain_preflight,
    )
    monkeypatch.setattr(
        "src.search.scheduler.DefaultScheduler",
        _FakeScheduler,
    )

    from src.search.directed.run import run_directed

    res = run_directed(
        function="ftCo_8009E7B4",
        unit="melee/ft/ftdynamics",
        melee_root=repo,
        store_dir=tmp_path / "store",
        max_iters=1,
        proof_force_phys={58: 4},
    )

    assert seed_texts == [source_path.read_text()]
    assert res["gate"]["reason"] == "attributable_progress"
    assert res["directed_telemetry"][0]["case"] == "force_phys_assignment"
    assert res["accounting"]["preflight"]["fallback"] == "force_phys_assignment"


def test_run_directed_live_seed_override_keeps_repo_source_as_baseline(
    tmp_path,
    monkeypatch,
):
    from src.search.directed.contracts import DirectedObjective
    from src.search.types import SearchResult

    repo = tmp_path / "repo"
    source_path = repo / "src" / "melee" / "ft" / "ftdynamics.c"
    source_path.parent.mkdir(parents=True)
    repo_source = "int ftCo_8009E7B4(void){return 0;}\n"
    source_path.write_text(repo_source)
    seed_path = tmp_path / "candidate.c"
    candidate_source = "int ftCo_8009E7B4(void){return 1;}\n"
    seed_path.write_text(candidate_source)

    objective_sources = []
    scheduled_sources = []
    control_sources = []

    class _Roles:
        function = "ftCo_8009E7B4"
        roles = [object()]

    class _FakePcdumpBackend:
        def __init__(self, **kwargs):
            pass

    class _FakePipeline:
        def __init__(self, *args, **kwargs):
            pass

    class _FakeScheduler:
        def __init__(self, **kwargs):
            pass

        def run(self, *, sources, **kwargs):
            scheduled_sources.extend(
                getattr(source, "_current_best", None) for source in sources
            )
            return SearchResult(accounting={"compiled": 0}, directed_telemetry=[])

    def fake_objective(**kwargs):
        objective_sources.append(kwargs["baseline_source_text"])
        return DirectedObjective(
            search_target=kwargs["search_target"],
            role_target=_Roles(),
            baseline_compile=object(),
            baseline_pcdump_path=tmp_path / "baseline.pcdump.txt",
            baseline_source_hash="baseline",
            class_id=kwargs["class_id"],
            objective_iter_by_original_ig={58: 1},
            proof_force_phys=kwargs["proof_force_phys"],
        )

    def fake_control(**kwargs):
        control_sources.append(kwargs["source_text"])
        return 0.0, None

    monkeypatch.setattr(
        "src.search.directed.pcdump_backend.PcdumpLocalBackend",
        _FakePcdumpBackend,
    )
    monkeypatch.setattr(
        "src.search.directed.objective.build_directed_objective",
        fake_objective,
    )
    monkeypatch.setattr(
        "src.search.directed.objective.preflight_objective",
        lambda objective: None,
    )
    monkeypatch.setattr(
        "src.search.directed.scorer.DirectedScorePipeline",
        _FakePipeline,
    )
    monkeypatch.setattr(
        "src.search.scheduler.DefaultScheduler",
        _FakeScheduler,
    )
    monkeypatch.setattr(
        "src.search.directed.run._score_control_baseline",
        fake_control,
    )

    from src.search.directed.run import run_directed

    run_directed(
        function="ftCo_8009E7B4",
        unit="melee/ft/ftdynamics",
        melee_root=repo,
        store_dir=tmp_path / "store",
        max_iters=1,
        proof_force_phys={58: 4},
        source_file=seed_path,
    )

    assert objective_sources == [repo_source]
    assert scheduled_sources == [candidate_source]
    assert control_sources == [repo_source]
