import json
from pathlib import Path

from typer.testing import CliRunner

import src.mwcc_debug.post_ceiling_baseline_escape as pbe
from src.mwcc_debug.post_ceiling_baseline_escape import (
    CONTINUATION_FAMILY,
    CONTINUATION_TERMINAL_KIND,
    CONTINUATION_TERMINAL_REASON,
    FINAL_TERMINAL_KIND,
    FINAL_TERMINAL_REASON,
    FORCE_CONFLICT_TERMINAL_KIND,
    SORT_TERMINAL_KIND,
    TERMINAL_REASON,
    analyze_baseline_escape_continuations,
    classify_baseline_escape_scores,
    generate_baseline_escape_candidate_files,
    generate_baseline_escape_candidates,
    resolve_baseline_source_path,
)
from src.search.cli import search_app


FUNC = "mnDiagram_DrawCellNumber"
SORT_FUNC = "mnDiagram_SortNamesByKOs"
SORT_SOURCE_FUNC = "mnDiagram_8023FC28"
SORT_POST_LOWER_DRIFT_MODEL = (
    "Sort protected-loss init-lifetime scoring exhausted the bounded lower-drift "
    "source family without jointly preserving IG34/IG44. The next unsupported "
    "source model is the full Sort selection/swap source structure outside the "
    "current protected-loss and init-lifetime families."
)
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY = (
    "draw-no-modeled-source-actionable-family-after-post-stack-loop-callsite-"
    "source-context"
)
DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL = (
    "Draw post-stack-clean/no-anchor loop-callsite source-context synthesis "
    "exhausted bounded digit object, animation callarg, translate-X/translate-Y "
    "owner, and add-child parent owner probes from the retained post-stack seed "
    "without recovering IG32/IG37/IG46 expression anchors or eliminating "
    "stack-frame drift under the structural guard."
)


def _source(function: str = FUNC) -> str:
    return (
        "typedef float f32;\n"
        "typedef unsigned char u8;\n"
        "extern void HSD_JObjReqAnimAll(void* jobj, f32 frame);\n"
        f"void {function}(void* jobj, u8 col, u8 row, int digit)\n"
        "{\n"
        "    f32 col_offset;\n"
        "    f32 row_offset;\n"
        "    f32 row_offset_adj;\n"
        "    f32 rowf;\n"
        "    f32 y_spacing;\n"
        "    f32 base;\n"
        "\n"
        "    col_offset = y_spacing * (f32) col;\n"
        "    rowf = (f32) row;\n"
        "    row_offset *= rowf;\n"
        "    row_offset_adj = row_offset - 0.4f;\n"
        "    base = (f32) digit;\n"
        "    HSD_JObjReqAnimAll(jobj, base);\n"
        "    sink(col_offset, row_offset_adj);\n"
        "}\n"
    )


def _expression_score(matched: int = 0) -> dict:
    return {
        "matched": matched,
        "targeted": 3,
        "virtual_distance": 3 - matched,
        "virtuals": {
            "37": {
                "baseline_source": {"name": "row_offset"},
                "expected": 26,
                "actual": 26 if matched else 28,
                "matched": bool(matched),
            },
            "32": {
                "baseline_source": {"name": "col_offset"},
                "expected": 28,
                "actual": 26,
                "matched": False,
            },
            "46": {
                "baseline_source": {"name": "digit_call_fpr"},
                "expected": 26,
                "actual": None,
                "matched": False,
            },
        },
    }


def _allocator(source_file: str | None = None) -> dict:
    payload = {
        "function": FUNC,
        "status": "practical-ceiling",
        "terminal_reason": "expression-scored-fpr-allocator-ceiling",
        "missing_evidence": [],
    }
    if source_file is not None:
        payload["expression_interferer_terminal"] = {
            "source_generation": {"source_file": source_file},
        }
    return payload


def _expression(source_file: str | None = None) -> dict:
    payload = {
        "function": FUNC,
        "post_bridge_terminal_summary": {
            "status": "blocked",
            "kind": "no-expression-progress-after-row-fsubs-and-support-orders",
            "candidate_count": 16,
            "best_expression_matched": 0,
            "attempted_families": ["product_operand_ownership"],
        },
        "expression_score": _expression_score(),
        "target_score": {
            "virtuals": {
                "37": {"expected": 26},
                "32": {"expected": 28},
                "46": {"expected": 26},
            },
        },
    }
    if source_file is not None:
        payload["source_generation"] = {"source_file": source_file}
    return payload


def _retained(source_file: str | None = None) -> dict:
    frontier = {
        "terminal": True,
        "family_id": "retained-source-select-order-repair",
        "terminal_reason": "transform-family-exhausted",
    }
    if source_file is not None:
        frontier["source_file"] = source_file
    return {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": FUNC,
                "frontiers": [],
                "terminal_frontiers": [frontier],
                "next_frontier": None,
            }
        ],
    }


def _sort_source(function: str = SORT_SOURCE_FUNC) -> str:
    return (
        "typedef unsigned char u8;\n"
        "typedef unsigned int u32;\n"
        "typedef struct mnDiagram_Assets { u8 sorted_fighters[0x19]; u8 sorted_names[0x78]; } mnDiagram_Assets;\n"
        "typedef struct mnDiagram_804A0750_t { u8 sorted_fighters[0x19]; u8 sorted_names[0x78]; } mnDiagram_804A0750_t;\n"
        "extern struct { u8 sorted_names[0x78]; } mnDiagram_804A076C;\n"
        "extern void* mnDiagram_804A0750;\n"
        "extern char* GetNameText(u8 idx);\n"
        "extern int mnDiagram_SumNameKOs(u8 idx);\n"
        f"void {function}(void)\n"
        "{\n"
        "    u32 totals[0x78];\n"
        "    int max_idx;\n"
        "    u8* dst_iter;\n"
        "    int i;\n"
        "    mnDiagram_Assets* assets = (mnDiagram_Assets*) &mnDiagram_804A0750;\n"
        "    u8* dst = assets->sorted_names;\n"
        "    u32* tp;\n"
        "    int n;\n"
        "    int j;\n"
        "\n"
        "    dst_iter = dst;\n"
        "    tp = totals;\n"
        "    for (n = 0; n < 0x78; n++, dst_iter++, tp++) {\n"
        "        *dst_iter = (u8) n;\n"
        "        *tp = mnDiagram_SumNameKOs(n & 0xFF);\n"
        "    }\n"
        "\n"
        "    for (i = 0; i < 0x78; i++) {\n"
        "        max_idx = i;\n"
        "        for (j = i + 1; j < 0x78; j++) {\n"
        "            if ((GetNameText(mnDiagram_804A076C.sorted_names[j]) != NULL) &&\n"
        "                ((totals[mnDiagram_804A076C.sorted_names[max_idx]] <\n"
        "                  totals[mnDiagram_804A076C.sorted_names[j]]) ||\n"
        "                 ((GetNameText(\n"
        "                       (0, mnDiagram_804A076C.sorted_names[max_idx])) ==\n"
        "                   NULL) &&\n"
        "                  (GetNameText(mnDiagram_804A076C.sorted_names[j]) != NULL))))\n"
        "            {\n"
        "                max_idx = j;\n"
        "            }\n"
        "        }\n"
        "        if (max_idx != i) {\n"
        "            u8* p = &assets->sorted_fighters[max_idx];\n"
        "            u8 temp = *(p += sizeof(mnDiagram_804A0750_t));\n"
        "            while (max_idx > i) {\n"
        "                *p = *(p - 1);\n"
        "                p--;\n"
        "                max_idx--;\n"
        "            }\n"
        "            dst[i] = temp;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _sort_allocator() -> dict:
    return {
        "function": SORT_FUNC,
        "status": "practical-ceiling",
        "terminal_reason": "residual-case-c-source-repair-exhausted",
        "missing_evidence": [],
        "residual_case_c_source_repair": {
            "status": "terminal-current-source-shape-ceiling",
            "terminal_blocker": "current-source-shape-allocator-ceiling",
        },
    }


def _sort_retained_allocator() -> dict:
    payload = _sort_allocator()
    payload["terminal_reason"] = (
        "retained-frontiers-all-known-frontiers-exhausted/"
        "current-source-shape-ceiling"
    )
    return payload


def _sort_retained(source_file: str | None = None) -> dict:
    frontier = {
        "terminal": True,
        "family_id": "copy-survived-pointer-reset",
        "terminal_reason": "copy-survived pointer-reset repair exhausted",
    }
    if source_file is not None:
        frontier["source_file"] = source_file
    return {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": SORT_FUNC,
                "terminal_frontiers": [frontier],
                "next_frontier": None,
            }
        ],
    }


