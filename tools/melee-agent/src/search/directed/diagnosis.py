"""Build a DirectedDiagnosis from raw analysis outputs.

The KEY invariant: ``analysis_valid`` (is the divergence diagnosable?) is
SEPARATE from ``actionable`` (can we resolve a source anchor + mutator for
it?).  A candidate's directed progress must never be discarded just because
the NEXT edit isn't actionable.
"""
from __future__ import annotations

from src.search.directed.contracts import DirectedDiagnosis


def _case_str(c):
    return c.value if hasattr(c, "value") else str(c)


def build_diagnosis(
    *,
    state,
    report,
    reanchor,
    compile,
    function,
    source_text,
    pcdump_text="",
    suggest=None,
    attach=None,
    resolve=None,
):
    """Produce a :class:`DirectedDiagnosis` from analysis outputs.

    Parameters
    ----------
    state:       object with ``.fact.case`` and ``.fact.ig_idx``
    report:      AllocatorReport with ``.fact`` and ``.source``
    reanchor:    reanchor result with ``.matched`` dict
    compile:     candidate compile object; ``compile.fn`` is passed as
                 ``pre_pass`` to ``attach_source_ideas``
    function:    function name string
    source_text: current C source
    pcdump_text: pcdump output text
    suggest:     injectable override for ``suggest_coalesce.run``
    attach:      injectable override for ``attach_source_ideas``
    resolve:     injectable override for ``anchors.resolve_anchor``
    """
    if suggest is None:
        from src.mwcc_debug.suggest_coalesce import run as suggest  # type: ignore[assignment]
    if attach is None:
        from src.mwcc_debug.first_divergence import attach_source_ideas as attach  # type: ignore[assignment]
    if resolve is None:
        from src.search.directed.anchors import resolve_anchor as resolve  # lazy: Task 8

    case = _case_str(state.fact.case)

    analysis_valid = (
        bool(reanchor.matched)
        and case not in {"none", "abstained"}
        and report is not None
    )

    idea = None
    coalesce_pair = None

    if report is not None:
        # report.source is ALWAYS None from analyze_first_divergence; call
        # attach_source_ideas to obtain a SourceIdea.  pre_pass must be
        # compile.fn, NOT None.
        idea = report.source or attach(report.fact, source_text, function, compile.fn)

        try:
            sug = suggest(
                function=function,
                discover=True,
                pcdump_text=pcdump_text,
                source_text=source_text,
            )
            if sug.pairs:
                p = sug.pairs[0]
                coalesce_pair = (p.from_virt, p.to_virt)
        except Exception:
            coalesce_pair = None

    anchor = resolve(idea, source_text) if idea is not None else None
    actionable = anchor is not None

    return DirectedDiagnosis(
        case=case,
        target_igs=(state.fact.ig_idx,),
        source_idea=idea,
        coalesce_pair=coalesce_pair,
        mutator_key=(anchor.mutator_key if anchor else None),
        resolved_anchor=anchor,
        analysis_valid=analysis_valid,
        actionable=actionable,
        invalid_reason=(None if analysis_valid else case),
    )
