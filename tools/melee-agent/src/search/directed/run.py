"""run_directed: assemble and execute the directed search layer.

This module is the final assembly point for the directed-search pipeline.
It wires together:
  - DirectedObjective (build_directed_objective / preflight_objective)
  - PcdumpLocalBackend
  - DirectedScorePipeline
  - DirectedSource (with a ``propose`` function)
  - DefaultScheduler.run(..., directed=DirectedSchedulerConfig(...))
  - evaluate_phase1_gate

Dry mode (dry=True) substitutes in-memory fakes for the objective, backend,
and score pipeline so NO mwcc runs occur. It is used for testing and CI.

Returns a dict with keys:
  "gate":                GateVerdict as dict (passed, reason, evidence)
  "directed_telemetry":  list of DirectedMeta dicts
  "accounting":          scheduler accounting dict
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_directed(
    *,
    function: str,
    unit: str,
    melee_root: Any,
    store_dir: Any,
    dry: bool = False,
    max_iters: int = 8,
    proof_force_phys: dict[int, int] | None = None,
    class_id: int = 0,
    source_file: Any = None,
) -> dict:
    """Run the directed search layer for *function* in *unit*.

    Parameters
    ----------
    function:
        Short function name, e.g. ``"grIceMt_801F9ACC"``.
    unit:
        TU path relative to ``src/``, e.g. ``"melee/gr/gricemt"``.
    melee_root:
        Absolute path to the melee repository root.
    store_dir:
        Directory for the ArtifactStore.
    dry:
        If True, skip all real mwcc invocations: assemble fakes and return
        a well-formed gate verdict.  Used for testing.
    max_iters:
        Maximum scheduler iterations.

    Returns
    -------
    dict with keys ``"gate"``, ``"directed_telemetry"``, ``"accounting"``.
    """
    melee_root = Path(melee_root)
    store_dir = Path(store_dir)

    from src.search.store import ArtifactStore

    store = ArtifactStore(store_dir)

    if dry:
        return _run_dry(
            function=function,
            unit=unit,
            melee_root=melee_root,
            store=store,
            max_iters=max_iters,
        )
    return _run_live(
        function=function,
        unit=unit,
        melee_root=melee_root,
        store=store,
        max_iters=max_iters,
        proof_force_phys=proof_force_phys,
        class_id=class_id,
        source_file=source_file,
    )


# ---------------------------------------------------------------------------
# Dry path
# ---------------------------------------------------------------------------


def _run_dry(*, function: str, unit: str, melee_root: Path, store: Any, max_iters: int) -> dict:
    """Dry run: fakes that exercise the gate without any mwcc compilation."""
    from dataclasses import replace

    from src.search.artifact import (
        CandidateArtifact,
        CompileSpec,
        Provenance,
    )
    from src.search.directed.contracts import (
        DirectedMeta,
        DirectedSchedulerConfig,
        DirectedSearchState,
        DirectedScoringCall,
    )
    from src.search.directed.gate import evaluate_phase1_gate
    from src.search.scheduler import DefaultScheduler
    from src.search.types import (
        Budget,
        SchedulePolicy,
        SourceVariant,
        TargetSpec,
    )

    # Build a fake TargetSpec (no expected .o needed for dry)
    target = TargetSpec(
        function=function,
        unit=unit,
        expected_obj=melee_root / "build" / "GALE01" / "obj" / f"{unit}.o",
    )

    # A minimal source text to seed the source
    fake_source = f"// dry-run stub for {function}\nvoid {function}(void) {{}}\n"

    # -----------------------------------------------------------------------
    # Fake backend: always returns ok artifact
    # -----------------------------------------------------------------------
    class _FakePcdumpBackend:
        def capabilities(self):
            from src.search.types import BackendCaps
            return BackendCaps("local", 1, True)

        def compile(self, variant: SourceVariant, *, want_pcdump: bool = False) -> CandidateArtifact:
            src_hash = hashlib.sha256(variant.source_text.encode()).hexdigest()[:32]
            src_blob = store.put_source(variant.source_text)
            spec = CompileSpec(
                target_id=f"{function}@{unit}",
                cflags_hash="drydry",
                base_context_hash="dry",
                toolchain_fingerprint="dry",
                backend_mode="dry",
                manifest_path=store.root / "dry_manifest.json",
            )
            prov = variant.provenance or Provenance("dry", None, None, "", {})
            from src.search.artifact import compute_candidate_id
            cid = compute_candidate_id(spec, src_hash)
            obj_path = store.root / f"{cid}.o"
            obj_path.write_bytes(b"\x00" * 16)
            return CandidateArtifact(
                candidate_id=cid,
                source_hash=src_hash,
                source_blob=src_blob,
                compile_spec=spec,
                object_path=obj_path,
                producer_score=None,
                byte_score=42,
                directed_score=None,
                pcdump_path=None,
                compiler_stderr="",
                provenance=prov,
                status="ok",
                directed_meta=None,
            )

    # -----------------------------------------------------------------------
    # Fake score pipeline: returns valid DirectedMeta with a fixed displacement
    # -----------------------------------------------------------------------
    class _FakeScorePipeline:
        def __init__(self) -> None:
            self._call = 0

        def score_byte(self, art: CandidateArtifact, target: Any) -> CandidateArtifact:
            return art

        def should_escalate(self, art: Any, ctx: Any) -> bool:
            return True  # always escalate so directed scoring runs

        def score_directed(self, art: CandidateArtifact, call: DirectedScoringCall) -> CandidateArtifact:
            self._call += 1
            # Produce an attributed, covered, displacement-improving meta so the
            # gate sees "attributable_progress" on iteration 2+; on the first
            # call displacement_delta is 0 (no parent to compare against yet).
            parent_disp = 0.0
            disp = 0.5 + self._call * 0.1
            delta = disp - parent_disp
            meta = DirectedMeta(
                candidate_id=art.candidate_id,
                source_hash=art.source_hash,
                iteration=self._call,
                parent_id=None,
                parent_state_id=call.parent_state.state_id,
                valid=True,
                invalid_reason=None,
                case="select_order",
                label="improving",
                order_distance=1,
                displacement=disp,
                displacement_delta=delta,
                reanchor_matched=2,
                reanchor_total=2,
                diagnosis_chars=len("select_order"),
                applied_mutator="reorder_local_decls",
                directed_scalar=disp,
            )
            return replace(art, directed_score=disp, directed_meta=meta, status="ok")

    # -----------------------------------------------------------------------
    # Fake source: vends a couple of variants then drains
    # -----------------------------------------------------------------------
    class _FakeSource:
        def __init__(self) -> None:
            self._call = 0

        def name(self) -> str:
            return "dry-source"

        def seed(self, base: Any) -> None:
            pass

        def next_batch(self, n: int) -> list[SourceVariant]:
            if self._call >= 2:
                return []
            self._call += 1
            return [SourceVariant(
                source_text=fake_source + f"// iter {self._call}",
                provenance=None,
            )]

        def observe(self, scored: list) -> None:
            pass

    pcdump_backend = _FakePcdumpBackend()
    score_pipeline = _FakeScorePipeline()
    fake_source_obj = _FakeSource()

    from src.search.directed.contracts import DirectedSchedulerConfig
    from src.search.directed.objective import DirectedObjective  # for type hint

    # Build a minimal objective (all Nones — gate uses only telemetry)
    # We need a dummy role_target with truthy .roles for the preflight check
    # that run through the score_pipeline.
    fake_objective = _DryObjective(function=function)

    cfg = DirectedSchedulerConfig(
        objective=fake_objective,
        score_pipeline=score_pipeline,
        backend=pcdump_backend,
        plateau_n=3,
    )

    sched = DefaultScheduler(store=store, verifier=None)

    result = sched.run(
        sources=[fake_source_obj],
        backends=[pcdump_backend],
        producers=[],
        pipeline=score_pipeline,
        target=target,
        budget=Budget(max_iters=max_iters),
        policy=SchedulePolicy(batch_size=1),
        directed=cfg,
    )

    # Evaluate the gate (preflight always passes in dry mode)
    from src.search.directed.gate import evaluate_phase1_gate
    verdict = evaluate_phase1_gate(
        preflight_ok=True,
        telemetry=result.directed_telemetry,
        control_displacement=0.0,
    )

    return {
        "gate": {
            "passed": verdict.passed,
            "reason": verdict.reason,
            "evidence": verdict.evidence,
        },
        "directed_telemetry": [
            _meta_to_dict(m) for m in result.directed_telemetry
        ],
        "accounting": result.accounting,
    }


class _DryObjective:
    """Minimal stand-in for DirectedObjective (dry mode only)."""

    def __init__(self, function: str) -> None:
        self.function = function
        # Minimal role_target: truthy .roles so scorer validity-gate 1 passes
        self.role_target = _DryRoleTarget()
        self.class_id = 0
        self.objective_iter_by_original_ig: dict = {0: 0, 1: 1}
        self.proof_force_phys: dict = {}
        self.baseline_compile = None
        self.baseline_pcdump_path = None
        self.baseline_source_hash = "dry"
        self.search_target = None


class _DryRoleTarget:
    """Minimal stand-in for a TargetSpec role_target (dry mode only)."""

    def __init__(self) -> None:
        self.roles = [_DryRole(0), _DryRole(1)]
        self.function = "dry_fn"

    class _R:
        pass


class _DryRole:
    def __init__(self, ig: int) -> None:
        self.original_ig = ig
        self.desired_phys = ig + 27


def _meta_to_dict(m: Any) -> dict:
    """Serialize a DirectedMeta to a plain dict for JSON output."""
    from dataclasses import asdict, fields
    try:
        return asdict(m)
    except Exception:
        # Fallback for any custom types
        result = {}
        for f in fields(m):
            v = getattr(m, f.name)
            result[f.name] = v
        return result


# ---------------------------------------------------------------------------
# Live path
# ---------------------------------------------------------------------------


def _make_propose(*, backend: Any, function: str, source_text_ref: list) -> Any:
    """Build a propose callable for DirectedSource.

    Tries levers in order: reorder_local_decls, change_counter_width,
    split_decl_init.  Compiles the source to a pcdump via backend, runs
    analyze_iteration_full + build_diagnosis, then calls resolve_anchor on
    each untried lever.

    Returns (mutator_key, anchor) | None.
    """
    from src.search.directed.anchors import resolve_anchor
    from src.search.directed.diagnosis import build_diagnosis

    _LEVER_ORDER = [
        "reorder_local_decls",
        "change_counter_width",
        "split_decl_init",
    ]

    def propose(source_text: str, tried: frozenset) -> Optional[tuple]:
        # Compile to get a pcdump
        from src.search.types import SourceVariant
        variant = SourceVariant(source_text, None)
        art = backend.compile(variant, want_pcdump=True)
        if art.status != "ok" or art.pcdump_path is None:
            return None

        # Build Compile and run analysis
        try:
            pcdump_text = Path(art.pcdump_path).read_text(encoding="utf-8")
            from src.mwcc_debug.role_descriptor import Compile
            compile_obj = Compile.from_text(pcdump_text, function, source_text)
            from src.mwcc_debug.convergence import analyze_iteration_full
            # We need a target for analyze; use a minimal proxy
            # diagnosis.build_diagnosis handles the target internally
            state, report, reanchor = None, None, None
            try:
                # analyze_iteration_full needs a role_target — use bare
                # convergence API (first pass uses the compile object)
                from src.mwcc_debug import convergence as _cv
                # Fallback: build diagnosis with what we have
            except Exception:
                pass

            # Build diagnosis for the anchor
            diag = build_diagnosis(
                state=_DummyState(),
                report=None,
                reanchor=_DummyReanchor(),
                compile=compile_obj,
                function=function,
                source_text=source_text,
                pcdump_text=pcdump_text,
            )
        except Exception:
            diag = None

        # Try each lever in order
        for lever in _LEVER_ORDER:
            if lever in tried:
                continue
            if diag is not None and diag.source_idea is not None:
                anchor = resolve_anchor(diag.source_idea, source_text)
                if anchor is not None and anchor.mutator_key == lever:
                    return (lever, anchor)
            # Try to resolve without a diagnosis (lever-specific fallback)
            # — pass None idea filtered to this lever only
        return None

    return propose


class _DummyState:
    """Minimal state stub for propose/diagnosis (live path propose helper)."""
    class _Fact:
        case = "select_order"
        ig_idx = 0
    fact = _Fact()


class _DummyReanchor:
    """Minimal reanchor stub."""
    matched: dict = {}


def _run_live(
    *,
    function: str,
    unit: str,
    melee_root: Path,
    store: Any,
    max_iters: int,
    proof_force_phys: dict[int, int] | None = None,
    class_id: int = 0,
    source_file: Any = None,
) -> dict:
    """Live run: real mwcc compile + analysis + scoring."""
    import hashlib as _hashlib

    from src.search.adapters import RealLocalCompiler, RealByteScorer
    from src.search.artifact import CompileManifest, CompileSpec
    from src.search.directed.contracts import DirectedSchedulerConfig
    from src.search.directed.gate import evaluate_phase1_gate
    from src.search.directed.objective import (
        GRICEMT_9ACC_FORCE_PHYS,
        build_directed_objective,
        preflight_objective,
        PreflightError,
    )
    from src.search.directed.pcdump_backend import PcdumpLocalBackend
    from src.search.directed.scorer import DirectedScorePipeline
    from src.search.directed.source import DirectedSource
    from src.search.scheduler import DefaultScheduler
    from src.search.scoring import ByteScorePipeline, DefaultSchedulePolicy
    from src.search.types import Budget, SchedulePolicy, SourceSpec, TargetSpec

    # Resolve expected .o and initial source.
    tu_path = melee_root / "src" / f"{unit}.c"
    source_path = Path(source_file) if source_file is not None else tu_path
    source_text = source_path.read_text(encoding="utf-8")

    # Determine force_phys: prefer operator-provided proof, retain the older
    # grIceMt fixture default for backward compatibility.
    is_9acc = function == "grIceMt_801F9ACC"
    force_phys = (
        proof_force_phys
        if proof_force_phys is not None
        else GRICEMT_9ACC_FORCE_PHYS if is_9acc else {}
    )

    # Build compile spec factory (shared by both backends)
    _CFLAGS = (
        "-O4,p -nodefaults -proc gekko -fp hardware -Cpp_exceptions off "
        "-enum int -fp_contract on -inline auto"
    )
    cflags_hash = _hashlib.sha256(_CFLAGS.encode()).hexdigest()[:16]
    base_context_hash = _hashlib.sha256(
        source_text.encode()
    ).hexdigest()[:32]

    # Minimal manifest
    _INCLUDES_BASE = ["src", "src/MSL", "src/Runtime", "extern/dolphin/include"]
    include_paths = [str((melee_root / inc).resolve()) for inc in _INCLUDES_BASE]
    obj_rel = f"build/GALE01/src/{unit}.o"
    manifest = CompileManifest(
        compile_command=["ninja", obj_rel],
        cflags=_CFLAGS.split(),
        include_paths=include_paths,
        base_context_blob=store.put_source(""),
        permuter_compile_sh=None,
        permuter_settings_toml=None,
    )
    manifest_path = store.put_manifest(manifest)

    from src.search.types import SourceVariant

    def _make_spec(variant: SourceVariant) -> CompileSpec:
        src_hash = _hashlib.sha256(variant.source_text.encode()).hexdigest()[:32]
        return CompileSpec(
            target_id=f"{function}@{unit}",
            cflags_hash=cflags_hash,
            base_context_hash=base_context_hash,
            toolchain_fingerprint="mwcc_233_163n",
            backend_mode="pcdump-local",
            manifest_path=manifest_path,
        )

    target = TargetSpec(
        function=function,
        unit=unit,
        expected_obj=melee_root / "build" / "GALE01" / "obj" / f"{unit}.o",
    )

    # Pcdump backend (tier-2)
    pcdump_backend = PcdumpLocalBackend(
        melee_root=melee_root,
        unit=unit,
        target=target,
        store=store,
        compile_spec_factory=_make_spec,
    )

    # Build the DirectedObjective
    preflight_ok = True
    preflight_reason = None
    objective = None
    try:
        objective = build_directed_objective(
            melee_root=melee_root,
            search_target=None,
            function=function,
            unit=unit,
            proof_force_phys=force_phys,
            class_id=class_id,
            backend=pcdump_backend,
            baseline_source_text=source_text,
        )
        preflight_objective(objective)
    except PreflightError as exc:
        preflight_ok = False
        preflight_reason = str(exc)
    except Exception as exc:
        preflight_ok = False
        preflight_reason = f"build_error:{exc}"

    if not preflight_ok:
        from src.search.directed.gate import evaluate_phase1_gate
        verdict = evaluate_phase1_gate(
            preflight_ok=False,
            telemetry=[],
            control_displacement=0.0,
        )
        return {
            "gate": {
                "passed": verdict.passed,
                "reason": verdict.reason,
                "evidence": {"preflight_reason": preflight_reason},
            },
            "directed_telemetry": [],
            "accounting": {"preflight_failed": True, "reason": preflight_reason},
        }

    # Score pipeline (real): always escalate to directed scoring so the pcdump
    # backend is used from iteration 0. The DirectedSource's propose function
    # already does its own compile for analysis; tier-1-first would never
    # populate the byte_history needed to trigger should_escalate normally.
    from src.search.adapters import RealByteScorer

    def _safe_classify(prev: Any, curr: Any, *, edit_was_order_change: bool,
                       history: list, checkdiff_clean: bool):
        """classify_progress wrapper that guards against DirectedSearchState 'prev'.

        The scorer passes ``parent_state.prev_state`` as ``prev``.
        ``parent_state.prev_state`` is a ``DirectedSearchState`` (or None for
        the root) which does NOT have the ``.identity`` attribute that
        ``classify_progress`` expects.  Guard by passing ``None`` whenever
        ``prev`` lacks that attribute.
        """
        from src.mwcc_debug.progress_classifier import classify_progress
        # Only pass prev if it has the .identity attribute (an IterationState).
        safe_prev = prev if hasattr(prev, "identity") else None
        return classify_progress(
            safe_prev, curr,
            edit_was_order_change=edit_was_order_change,
            history=history,
            checkdiff_clean=checkdiff_clean,
        )

    class _AlwaysEscalate(DirectedScorePipeline):
        """DirectedScorePipeline that always escalates to pcdump/directed."""
        def should_escalate(self, art: Any, ctx: Any) -> bool:
            return True

    score_pipeline = _AlwaysEscalate(
        plateau_n=3,
        byte_scorer=RealByteScorer(),
        classify=_safe_classify,
    )

    # Source text for seeding
    tu_source = source_text

    # Build the propose function
    def propose(source_text: str, tried: frozenset):
        """Try levers in priority order, returning the first untried anchor.

        Primary path: use build_diagnosis to identify the source_idea and
        resolve an anchor from it.

        Fallback path (C2_STICKY_POOL / var_name=None): when the analysis
        produces a valid diagnosis but no named var (common for sticky-pool
        divergence), enumerate adjacent local declaration pairs in the
        function body and try ``reorder_local_decls`` on each in turn.
        This lets the gate see real compiled/scored candidates even when the
        analysis doesn't resolve a specific variable.
        """
        import re as _re
        from src.search.directed.anchors import resolve_anchor, Anchor

        _LEVER_ORDER = [
            "reorder_local_decls",
            "change_counter_width",
            "split_decl_init",
        ]

        # Compile to get a fresh pcdump for diagnosis
        variant = SourceVariant(source_text, None)
        art = pcdump_backend.compile(variant, want_pcdump=True)
        if art.status != "ok" or art.pcdump_path is None:
            return None

        try:
            pcdump_text = Path(art.pcdump_path).read_text(encoding="utf-8")
            from src.mwcc_debug.role_descriptor import Compile
            compile_obj = Compile.from_text(pcdump_text, function, source_text)
            from src.mwcc_debug.convergence import analyze_iteration_full

            state, report, reanchor = analyze_iteration_full(
                objective.role_target, compile_obj, class_id=objective.class_id
            )
            from src.search.directed.diagnosis import build_diagnosis
            diag = build_diagnosis(
                state=state,
                report=report,
                reanchor=reanchor,
                compile=compile_obj,
                function=function,
                source_text=source_text,
                pcdump_text=pcdump_text,
            )
        except Exception:
            return None

        # Primary path: resolve via diagnosis source_idea
        if diag is not None and diag.source_idea is not None:
            si = diag.source_idea
            if si.var_name is not None:
                for lever in _LEVER_ORDER:
                    if lever in tried:
                        continue
                    anchor = resolve_anchor(si, source_text)
                    if anchor is not None and anchor.mutator_key == lever:
                        return (lever, anchor)

        # Fallback path: when var_name is None (e.g. C2_STICKY_POOL), try
        # reorder_local_decls on the first untried adjacent local declaration
        # pair in the function body.  We iterate through pairs and skip those
        # whose pair index is already in the tried set (stored as
        # "reorder_local_decls@N").  The key passed to DirectedSource is the
        # pair-specific token; a custom apply_fn (below) strips the "@N"
        # suffix before dispatching to apply_mutator.
        _DECL_RE = _re.compile(
            r"^(?P<indent>[ \t]+)"
            r"(?P<type>[A-Za-z_][\w* ]*?)"
            r"[ \t]+"
            r"(?P<var>[A-Za-z_]\w*)"
            r"[^;]*;",
            _re.MULTILINE,
        )
        matches = list(_DECL_RE.finditer(source_text))
        for i in range(len(matches) - 1):
            pair_key = f"reorder_local_decls@{i}"
            if pair_key in tried:
                continue
            m1, m2 = matches[i], matches[i + 1]
            # They must be adjacent (only whitespace between them)
            between = source_text[m1.end():m2.start()]
            if between.strip():
                continue
            line_start1 = source_text.rfind("\n", 0, m1.start()) + 1
            line_end1 = source_text.find("\n", m1.end())
            if line_end1 == -1:
                line_end1 = len(source_text)
            first_line = source_text[line_start1:line_end1]

            line_start2 = source_text.rfind("\n", 0, m2.start()) + 1
            line_end2 = source_text.find("\n", m2.end())
            if line_end2 == -1:
                line_end2 = len(source_text)
            second_line = source_text[line_start2:line_end2]

            if first_line + "\n" + second_line not in source_text:
                continue

            start = line_start1
            end = line_end2 + 1 if line_end2 < len(source_text) else line_end2
            anchor = Anchor(
                mutator_key="reorder_local_decls",
                span=(start, end),
                payload={
                    "first_line": first_line,
                    "second_line": second_line,
                },
            )
            return (pair_key, anchor)

        return None

    # Custom apply: strip "@N" suffix from fallback pair keys before dispatch
    def _apply_fn(key: str, anchor, source_text: str):
        from src.search.directed.mutators import apply_mutator
        # Strip "@N" suffix produced by the fallback pair enumeration
        base_key = key.split("@")[0] if "@" in key else key
        return apply_mutator(base_key, anchor, source_text)

    # DirectedSource
    directed_source = DirectedSource(propose=propose, apply=_apply_fn)
    directed_source.seed(SourceSpec(tu_source, target))

    cfg = DirectedSchedulerConfig(
        objective=objective,
        score_pipeline=score_pipeline,
        backend=pcdump_backend,
        plateau_n=3,
    )

    sched = DefaultScheduler(store=store, verifier=None)

    result = sched.run(
        sources=[directed_source],
        backends=[pcdump_backend],
        producers=[],
        pipeline=score_pipeline,
        target=target,
        budget=Budget(max_iters=max_iters),
        policy=SchedulePolicy(batch_size=1),
        directed=cfg,
    )

    from src.search.directed.gate import evaluate_phase1_gate
    verdict = evaluate_phase1_gate(
        preflight_ok=True,
        telemetry=result.directed_telemetry,
        control_displacement=0.0,
    )

    return {
        "gate": {
            "passed": verdict.passed,
            "reason": verdict.reason,
            "evidence": verdict.evidence,
        },
        "directed_telemetry": [
            _meta_to_dict(m) for m in result.directed_telemetry
        ],
        "accounting": result.accounting,
    }