def _sort_retained_all_known_source_shape(
    *,
    closed_families: list[str] | None = None,
) -> dict:
    exhausted = [
        {"dimension_id": "sort-protected-loss-init-lifetime"},
    ]
    proof = {
        "status": "complete",
        "reason": "no-modeled-source-actionable-frontiers-remain",
        "next_unsupported_source_model": SORT_POST_LOWER_DRIFT_MODEL,
        "source_spans": [
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2100,
                "confidence": "source-hunk",
            }
        ],
        "source_family_synthesis": {
            "status": "synthesis-exhausted",
            "evidence_status": "artifact-score-rows",
            "exhausted_dimensions": exhausted,
            "source_hunks_by_candidate": [
                {
                    "candidate_id": "post-meta-source-family-sort-protected-loss",
                    "dimension_id": "sort-protected-loss-init-lifetime",
                    "source_hunks": [
                        {
                            "hunk_id": "lower-drift-h0",
                            "old_start": 2100,
                            "old_lines": ["old"],
                            "new_start": 2100,
                            "new_lines": ["new"],
                        }
                    ],
                }
            ],
        },
        "exhausted_dimensions": exhausted,
    }
    if closed_families is not None:
        proof["suppressed_families"] = closed_families
    return {
        "status": "all-known-frontiers-exhausted",
        "functions": [
            {
                "function": SORT_FUNC,
                "terminal_frontiers": [
                    {
                        "terminal": True,
                        "family_id": "post-ceiling-source-model-proof",
                        "terminal_reason": (
                            "post-ceiling-gpr-case-c-source-model-synthesis-exhausted"
                        ),
                    }
                ],
                "next_frontier": None,
                "meta_ceiling": {
                    "kind": "retained-frontiers-meta-ceiling",
                    "function": SORT_FUNC,
                    "status": "terminal-current-source-shape-ceiling",
                    "terminal_reason": (
                        "retained-frontiers-all-known-frontiers-exhausted/"
                        "current-source-shape-ceiling"
                    ),
                    "next_frontier": None,
                    "terminal_proof": proof,
                },
            }
        ],
    }


def _draw_retained_all_known_current_ceiling_family(
    *,
    closed_families: list[str] | None = None,
) -> dict:
    proof = {
        "status": "complete",
        "reason": "no-modeled-source-actionable-frontiers-remain",
        "next_unsupported_source_model": (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL
        ),
        "source_spans": [
            {
                "source_file": "src/melee/mn/mndiagram.c",
                "source_line": 2500,
                "confidence": "source-hunk",
            }
        ],
        "source_family_synthesis": {
            "status": "synthesis-exhausted",
            "evidence_status": "artifact-score-rows",
            "exhausted_dimensions": [
                {
                    "dimension_id": (
                        "draw-post-stack-clean-no-anchor-loop-callsite-"
                        "source-context"
                    )
                }
            ],
            "source_hunks_by_candidate": [
                {
                    "candidate_id": "draw-post-stack-loop-callsite-owner",
                    "dimension_id": (
                        "draw-post-stack-clean-no-anchor-loop-callsite-"
                        "source-context"
                    ),
                    "source_hunks": [{"hunk_id": "loop-callsite-h0"}],
                }
            ],
        },
    }
    if closed_families is not None:
        proof["suppressed_families"] = closed_families
    current_ceiling = {
        "function": FUNC,
        "next_unsupported_source_family": (
            DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
        ),
    }
    return {
        "status": "all-known-frontiers-exhausted",
        "current_ceiling": current_ceiling,
        "functions": [
            {
                "function": FUNC,
                "terminal_frontiers": [
                    {
                        "terminal": True,
                        "family_id": "post-ceiling-source-model-proof",
                        "terminal_reason": (
                            "post-ceiling-fpr-expression-source-model-"
                            "synthesis-exhausted"
                        ),
                    }
                ],
                "next_frontier": None,
                "meta_ceiling": {
                    "kind": "retained-frontiers-meta-ceiling",
                    "function": FUNC,
                    "status": "terminal-current-source-shape-ceiling",
                    "terminal_reason": (
                        "retained-frontiers-all-known-frontiers-exhausted/"
                        "current-source-shape-ceiling"
                    ),
                    "current_ceiling": current_ceiling,
                    "next_frontier": None,
                    "terminal_proof": proof,
                },
            }
        ],
    }


def _with_post_ceiling_continuation_closed(
    retained: dict,
    *,
    route_signatures: list[str] | None = None,
    terminal_kind: str = "post-ceiling-baseline-escape-continuation",
    terminal_reason: str = (
        "post-ceiling-continuation-routes-exhausted/current-source-shape-ceiling"
    ),
) -> dict:
    copied = json.loads(json.dumps(retained))
    function_entry = copied["functions"][0]
    blockers = [
        {
            "post_ceiling_route_signature": signature,
            "terminal_reason": "transform-family-exhausted",
        }
        for signature in (route_signatures or [])
    ]
    function_entry.setdefault("terminal_frontiers", []).insert(
        0,
        {
            "kind": terminal_kind,
            "family_id": CONTINUATION_FAMILY,
            "status": "source-actionable",
            "terminal_reason": terminal_reason,
            "post_ceiling_route_signatures": route_signatures or [],
            "route_terminal_blockers": blockers,
        },
    )
    function_entry["next_frontier"] = None
    copied["status"] = "all-known-frontiers-exhausted"
    return copied


def _sort_evidence() -> list[dict]:
    return [
        {
            "function": SORT_FUNC,
            "status": "ok",
            "window_order_probe_diagnostics": {"listed_source_probes": 2},
        },
        {
            "function": SORT_FUNC,
            "status": "blocked",
            "stop_reason": "no-coupled-probes",
            "blocked_reason": "coupled mode needs >=2 bindable missing virtuals",
            "in_place_recolor": {"status": "insufficient-source-bindings"},
        },
        {
            "function": SORT_FUNC,
            "status": "ok",
            "source": "src/melee/mn/mndiagram.c",
            "copy_survived_repair": {
                "status": "terminal-blocker",
                "from_virtual": 34,
                "to_virtual": 41,
            },
        },
        {
            "function": SORT_FUNC,
            "virtuals": {"34": 27, "44": 25},
        },
    ]


def _target_score(matched: int = 0) -> dict:
    return {
        "targeted": 2,
        "matched": matched,
        "virtual_distance": 2 - matched,
        "virtuals": {
            "34": {"expected": 27, "actual": 27 if matched else 24},
            "44": {"expected": 25, "actual": 25 if matched > 1 else 28},
        },
    }


def _draw_route_expression_score(
    *,
    candidate_id: str,
) -> dict:
    if candidate_id == "post-ceiling-paired-offset-block":
        virtuals = {
            "32": {"expected": 28, "actual": 26, "candidate_virtual": 33},
            "37": {"expected": 26, "actual": 28, "candidate_virtual": 48},
            "46": {"expected": 26, "actual": 1, "candidate_virtual": 46},
        }
    else:
        virtuals = {
            "32": {"expected": 28, "actual": 26, "candidate_virtual": 33},
            "37": {"expected": 26, "actual": 28, "candidate_virtual": 37},
            "46": {"expected": 26, "actual": 1, "candidate_virtual": 46},
        }
    return {
        "matched": 0,
        "targeted": 3,
        "virtual_distance": 3,
        "virtuals": virtuals,
    }


def _draw_route_signature(
    *,
    candidate_id: str,
    source_path: Path,
    pcdump_path: Path,
) -> str:
    if candidate_id == "post-ceiling-paired-offset-block":
        force = {"33": 28, "48": 26, "46": 26}
        orders = [[33, 48]]
    else:
        force = {"33": 28, "37": 26, "46": 26}
        orders = [[33, 46]]
    signature = pbe._post_ceiling_route_signature(
        route="retained-source-select-order-repair",
        function=FUNC,
        class_id=1,
        target_orders=orders,
        final_force=force,
        source_file=str(source_path),
        pcdump=str(pcdump_path),
    )
    assert signature is not None
    return signature


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_source_resolution_uses_documented_priority(tmp_path: Path) -> None:
    allocator_source = tmp_path / "allocator.c"
    expression_source = tmp_path / "expression.c"
    retained_source = tmp_path / "retained.c"
    for path in (allocator_source, expression_source, retained_source):
        path.write_text(_source(), encoding="utf-8")

    resolved = resolve_baseline_source_path(
        repo_root=tmp_path,
        function=FUNC,
        allocator_ceiling=_allocator(str(allocator_source)),
        expression_interferer=_expression(str(expression_source)),
        retained_frontiers=_retained(str(retained_source)),
    )

    assert resolved == allocator_source.resolve()


def test_generation_emits_novel_post_ceiling_families_and_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "probes"

    payload = generate_baseline_escape_candidate_files(
        _source(),
        function=FUNC,
        allocator_ceiling=_allocator(),
        expression_interferer=_expression(),
        retained_frontiers=_retained(),
        output_dir=out_dir,
        max_candidates=8,
        validation_options={
            "function": FUNC,
            "source_function": FUNC,
            "target": "target.json",
            "cflags_from": "src/melee/mn/mndiagram.c",
            "expression_baseline": "baseline.c",
            "expression_source": "expression.c",
        },
    )

    assert payload["status"] == "generated"
    assert set(payload["families"]) == {
        "post_ceiling_statement_grouping",
        "post_ceiling_paired_owner_baseline",
        "post_ceiling_call_temp_materialization",
    }
    assert payload["candidate_count"] == 3
    for candidate in payload["candidates"]:
        assert Path(candidate["path"]).is_file()
        assert candidate["source_hunks"]
        assert candidate["novelty_reason"]
        assert candidate["overlap_blockers"] == []
        command = candidate["validation_metadata"]["score_source_command_hint"]
        assert "--target target.json" in command
        assert "--expression-baseline baseline.c" in command
        assert "--expression-source expression.c" in command


def test_score_classification_reports_expression_progress() -> None:
    generated = generate_baseline_escape_candidates(
        _source(),
        function=FUNC,
        allocator_ceiling=_allocator(),
        expression_interferer=_expression(),
        retained_frontiers=_retained(),
    )
    candidate_id = generated["candidates"][0]["candidate_id"]

    classified = classify_baseline_escape_scores(
        [{"candidate_id": candidate_id, "expression_score": _expression_score(1)}],
        generated_candidate_ids=[candidate_id],
    )

    assert classified["progress_count"] == 1
    assert classified["candidates"][0]["classification"] == "expression-progress"


def test_all_scored_without_expression_progress_emits_terminal() -> None:
    generated = generate_baseline_escape_candidates(
        _source(),
        function=FUNC,
        allocator_ceiling=_allocator(),
        expression_interferer=_expression(),
        retained_frontiers=_retained(),
    )
    scores = [
        {
            "candidate_id": candidate["candidate_id"],
            "expression_score": _expression_score(0),
            "structural_guard": {"accepted": True},
        }
        for candidate in generated["candidates"]
    ]

    scored = generate_baseline_escape_candidates(
        _source(),
        function=FUNC,
        allocator_ceiling=_allocator(),
        expression_interferer=_expression(),
        retained_frontiers=_retained(),
        score_payloads=scores,
    )

    assert scored["status"] == "terminal"
    terminal = scored["terminal_summary"]
    assert terminal["terminal_reason"] == TERMINAL_REASON
    assert terminal["candidate_count"] == len(generated["candidates"])
    assert terminal["final_force_phys"] == {"37": 26, "32": 28, "46": 26}
    assert terminal["target_anchors"]


def test_closed_draw_continuation_routes_emit_final_synthesis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    generated = generate_baseline_escape_candidates(
        _source(),
        function=FUNC,
        allocator_ceiling=_allocator(),
        expression_interferer=_expression(),
        retained_frontiers=_retained(),
    )
    scores = []
    route_signatures = []
    for candidate in generated["candidates"]:
        candidate_id = candidate["candidate_id"]
        row = {
            "candidate_id": candidate_id,
            "expression_score": _draw_route_expression_score(
                candidate_id=candidate_id,
            ),
            "structural_guard": {"accepted": True},
        }
        if candidate_id in {
            "post-ceiling-digit-anim-callarg-block",
            "post-ceiling-paired-offset-block",
        }:
            source_path = tmp_path / f"{candidate_id}.c"
            pcdump_path = tmp_path / f"{candidate_id}.pcdump.txt"
            source_path.write_text(_source(), encoding="utf-8")
            pcdump_path.write_text("pcdump", encoding="utf-8")
            row["source_retained"] = str(source_path)
            row["pcdump_path"] = str(pcdump_path)
            route_signatures.append(
                _draw_route_signature(
                    candidate_id=candidate_id,
                    source_path=source_path,
                    pcdump_path=pcdump_path,
                )
            )
        scores.append(row)

    def fake_first_divergence(pcdump_path, *args, **kwargs):
        if "paired-offset" in str(pcdump_path):
            return {
                "status": "ok",
                "fact": {"class_id": 1, "ig_idx": 48, "case": "C"},
                "source": {"source_expression": "fsubs f48,f46,f33"},
            }
        return {
            "status": "ok",
            "fact": {"class_id": 1, "ig_idx": 46, "case": "C"},
            "source": {"source_expression": "fsubs f46,f45,f33"},
        }

    monkeypatch.setattr(pbe, "_first_divergence_for_candidate", fake_first_divergence)

    payload = generate_baseline_escape_candidates(
        _source(),
        function=FUNC,
        allocator_ceiling=_allocator(),
        expression_interferer=_expression(),
        retained_frontiers=_with_post_ceiling_continuation_closed(
            _retained(),
            route_signatures=route_signatures,
        ),
        score_payloads=scores,
    )

    assert payload["status"] == "terminal"
    assert "post_ceiling_continuation_summary" not in payload
    final = payload["post_ceiling_final_summary"]
    assert final["kind"] == FINAL_TERMINAL_KIND
    assert final["terminal_reason"] == FINAL_TERMINAL_REASON
    assert final["final_force_phys"] == {"37": 26, "32": 28, "46": 26}
    assert CONTINUATION_FAMILY in final["closed_families"]
    assert set(final["current_route_signatures"]) == set(route_signatures)
    assert final["residual_blocker_targets"]
    discovery = final["post_ceiling_source_family_discovery"]
    assert discovery["status"] == "source-actionable"
    assert discovery["kind"] == "post-ceiling-source-family-discovery"
    assert discovery["final_force_phys"] == {"37": 26, "32": 28, "46": 26}
    assert {
        neighborhood["neighborhood_id"]
        for neighborhood in discovery["source_neighborhoods"]
    } == {
        "draw-col-offset-product",
        "draw-row-offset-scale",
        "draw-digit-callarg",
    }
    assert {
        probe["probe_id"]
        for probe in discovery["probes"]
    } == {
        "post-ceiling-source-family-draw-col-cast-product-local",
        "post-ceiling-source-family-draw-row-translation-scale-split",
        "post-ceiling-source-family-draw-digit-callarg-fsubs-temp",
    }
    assert all(probe["source_hunks"] for probe in discovery["probes"])
    assert any(
        row["candidate_id"] == "post-ceiling-digit-anim-callarg-block"
        and row["pcdump_path"]
        and row["expression_score"]["targeted"] == 3
        for row in discovery["retained_scored_probes"]
    )


def test_stale_draw_route_closure_does_not_suppress_fresh_route(
    tmp_path: Path,
    monkeypatch,
) -> None:
    generated = generate_baseline_escape_candidates(
        _source(),
        function=FUNC,
        allocator_ceiling=_allocator(),
        expression_interferer=_expression(),
        retained_frontiers=_retained(),
    )
    scores = []
    for candidate in generated["candidates"]:
        candidate_id = candidate["candidate_id"]
        row = {
            "candidate_id": candidate_id,
            "expression_score": _draw_route_expression_score(
                candidate_id=candidate_id,
            ),
        }
        if candidate_id == "post-ceiling-digit-anim-callarg-block":
            source_path = tmp_path / f"{candidate_id}.c"
            pcdump_path = tmp_path / f"{candidate_id}.pcdump.txt"
            source_path.write_text(_source(), encoding="utf-8")
            pcdump_path.write_text("pcdump", encoding="utf-8")
            row["source_retained"] = str(source_path)
            row["pcdump_path"] = str(pcdump_path)
        scores.append(row)

    monkeypatch.setattr(
        pbe,
        "_first_divergence_for_candidate",
        lambda *args, **kwargs: {
            "status": "ok",
            "fact": {"class_id": 1, "ig_idx": 46, "case": "C"},
            "source": {"source_expression": "fsubs f46,f45,f33"},
        },
    )

    payload = generate_baseline_escape_candidates(
        _source(),
        function=FUNC,
        allocator_ceiling=_allocator(),
        expression_interferer=_expression(),
        retained_frontiers=_with_post_ceiling_continuation_closed(
            _retained(),
            route_signatures=["stale-route-signature"],
        ),
        score_payloads=scores,
    )

    assert payload["status"] == "actionable"
    assert "post_ceiling_final_summary" not in payload
    assert payload["post_ceiling_continuation_summary"]["status"] == "source-actionable"


def test_scored_draw_source_family_suppresses_stale_continuation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    generated = generate_baseline_escape_candidates(
        _source(),
        function=FUNC,
        allocator_ceiling=_allocator(),
        expression_interferer=_expression(),
        retained_frontiers=_retained(),
    )
    source_family_ids = [
        "post-ceiling-source-family-draw-col-cast-product-local",
        "post-ceiling-source-family-draw-row-translation-scale-split",
        "post-ceiling-source-family-draw-digit-callarg-fsubs-temp",
    ]
    scores = []
    for candidate_id in [
        *(candidate["candidate_id"] for candidate in generated["candidates"]),
        *source_family_ids,
    ]:
        source_path = tmp_path / f"{candidate_id}.c"
        pcdump_path = tmp_path / f"{candidate_id}.pcdump.txt"
        source_path.write_text(_source(), encoding="utf-8")
        pcdump_path.write_text("pcdump", encoding="utf-8")
        scores.append(
            {
                "candidate_id": candidate_id,
                "expression_score": _expression_score(0),
                "source_retained": str(source_path),
                "pcdump_path": str(pcdump_path),
                "structural_guard": {"accepted": True},
            }
        )

    def fail_first_divergence(*args, **kwargs):
        raise AssertionError("stale continuation routes must not be re-emitted")

    monkeypatch.setattr(pbe, "_first_divergence_for_candidate", fail_first_divergence)

    payload = generate_baseline_escape_candidates(
        _source(),
        function=FUNC,
        allocator_ceiling=_allocator(),
        expression_interferer=_expression(),
        retained_frontiers=_with_post_ceiling_continuation_closed(
            _retained(),
            route_signatures=["stale-route-signature"],
        ),
        score_payloads=scores,
    )

    assert payload["status"] == "terminal"
    assert "post_ceiling_continuation_summary" not in payload
    final = payload["post_ceiling_final_summary"]
    discovery = final["post_ceiling_source_family_discovery"]
    assert discovery["status"] == "terminal"
    assert discovery["candidate_count"] == 0
    assert {row["candidate_id"] for row in discovery["retained_scored_probes"]} >= set(
        source_family_ids
    )
    assert {
        row["exhaustion_reason"]
        for row in discovery["exhausted_dimensions"]
        if row["dimension_id"].startswith("draw-")
    } == {"retained-source-family-scored-no-progress"}


def test_unsigned_mixed_continuation_route_prevents_final_synthesis(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "draw.c"
    pcdump_path = tmp_path / "draw.pcdump.txt"
    source_path.write_text(_source(), encoding="utf-8")
    pcdump_path.write_text("pcdump", encoding="utf-8")
    signature = _draw_route_signature(
        candidate_id="post-ceiling-digit-anim-callarg-block",
        source_path=source_path,
        pcdump_path=pcdump_path,
    )
    evidence = {
        "retained_frontiers": {
            "status": "all-known-frontiers-exhausted",
            "next_frontier_present": False,
            "closed_families": [CONTINUATION_FAMILY],
            "terminal_frontiers": [
                {
                    "family_id": CONTINUATION_FAMILY,
                    "kind": "post-ceiling-baseline-escape-continuation",
                    "post_ceiling_route_signatures": [signature],
                }
            ],
        }
    }
    continuation_summary = {
        "status": "source-actionable",
        "function": FUNC,
        "class_id": 1,
        "ranked_candidates": [
            {
                "candidate_id": "post-ceiling-digit-anim-callarg-block",
                "candidate_force_phys": {"33": 28, "37": 26, "46": 26},
                "continuation": {
                    "route": "retained-source-select-order-repair",
                    "target_orders": [[33, 46]],
                    "source_retained": str(source_path),
                    "pcdump_path": str(pcdump_path),
                },
            },
            {
                "candidate_id": "fresh-coalesce",
                "candidate_force_phys": {"33": 28, "37": 26, "46": 26},
                "continuation": {
                    "route": "retained-coalesce-search",
                    "target_pairs": [[46, 37]],
                    "source_retained": str(source_path),
                    "pcdump_path": str(pcdump_path),
                },
            },
        ],
    }

    assert not pbe._continuation_routes_closed_by_retained(
        evidence,
        continuation_summary,
    )


def test_cli_smoke_writes_probes_from_artifact_source_resolution(
    tmp_path: Path,
) -> None:
    source = tmp_path / "retained.c"
    source.write_text(_source(), encoding="utf-8")
    allocator = _write_json(tmp_path / "allocator.json", _allocator(str(source)))
    expression = _write_json(tmp_path / "expression.json", _expression())
    retained = _write_json(tmp_path / "retained.json", _retained())
    out_dir = tmp_path / "out"

    result = CliRunner().invoke(
        search_app,
        [
            "baseline-escape",
            "--function",
            FUNC,
            "--allocator-ceiling-json",
            str(allocator),
            "--expression-interferer-json",
            str(expression),
            "--retained-frontiers-json",
            str(retained),
            "--target",
            str(tmp_path / "target.json"),
            "--cflags-from",
            "src/melee/mn/mndiagram.c",
            "--expression-baseline",
            str(tmp_path / "baseline.c"),
            "--write-probes",
            str(out_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "generated"
    assert payload["source_file"] == str(source.resolve())
    assert Path(payload["candidates"][0]["path"]).is_file()


def test_sort_generation_uses_residual_case_c_and_supplemental_evidence() -> None:
    payload = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence(),
    )

    assert payload["status"] == "generated"
    assert payload["source_function"] == SORT_SOURCE_FUNC
    assert set(payload["families"]) == {
        "post_ceiling_sort_address_value_pair",
        "post_ceiling_sort_loop_shape",
        "post_ceiling_sort_swap_materialization",
    }
    assert payload["evidence"]["supplemental_evidence"]["kinds"] == [
        "coalesce",
        "node-set",
        "select-order",
        "target",
    ]
    assert payload["evidence"]["final_force_phys"] == {"34": 27, "44": 25}


def test_sort_accepts_retained_frontiers_all_known_practical_ceiling() -> None:
    payload = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_retained_allocator(),
        retained_frontiers=_sort_retained_all_known_source_shape(),
        supplemental_evidence=[_sort_evidence()[-1]],
    )

    assert payload["evidence"]["ready"] is True
    assert "select-order-evidence" not in payload["evidence"]["missing_evidence"]
    assert "node-set-evidence" not in payload["evidence"]["missing_evidence"]
    assert "coalesce-evidence" not in payload["evidence"]["missing_evidence"]
    assert not (
        payload["status"] == "blocked"
        and payload.get("reason")
        == "required post-ceiling terminal evidence is incomplete"
    )
    assert payload["evidence"]["retained_source_model_proof"][
        "next_unsupported_source_model"
    ] == SORT_POST_LOWER_DRIFT_MODEL


def test_draw_retained_source_model_summary_preserves_current_ceiling_family() -> None:
    payload = generate_baseline_escape_candidates(
        _source(),
        function=FUNC,
        allocator_ceiling=_allocator(),
        expression_interferer=_expression(),
        retained_frontiers=_draw_retained_all_known_current_ceiling_family(),
    )

    proof = payload["evidence"]["retained_source_model_proof"]
    assert proof["next_unsupported_source_model"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_MODEL
    )
    assert proof["next_unsupported_source_family"] == (
        DRAW_POST_STACK_LOOP_CALLSITE_SOURCE_CONTEXT_FINAL_FAMILY
    )


def test_sort_all_known_exhausted_returns_terminal_source_model_summary_when_no_supported_escape() -> None:
    local_families = [
        "post_ceiling_sort_address_value_pair",
        "post_ceiling_sort_loop_shape",
        "post_ceiling_sort_swap_materialization",
    ]
    payload = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_retained_allocator(),
        retained_frontiers=_sort_retained_all_known_source_shape(
            closed_families=local_families,
        ),
        supplemental_evidence=[_sort_evidence()[-1]],
    )

    assert payload["status"] == "terminal"
    assert payload["candidate_count"] == 0
    final = payload["post_ceiling_final_summary"]
    assert final["kind"] == FINAL_TERMINAL_KIND
    assert final["terminal_reason"] == FINAL_TERMINAL_REASON
    assert final["next_unsupported_source_model"] == SORT_POST_LOWER_DRIFT_MODEL
    assert final["source_model_proof"]["exhausted_dimensions"] == [
        {"dimension_id": "sort-protected-loss-init-lifetime"}
    ]


def test_sort_source_resolution_does_not_use_other_retained_function(
    tmp_path: Path,
) -> None:
    draw_source = tmp_path / "draw.c"
    sort_source = tmp_path / "sort.c"
    draw_source.write_text(_source(), encoding="utf-8")
    sort_source.write_text(_sort_source(), encoding="utf-8")
    retained = _retained(str(draw_source))
    retained["functions"].insert(
        0,
        {
            "function": SORT_FUNC,
            "terminal_frontiers": [{"family_id": "copy-survived-pointer-reset"}],
            "next_frontier": None,
        },
    )

    resolved = resolve_baseline_source_path(
        repo_root=tmp_path,
        function=SORT_FUNC,
        retained_frontiers=retained,
        supplemental_evidence=[{"function": SORT_FUNC, "source": str(sort_source)}],
    )

    assert resolved == sort_source.resolve()


def test_sort_target_score_progress_and_terminal_reason() -> None:
    generated = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence(),
    )
    candidate_id = generated["candidates"][0]["candidate_id"]

    classified = classify_baseline_escape_scores(
        [{"candidate_id": candidate_id, "target_score": _target_score(1)}],
        generated_candidate_ids=[candidate_id],
        function=SORT_FUNC,
    )

    assert classified["progress_count"] == 1
    assert classified["candidates"][0]["classification"] == "target-progress"

    terminal = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence(),
        score_payloads=[
            {
                "candidate_id": candidate["candidate_id"],
                "target_score": _target_score(0),
                "structural_guard": {"accepted": True},
            }
            for candidate in generated["candidates"]
        ],
    )

    assert terminal["status"] == "terminal"
    assert terminal["terminal_summary"]["kind"] == SORT_TERMINAL_KIND
    assert terminal["terminal_summary"]["terminal_reason"] == (
        "no-post-ceiling-sort-source-family/current-source-shape-ceiling"
    )
    assert terminal["terminal_summary"]["best_target_targeted"] == 2


def test_sort_terminal_accepts_scorer_pcdump_paths_as_candidate_ids() -> None:
    generated = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence(),
    )

    terminal = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence(),
        score_payloads=[
            {
                "pcdump_path": f"/tmp/{candidate['candidate_id']}.pcdump.txt",
                "target_score": _target_score(0),
            }
            for candidate in generated["candidates"]
        ],
    )

    assert terminal["status"] == "terminal"
    assert terminal["score_classification"]["all_generated_scored"] is True


def test_sort_terminal_scores_emit_select_order_continuation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    generated = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence(),
    )
    scores = []
    for candidate in generated["candidates"]:
        stem = tmp_path / candidate["candidate_id"]
        (stem.with_suffix(".c")).write_text(_sort_source(), encoding="utf-8")
        pcdump = tmp_path / f"{candidate['candidate_id']}.pcdump.txt"
        pcdump.write_text("pcdump", encoding="utf-8")
        scores.append({"pcdump_path": str(pcdump), "target_score": _target_score(0)})

    def fake_first_divergence(*args, force_phys, **kwargs):
        assert force_phys == {34: 27, 44: 25}
        return {
            "status": "ok",
            "fact": {
                "class_id": 0,
                "ig_idx": 44,
                "case": "C",
                "baseline_reg": 27,
                "target_reg": 25,
                "local_target": "shift simplify order",
            },
            "source": {
                "source_kind": "implicit-temp",
                "source_expression": "add r44,r51,r34",
            },
        }

    monkeypatch.setattr(pbe, "_first_divergence_for_candidate", fake_first_divergence)

    payload = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence(),
        score_payloads=scores,
    )

    assert payload["status"] == "actionable"
    summary = payload["post_ceiling_continuation_summary"]
    assert summary["status"] == "source-actionable"
    route = summary["ranked_candidates"][0]["continuation"]
    assert route["route"] == "retained-source-select-order-repair"
    assert route["target_orders"] == [[34, 44]]
    assert "debug select-order-search" in route["command"]
    assert "--target 'r34<r44'" in route["command"]


def test_sort_final_synthesis_preserves_force_map_from_scores(monkeypatch) -> None:
    generated = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence()[:3],
    )
    assert generated["evidence"]["final_force_phys"] == {}
    scores = [
        {
            "candidate_id": candidate["candidate_id"],
            "target_score": _target_score(0),
            "structural_guard": {"accepted": True},
        }
        for candidate in generated["candidates"]
    ]

    def fail_first_divergence(*args, **kwargs):
        raise AssertionError("closed continuation routes must not be re-emitted")

    monkeypatch.setattr(pbe, "_first_divergence_for_candidate", fail_first_divergence)

    payload = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_with_post_ceiling_continuation_closed(
            _sort_retained(),
            terminal_kind=CONTINUATION_TERMINAL_KIND,
            terminal_reason=CONTINUATION_TERMINAL_REASON,
        ),
        supplemental_evidence=_sort_evidence()[:3],
        score_payloads=scores,
    )

    assert payload["status"] == "terminal"
    assert "post_ceiling_continuation_summary" not in payload
    assert payload["evidence"]["final_force_phys"] == {"34": 27, "44": 25}
    assert payload["terminal_summary"]["final_force_phys"] == {"34": 27, "44": 25}
    final = payload["post_ceiling_final_summary"]
    assert final["kind"] == FINAL_TERMINAL_KIND
    assert final["final_force_phys"] == {"34": 27, "44": 25}
    assert final["residual_blocker_targets"] == [
        {
            "virtual": 34,
            "expected": 27,
            "actual": 24,
            "matched": False,
            "score_source": "target_score",
        },
        {
            "virtual": 44,
            "expected": 25,
            "actual": 28,
            "matched": False,
            "score_source": "target_score",
        },
    ]
    discovery = final["post_ceiling_source_family_discovery"]
    assert discovery["status"] == "source-actionable"
    assert discovery["final_force_phys"] == {"34": 27, "44": 25}
    assert {
        neighborhood["neighborhood_id"]
        for neighborhood in discovery["source_neighborhoods"]
    } == {
        "sort-init-pointer-walk",
        "sort-max-idx-indexed-byte",
        "sort-call-return-copy",
        "sort-swap-materialization",
    }
    assert {
        probe["probe_id"]
        for probe in discovery["probes"]
    } == {
        "post-ceiling-source-family-sort-init-indexed-write",
        "post-ceiling-source-family-sort-indexed-byte-cache",
        "post-ceiling-source-family-sort-call-return-copy-local",
        "post-ceiling-source-family-sort-swap-slot-lvalue",
    }
    call_return_probe = next(
        probe
        for probe in discovery["probes"]
        if probe["probe_id"]
        == "post-ceiling-source-family-sort-call-return-copy-local"
    )
    assert "IG34->r27" in call_return_probe["expected_effect"]
    assert "IG44->r25" in call_return_probe["expected_effect"]
    assert "post_ceiling_j_text_copy" in json.dumps(
        call_return_probe["source_hunks"]
    )
    assert all(probe["source_hunks"] for probe in discovery["probes"])
    assert any(
        row["candidate_id"] == "post-ceiling-sort-init-pointer-walk"
        and row["target_score"]["targeted"] == 2
        for row in discovery["retained_scored_probes"]
    )


def test_write_probes_materializes_source_family_discovery_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    generated = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence()[:3],
    )
    scores = [
        {
            "candidate_id": candidate["candidate_id"],
            "target_score": _target_score(0),
            "structural_guard": {"accepted": True},
        }
        for candidate in generated["candidates"]
    ]
    out_dir = tmp_path / "baseline_escape"

    def fail_first_divergence(*args, **kwargs):
        raise AssertionError("closed continuation routes must not be re-emitted")

    monkeypatch.setattr(pbe, "_first_divergence_for_candidate", fail_first_divergence)

    payload = generate_baseline_escape_candidate_files(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_with_post_ceiling_continuation_closed(
            _sort_retained(),
            terminal_kind=CONTINUATION_TERMINAL_KIND,
            terminal_reason=CONTINUATION_TERMINAL_REASON,
        ),
        supplemental_evidence=_sort_evidence()[:3],
        score_payloads=scores,
        output_dir=out_dir,
        validation_options={
            "function": SORT_FUNC,
            "source_function": SORT_SOURCE_FUNC,
            "target": "sort-target.json",
            "cflags_from": "src/melee/mn/mndiagram.c",
        },
    )

    discovery = payload["post_ceiling_source_family_discovery"]
    call_return = next(
        probe
        for probe in discovery["candidates"]
        if probe["candidate_id"]
        == "post-ceiling-source-family-sort-call-return-copy-local"
    )
    retained = Path(call_return["source_retained"])
    assert retained.is_file()
    assert retained == Path(call_return["candidate_path"])
    assert retained.parent.name == "source-family"
    assert retained.name == "post-ceiling-source-family-sort-call-return-copy-local.c"
    assert len(retained.name.encode("utf-8")) <= 180
    retained_text = retained.read_text(encoding="utf-8")
    assert "post_ceiling_j_text_copy" in retained_text
    assert "void mnDiagram_8023FC28(void)" in retained_text
    assert "source_text" not in call_return
    command = call_return["validation_metadata"]["score_source_command_hint"]
    assert str(retained) in command
    assert "{candidate_path}" not in command


def test_scored_sort_source_family_progress_plateau_terminalizes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    generated = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence()[:3],
    )
    plateau_score = _target_score(0)
    plateau_score["matched"] = 1
    plateau_score["virtual_distance"] = 1
    plateau_score["virtuals"]["34"]["actual"] = None
    plateau_score["virtuals"]["34"]["matched"] = False
    plateau_score["virtuals"]["44"]["actual"] = 25
    plateau_score["virtuals"]["44"]["matched"] = True
    plateau_score["wrong"] = [
        {"virtual": 34, "expected": 27, "actual": None}
    ]
    source_family_scores = {
        "post-ceiling-source-family-sort-init-indexed-write": _target_score(0),
        "post-ceiling-source-family-sort-indexed-byte-cache": plateau_score,
        "post-ceiling-source-family-sort-call-return-copy-local": plateau_score,
        "post-ceiling-source-family-sort-swap-slot-lvalue": _target_score(0),
    }
    scores = []
    for candidate_id in [
        *(candidate["candidate_id"] for candidate in generated["candidates"]),
        *source_family_scores,
    ]:
        source_path = tmp_path / f"{candidate_id}.c"
        pcdump_path = tmp_path / f"{candidate_id}.pcdump.txt"
        source_path.write_text(_sort_source(), encoding="utf-8")
        pcdump_path.write_text("pcdump", encoding="utf-8")
        scores.append(
            {
                "candidate_id": candidate_id,
                "target_score": source_family_scores.get(
                    candidate_id,
                    _target_score(0),
                ),
                "source_retained": str(source_path),
                "pcdump_path": str(pcdump_path),
                "structural_guard": {"accepted": True},
            }
        )

    def fail_first_divergence(*args, **kwargs):
        raise AssertionError("source-family progress plateau should terminalize")

    monkeypatch.setattr(pbe, "_first_divergence_for_candidate", fail_first_divergence)

    payload = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence()[:3],
        score_payloads=scores,
    )

    assert payload["score_classification"]["progress_count"] == 2
    assert payload["status"] == "terminal"
    assert "post_ceiling_continuation_summary" not in payload
    assert payload["terminal_summary"]["kind"] == SORT_TERMINAL_KIND
    assert payload["terminal_summary"]["source_family_progress_plateau"]["kind"] == (
        "post-ceiling-source-family-progress-plateau"
    )
    plateau = payload["post_ceiling_source_family_plateau_summary"]
    assert plateau["kind"] == "post-ceiling-source-family-progress-plateau"
    assert plateau["best_candidate_id"] == (
        "post-ceiling-source-family-sort-call-return-copy-local"
    )
    assert plateau["source_family_residual_blocker_targets"] == [
        {
            "virtual": 34,
            "expected": 27,
            "actual": None,
            "matched": False,
            "score_source": "target_score",
        }
    ]
    final = payload["post_ceiling_final_summary"]
    assert final["terminal_summary_kind"] == SORT_TERMINAL_KIND
    discovery = payload["post_ceiling_source_family_discovery"]
    assert discovery["status"] == "terminal"
    assert discovery["candidate_count"] == 0
    assert {
        row["exhaustion_reason"]
        for row in discovery["exhausted_dimensions"]
        if row["dimension_id"].startswith("sort-")
    } == {"retained-source-family-scored-no-progress"}


def test_sort_source_family_plateau_keeps_fresh_top_level_progress_actionable(
    tmp_path: Path,
) -> None:
    generated = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence()[:3],
    )
    plateau_score = _target_score(0)
    plateau_score["matched"] = 1
    plateau_score["virtual_distance"] = 1
    plateau_score["virtuals"]["34"]["actual"] = None
    plateau_score["virtuals"]["34"]["matched"] = False
    plateau_score["virtuals"]["44"]["actual"] = 25
    plateau_score["virtuals"]["44"]["matched"] = True
    source_family_scores = {
        "post-ceiling-source-family-sort-init-indexed-write": _target_score(0),
        "post-ceiling-source-family-sort-indexed-byte-cache": plateau_score,
        "post-ceiling-source-family-sort-call-return-copy-local": plateau_score,
        "post-ceiling-source-family-sort-swap-slot-lvalue": _target_score(0),
    }
    scores = []
    top_progress_id = generated["candidates"][0]["candidate_id"]
    for candidate_id in [
        *(candidate["candidate_id"] for candidate in generated["candidates"]),
        *source_family_scores,
    ]:
        source_path = tmp_path / f"{candidate_id}.c"
        pcdump_path = tmp_path / f"{candidate_id}.pcdump.txt"
        source_path.write_text(_sort_source(), encoding="utf-8")
        pcdump_path.write_text("pcdump", encoding="utf-8")
        scores.append(
            {
                "candidate_id": candidate_id,
                "target_score": (
                    _target_score(1)
                    if candidate_id == top_progress_id
                    else source_family_scores.get(candidate_id, _target_score(0))
                ),
                "source_retained": str(source_path),
                "pcdump_path": str(pcdump_path),
                "structural_guard": {"accepted": True},
            }
        )

    payload = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence()[:3],
        score_payloads=scores,
    )

    assert payload["status"] == "actionable"
    assert "post_ceiling_source_family_plateau_summary" not in payload
    assert "terminal_summary" not in payload


def test_conflicting_score_force_targets_emit_conflict_terminal() -> None:
    generated = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence()[:3],
    )
    scores = []
    for index, candidate in enumerate(generated["candidates"]):
        target_score = _target_score(0)
        if index == 1:
            target_score["virtuals"]["34"]["expected"] = 29
        scores.append(
            {
                "candidate_id": candidate["candidate_id"],
                "target_score": target_score,
                "structural_guard": {"accepted": True},
            }
        )

    payload = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_with_post_ceiling_continuation_closed(
            _sort_retained(),
            terminal_kind=CONTINUATION_TERMINAL_KIND,
            terminal_reason=CONTINUATION_TERMINAL_REASON,
        ),
        supplemental_evidence=_sort_evidence()[:3],
        score_payloads=scores,
    )

    assert payload["status"] == "terminal"
    final = payload["post_ceiling_final_summary"]
    assert final["kind"] == FORCE_CONFLICT_TERMINAL_KIND
    assert final["terminal_blocker"] == "ambiguous-score-force-targets"
    assert final["force_map_conflicts"][0]["virtual"] == 34
    assert "post_ceiling_continuation_summary" not in payload


def test_progress_with_conflicting_force_targets_still_conflict_terminal() -> None:
    generated = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence()[:3],
    )
    scores = []
    for index, candidate in enumerate(generated["candidates"]):
        target_score = _target_score(1 if index == 0 else 0)
        if index == 1:
            target_score["virtuals"]["34"]["expected"] = 29
        scores.append(
            {
                "candidate_id": candidate["candidate_id"],
                "target_score": target_score,
                "structural_guard": {"accepted": True},
            }
        )

    payload = generate_baseline_escape_candidates(
        _sort_source(),
        function=SORT_FUNC,
        allocator_ceiling=_sort_allocator(),
        retained_frontiers=_sort_retained(),
        supplemental_evidence=_sort_evidence()[:3],
        score_payloads=scores,
    )

    assert payload["score_classification"]["progress_count"] == 1
    assert payload["status"] == "terminal"
    assert payload["post_ceiling_final_summary"]["kind"] == (
        FORCE_CONFLICT_TERMINAL_KIND
    )


def test_draw_continuation_reanchors_expression_candidate_virtuals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = tmp_path / "draw.c"
    pcdump = tmp_path / "draw.pcdump.txt"
    source_path.write_text(_source(), encoding="utf-8")
    pcdump.write_text("pcdump", encoding="utf-8")
    captured = {}

    def fake_first_divergence(*args, force_phys, **kwargs):
        captured["force_phys"] = force_phys
        return {
            "status": "ok",
            "fact": {
                "class_id": 1,
                "ig_idx": 46,
                "case": "C",
                "baseline_reg": 1,
                "target_reg": 26,
                "local_target": "shift simplify order",
            },
            "source": {
                "source_kind": "fpr-temp",
                "source_expression": "fsubs f46,f45,f44",
            },
        }

    monkeypatch.setattr(pbe, "_first_divergence_for_candidate", fake_first_divergence)
    rows = classify_baseline_escape_scores(
        [
            {
                "pcdump_path": str(pcdump),
                "expression_score": {
                    "matched": 0,
                    "targeted": 2,
                    "virtuals": {
                        "32": {"expected": 28, "candidate_virtual": 33},
                        "46": {
                            "expected": 26,
                            "candidate_virtual": 46,
                            "baseline_source": {"kind": "first-def"},
                        },
                    },
                },
            }
        ],
        generated_candidate_ids=["draw"],
        function=FUNC,
    )["candidates"]

    summary = analyze_baseline_escape_continuations(
        _source(),
        function=FUNC,
        source_function=FUNC,
        generated_candidates=[{"candidate_id": "draw", "source_retained": str(source_path)}],
        score_rows=rows,
        evidence={"final_force_phys": {"32": 28, "46": 26}},
        validation_options={"function": FUNC},
    )

    assert captured["force_phys"] == {33: 28, 46: 26}
    derivation = summary["ranked_candidates"][0]["force_derivation"]
    assert derivation[0]["source"] == "expression-candidate-virtual"


def test_fpr_case_d_rejects_gpr_looking_split_var(tmp_path: Path) -> None:
    source_path = tmp_path / "draw.c"
    pcdump = tmp_path / "draw.pcdump.txt"
    source_path.write_text(_source(), encoding="utf-8")
    pcdump.write_text("pcdump", encoding="utf-8")

    route = pbe._continuation_route(
        function=FUNC,
        class_id=1,
        pcdump_path=pcdump,
        source_retained=source_path,
        candidate_force_phys={32: 28},
        first_divergence={
            "fact": {
                "case": "D",
                "ig_idx": 32,
                "coalesced_root": 1,
            },
            "source": {
                "var_name": "gobj",
                "confidence": "high",
                "source_confidence": "high",
            },
        },
        suppressed_families=set(),
    )

    assert route["route"] == "retained-coalesce-search"
    assert route["split_var"] is None
    assert "--split-var gobj" not in route["command"]


def test_fpr_stack_load_temp_becomes_continuation_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = tmp_path / "draw.c"
    pcdump = tmp_path / "draw.pcdump.txt"
    source_path.write_text(_source(), encoding="utf-8")
    pcdump.write_text("pcdump", encoding="utf-8")

    monkeypatch.setattr(
        pbe,
        "_first_divergence_for_candidate",
        lambda *args, **kwargs: {
            "status": "ok",
            "fact": {"class_id": 1, "ig_idx": 46, "case": "C", "target_reg": 26},
            "source": {
                "source_kind": "fpr-temp",
                "source_expression": "lfd f46,@1539(r1)",
                "candidate_spans": [],
            },
        },
    )
    rows = classify_baseline_escape_scores(
        [
            {
                "pcdump_path": str(pcdump),
                "expression_score": {
                    "matched": 0,
                    "targeted": 1,
                    "virtuals": {
                        "46": {
                            "expected": 26,
                            "candidate_virtual": 46,
                            "baseline_source": {"kind": "first-def"},
                        }
                    },
                },
            }
        ],
        generated_candidate_ids=["draw"],
        function=FUNC,
    )["candidates"]

    summary = analyze_baseline_escape_continuations(
        _source(),
        function=FUNC,
        source_function=FUNC,
        generated_candidates=[{"candidate_id": "draw", "source_retained": str(source_path)}],
        score_rows=rows,
        evidence={"final_force_phys": {"46": 26}},
        validation_options={"function": FUNC},
    )

    assert summary["status"] == "terminal"
    assert summary["kind"] == CONTINUATION_TERMINAL_KIND
    assert summary["blockers"][0]["blocker"] == "no-source-actionable-route"


def test_missing_candidate_pcdump_is_explicit_continuation_blocker() -> None:
    rows = classify_baseline_escape_scores(
        [{"candidate_id": "draw", "expression_score": _expression_score(0)}],
        generated_candidate_ids=["draw"],
        function=FUNC,
    )["candidates"]

    summary = analyze_baseline_escape_continuations(
        _source(),
        function=FUNC,
        source_function=FUNC,
        generated_candidates=[{"candidate_id": "draw"}],
        score_rows=rows,
        evidence={"final_force_phys": {"37": 26}},
        validation_options={"function": FUNC},
    )

    assert summary["status"] == "terminal"
    assert summary["blockers"][0]["blocker"] == "retained-pcdump-missing"


def test_sort_cli_accepts_repeatable_evidence_json_without_expression(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sort.c"
    source.write_text(_sort_source(), encoding="utf-8")
    allocator = _write_json(tmp_path / "allocator.json", _sort_allocator())
    retained = _write_json(tmp_path / "retained.json", _sort_retained(str(source)))
    evidence_paths = [
        _write_json(tmp_path / f"evidence_{index}.json", payload)
        for index, payload in enumerate(_sort_evidence())
    ]
    out_dir = tmp_path / "out"
    args = [
        "baseline-escape",
        "--function",
        SORT_FUNC,
        "--allocator-ceiling-json",
        str(allocator),
        "--retained-frontiers-json",
        str(retained),
        "--write-probes",
        str(out_dir),
        "--json",
    ]
    for path in evidence_paths:
        args.extend(["--evidence-json", str(path)])

    result = CliRunner().invoke(search_app, args)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["candidate_count"] == 3
    assert len(list(out_dir.glob("*.c"))) == 3
