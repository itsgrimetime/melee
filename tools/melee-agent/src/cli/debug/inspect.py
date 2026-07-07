"""`debug inspect ...` — read, compare, and explain MWCC pcdumps.

Carved out of cli/debug/__init__.py. Contains the inspect command
handlers and their group-private helpers.

Shared helpers (and module-level names the tests patch on the cli.debug
package) still live in cli/debug/__init__.py. They are reached via
call-time (deferred) ``from src.cli.debug import ...`` imports inside
the function bodies -- a load-time import would create a cycle (__init__
imports this module) and would also break ``monkeypatch.setattr(debug_cli,
...)`` semantics, since the patched name must resolve against __init__ at
call time.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import dataclasses
import difflib
import hashlib
import itertools
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Any, Callable, Iterable, Iterator, Mapping, NoReturn, Optional, Sequence

import typer

from .._common import DEFAULT_MELEE_ROOT, console

if TYPE_CHECKING:  # annotation-only; the runtime objects live in cli.debug
    from src.cli.debug import (  # noqa: F401
        DiagnoseForcePhysEntry,
        _ForceVectorEntry,
    )
from ...mwcc_debug import (
    FunctionEvents,
    analyze_function,
    derive_target_from_function,
    find_function,
    format_suggestions,
    parse_hook_events,
    parse_pcdump,
    score_function,
    simulate_function,
    slice_pcdump_to_function,
    suggest,
)
from ...mwcc_debug import candidate_audit
from ...mwcc_debug import cache as pcdump_cache
from ...mwcc_debug import local_safety
from ...mwcc_debug import permuter_remote
from ...mwcc_debug.cast_audit import (
    audit_function_casts,
    crossref_with_asm,
    detect_signedness_mismatches,
    find_call_sites,
)
from ...mwcc_debug.patterns import (
    PATTERNS,
    list_patterns,
)
from ...mwcc_debug.pressure_explorer import HELPER_INLINE_LIFETIME_OPERATORS
from ...mwcc_debug.source_patch import (
    build_decl_order_candidates_for_scope,
    explain_decl_reorder_skip,
    extract_function,
    find_function as find_source_function,
    find_function_definitions,
    get_decl_names_by_scope,
    reorder_decls_in_function_scope,
    transfer_candidate,
)
from ...mwcc_debug.asm_parser import (
    AsmInstruction,
    extract_function as asm_extract_function,
    find_first_def as asm_find_first_def,
    parse_prologue_end as asm_parse_prologue_end,
)
from ...mwcc_debug.iter_match import (
    MatchResult,
    instr_signature,
    match_virtual_for_expected_def,
)
from ...mwcc_debug.diff_capture import (
    CompileFailure,
    _env_with_child_hang_timeout,
    _kill_process_tree,
    _run_with_process_group_timeout,
    read_inspect_input_if_available,
    read_or_compile_input,
    resolve_diff_input,
)
from ...mwcc_debug.diff_report import (
    compare_function_dumps,
    render_text_report,
)
from ...mwcc_debug.temp_scratch import mkdtemp as mwcc_debug_mkdtemp
from ...mwcc_debug.temp_scratch import reaped_scratch_root as mwcc_debug_scratch_root
from ...mwcc_debug.temp_scratch import scratch_path as mwcc_debug_scratch_path
from ...mwcc_debug.frame_reservations import (
    analyze_frame_from_asm_text,
    analyze_frame_from_function,
    analyze_frame_reservations,
    evaluate_frame_transform_probe_results,
    evaluate_stack_home_probe_results,
)
from ...mwcc_debug.frame_taxonomy import classify_frame_taxonomy
from ...mwcc_debug.signature_audit import (
    audit_signature_call_type,
    validate_signature_patches,
)
from ...mwcc_debug.value_numbering import detect_divide_rematerialization_ceiling

__all__ = [
    'PPC_ABI_GPR',
    '_BOOTSTRAP_CALL_KEYWORDS',
    '_BOOTSTRAP_IDENTIFIER_KEYWORDS',
    '_BOOTSTRAP_IDENTIFIER_RE',
    '_BOOTSTRAP_INCLUDE_RE',
    '_BOOTSTRAP_INLINE_RE',
    '_BOOTSTRAP_PERMUTER_ASSERT_DEFINE_RE',
    '_BOOTSTRAP_RAW_ASSERT_DIRECTIVE_RE',
    '_BOOTSTRAP_SOURCE_CALL_RE',
    '_BOOTSTRAP_TARGET_BL_RE',
    '_BOOTSTRAP_TARGET_B_RE',
    '_BOOTSTRAP_TARGET_REL24_RE',
    '_CHECKDIFF_ASM_REG_RE',
    '_CHECKDIFF_NORMALIZE_FN',
    '_CHECKDIFF_STACK_SLOT_RE',
    '_CHECKDIFF_STWU_FRAME_RE',
    '_FORCE_SELECT_ACTIONS',
    '_FORCE_VECTOR_CLASS_NAMES',
    '_FPR_MULTI_SOURCE_OPS',
    '_IDENT_RE',
    '_INT_LITERAL_RE',
    '_PERMUTER_PERM_MACRO_RE',
    '_REGISTER_DIFF_CURRENT_REG_POSITION_SLOP',
    '_SELECT_ORDER_INTERFERENCE_INTENT_KINDS',
    '_SELECT_ORDER_VIRTUAL_OPERAND_RE',
    '_TIEBREAK_MOVE_RE',
    '_TIEBREAK_PAIR_RE',
    '_TIEBREAK_TOKEN_PATTERN',
    '_TIEBREAK_TOKEN_RE',
    '_TIEBREAK_WHATIF_NOTE',
    '_TIEBREAK_WHATIF_REALIZABILITY',
    '_TRACE_COPY_REGISTER_TOKEN_RE',
    '_abi_arg_reg',
    '_abi_hint',
    '_acquire_source_score_repo_lock',
    '_adjust_checkdiff_stack_slots',
    '_append_unique',
    '_asm_instruction_destination',
    '_attach_frame_taxonomy_hint_fields',
    '_attach_frame_transform_validated_verdict',
    '_attach_stack_home_validated_verdict',
    '_attempt_evidence_for_keywords',
    '_basis_to_dict',
    '_bootstrap_base_has_function_declaration',
    '_bootstrap_base_has_macro',
    '_bootstrap_base_has_object_declaration',
    '_bootstrap_base_has_permuter_define',
    '_bootstrap_dependency_context',
    '_bootstrap_enum_constant_defines',
    '_bootstrap_identifier_names',
    '_bootstrap_injected_callee_dependencies',
    '_bootstrap_inline_definition',
    '_bootstrap_macro_blocks',
    '_bootstrap_melee_root_candidates',
    '_bootstrap_resolve_include',
    '_bootstrap_source_calls',
    '_bootstrap_source_function_prototype',
    '_bootstrap_target_calls',
    '_build_force_vector_auto_verify_cmd',
    '_call_symbol_from_operands',
    '_ceiling_recommendations',
    '_checkdiff_asm_body',
    '_checkdiff_env_for_locked_child',
    '_checkdiff_frame_size',
    '_checkdiff_instruction_signature',
    '_classify_decl_candidate_failure',
    '_cluster_entries_by_virtuals',
    '_coalesce_cli_path_arg',
    '_coalesce_generated_local_source_attribution',
    '_coalesce_generated_local_source_cli_payload',
    '_coalesce_primary_force_target',
    '_coalesce_trace_assignment_for_ig',
    '_collect_order_target_inputs',
    '_copy_propagation_assigned_local',
    '_copy_propagation_ranked_source_repairs',
    '_copy_propagation_repair_applies',
    '_copy_propagation_retained_source_shape_candidates',
    '_copy_propagation_source_expression',
    '_copy_propagation_source_shape_terminal_summary',
    '_copy_propagation_terminal_blocker',
    '_copy_propagation_unmapped_operands',
    '_copy_repair_candidate_summary',
    '_coverage_family',
    '_current_colorgraph_reg',
    '_current_pointer_reassoc_evidence',
    '_default_decl_order_search_summary',
    '_detect_disp_form_rollback_hint',
    '_detect_new_permuter_import_dir',
    '_detect_pointer_offset_reassociation_hint',
    '_diagnose_call_return_recommendations',
    '_diagnose_coupled_force_phys_guidance',
    '_diagnose_site_hint',
    '_diagnose_spilled_virtual_hints',
    '_ensure_source_restore_signal_handlers',
    '_env_with_current_melee_agent_package',
    '_expected_pointer_reassoc_evidence',
    '_extract_pcdump_function_chunk',
    '_find_brace_close',
    '_find_matching_delimiter',
    '_find_stack_slot_localizer_in_json',
    '_first_divergence_frame_case',
    '_first_divergence_frame_local_target',
    '_first_divergence_frame_report',
    '_first_float',
    '_first_int',
    '_first_mapping',
    '_fn_addr_from_name',
    '_force_phys_coverage_matrix',
    '_force_vector_dump_args',
    '_force_vector_probe_groups',
    '_force_vector_probe_payload',
    '_format_asm_hunks',
    '_format_byte_word_delta',
    '_format_diagnose_hint_location',
    '_format_first_divergence_frame_report',
    '_format_fn_addr',
    '_format_force_phys_members',
    '_format_hsd_assert_override_guidance',
    '_format_signed_hex',
    '_format_stack_range',
    '_format_tiebreak_reg',
    '_format_words_suffix',
    '_fpr_reassociation_suspect_count',
    '_frame_residual_for_case',
    '_frame_residual_hint_from_checkdiff_classification',
    '_frame_residual_hint_from_report',
    '_frame_source_path_for_unit',
    '_frame_subcategory_from_taxonomy',
    '_frame_taxonomy_next_steps',
    '_fresh_node_set_split_baseline_pct',
    '_fresh_pcdump_cache_path_for_restore',
    '_get_asm_hunks',
    '_get_checkdiff_classification',
    '_has_register_def',
    '_infer_tiebreak_class',
    '_inject_bootstrap_same_tu_inlined_callees',
    '_instruction_defines_reg',
    '_load_checkdiff_normalized_structural_lines',
    '_looks_like_decomp_permuter_root',
    '_loop_has_self_update',
    '_loop_id_for_offset',
    '_loop_ranges_in_body',
    '_mask_c_comments_and_strings',
    '_match_virtual_for_register_diff',
    '_name_magic_decode_anonymous_symbol',
    '_new_external_function_definitions',
    '_node_set_split_compile_signature_and_pcdump',
    '_normalize_force_phys',
    '_normalize_header_declaration',
    '_normalize_virtual_to_var_reg_class',
    '_operand_shape',
    '_order_move_for_insertion_slot',
    '_order_target_forced_dump',
    '_parse_add_operands',
    '_parse_addi_operands',
    '_parse_and_run_tiebreak_whatif',
    '_parse_checkdiff_asm_instruction',
    '_parse_force_phys_class',
    '_parse_force_vector',
    '_parse_force_vector_int',
    '_parse_force_vector_phys',
    '_parse_int_literal',
    '_parse_int_value',
    '_parse_pcdump_instruction',
    '_parse_tiebreak_token',
    '_parse_tiebreak_token_for_ig',
    '_parse_virtual_csv',
    '_parse_virtual_reg_token',
    '_permuter_import_dirs',
    '_pointer_call_source_sites',
    '_pointer_expression_constants',
    '_prepass_destination_virtual',
    '_preserve_pcdump_cache_freshness_after_restore',
    '_preserve_source_restore_backup',
    '_print_basis',
    '_print_coupled_force_phys_guidance',
    '_print_disp_form_rollback_hint',
    '_print_frame_allocation_trace_summary',
    '_print_frame_reservation_report',
    '_print_outgoing_parameter_area_floor',
    '_print_pointer_offset_reassociation_hint',
    '_print_register_tiebreak_guidance',
    '_print_stack_home_order_summary',
    '_print_unused_ranges',
    '_print_value_numbering_ceiling',
    '_promote_permuter_import_dir',
    '_read_bootstrap_source_file',
    '_read_bootstrap_target_asm',
    '_read_diagnose_expected_asm',
    '_read_force_phys_checkdiff_payload',
    '_read_stack_home_probe_results_json',
    '_register_active_source_restore',
    '_register_class_name_from_id',
    '_register_tiebreak_guidance',
    '_register_tiebreak_order_flip_leads',
    '_register_window_rotation_desired_regs',
    '_render_virtual_to_var_call_return_source',
    '_replace_path_from',
    '_report_function_virtual_address',
    '_resolve_bootstrap_melee_root',
    '_resolve_force_vector_probe_timeout',
    '_resolve_tiebreak_class',
    '_restore_active_sources_for_signal',
    '_restore_object_report_for_unit',
    '_restore_signature_candidate_validation_state',
    '_restore_source_bytes_snapshot',
    '_retained_c_source_variant_hit',
    '_retained_source_sibling_for_pcdump',
    '_run_checkdiff_json',
    '_run_checkdiff_stack_slot_localizer',
    '_run_checkdiff_stack_slot_payload',
    '_run_decl_candidates',
    '_run_signature_candidate_checkdiff_many_rebuild',
    '_safe_filename',
    '_sanitize_bootstrap_assert_macros',
    '_select_order_already_satisfied_support_order_action',
    '_select_order_asm_signature',
    '_select_order_asm_signature_rows',
    '_select_order_bridge_actual_registers',
    '_select_order_bridge_force_distance',
    '_select_order_bridge_force_phys_target_score',
    '_select_order_bridge_lead_source_candidates',
    '_select_order_bridge_probe_intent',
    '_select_order_bridge_probe_payload',
    '_select_order_bridge_probe_sort_key',
    '_select_order_bridge_ranked_source_probes',
    '_select_order_bridge_score_command_hint',
    '_select_order_bridge_source_owner',
    '_select_order_candidate_hits_force_phys',
    '_select_order_candidate_probe_intents',
    '_select_order_causal_complement_composition_lane',
    '_select_order_causal_delta_entry',
    '_select_order_causal_lane_coverage',
    '_select_order_causal_target_for_ig',
    '_select_order_causal_target_plans',
    '_select_order_checkdiff_drift_summary',
    '_select_order_coerce_int',
    '_select_order_complement_candidate_summary',
    '_select_order_complement_candidate_target_status',
    '_select_order_complement_preserving_sort_key',
    '_select_order_complement_source_diagnostics',
    '_select_order_complement_source_provenance',
    '_select_order_complement_structural_sort_key',
    '_select_order_component_provenance',
    '_select_order_composition_candidate_payload',
    '_select_order_composition_coverage',
    '_select_order_dedupe_duplicate_local_declarations',
    '_select_order_downhill_complement_summary',
    '_select_order_duplicate_local_declaration_key',
    '_select_order_entry_target_ig',
    '_select_order_expression_looks_pcode',
    '_select_order_expression_provenance',
    '_select_order_expression_safe_to_bind',
    '_select_order_filter_materialized_delta_for_targets',
    '_select_order_first_unified_diff_hunk',
    '_select_order_float_sort_value',
    '_select_order_force_phys_csv',
    '_select_order_force_phys_hits',
    '_select_order_force_phys_mismatched_registers',
    '_select_order_force_phys_missing_registers',
    '_select_order_frame_preserved',
    '_select_order_guard_repair_action',
    '_select_order_guard_repair_candidate_sort_key',
    '_select_order_guard_repair_kind',
    '_select_order_guard_repair_ledger_mapping',
    '_select_order_guard_repair_result_summary',
    '_select_order_inline_boundary_drift_summary',
    '_select_order_inline_boundary_repair_routes',
    '_select_order_inline_boundary_score_probe',
    '_select_order_int_mapping',
    '_select_order_lead_diagnostics_by_target',
    '_select_order_materialized_causal_candidate_combos',
    '_select_order_materialized_causal_candidates',
    '_select_order_materialized_causal_delta',
    '_select_order_materialized_targeted_interference_delta',
    '_select_order_merge_protected_hits',
    '_select_order_mixed_source_repair_plan',
    '_select_order_node_set_delta_targets',
    '_select_order_opcode_hunk_from_asm',
    '_select_order_orientation_reconciliation_lane',
    '_select_order_owner_split_candidates',
    '_select_order_owner_split_safe_source',
    '_select_order_partial_protected_complement_summary',
    '_select_order_payload_asm_lines',
    '_select_order_pcode_first_def_payload',
    '_select_order_protected_complement_candidate_summary',
    '_select_order_protected_complement_preserving_sort_key',
    '_select_order_protected_complement_sort_key',
    '_select_order_protected_complement_summary',
    '_select_order_protected_hit_composition_summary',
    '_select_order_protected_structural_plateau_summary',
    '_select_order_real_score_sort_key',
    '_select_order_repair_preserves_force_phys',
    '_select_order_replace_function_text',
    '_select_order_saved_register_delta',
    '_select_order_sorted_numeric_keys',
    '_select_order_source_attr_for_ig',
    '_select_order_source_attribution_for_target',
    '_select_order_source_body_executable_spans',
    '_select_order_source_bridge_action_for_blocker',
    '_select_order_source_bridge_blocker_classes',
    '_select_order_source_bridge_dominant_nonterminal_blocker',
    '_select_order_source_bridge_frame_repair_lane',
    '_select_order_source_bridge_lane',
    '_select_order_source_bridge_leads',
    '_select_order_source_bridge_terminal_next_lane',
    '_select_order_source_bridge_variant_registers',
    '_select_order_source_components_overlap',
    '_select_order_source_composition_payload',
    '_select_order_source_excerpt',
    '_select_order_source_hunk_call_lines',
    '_select_order_source_hunk_code_line',
    '_select_order_source_hunk_executable_lines',
    '_select_order_source_hunk_has_statement',
    '_select_order_source_hunk_line_components',
    '_select_order_source_hunks_from_provenance',
    '_select_order_source_idea_payload',
    '_select_order_source_is_raw_pcode',
    '_select_order_source_line_is_non_executable_declaration',
    '_select_order_source_reference_score',
    '_select_order_source_span_payload',
    '_select_order_spill_delta',
    '_select_order_strings_in',
    '_select_order_structural_ndiff',
    '_select_order_structural_plateau_attempt',
    '_select_order_structural_plateau_sort_key',
    '_select_order_structural_plateau_source_components',
    '_select_order_suggest_non_satisfied_targets',
    '_select_order_target_key',
    '_select_order_target_order_actionability',
    '_select_order_target_order_csv',
    '_select_order_targeted_interference_source_diagnostics',
    '_select_order_targeted_interference_transform_plan',
    '_select_order_terminal_owner_probe_summary',
    '_select_order_terminal_summary_best_retained_variants',
    '_select_order_terminal_summary_blocker_classes',
    '_select_order_unit_hint_from_source_path',
    '_select_order_validated_materialized_delta',
    '_select_order_variant_pcdump_path',
    '_select_order_virtual_operands_from_expression',
    '_select_order_window_order_lead_diagnostic_by_key',
    '_select_order_window_order_lead_key',
    '_shape_guard_from_checkdiff_payload',
    '_signature_report_return_width_helpers',
    '_source_contains_perm_macros',
    '_source_file_melee_root',
    '_source_restore_byte_guard',
    '_source_restore_guard',
    '_split_asm_operands',
    '_split_call_args',
    '_staged_permuter_import_source',
    '_tiebreak_class_label',
    '_tiebreak_whatif_payload',
    '_tmp_asm_path_for_function',
    '_trace_copy_inferred_register_class',
    '_trace_copy_json_int',
    '_trace_copy_json_occurrence',
    '_trace_copy_operand_expression',
    '_trace_copy_pair_token',
    '_trace_copy_source_operand',
    '_trace_mapping_int',
    '_trace_mapping_nested_string',
    '_trace_mapping_source_local',
    '_trace_mapping_source_type',
    '_trace_mapping_string',
    '_trace_occurrence_register_class_for_virtuals',
    '_trace_register_class_name',
    '_unique_existing_source_restore_paths',
    '_unregister_active_source_restore',
    '_validate_signature_checkdiff_function',
    '_value_numbering_ceiling_recommendation',
    '_virtreg_to_dict',
    '_virtual_to_var_call_return_source',
    'analyze',
    'ceiling',
    'diff',
    'first_divergence_cmd',
    'frame_reservations',
    'guide',
    'inspect_app',
    'inspect_asm',
    'inspect_explain_diff',
    'inspect_explain_schedule',
    'inspect_explain_virtual',
    'inspect_lifetime_pressure',
    'inspect_stack_homes',
    'inspect_tiebreak',
    'rank_callees',
    'simulate',
    'stuck',
    'trace_copy',
    'var_to_virtual',
    'virtual_to_ig',
    'virtual_to_var',
]


_CHECKDIFF_ASM_REG_RE = re.compile(r"\b([rf])(\d+)\b")
_CHECKDIFF_STWU_FRAME_RE = re.compile(r"\bstwu\s+r1,\s*(-?\d+)\(r1\)")
_CHECKDIFF_STACK_SLOT_RE = re.compile(
    r"(?P<offset>-?(?:0x[0-9a-fA-F]+|\d+))(?P<suffix>\s*\(\s*r1\s*\))"
)
def _checkdiff_asm_body(line: str) -> str:
    if line.startswith("<"):
        return line
    if ":" in line:
        line = line.split(":", 1)[1]
    line = line.strip()
    line = re.sub(r"^(?:[0-9a-fA-F]{2}\s+){4}", "", line)
    line = re.sub(r"^[0-9a-fA-F]{8}\s+", "", line)
    return line.strip()
def _parse_checkdiff_asm_instruction(line: str) -> AsmInstruction | None:
    body = _checkdiff_asm_body(line)
    if not body or body.startswith("<") or body.startswith("."):
        return None
    parts = body.split(None, 1)
    if not parts:
        return None
    opcode = parts[0].rstrip(".")
    operands = parts[1] if len(parts) > 1 else ""
    regs = [
        (kind, int(number))
        for kind, number in _CHECKDIFF_ASM_REG_RE.findall(operands)
    ]
    return AsmInstruction(opcode=opcode, operands=operands, regs=regs)
def _operand_shape(operands: str) -> tuple[int, ...]:
    """Relabel-INVARIANT canonical shape of an operand list: each token mapped
    to its first-occurrence index. 'f26,f26,f0' -> (0,0,1); 'f28,f1,f0' ->
    (0,1,2); 'f28,f28,f30' and 'f26,f26,f30' both -> (0,0,1). Lets a pure
    register relabel compare EQUAL while an operand-structure change differs."""
    seen: dict[str, int] = {}
    shape: list[int] = []
    for tok in (operands or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok not in seen:
            seen[tok] = len(seen)
        shape.append(seen[tok])
    return tuple(shape)
_FPR_MULTI_SOURCE_OPS = {
    "fadd", "fadds", "fsub", "fsubs", "fmul", "fmuls", "fdiv", "fdivs",
    "fmadd", "fmadds", "fmsub", "fmsubs", "fnmadd", "fnmadds", "fnmsub",
    "fnmsubs", "fsel",
}
def _fpr_reassociation_suspect_count(class_targets: list[dict]) -> int:
    """#705 honest-coupling heuristic. Count class-1 target occurrences whose
    defining multi-source FP instruction has a DIFFERENT operand structure
    (register-aliasing pattern) between target and current asm — a
    reassociation/scheduling signal, NOT a pure coloring relabel (which an FPR
    node-set split CAN fix). Relabel-invariant (see _operand_shape), so clean
    relabels are NOT counted. Soft hint only; the consumer's verify-and-accept
    gate is the real correctness check. Defensive: never raises."""
    count = 0
    for target in class_targets or []:
        for occ in target.get("occurrences", []) or []:
            opcode = (occ.get("opcode") or "").strip()
            if opcode not in _FPR_MULTI_SOURCE_OPS:
                continue
            tgt_ops = occ.get("operands", "") or ""
            cur_instr = _parse_checkdiff_asm_instruction(occ.get("current_asm") or "")
            cur_ops = cur_instr.operands if cur_instr is not None else ""
            if _operand_shape(tgt_ops) != _operand_shape(cur_ops):
                count += 1
    return count
def _checkdiff_frame_size(lines: list[str]) -> int | None:
    for line in lines:
        body = _checkdiff_asm_body(line)
        match = _CHECKDIFF_STWU_FRAME_RE.search(body)
        if match is None:
            continue
        offset = int(match.group(1), 10)
        if offset < 0:
            return -offset
    return None
def _adjust_checkdiff_stack_slots(operands: str, delta: int) -> str:
    if delta == 0:
        return operands

    def repl(match: re.Match[str]) -> str:
        raw_offset = match.group("offset")
        base = 16 if raw_offset.lower().startswith("0x") else 10
        value = int(raw_offset, base) + delta
        rendered = hex(value) if base == 16 else str(value)
        return f"{rendered}{match.group('suffix')}"

    return _CHECKDIFF_STACK_SLOT_RE.sub(repl, operands)
def _checkdiff_instruction_signature(
    instruction: AsmInstruction,
    *,
    stack_delta: int = 0,
) -> tuple[str, str]:
    operands = _adjust_checkdiff_stack_slots(instruction.operands, stack_delta)
    return instr_signature(instruction.opcode, operands)
def _asm_instruction_destination(
    instruction: AsmInstruction | None,
) -> tuple[str, int] | None:
    if instruction is None or not instruction.regs:
        return None
    opcode = instruction.opcode
    if (
        opcode.startswith("st")
        or opcode.startswith("psq_st")
        or opcode.startswith("b")
        or opcode.startswith("cmp")
    ):
        return None
    kind, number = instruction.regs[0]
    if number > 31:
        return None
    return kind, number
def _current_colorgraph_reg(
    events: FunctionEvents | None,
    *,
    class_id: int,
    ig_idx: int,
) -> int | None:
    if events is None:
        return None
    for section in events.colorgraph_sections:
        if section.class_id != class_id:
            continue
        for decision in section.decisions:
            if decision.ig_idx == ig_idx:
                return decision.assigned_reg
    return None
def _prepass_destination_virtual(instruction, reg_kind: str) -> int | None:
    if not instruction.regs:
        return None
    kind, number = instruction.regs[0]
    if kind != reg_kind or number < 32:
        return None
    return number
_REGISTER_DIFF_CURRENT_REG_POSITION_SLOP = 8
def _match_virtual_for_register_diff(
    *,
    expected_ist: AsmInstruction,
    expected_position: int,
    pre_pass,
    reg_kind: str,
    current_phys: int,
    events: FunctionEvents | None,
) -> MatchResult | None:
    from src.cli.debug import _match_iter_first_class_id  # noqa: PLC0415
    target_sig = instr_signature(expected_ist.opcode, expected_ist.operands)
    candidates: list[tuple[int, Any, int, int | None]] = []
    linear_index = 0
    for block in pre_pass.blocks:
        for instruction in block.instructions:
            if instr_signature(instruction.opcode, instruction.operands) != target_sig:
                linear_index += 1
                continue
            virtual = _prepass_destination_virtual(instruction, reg_kind)
            if virtual is None:
                linear_index += 1
                continue
            class_id = _match_iter_first_class_id(reg_kind)
            assigned = (
                None if class_id is None else _current_colorgraph_reg(
                    events,
                    class_id=class_id,
                    ig_idx=virtual,
                )
            )
            candidates.append((linear_index, instruction, virtual, assigned))
            linear_index += 1
    if not candidates:
        return None

    candidates.sort(key=lambda item: abs(item[0] - expected_position))
    nearest_distance = abs(candidates[0][0] - expected_position)
    current_matches = [
        candidate for candidate in candidates
        if (
            candidate[3] == current_phys
            and abs(candidate[0] - expected_position)
            <= nearest_distance + _REGISTER_DIFF_CURRENT_REG_POSITION_SLOP
        )
    ]
    ranked = current_matches or candidates
    ranked.sort(key=lambda item: (
        abs(item[0] - expected_position),
        0 if item[3] == current_phys else 1,
    ))
    best_i, _best_instruction, virtual, _assigned = ranked[0]
    if len(candidates) == 1:
        confidence = "exact"
    elif len(current_matches) == 1:
        confidence = "current-reg"
    else:
        confidence = "ambiguous"
    return MatchResult(
        virtual=virtual,
        ig_idx=virtual,
        instruction_index=best_i,
        confidence=confidence,
    )
def _read_force_phys_checkdiff_payload(
    *,
    function: str,
    melee_root: Path,
    checkdiff_json: Path | None,
    checkdiff_timeout: float,
) -> tuple[dict, str]:
    from src.cli.debug import _checkdiff_env_without_fingerprint, _checkdiff_script_path
    if checkdiff_json is not None:
        try:
            return json.loads(checkdiff_json.read_text()), str(checkdiff_json)
        except json.JSONDecodeError as exc:
            typer.echo(
                f"checkdiff JSON could not be parsed: {exc}",
                err=True,
            )
            raise typer.Exit(2) from exc
        except OSError as exc:
            typer.echo(f"checkdiff JSON could not be read: {exc}", err=True)
            raise typer.Exit(2) from exc

    cmd = [
        sys.executable,
        str(_checkdiff_script_path(melee_root)),
        function,
        "--format",
        "json",
        "--no-build",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=checkdiff_timeout,
            env=_checkdiff_env_without_fingerprint(),
        )
    except subprocess.TimeoutExpired as exc:
        typer.echo(
            f"checkdiff timed out after {checkdiff_timeout:g}s",
            err=True,
        )
        raise typer.Exit(3) from exc
    except OSError as exc:
        typer.echo(f"failed to run checkdiff: {exc}", err=True)
        raise typer.Exit(3) from exc

    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        if proc.stdout:
            typer.echo(proc.stdout.rstrip(), err=True)
        raise typer.Exit(proc.returncode or 3)
    try:
        return json.loads(proc.stdout), "checkdiff"
    except json.JSONDecodeError as exc:
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        typer.echo(f"checkdiff did not emit JSON: {exc}", err=True)
        raise typer.Exit(3) from exc
_CHECKDIFF_NORMALIZE_FN = None
def _load_checkdiff_normalized_structural_lines(melee_root: Path):
    """Load tools/checkdiff.py's PURE `normalized_structural_lines` in-process
    (it lives outside the package; checkdiff.py guards execution behind
    `if __name__ == "__main__"`, so importing it by path is side-effect-free).

    Reused by the #619 solve-coloring admission gate's direct-evidence verdict so
    the admission decision runs on the SAME masked normalization the live
    checkdiff classification uses. Cached after first load."""
    global _CHECKDIFF_NORMALIZE_FN
    if _CHECKDIFF_NORMALIZE_FN is None:
        import importlib.util

        path = melee_root / "tools" / "checkdiff.py"
        spec = importlib.util.spec_from_file_location("checkdiff_inproc", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CHECKDIFF_NORMALIZE_FN = mod.normalized_structural_lines
    return _CHECKDIFF_NORMALIZE_FN
_FORCE_VECTOR_CLASS_NAMES = {
    "gpr": 0,
    "int": 0,
    "r": 0,
    "class0": 0,
    "fp": 1,
    "fpr": 1,
    "f": 1,
    "class1": 1,
}
def _parse_force_vector_int(raw: str, *, prefix: str = "") -> int:
    value = raw.strip().lower()
    if prefix and value.startswith(prefix):
        value = value[len(prefix):]
    if not value:
        raise ValueError(f"expected integer in {raw!r}")
    return int(value, 0)
def _parse_force_vector_phys(raw: str) -> int:
    value = raw.strip().lower()
    if value.startswith(("r", "f")):
        value = value[1:]
    if not value:
        raise ValueError(f"expected physical register in {raw!r}")
    return int(value, 0)
_FORCE_SELECT_ACTIONS = {
    "select-first",
    "select_first",
    "select-order",
    "select_order",
    "select",
}
def _parse_force_vector(raw: str) -> list[_ForceVectorEntry]:
    """Parse composed force specs for one diagnostic auto-verify run.

    Supported entries:
      - ``ig40:phys=r30`` or ``40:phys=30`` -> ``--force-phys 40:30``
      - ``class0:ig40:phys=r29`` -> ``--force-phys 0:40:29``
      - ``class0:iter5:phys=r31`` -> ``--force-phys-iter 0:5:31``
      - ``ig42:coalesce=38`` / ``ig42:root=38`` / ``42=38`` -> coalesce
      - ``ig50:iter-first`` -> ``--force-iter-first 50``
      - ``class1:ig50:iter-first`` -> scoped ``--force-iter-first 50``
      - ``class1:iter4:iter-first`` -> ``--force-iter-first-iter 1:4``
      - ``class0:ig40:select-first`` -> ``--force-select-order 40``
    """
    from src.cli.debug import _ForceVectorEntry  # noqa: PLC0415
    if any(c in raw for c in '"\';\r\n&|<>'):
        raise ValueError(
            "--force-vector must not contain quotes, semicolons, newlines, "
            "or shell metacharacters"
        )

    entries: list[_ForceVectorEntry] = []
    for item in raw.split(","):
        spec = item.strip()
        if not spec:
            continue
        lower = spec.lower()
        try:
            parts = spec.split(":")
            if len(parts) == 2 and parts[1].lower() in {
                "iter-first", "iter_first", "first",
            }:
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_iter_first",
                    ig_idx=_parse_force_vector_int(parts[0], prefix="ig"),
                ))
                continue

            if len(parts) == 2 and parts[1].lower() in _FORCE_SELECT_ACTIONS:
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_select_order",
                    ig_idx=_parse_force_vector_int(parts[0], prefix="ig"),
                ))
                continue

            if len(parts) == 2 and parts[1].lower().startswith("phys="):
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_phys",
                    ig_idx=_parse_force_vector_int(parts[0], prefix="ig"),
                    phys=_parse_force_vector_phys(parts[1].split("=", 1)[1]),
                ))
                continue

            if len(parts) == 2 and (
                parts[1].lower().startswith("coalesce=")
                or parts[1].lower().startswith("root=")
            ):
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_coalesce",
                    ig_idx=_parse_force_vector_int(parts[0], prefix="ig"),
                    root=_parse_force_vector_int(parts[1].split("=", 1)[1], prefix="ig"),
                ))
                continue

            if len(parts) == 3 and parts[2].lower().startswith("phys="):
                class_name = parts[0].lower()
                if class_name not in _FORCE_VECTOR_CLASS_NAMES:
                    raise ValueError(f"unknown force-vector class {parts[0]!r}")
                class_id = _FORCE_VECTOR_CLASS_NAMES[class_name]
                middle = parts[1].lower()
                if middle.startswith("iter"):
                    entries.append(_ForceVectorEntry(
                        raw=spec,
                        kind="force_phys_iter",
                        class_id=class_id,
                        iter_idx=_parse_force_vector_int(parts[1], prefix="iter"),
                        phys=_parse_force_vector_phys(parts[2].split("=", 1)[1]),
                    ))
                else:
                    entries.append(_ForceVectorEntry(
                        raw=spec,
                        kind="force_phys",
                        class_id=class_id,
                        ig_idx=_parse_force_vector_int(parts[1], prefix="ig"),
                        phys=_parse_force_vector_phys(parts[2].split("=", 1)[1]),
                    ))
                continue

            if len(parts) == 3 and parts[2].lower() in {
                "iter-first", "iter_first", "first",
            }:
                class_name = parts[0].lower()
                if class_name not in _FORCE_VECTOR_CLASS_NAMES:
                    raise ValueError(f"unknown force-vector class {parts[0]!r}")
                class_id = _FORCE_VECTOR_CLASS_NAMES[class_name]
                middle = parts[1].lower()
                if middle.startswith("iter"):
                    entries.append(_ForceVectorEntry(
                        raw=spec,
                        kind="force_iter_first_iter",
                        class_id=class_id,
                        iter_idx=_parse_force_vector_int(parts[1], prefix="iter"),
                    ))
                else:
                    entries.append(_ForceVectorEntry(
                        raw=spec,
                        kind="force_iter_first",
                        class_id=class_id,
                        ig_idx=_parse_force_vector_int(parts[1], prefix="ig"),
                    ))
                continue

            if len(parts) == 3 and parts[2].lower() in _FORCE_SELECT_ACTIONS:
                class_name = parts[0].lower()
                if class_name not in _FORCE_VECTOR_CLASS_NAMES:
                    raise ValueError(f"unknown force-vector class {parts[0]!r}")
                class_id = _FORCE_VECTOR_CLASS_NAMES[class_name]
                middle = parts[1].lower()
                if middle.startswith("iter"):
                    raise ValueError(
                        "select-order entries must target an ig_idx, not an iter"
                    )
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_select_order",
                    class_id=class_id,
                    ig_idx=_parse_force_vector_int(parts[1], prefix="ig"),
                ))
                continue

            if "=" in lower and ":" not in lower:
                lhs, rhs = spec.split("=", 1)
                entries.append(_ForceVectorEntry(
                    raw=spec,
                    kind="force_coalesce",
                    ig_idx=_parse_force_vector_int(lhs, prefix="ig"),
                    root=_parse_force_vector_int(rhs, prefix="ig"),
                ))
                continue
        except ValueError as exc:
            raise ValueError(f"invalid --force-vector entry {spec!r}: {exc}") from exc

        raise ValueError(
            f"invalid --force-vector entry {spec!r}; expected forms like "
            "ig40:phys=r30, ig42:coalesce=38, "
            "class0:ig40:phys=r29, class0:iter5:phys=r31, "
            "class1:ig50:iter-first, "
            "class1:iter4:iter-first, class0:ig40:select-first, "
            "or ig50:iter-first"
        )

    if not entries:
        raise ValueError("--force-vector did not contain any entries")
    return entries
def _force_vector_dump_args(
    entries: list[_ForceVectorEntry],
    *,
    function: str,
) -> tuple[list[str], dict]:
    force_phys = [
        (
            f"{entry.class_id}:{entry.ig_idx}:{entry.phys}"
            if entry.class_id is not None
            else f"{entry.ig_idx}:{entry.phys}"
        )
        for entry in entries
        if entry.kind == "force_phys"
        and entry.ig_idx is not None
        and entry.phys is not None
    ]
    force_phys_iter = [
        f"{entry.class_id}:{entry.iter_idx}:{entry.phys}"
        for entry in entries
        if entry.kind == "force_phys_iter"
        and entry.class_id is not None
        and entry.iter_idx is not None
        and entry.phys is not None
    ]
    force_coalesce = [
        f"{entry.ig_idx}={entry.root}"
        for entry in entries
        if entry.kind == "force_coalesce"
        and entry.ig_idx is not None
        and entry.root is not None
    ]
    force_iter_first_unscoped = [
        str(entry.ig_idx)
        for entry in entries
        if entry.kind == "force_iter_first"
        and entry.class_id is None
        and entry.ig_idx is not None
    ]
    force_iter_first_scoped = [
        entry
        for entry in entries
        if entry.kind == "force_iter_first"
        and entry.class_id is not None
        and entry.ig_idx is not None
    ]
    force_iter_first_iter = [
        f"{entry.class_id}:{entry.iter_idx}"
        for entry in entries
        if entry.kind == "force_iter_first_iter"
        and entry.class_id is not None
        and entry.iter_idx is not None
    ]
    force_select_order_unscoped = [
        str(entry.ig_idx)
        for entry in entries
        if entry.kind == "force_select_order"
        and entry.class_id is None
        and entry.ig_idx is not None
    ]
    force_select_order_scoped = [
        entry
        for entry in entries
        if entry.kind == "force_select_order"
        and entry.class_id is not None
        and entry.ig_idx is not None
    ]
    if force_iter_first_unscoped and force_iter_first_scoped:
        raise ValueError(
            "--force-vector cannot mix unscoped and class-scoped iter-first "
            "entries in one probe"
        )
    iter_first_classes = {
        entry.class_id for entry in force_iter_first_scoped
        if entry.class_id is not None
    }
    if len(iter_first_classes) > 1:
        raise ValueError(
            "--force-vector class-scoped iter-first entries must use one "
            "class per probe"
        )
    force_iter_first = force_iter_first_unscoped or [
        str(entry.ig_idx) for entry in force_iter_first_scoped
        if entry.ig_idx is not None
    ]
    force_iter_first_class = (
        str(next(iter(iter_first_classes))) if iter_first_classes else ""
    )
    if (force_iter_first_unscoped or force_iter_first_scoped
            or force_iter_first_iter) and (
                force_select_order_unscoped or force_select_order_scoped):
        raise ValueError(
            "--force-vector cannot mix iter-first and select-order entries "
            "in one probe"
        )
    if force_select_order_unscoped and force_select_order_scoped:
        raise ValueError(
            "--force-vector cannot mix unscoped and class-scoped select-order "
            "entries in one probe"
        )
    select_order_classes = {
        entry.class_id for entry in force_select_order_scoped
        if entry.class_id is not None
    }
    if len(select_order_classes) > 1:
        raise ValueError(
            "--force-vector class-scoped select-order entries must use one "
            "class per probe"
        )
    force_select_order = force_select_order_unscoped or [
        str(entry.ig_idx) for entry in force_select_order_scoped
        if entry.ig_idx is not None
    ]
    force_select_order_class = (
        str(next(iter(select_order_classes))) if select_order_classes else ""
    )

    args: list[str] = []
    summary = {
        "force_phys_csv": ",".join(force_phys),
        "force_phys_iter_csv": ",".join(force_phys_iter),
        "force_coalesce_csv": ",".join(force_coalesce),
        "force_iter_first_csv": ",".join(force_iter_first),
        "force_iter_first_class": force_iter_first_class,
        "force_iter_first_iter_csv": ",".join(force_iter_first_iter),
        "force_select_order_csv": ",".join(force_select_order),
        "force_select_order_class": force_select_order_class,
    }
    if force_phys or force_phys_iter:
        needs_force_phys_scope = True
    else:
        needs_force_phys_scope = False

    if force_phys:
        args.extend(["--force-phys", summary["force_phys_csv"]])
    if force_phys_iter:
        args.extend(["--force-phys-iter", summary["force_phys_iter_csv"]])
    if needs_force_phys_scope:
        args.extend(["--force-phys-fn", function])
    if force_coalesce:
        args.extend(["--force-coalesce", summary["force_coalesce_csv"]])
        args.extend(["--force-coalesce-fn", function])
    if force_iter_first:
        args.extend(["--force-iter-first", summary["force_iter_first_csv"]])
        if force_iter_first_class:
            args.extend(["--force-iter-first-class", force_iter_first_class])
    if force_iter_first_iter:
        args.extend([
            "--force-iter-first-iter",
            summary["force_iter_first_iter_csv"],
        ])
    if force_iter_first or force_iter_first_iter:
        args.extend(["--force-iter-first-fn", function])
    if force_select_order:
        args.extend(["--force-select-order", summary["force_select_order_csv"]])
        if force_select_order_class:
            args.extend(["--force-select-order-class", force_select_order_class])
        args.extend(["--force-select-order-fn", function])
    return args, summary
def _build_force_vector_auto_verify_cmd(
    *,
    src_path: Path,
    function: str,
    entries: list[_ForceVectorEntry],
    output_path: Optional[Path] = None,
    checkdiff_timeout: float = 60.0,
) -> list[str]:
    if output_path is None:
        output_path = (
            src_path.parent
            / f".{function}.force-vector.{os.getpid()}.{int(time.time() * 1000)}.pcdump.txt"
        )
    force_args, _summary = _force_vector_dump_args(entries, function=function)
    return [
        sys.executable, "-m", "src.cli", "debug", "dump", "local", str(src_path),
        *force_args,
        "--function", function,
        "--diff",
        "--checkdiff-timeout", f"{checkdiff_timeout:g}",
        "-o", str(output_path),
    ]
def _force_vector_probe_groups(
    entries: list[_ForceVectorEntry],
    *,
    include_diagnostic_probes: bool,
) -> list[tuple[str, list[_ForceVectorEntry], int | None]]:
    groups: list[tuple[str, list[_ForceVectorEntry], int | None]] = [
        ("union", entries, None)
    ]
    if not include_diagnostic_probes:
        return groups
    for index, entry in enumerate(entries, start=1):
        groups.append((f"single[{index}]", [entry], index))
    for end in range(2, len(entries)):
        groups.append((f"prefix[1..{end}]", entries[:end], end))
    return groups
def _force_vector_probe_payload(
    *,
    label: str,
    entries: list[_ForceVectorEntry],
    proc: subprocess.CompletedProcess[str],
    output_path: Path,
    ordinal: int | None,
) -> dict:
    from src.cli.debug import _run_auto_verify_command_with_status
    _args, summary = _force_vector_dump_args(entries, function="<fn>")
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    # #620: rc=124 is the per-probe-timeout sentinel from
    # _run_auto_verify_command_with_status (a hung mwcc/wibo child the watchdog
    # SIGKILLed). Record it as INCONCLUSIVE (timed_out), distinct from a real
    # build `failed`, so the caller continues/abstains cleanly — never as a
    # `match`.
    timed_out = proc.returncode == 124
    match = (not timed_out) and "[diff] MATCH" in stdout
    return {
        "label": label,
        "ordinal": ordinal,
        "entries": [entry.to_payload() for entry in entries],
        "force_phys_csv": summary["force_phys_csv"],
        "force_phys_iter_csv": summary["force_phys_iter_csv"],
        "force_coalesce_csv": summary["force_coalesce_csv"],
        "force_iter_first_csv": summary["force_iter_first_csv"],
        "force_iter_first_class": summary["force_iter_first_class"],
        "force_iter_first_iter_csv": summary["force_iter_first_iter_csv"],
        "force_select_order_csv": summary["force_select_order_csv"],
        "force_select_order_class": summary["force_select_order_class"],
        "returncode": proc.returncode,
        "match": match,
        "timed_out": timed_out,
        "status": (
            "inconclusive" if timed_out else
            "match" if match else
            "no_match" if proc.returncode == 0 else
            "failed"
        ),
        "pcdump": str(output_path),
        "stdout_tail": "\n".join(stdout.splitlines()[-8:]),
        "stderr_tail": "\n".join(stderr.splitlines()[-8:]),
    }
def _order_target_forced_dump(
    *,
    tu_c: Path,
    function: str,
    class_id: int,
    force_iter_first: list,
    melee_root: Path,
) -> tuple[dict, set, str]:
    """Run ONE forced-ORDER dump of the CURRENT TU bytes and read it back.

    Returns (ranks {ig: 1-based rank}, ig_set, decisions_sha256). The dump is
    written to an explicit temp path and never touches the shared cache
    (forced dumps skip cache sync by design; --no-cache-sync doubles down).
    Caller must hold (or have disabled via CHECKDIFF_NO_LOCK) the repo lock.
    """
    from src.cli.debug import find_function, parse_hook_events
    import hashlib

    from src.mwcc_debug.colorgraph_parser import find_function, parse_hook_events
    from src.search.directed.order_metric import colorgraph_ranks

    out_path = (
        tu_c.parent
        / f".{function}.order-target.{os.getpid()}.{int(time.time() * 1000)}.pcdump.txt"
    )
    ig_csv = ",".join(str(i) for i in force_iter_first)
    argv = [
        sys.executable, "-m", "src.cli", "debug", "dump", "local", str(tu_c),
        "--function", function, "--output", str(out_path), "--no-cache-sync",
        "--force-iter-first", ig_csv,
        "--force-iter-first-class", str(class_id),
        "--force-iter-first-fn", function,
    ]
    proc = subprocess.run(
        argv, cwd=melee_root / "tools" / "melee-agent",
        capture_output=True, text=True, timeout=600,
        env=os.environ.copy(),
    )
    if proc.returncode != 0 or not out_path.exists():
        out_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"forced dump failed (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '')[-500:]}"
        )
    text = out_path.read_text(encoding="utf-8")
    out_path.unlink(missing_ok=True)
    ranks = colorgraph_ranks(text, function, class_id=class_id)
    fev = find_function(parse_hook_events(text), function)
    matching = [
        s for s in (fev.colorgraph_sections if fev else [])
        if s.class_id == class_id
    ]
    section = matching[-1] if matching else None
    decisions = section.decisions if section else []
    ig_set = {d.ig_idx for d in decisions}
    sha = hashlib.sha256(
        "\n".join(
            f"{d.iter_idx}:{d.ig_idx}:{d.assigned_reg}" for d in decisions
        ).encode()
    ).hexdigest()
    return ranks, ig_set, sha
def _collect_order_target_inputs(
    *,
    function: str,
    unit: str,
    class_id: int,
    melee_root: Path,
    checkdiff_timeout: float,
    register_only_gate: Optional[Callable[[str, list, list], dict]] = None,
    force_vector_probes: bool = False,
    force_vector_timeout: float | None = None,
    retain_force_vector_pcdumps: bool = False,
    node_set_delta_fallback: bool = False,
):
    """Collect the §4.2 tool outputs for order-target derivation.

    ADMISSION GATE (#619): the early register-only gate normally keys on the
    checkdiff PRIMARY label (`checkdiff_primary in REGISTER_ONLY_PRIMARIES`) —
    the order-target derivation path relies on that (its pure classifier's
    Step-1 precondition re-checks the same label). Pass `register_only_gate` to
    OVERRIDE that gate with a computed predicate: a callable
    (checkdiff_primary, target_asm, current_asm) -> dict with an `admitted`
    bool. The solve-coloring path passes the direct-evidence gate
    (win_fixture.is_register_only_admission) so 8024227C-class walls labelled
    `register-allocation` that are PROVABLE pure permutations are admitted; the
    verdict is recorded on the returned DeriveInputs.direct_evidence_register_only.

    FRESH-EVERYTHING CONTRACT (cache coherence): never auto-resolves the cached
    pcdump and never runs checkdiff --no-build. Everything is derived from the
    CURRENT TU bytes at call time: (1) checkdiff WITH a build; (2) a fresh
    baseline pcdump compiled to an explicit temp path with --no-cache-sync.

    LOCK CONTRACT (B9): wraps the whole run in _acquire_checkdiff_repo_lock
    and runs children with CHECKDIFF_NO_LOCK=1 (_checkdiff_env_for_locked_child)
    so they don't deadlock on the same lock file. Under a parent that already
    holds the lock and exported CHECKDIFF_NO_LOCK=1 (T6 generate.py), the
    acquisition here no-ops — the established contract.

    MINIMAL <=64 FORCING-SET SEARCH (B1), concrete strategy:
      (a) greedy drop of already-correct registers (force-phys targets with
          already_target=True need no forcing);
      (b) natural-prefix preservation: per-register first-def anchors ordered
          by expected first-def position, windowed to the first 64;
      (c) outcome-verified union probe via _run_force_vector_auto_verify
          (forced dump + integrated checkdiff); singleton/prefix probes are
          optional diagnostics because solve-coloring reachability only needs
          the union result.
    force_cap_exceeded is True ONLY when len(anchors) > 64 AND the 64-window
    union does not eliminate the residual.

    Monkeypatched out in unit tests; the live path is exercised at T6's
    fixture generation and the Plan-C pool census.
    """
    from src.cli.debug import _acquire_checkdiff_repo_lock, _checkdiff_asm_lines, find_function, parse_hook_events, parse_pcdump
    from src.cli.debug import (  # noqa: PLC0415
        _checkdiff_script_path,
        _derive_force_phys_from_register_diff_lines,
        _parse_match_iter_first_regs,
        _run_force_vector_auto_verify,
        asm_extract_function,
        asm_find_first_def,
        asm_parse_prologue_end,
    )
    import hashlib

    from src.mwcc_debug.order_target_derive import (
        REGISTER_ONLY_PRIMARIES,
        DeriveInputs,
    )
    from src.mwcc_debug.role_descriptor import Compile, build_descriptors
    from src.mwcc_debug.role_reanchor import reanchor_descs
    from src.search.directed.order_metric import colorgraph_ranks
    from src.search.directed.order_target import FORCE_CAP

    tu_c = melee_root / "src" / f"{unit}.c"
    child_env = _checkdiff_env_for_locked_child(disable_fingerprint=False)
    retained_force_vector_dir = (
        melee_root
        / "build"
        / "diagnostics"
        / _safe_filename(function)
        / "force_vector"
    )
    fresh_natural_pcdump: str | None = None

    with _acquire_checkdiff_repo_lock(melee_root, label="order-target derivation"):
        # ---- Step 1: FRESH checkdiff (WITH build) --------------------------
        proc = subprocess.run(
            [sys.executable, str(_checkdiff_script_path(melee_root)),
             function, "--format", "json"],
            capture_output=True, text=True,
            timeout=max(checkdiff_timeout, 600),  # the build dominates
            cwd=melee_root, env=child_env,
        )
        # rc 0=match, 1=mismatch (both emit JSON); anything else, or an empty
        # stdout (e.g. "ninja failed:" goes to stderr with rc=1), is a hard
        # failure — surface it cleanly instead of a raw JSONDecodeError.
        if proc.returncode not in (0, 1) or not (proc.stdout or "").strip():
            raise RuntimeError(
                f"checkdiff failed (rc={proc.returncode}): "
                f"{(proc.stderr or proc.stdout or '')[-500:]}"
            )
        checkdiff_payload = json.loads(proc.stdout)
        classification = checkdiff_payload.get("classification") or {}
        checkdiff_primary = (
            classification.get("primary")
            if isinstance(classification, dict) else str(classification)
        ) or "unknown"

        # #619: compute the admission verdict from the asm checkdiff already
        # fetched (target_asm/current_asm). The default gate is the label-only
        # check (order-target derivation contract); the solve path injects the
        # direct-evidence gate so PROVABLE pure-permutation walls labelled
        # `register-allocation` are admitted.
        target_asm = _checkdiff_asm_lines(checkdiff_payload, "target_asm")
        current_asm = _checkdiff_asm_lines(checkdiff_payload, "current_asm")
        if register_only_gate is not None:
            gate_verdict = register_only_gate(
                checkdiff_primary, target_asm, current_asm)
            admitted = bool(gate_verdict.get("admitted"))
            direct_evidence_register_only = admitted
        else:
            gate_verdict = None
            admitted = checkdiff_primary in REGISTER_ONLY_PRIMARIES
            direct_evidence_register_only = None

        # #705: FPR node-set fallback. When the residual is NOT admitted as
        # register-only but the call shape is intact (bl-multiset equal => same
        # algorithm), proceed to derive the class-1 FPR target and emit a
        # node-set-delta worksheet anyway (the register-only gate is the wrong
        # gate for node-set-split, which exists for not-reorderable residuals).
        # Requires the direct-evidence gate (label gate has no direct_evidence).
        # node_set_delta_fallback = "this call MAY use the fallback";
        # take_node_set_fallback = "the gate fired, so take it now".
        take_node_set_fallback = (
            node_set_delta_fallback and not admitted
            and gate_verdict is not None
            and bool(gate_verdict.get("direct_evidence", {})
                     .get("check_i_bl_multiset_equal"))
        )

        def _inert(**over):
            base = dict(
                function=function, unit=unit, class_id=class_id,
                checkdiff_primary=checkdiff_primary,
                phys_target={}, phys_conflicts=[],
                force_iter_first=[], applied_positions={},
                forced_class_clean=False, forced_ranks={},
                baseline_ig_set=set(), forced_ig_set=set(),
                self_reanchored_roles=set(), unscored_roles=[],
                forced_decisions_sha256=[],
                baseline_source_sha256=hashlib.sha256(
                    tu_c.read_bytes()).hexdigest()[:32],
                baseline_pcdump_sha256="",
                force_cap_exceeded=False,
                direct_evidence_register_only=direct_evidence_register_only,
                coupled_residual=None,
                force_vector_probe=None,
                natural_pcdump=fresh_natural_pcdump,
            )
            base.update(over)
            return DeriveInputs(**base)

        if not admitted and not take_node_set_fallback:
            # Not register-only. For the label gate the order-target classifier
            # raises on this (hard error, not a routing); for the solve gate the
            # solve loop turns the empty phys_target into the exit-3 abstain.
            return _inert()

        # ---- FRESH baseline pcdump (explicit temp path, never the cache) ---
        baseline_dump = (
            tu_c.parent
            / f".{function}.order-target.baseline.{os.getpid()}.pcdump.txt"
        )
        proc = subprocess.run(
            [sys.executable, "-m", "src.cli", "debug", "dump", "local",
             str(tu_c), "--function", function,
             "--output", str(baseline_dump), "--no-cache-sync"],
            cwd=melee_root / "tools" / "melee-agent",
            capture_output=True, text=True, timeout=600, env=child_env,
        )
        if proc.returncode != 0 or not baseline_dump.exists():
            baseline_dump.unlink(missing_ok=True)
            raise RuntimeError(
                f"baseline dump failed (rc={proc.returncode}): "
                f"{(proc.stderr or proc.stdout or '')[-500:]}"
            )
        pcdump_text = baseline_dump.read_text(encoding="utf-8")
        retained_natural_pcdump: Path | None = None
        if retain_force_vector_pcdumps:
            retained_force_vector_dir.mkdir(parents=True, exist_ok=True)
            retained_natural_pcdump = (
                retained_force_vector_dir / baseline_dump.name.lstrip(".")
            )
            try:
                shutil.move(str(baseline_dump), str(retained_natural_pcdump))
            except OSError:
                retained_natural_pcdump = baseline_dump
        else:
            baseline_dump.unlink(missing_ok=True)
        fresh_natural_pcdump = (
            str(retained_natural_pcdump)
            if retained_natural_pcdump is not None
            else None
        )

        # ---- Step 2: phys target + conflicts (from the FRESH artifacts) ----
        fns = parse_pcdump(pcdump_text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is None:
            raise RuntimeError(f"{function} not found in fresh baseline pcdump")
        pre_pass = fn.last_precolor_pass()
        events_fn = find_function(parse_hook_events(pcdump_text), function)
        vector = _derive_force_phys_from_register_diff_lines(
            target_asm, current_asm, pre_pass, events_fn,
        )
        class_targets = [
            target for target in vector["targets"]
            if int(target.get("class_id", -1)) == class_id
            and target.get("force_vector_runnable", True)
        ]
        class_conflicts = [
            conflict for conflict in vector["conflicts"]
            if int(conflict.get("class_id", -1)) == class_id
        ]
        phys_target = {
            int(target["ig_idx"]): int(target["target_reg"])
            for target in class_targets
        }
        phys_conflicts = list(class_conflicts)

        # #705: on the FPR node-set fallback, summarize the coupling honestly so
        # the emitted worksheet does not read as a false "splittable" lead.
        coupled_residual = None
        if take_node_set_fallback:
            other_class = [t for t in vector["targets"]
                           if int(t.get("class_id", -1)) != class_id]
            de = (gate_verdict or {}).get("direct_evidence", {})
            coupled_residual = {
                "other_class_register_targets": len(other_class),
                "other_class_target_regs": sorted({
                    t.get("target_reg_name") for t in other_class
                    if t.get("target_reg_name")}),
                "nonregister_class_lines": int(de.get("nonregister_class_lines", 0) or 0),
                "reassociation_suspect_targets":
                    _fpr_reassociation_suspect_count(class_targets),
            }

        if phys_conflicts:
            # Spec §4.2 step 2: route BEFORE any forced compile is spent.
            return _inert(phys_target=phys_target, phys_conflicts=phys_conflicts,
                          coupled_residual=coupled_residual)

        # #705: FPR fallback returns the derived target (no conflicts) BEFORE the
        # anchor search + force-vector probe (the costly #639 cascade trap,
        # irrelevant for node-set-split). Empty target => nothing to split.
        if take_node_set_fallback:
            if not phys_target:
                return _inert(coupled_residual=coupled_residual)
            return _inert(phys_target=phys_target, coupled_residual=coupled_residual)

        # ---- Step 3: per-register anchors + minimal <=64 set search (B1) ---
        mismatched_reg_names: list[str] = []
        for tgt in class_targets:
            if tgt.get("already_target") is True:
                continue
            name = tgt.get("target_reg_name")
            if name and name not in mismatched_reg_names:
                mismatched_reg_names.append(name)
        if not mismatched_reg_names:
            return _inert(phys_target=phys_target)

        asm_path = melee_root / "build" / "GALE01" / "asm" / f"{unit}.s"
        asm_fn = asm_extract_function(asm_path.read_text(), function)
        prologue_end = asm_parse_prologue_end(asm_fn.instructions)
        body = asm_fn.instructions[prologue_end:]
        anchor_rows: list[tuple[int, int]] = []  # (expected_pos, ig_idx)
        for reg in _parse_match_iter_first_regs(",".join(mismatched_reg_names)):
            expected_def = asm_find_first_def(
                body, target_reg=reg.number, reg_kind=reg.kind,
            )
            if expected_def is None:
                continue
            pos, expected_ist = expected_def
            match = match_virtual_for_expected_def(
                expected_ist=expected_ist, expected_position=pos,
                pre_pass=pre_pass, reg_kind=reg.kind,
            )
            if match is not None:
                anchor_rows.append((pos, match.ig_idx))
        anchor_rows.sort(key=lambda t: t[0])
        anchors = list(dict.fromkeys(ig for _pos, ig in anchor_rows))

        window = anchors[:FORCE_CAP]
        if not window:
            return _inert(phys_target=phys_target)
        entries = _parse_force_vector(
            ",".join(f"class{class_id}:ig{ig}:iter-first" for ig in window)
        )
        probe = _run_force_vector_auto_verify(
            src_path=tu_c, function=function, entries=entries,
            melee_root=melee_root, checkdiff_timeout=checkdiff_timeout,
            run_diagnostic_probes=force_vector_probes,
            # #620: bound each probe build so a hung mwcc/wibo child cannot stall
            # the union build indefinitely. A timed-out union -> status
            # "inconclusive" -> forced_class_clean False -> the solve loop
            # abstains cleanly instead of hanging.
            per_probe_timeout_s=(
                force_vector_timeout
                if force_vector_timeout is not None
                else _resolve_force_vector_probe_timeout()
            ),
            env=child_env,
            retain_pcdumps=retain_force_vector_pcdumps,
            retain_dir=retained_force_vector_dir,
        )
        forced_class_clean = (probe.get("union") or {}).get("status") == "match"
        force_cap_exceeded = (not forced_class_clean) and len(anchors) > FORCE_CAP
        if force_cap_exceeded:
            return _inert(
                phys_target=phys_target, force_iter_first=window,
                force_cap_exceeded=True,
                force_vector_probe=probe,
            )
        if not forced_class_clean:
            return _inert(
                phys_target=phys_target,
                force_iter_first=window,
                forced_class_clean=False,
                force_vector_probe=probe,
            )

        # ---- Steps 4-5: forced readback x2 (positions, ranks, igset, sha) --
        forced_ranks, forced_ig_set, sha1 = _order_target_forced_dump(
            tu_c=tu_c, function=function, class_id=class_id,
            force_iter_first=window, melee_root=melee_root,
        )
        applied_positions = {
            ig: forced_ranks[ig] - 1 for ig in window if ig in forced_ranks
        }
        _r2, _s2, sha2 = _order_target_forced_dump(
            tu_c=tu_c, function=function, class_id=class_id,
            force_iter_first=window, melee_root=melee_root,
        )

        # ---- Step 6: baseline self-reanchor over the phys-target roles -----
        baseline_compile = Compile.from_text(
            pcdump_text, function, tu_c.read_text(encoding="utf-8")
        )
        baseline_descs = build_descriptors(baseline_compile, class_id=class_id)
        baseline_ig_set = set(
            colorgraph_ranks(pcdump_text, function, class_id=class_id).keys()
        )
        self_ra = reanchor_descs(
            baseline_descs, baseline_descs, dict(phys_target), class_id=class_id,
        )
        self_reanchored_roles = {orig for _new, orig in self_ra.matched.items()}
        unscored_roles = [
            {"ig": ig, "reason": status}
            for ig, status in self_ra.diagnostics.items()
            if ig in phys_target
        ]

        return DeriveInputs(
            function=function, unit=unit, class_id=class_id,
            checkdiff_primary=checkdiff_primary,
            phys_target=phys_target, phys_conflicts=phys_conflicts,
            force_iter_first=window, applied_positions=applied_positions,
            forced_class_clean=forced_class_clean, forced_ranks=forced_ranks,
            baseline_ig_set=baseline_ig_set, forced_ig_set=forced_ig_set,
            self_reanchored_roles=self_reanchored_roles,
            unscored_roles=unscored_roles,
            forced_decisions_sha256=[sha1, sha2],
            baseline_source_sha256=hashlib.sha256(
                tu_c.read_bytes()).hexdigest()[:32],
            baseline_pcdump_sha256=hashlib.sha256(
                pcdump_text.encode()).hexdigest()[:32],
            force_cap_exceeded=False,
            direct_evidence_register_only=direct_evidence_register_only,
            natural_pcdump=fresh_natural_pcdump,
        )
def _resolve_force_vector_probe_timeout() -> float:
    """#620: per-probe wall-clock bound for force-vector union builds. Reuses the
    repo's hang-timeout knob — MWCC_DEBUG_FORCE_VECTOR_TIMEOUT, then
    MWCC_DEBUG_HANG_TIMEOUT — defaulting to 300s (a clean union build is well
    under this; the bug had it stalling >340s with no bound)."""
    for key in ("MWCC_DEBUG_FORCE_VECTOR_TIMEOUT", "MWCC_DEBUG_HANG_TIMEOUT"):
        val = os.environ.get(key)
        if val:
            try:
                return float(val)
            except ValueError:
                pass
    return 300.0
def _env_with_current_melee_agent_package(
    base_env: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    from src.cli.debug import _package_melee_root  # noqa: PLC0415
    env = dict(base_env) if base_env is not None else os.environ.copy()
    package_path = str(_package_melee_root() / "tools" / "melee-agent")
    existing = env.get("PYTHONPATH")
    paths = [package_path]
    if existing:
        paths.extend(
            path for path in existing.split(os.pathsep)
            if path and path != package_path
        )
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env
def _checkdiff_env_for_locked_child(*, disable_fingerprint: bool) -> dict[str, str]:
    from src.cli.debug import _checkdiff_env_without_fingerprint
    env = (
        _checkdiff_env_without_fingerprint()
        if disable_fingerprint
        else os.environ.copy()
    )
    env["CHECKDIFF_NO_LOCK"] = "1"
    return env
@contextmanager
def _acquire_source_score_repo_lock(
    melee_root: Path,
    *,
    timeout: float | None = None,
):
    from src.cli.debug import _acquire_checkdiff_repo_lock
    with _acquire_checkdiff_repo_lock(
        melee_root,
        label="source-scoring",
        timeout=timeout,
    ):
        yield
inspect_app = typer.Typer(
    help="Read, compare, and explain MWCC pcdumps."
)
def _parse_force_phys_class(raw: str) -> int:
    from src.cli.debug.dump import _FORCE_PHYS_CLASS_NAMES
    class_s = raw.strip().lower()
    if class_s in _FORCE_PHYS_CLASS_NAMES:
        return _FORCE_PHYS_CLASS_NAMES[class_s]
    try:
        class_id = int(class_s, 0)
    except ValueError as exc:
        raise typer.BadParameter(
            f"--force-phys class {raw!r} is invalid. Expected one of "
            "{gpr, fp, fpr, int, class0, class1} or a numeric class ID."
        ) from exc
    if class_id < 0:
        raise typer.BadParameter("--force-phys class ID must be non-negative")
    return class_id
def _normalize_force_phys(raw: str) -> tuple[str, list[str]]:
    """Parse and normalize a ``--force-phys`` value.

    Accepts two forms per spec:
      - Legacy: ``ig_idx:phys[,ig_idx:phys]*``
      - Class-scoped: ``class:ig_idx:phys[,class:ig_idx:phys]*``
        where class is one of ``gpr``, ``fp``, ``fpr``, ``int`` or a
        numeric class ID.

    Returns ``(dll_value, warnings)`` where:
      - ``dll_value`` is the force-phys string to pass to the DLL. Bare
        entries remain ``ig_idx:phys``; scoped entries become
        ``class_id:ig_idx:phys``.
      - ``warnings`` is a list of human-readable warning strings
        (empty when input is unambiguous).

    Raises ``typer.BadParameter`` on malformed input.
    """
    parts = raw.split(",")
    dll_parts: list[str] = []
    warnings: list[str] = []
    seen_bare: list[str] = []  # bare ig_idx values, to detect later if wanted

    for spec in parts:
        spec = spec.strip()
        if not spec:
            continue
        tokens = spec.split(":")
        if len(tokens) == 3:
            class_s, ig_idx_s, phys_s = tokens
            class_id = _parse_force_phys_class(class_s)
            dll_parts.append(f"{class_id}:{ig_idx_s}:{phys_s}")
        elif len(tokens) == 2:
            # Bare ig_idx:phys form. The DLL accepts this but it matches
            # all IG classes (GPR, FP, etc.) with that ig_idx, which can
            # be ambiguous when a GPR and an FP node share the same ig_idx.
            dll_parts.append(spec)
            seen_bare.append(tokens[0])
        else:
            raise typer.BadParameter(
                f"--force-phys spec {spec!r} is invalid. "
                f"Expected 'ig_idx:physReg' or 'class:ig_idx:physReg' "
                f"(class in {{gpr, fp, fpr, int, class0, class1}} or numeric). "
                f"E.g. '36:31' or 'gpr:36:31'."
            )

    if seen_bare:
        warnings.append(
            f"[force-phys] bare ig_idx form used ({', '.join(seen_bare)}): "
            f"the DLL will force ALL IG classes (GPR, FP, …) that have a "
            f"node with that ig_idx. If this matches multiple classes, "
            f"use 'class:ig_idx:phys' (e.g. 'gpr:{seen_bare[0]}:N') to "
            f"scope to one class and avoid unintended FP register overrides."
        )

    return ",".join(dll_parts), warnings
PPC_ABI_GPR = {
    1: "SP",
    2: "TOC",
    3: "arg0 / ret",
    4: "arg1",
    5: "arg2",
    6: "arg3",
    7: "arg4",
    8: "arg5",
    9: "arg6",
    10: "arg7",
}
def _abi_hint(physical: Optional[int], reg_kind: str = "r") -> str:
    """Return a short ABI hint for a physical register, or empty string."""
    if physical is None:
        return ""
    if reg_kind == "f":
        if physical >= 14:
            return "callee-save FPR"
        return "caller-save FPR"
    if physical == 0:
        return "scratch"  # r0 has special semantics in some PPC instructions
    if physical in PPC_ABI_GPR:
        return PPC_ABI_GPR[physical]
    if 11 <= physical <= 12:
        return "caller-save"
    if 13 <= physical <= 31:
        return "callee-save"
    return ""
def _virtreg_to_dict(info) -> dict:
    """Serialize a VirtualRegInfo for JSON output."""
    reg_kind = getattr(info, "reg_kind", "r")
    return {
        "reg_kind": reg_kind,
        "virtual": info.virtual,
        "physical": info.physical,
        "physical_class": info.physical_class,
        "abi_hint": _abi_hint(info.physical, reg_kind),
        "first_use": info.first_use,
        "last_use": info.last_use,
        "use_count": info.use_count,
        "interferes_with": sorted(info.interferes_with),
        "candidates": sorted(info.candidates),
    }
@inspect_app.command("analyze")
def analyze(
    dump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to a pcdump.txt produced by 'debug dump remote'. "
                 "If omitted, auto-resolves via --function from the "
                 "cache at build/mwcc_debug_cache/.",
        ),
    ] = None,
    function: Annotated[
        Optional[str],
        typer.Option(
            "--function", "-f",
            help="Show only this function (default: list all). Also "
                 "used to auto-resolve the pcdump path when not given.",
        ),
    ] = None,
    show_candidates: Annotated[
        bool,
        typer.Option(
            "--candidates",
            help="Show the set of physicals each virtual could have been "
                 "assigned (based on interferer constraints).",
        ),
    ] = True,
    json_out: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit structured JSON instead of human-readable text.",
        ),
    ] = False,
):
    """Summarize a pcdump.txt: per-virtual register live ranges, use counts,
    interferences, and 'could have been' candidate sets.

    Without --function, lists all functions with brief summary. With --function,
    prints a detailed coloring-decision table for that function — the kind of
    output that tells you whether a register-cascade question is constrained
    by interferences or is a free allocator choice.

    The 'Candidates' column shows physicals not used by interfering virtuals.
    If a virtual got a physical that's NOT the lowest-numbered candidate, that
    asymmetry is the kind of allocator-preference question worth digging into.
    """
    from src.cli.debug import _resolve_pcdump_path, parse_pcdump
    dump = _resolve_pcdump_path(dump, function)

    text = dump.read_text()
    funcs = parse_pcdump(text)

    if not funcs:
        print(f"No functions found in {dump}", file=sys.stderr)
        raise typer.Exit(code=1)

    if function is None:
        # List all functions, brief summary
        if json_out:
            payload = [
                {
                    "name": fn.name,
                    "n_passes": len(fn.passes),
                    "has_coloring": fn.get_pass("AFTER REGISTER COLORING") is not None,
                }
                for fn in funcs
            ]
            print(json.dumps({"dump": str(dump), "functions": payload}, indent=2))
            return
        print(f"Functions in {dump.name}:")
        for fn in funcs:
            n_passes = len(fn.passes)
            has_color = fn.get_pass("AFTER REGISTER COLORING") is not None
            color_note = "" if has_color else " (no coloring pass — truncated dump?)"
            print(f"  {fn.name}: {n_passes} passes{color_note}")
        return

    # Find the requested function
    target = next((fn for fn in funcs if fn.name == function), None)
    if target is None:
        avail = ", ".join(fn.name for fn in funcs)
        raise typer.BadParameter(
            f"function '{function}' not in dump. Available: {avail}"
        )

    if target.get_pass("AFTER REGISTER COLORING") is None:
        print(
            f"WARNING: {function} has no AFTER REGISTER COLORING pass — "
            "dump may be truncated. Analysis skipped.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    pre = target.last_precolor_pass()
    post = target.get_pass("AFTER REGISTER COLORING")
    if not json_out:
        print(f"Function: {target.name}")
        print(f"Pre-coloring pass: {pre.name if pre else '<none>'}")
        print(f"Post-coloring pass: {post.name}")
        print()

    infos = analyze_function(target)
    if not infos:
        if json_out:
            print(json.dumps({"function": target.name, "virtuals": [], "warning": "no virtual registers found"}, indent=2))
            return
        print("No virtual registers found (or pass alignment failed).")
        return

    if json_out:
        payload = {
            "function": target.name,
            "pre_coloring_pass": pre.name if pre else None,
            "post_coloring_pass": post.name,
            "virtuals": [_virtreg_to_dict(info) for info in infos],
        }
        print(json.dumps(payload, indent=2))
        return

    # PowerPC EABI reminder
    print("ABI: r3=arg0/ret, r4=arg1, r5=arg2, ..., r10=arg7; "
          "r13-r31=callee-save; r0=scratch.")
    print()

    # Column widths
    print(f"{'Virtual':>8}  {'Phys':>5}  {'Class':<8}  {'ABI':<14}  {'Live[first..last]':<18}  {'Uses':>5}  Interferes")
    print(f"{'-' * 8:>8}  {'-' * 5:>5}  {'-' * 8:<8}  {'-' * 14:<14}  {'-' * 18:<18}  {'-' * 5:>5}  ----------")
    for info in infos:
        reg_kind = getattr(info, "reg_kind", "r")
        phys = f"{reg_kind}{info.physical}" if info.physical is not None else "?"
        live = f"{info.first_use}..{info.last_use}"
        abi = _abi_hint(info.physical, reg_kind)
        # Format interferes_with as a compact list
        if info.interferes_with:
            interferers = ",".join(
                f"{reg_kind}{v}" for v in sorted(info.interferes_with)
            )
        else:
            interferers = "-"
        print(
            f"     {reg_kind}{info.virtual:<3}  {phys:>5}  {info.physical_class:<8}  "
            f"{abi:<14}  {live:<18}  {info.use_count:>5}  {interferers}"
        )

    if show_candidates:
        print()
        print("Coloring decisions. Verified algorithm (Tier 2 binary-hook data):")
        print("  1. Compute workingMask = volatile-regs (r3..r12, r0 excluded)")
        print("     minus regs used by interferers.")
        print("  2. If workingMask non-empty: pick LOWEST set bit.")
        print("  3. Else call obtain_nonvolatile_register(), which dispenses")
        print("     TOP-DOWN: r31, r30, r29, r28, r27, then r26, r25, ...")
        print("     (Once dispensed, reg is added to volatile-regs pool and")
        print("     can be reused for non-interfering virtuals.)")
        print("Run 'debug inspect simulate' to see what the allocator would pick + why.")
        print("For exact iteration order + per-decision data, see the")
        print("'COLORGRAPH DECISIONS' sections in the raw pcdump.")
        for info in infos:
            if info.physical is None or not info.candidates:
                continue
            cands = sorted(info.candidates)
            reg_kind = getattr(info, "reg_kind", "r")
            cand_str = "{" + ",".join(f"{reg_kind}{c}" for c in cands) + "}"
            abi = _abi_hint(info.physical, reg_kind)
            abi_note = f"  [{abi}]" if abi else ""
            print(
                f"  {reg_kind}{info.virtual} → {reg_kind}{info.physical}"
                f"{abi_note}.  Candidates: {cand_str}"
            )
@inspect_app.command("simulate")
def simulate(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to simulate (required)",
        ),
    ],
    dump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to a pcdump.txt produced by 'debug dump remote'. "
                 "If omitted, auto-resolves via --function from cache."
        ),
    ] = None,
    show_all: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Show every decision, even when prediction matches actual.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit simulation results as JSON."),
    ] = False,
):
    """Simulate MWCC's coloring algorithm on a function and diff against actuals.

    Re-implements the register-coloring loop from MWCC's source (extracted from
    the 7.0 decompilation at git.wuffs.org/MWCC). For each virtual register,
    the simulator predicts what physical the allocator would have picked and
    why. Compares against the actual choice from the pcdump.

    Matches confirm our understanding of the algorithm. Mismatches highlight
    cases where our model is wrong — usually due to factors we don't see in
    pcdump (caller-save kill at call sites, argument-passing ABI pinning, or
    nonvolatile-allocation-order edge cases).

    See docs/mwcc-debug-future-ideas.md for the long-term plan to replace
    this simulator with a real hook into mwcceppc.exe's allocator.
    """
    from src.cli.debug import _abort_function_not_in_dump, _resolve_pcdump_path, parse_pcdump
    dump = _resolve_pcdump_path(dump, function)
    text = dump.read_text()
    funcs = parse_pcdump(text)
    target = next((fn for fn in funcs if fn.name == function), None)
    if target is None:
        _abort_function_not_in_dump(function, [fn.name for fn in funcs])

    decisions = simulate_function(target)
    if not decisions:
        infos = analyze_function(target)
        has_fpr_virtuals = any(
            getattr(info, "reg_kind", "r") == "f" for info in infos
        )
        has_gpr_virtuals = any(
            getattr(info, "reg_kind", "r") == "r" for info in infos
        )
        if has_fpr_virtuals and not has_gpr_virtuals:
            message = (
                "FPR virtual registers found, but simulate is GPR-only; "
                "use `debug inspect analyze` for FPR mapping details."
            )
            if json_out:
                print(json.dumps({
                    "function": function,
                    "error": "fpr-virtuals-unsupported-by-gpr-simulator",
                    "message": message,
                }))
            else:
                print(message)
            return
        if json_out:
            print(json.dumps({"function": function, "error":
                              "no virtual registers found (or pass alignment failed)"}))
        else:
            print("No virtual registers found (or pass alignment failed).")
        raise typer.Exit(code=1)

    matches = sum(1 for d in decisions if d.actual_physical == d.predicted_physical)
    mismatches = len(decisions) - matches

    if json_out:
        print(json.dumps({
            "function": target.name,
            "summary": {
                "matches": matches,
                "mismatches": mismatches,
                "total": len(decisions),
            },
            "decisions": [{
                "virtual": d.virtual,
                "actual_physical": d.actual_physical,
                "predicted_physical": d.predicted_physical,
                "match": d.actual_physical == d.predicted_physical,
                "reasoning": d.reasoning,
            } for d in decisions],
        }, indent=2))
        return

    print(f"Function: {target.name}")
    print(f"Algorithm: MWCC-style greedy coloring (per 7.0 source). Iteration")
    print(f"order: ascending interferer count.")
    print()
    print(f"{'Virtual':>8}  {'Actual':>7}  {'Predicted':>9}  {'Match':>5}  Reasoning")
    print(f"{'-' * 8:>8}  {'-' * 7:>7}  {'-' * 9:>9}  {'-' * 5:>5}  ---------")

    for d in decisions:
        actual = f"r{d.actual_physical}" if d.actual_physical is not None else "?"
        predicted = f"r{d.predicted_physical}" if d.predicted_physical is not None else "SPILL"
        is_match = d.actual_physical == d.predicted_physical
        match_marker = "✓" if is_match else "✗"
        if show_all or not is_match:
            print(
                f"     r{d.virtual:<3}  {actual:>7}  {predicted:>9}  "
                f"{match_marker:>5}  {d.reasoning}"
            )

    print()
    print(f"Summary: {matches} match, {mismatches} mismatch "
          f"(out of {len(decisions)} virtuals)")

    if mismatches and not show_all:
        print("Use --all to see matching decisions too.")
@inspect_app.command("first-divergence")
def first_divergence_cmd(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name"),
    ],
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help=(
                "Target coloring as ig:phys[,ig:phys] (the map KEYS are the "
                "target node set). Required unless --frame is used."
            ),
        ),
    ] = None,
    dump: Annotated[
        Optional[Path],
        typer.Argument(help="pcdump (auto-resolved if omitted)"),
    ] = None,
    class_id: Annotated[
        int,
        typer.Option("--class", help="Register class (0=GPR, 1=FPR)"),
    ] = 0,
    source: Annotated[
        bool,
        typer.Option("--source", help="Attach advisory source ideas"),
    ] = False,
    frame: Annotated[
        bool,
        typer.Option(
            "--frame",
            help=(
                "Explain the first stack-frame/local-area divergence instead "
                "of allocator force-phys divergence."
            ),
        ),
    ] = False,
    expected_asm: Annotated[
        Optional[Path],
        typer.Option(
            "--expected-asm",
            help=(
                "Expected target asm for --frame. Omit to extract via "
                "`melee-agent extract get <function> --full`."
            ),
        ),
    ] = None,
    no_expected: Annotated[
        bool,
        typer.Option(
            "--no-expected",
            help="For --frame, inspect only the current pcdump without target asm.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable output."),
    ] = False,
):
    """Find the earliest allocator decision diverging from a same-source target.

    Gated allocator facts are derived mechanically from the recorded colorgraph;
    --source adds a NON-gated advisory layer (heuristic symbol-bridge mapping).
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT, _resolve_pcdump_path, _source_path_for_function, find_function, parse_hook_events, parse_pcdump
    if frame:
        if source:
            typer.echo(
                "--source is only valid for allocator --force-phys mode; "
                "frame mode emits source levers directly.",
                err=True,
            )
            raise typer.Exit(2)
        report = _first_divergence_frame_report(
            function,
            dump=dump,
            expected_asm=expected_asm,
            no_expected=no_expected,
        )
        if json_out:
            print(json.dumps(report, indent=2))
        else:
            print(_format_first_divergence_frame_report(report))
        return

    if force_phys is None:
        raise typer.BadParameter("--force-phys is required unless --frame is used")
    if expected_asm is not None or no_expected:
        raise typer.BadParameter("--expected-asm/--no-expected require --frame")

    from ...mwcc_debug import first_divergence as fd
    from ...mwcc_debug.colorgraph_parser import parse_hook_events, find_function

    dump_path = _resolve_pcdump_path(dump, function)
    text = dump_path.read_text()
    events = parse_hook_events(text)
    fev = find_function(events, function)
    if fev is None:
        raise typer.BadParameter(f"function {function!r} not found in dump")
    try:
        fp_map = fd.parse_force_phys_arg(force_phys)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))
    target = fd.TargetColoring(class_id=class_id, force_phys=fp_map)
    try:
        report = fd.analyze_first_divergence(fev, target)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))
    if source:
        # Advisory (non-gated): resolve the unit source + pre-coloring pass the
        # same way `virtual-to-var` does, then attach symbol-bridge ideas.
        # Degrades to structural-only ideas on any resolution failure.
        src_text, pre, src_file = "", None, None
        try:
            fn = next((f for f in parse_pcdump(text) if f.name == function), None)
            if fn is not None:
                pre = fn.last_precolor_pass()
            source_path = _source_path_for_function(function, DEFAULT_MELEE_ROOT)
            if source_path is not None:
                src_text = source_path.read_text()
                try:
                    src_file = str(source_path.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    src_file = str(source_path)
        except Exception:
            src_text, pre, src_file = "", None, None
        report = fd.FirstDivergenceReport(
            fact=report.fact,
            source=fd.attach_source_ideas(
                report.fact, src_text, function, pre, source_file=src_file),
        )
    if json_out:
        print(json.dumps(fd.report_to_dict(report), indent=2))
    else:
        typer.echo(fd.format_report(report))


@inspect_app.command("lifetime-pressure")
def inspect_lifetime_pressure(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to inspect."),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help=(
                "Baseline pcdump. Auto-resolves from cache when omitted "
                "unless --backend-trace is used."
            ),
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help="Source file for source attribution and validation commands.",
        ),
    ] = None,
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help="Target coloring as ig:phys[,ig:phys] or class:ig:phys entries.",
        ),
    ] = None,
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target",
            help="JSON target file consumed by the pressure explorer.",
        ),
    ] = None,
    candidates: Annotated[
        Optional[list[str]],
        typer.Option(
            "--candidate",
            help="Candidate to compare or validate, repeatable. Format LABEL=PATH.",
        ),
    ] = None,
    backend_trace: Annotated[
        Optional[Path],
        typer.Option(
            "--backend-trace",
            help="Allocator backend trace JSON. Skips pcdump auto-resolution.",
        ),
    ] = None,
    class_id: Annotated[
        int,
        typer.Option("--class", help="Default register class for --force-phys."),
    ] = 0,
    allow_stale_pcdump: Annotated[
        bool,
        typer.Option(
            "--allow-stale-pcdump",
            help="Allow stale pcdump/source freshness when ranking hypotheses.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit structured JSON instead of text."),
    ] = False,
    dot: Annotated[
        Optional[Path],
        typer.Option("--dot", help="Write Graphviz DOT blocker graph to PATH."),
    ] = None,
    blocker_table: Annotated[
        Optional[Path],
        typer.Option(
            "--blocker-table",
            help="Write blocker table to PATH. Uses JSON for .json, CSV otherwise.",
        ),
    ] = None,
    validate: Annotated[
        str,
        typer.Option(
            "--validate",
            help="Validation mode: none, quick, bounded, or remote.",
        ),
    ] = "none",
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Validation subprocess timeout in seconds."),
    ] = 120,
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            help="Maximum bounded-validation candidates to try.",
        ),
    ] = 100,
):
    """Explain allocator lifetime pressure blockers and follow-up validation."""
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _resolve_pcdump_path,
        _source_path_for_function,
    )
    from src.mwcc_debug.pressure_explorer import (  # noqa: PLC0415
        build_lifetime_pressure_report,
        render_blocker_table_csv,
        render_blocker_table_json,
        render_dot,
        render_json_report,
        render_text_report,
    )

    validate_modes = {"none", "quick", "bounded", "remote"}
    if validate not in validate_modes:
        raise typer.BadParameter(
            f"--validate must be one of {', '.join(sorted(validate_modes))}"
        )

    if backend_trace is not None:
        try:
            with backend_trace.open("r", encoding="utf-8"):
                pass
        except OSError:
            typer.echo(
                f"backend trace not found or unreadable: {backend_trace}",
                err=True,
            )
            raise typer.Exit(2)

    pcdump_path = pcdump
    pcdump_text: str | None = None
    if backend_trace is None:
        pcdump_path = _resolve_pcdump_path(pcdump, function, DEFAULT_MELEE_ROOT)
        pcdump_text = pcdump_path.read_text(encoding="utf-8", errors="replace")

    warnings: list[str] = []
    resolved_source = source_file
    if resolved_source is None:
        try:
            resolved_source = _source_path_for_function(function, DEFAULT_MELEE_ROOT)
        except Exception as exc:
            warnings.append(f"source file auto-resolution failed: {exc}")
            resolved_source = None

    source_text: str | None = None
    if resolved_source is None:
        warnings.append("source file could not be resolved")
    elif resolved_source.exists():
        source_text = resolved_source.read_text(encoding="utf-8", errors="replace")
    else:
        warnings.append(f"source file not found: {resolved_source}")

    try:
        report = build_lifetime_pressure_report(
            function=function,
            pcdump_text=pcdump_text,
            pcdump_path=pcdump_path,
            source_text=source_text,
            source_path=resolved_source,
            force_phys=force_phys,
            target_path=target,
            candidates=list(candidates or []),
            backend_trace_path=backend_trace,
            class_id=class_id,
            allow_stale_pcdump=allow_stale_pcdump,
            validate_mode=validate,
            timeout=timeout,
            max_candidates=max_candidates,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    if warnings:
        report = dataclasses.replace(report, warnings=(*report.warnings, *warnings))

    if dot is not None:
        _write_text_creating_parent(dot, render_dot(report))
    if blocker_table is not None:
        if blocker_table.suffix.lower() == ".json":
            _write_text_creating_parent(
                blocker_table,
                json.dumps(render_blocker_table_json(report), indent=2) + "\n",
            )
        else:
            _write_text_creating_parent(
                blocker_table,
                render_blocker_table_csv(report),
            )

    if json_out:
        print(json.dumps(render_json_report(report), indent=2))
    else:
        print(render_text_report(report), end="")


def _write_text_creating_parent(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _first_divergence_frame_case(report: dict) -> str:
    if report.get("expected") is None:
        return "frame-current-only"
    if report.get("current_low_frame_expansion") is not None:
        return "frame-unused-low-home"
    if report.get("extra_low_frame_reservation") is not None:
        return "frame-missing-low-reservation"
    if report.get("frame_delta"):
        return "frame-size"
    return "none"
def _first_divergence_frame_local_target(case: str, residual: dict | None) -> str:
    if case == "frame-unused-low-home":
        text = (
            "suppress the unused low local home by changing the source shape "
            "that created it; for held-FP constants, try splitting the constant "
            "lifetime or using the literal/global expression at the final FP call"
        )
        if residual and residual.get("alignment_growth_bytes"):
            text += (
                ", then reduce the downstream 8-byte alignment growth from the "
                "int-to-float scratch slot"
            )
        return text
    if case == "frame-missing-low-reservation":
        return (
            "introduce the target's low-frame reservation naturally, or use "
            "frame patch/probe verification to confirm the expected frame is reachable"
        )
    if case == "frame-size":
        return (
            "derive a frame target from checkdiff and rank source candidates by "
            "frame-size and unused-range distance"
        )
    if case == "none":
        return "no frame/local-area divergence detected"
    return "inspect the current frame without a target frame comparison"
def _frame_residual_for_case(report: dict, case: str) -> dict | None:
    if case == "frame-unused-low-home":
        return report.get("current_low_frame_expansion")
    if case == "frame-missing-low-reservation":
        return report.get("extra_low_frame_reservation")
    return None
def _first_divergence_frame_report(
    function: str,
    *,
    dump: Path | None,
    expected_asm: Path | None,
    no_expected: bool,
) -> dict:
    from src.cli.debug import DEFAULT_MELEE_ROOT, _abort_frame_function_not_in_dump, _attach_frame_function_aliases, _find_unit_for_function, _frame_source_suggestions_from_report, _pcdump_has_symbolic_stack_homes, _read_frame_reservation_current_asm
    from src.cli.debug import _read_frame_reservation_expected_asm, _resolve_frame_function_names, _resolve_pcdump_path
    melee_root = DEFAULT_MELEE_ROOT
    dump_path = _resolve_pcdump_path(dump, function, melee_root)
    pcdump_text = dump_path.read_text()
    names = _resolve_frame_function_names(function, pcdump_text, melee_root)
    if names is None:
        _abort_frame_function_not_in_dump(function, pcdump_text)
    expected_text = _read_frame_reservation_expected_asm(
        names.report_function,
        expected_asm=expected_asm,
        no_expected=no_expected,
        melee_root=melee_root,
    )
    current_text = (
        _read_frame_reservation_current_asm(
            names.report_function,
            melee_root=melee_root,
        )
        if _pcdump_has_symbolic_stack_homes(pcdump_text)
        else None
    )
    try:
        frame_report = analyze_frame_reservations(
            pcdump_text,
            names.pcdump_function,
            expected_asm_text=expected_text,
            current_asm_text=current_text,
            display_function=function,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    _attach_frame_function_aliases(frame_report, names)

    case = _first_divergence_frame_case(frame_report)
    residual = _frame_residual_for_case(frame_report, case)
    unit = _find_unit_for_function(names.report_function, melee_root)
    suggestions = _frame_source_suggestions_from_report(frame_report, unit=unit)
    next_steps = [
        f"melee-agent debug inspect frame-reservations -f {function}",
        f"melee-agent debug suggest frame -f {function}",
    ]
    for suggestion in suggestions:
        for command in suggestion.get("commands") or []:
            if command not in next_steps:
                next_steps.append(command)

    residual_payload = None
    if isinstance(residual, dict):
        residual_payload = {
            "range": {
                "start": residual.get("start"),
                "end": residual.get("end"),
                "size": residual.get("size"),
            },
            "origin": residual.get("origin"),
            "frame_growth_bytes": residual.get("frame_growth_bytes"),
            "alignment_growth_bytes": residual.get("alignment_growth_bytes"),
            "current_accesses_in_range": residual.get("current_accesses_in_range", []),
        }

    current = frame_report.get("current") or {}
    expected = frame_report.get("expected") or {}
    return {
        "kind": "frame-local-area",
        "function": function,
        "case": case,
        "summary": frame_report.get("summary"),
        "current_frame": current.get("frame_size"),
        "target_frame": expected.get("frame_size"),
        "frame_delta": frame_report.get("frame_delta"),
        "residual": residual_payload,
        "local_target": _first_divergence_frame_local_target(case, residual),
        "next_steps": next_steps,
        "suggestions": suggestions,
        "frame": frame_report,
    }
def _format_first_divergence_frame_report(report: dict) -> str:
    lines = ["=== FRAME/LOCAL-AREA FACTS (gated) ==="]
    lines.append(
        "First divergence: frame/local-area "
        f"Case {report['case']}"
    )
    lines.append(f"  current frame: {report.get('current_frame')}")
    lines.append(f"  target frame: {report.get('target_frame')}")
    lines.append(f"  frame delta: {report.get('frame_delta')}")
    residual = report.get("residual")
    if residual is not None:
        range_info = residual["range"]
        if range_info.get("start") is not None:
            lines.append(
                "  residual range: "
                + _format_stack_range({
                    "start": range_info["start"],
                    "end": range_info["end"],
                    "size": range_info["size"],
                })
            )
        if residual.get("origin"):
            lines.append(f"  origin: {residual['origin']}")
        if residual.get("frame_growth_bytes") is not None:
            lines.append(f"  frame growth bytes: {residual['frame_growth_bytes']}")
        if residual.get("alignment_growth_bytes") is not None:
            lines.append(
                f"  alignment growth bytes: {residual['alignment_growth_bytes']}"
            )
    lines.append(f"  local target: {report['local_target']}")
    lines.append("")
    lines.append("=== SOURCE IDEAS (ADVISORY, not validated) ===")
    suggestions = report.get("suggestions") or []
    if suggestions:
        for suggestion in suggestions:
            lines.append(f"  {suggestion['rank']}. {suggestion['kind']}")
            lines.append(f"     {suggestion['description']}")
    else:
        lines.append("  (no frame source suggestions available)")
    lines.append("")
    lines.append("=== NEXT STEPS ===")
    for step in report.get("next_steps") or []:
        lines.append(f"  {step}")
    return "\n".join(lines)
@inspect_app.command("diff")
def diff(
    input_a: Annotated[
        str,
        typer.Argument(help="First source or pcdump file"),
    ],
    input_b: Annotated[
        str,
        typer.Argument(help="Second source or pcdump file"),
    ],
    function: Annotated[
        Optional[str],
        typer.Option(
            "--fn",
            "--function",
            "-f",
            help="Function to diff. Required for MVP.",
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            "-t",
            help="Per-source `debug dump local` timeout in seconds.",
        ),
    ] = 90,
    inspect_a: Annotated[
        Optional[Path],
        typer.Option(
            "--inspect-a",
            help="mwcc-inspect output for the first input. Requires --inspect-b.",
        ),
    ] = None,
    inspect_b: Annotated[
        Optional[Path],
        typer.Option(
            "--inspect-b",
            help="mwcc-inspect output for the second input. Requires --inspect-a.",
        ),
    ] = None,
    source_inspect: Annotated[
        bool,
        typer.Option(
            "--source-inspect",
            help=(
                "Also run tools/workflow/mwcc-inspect.sh for .c inputs. "
                "Default source mode is local pcdump-only."
            ),
        ),
    ] = False,
):
    """Compare two source or pcdump inputs through the mwcc-debug pipeline.

    Existing `.txt` inputs are treated as already-captured pcdumps. `.c`
    inputs are compiled with `debug dump local --no-cache-sync`, then the
    resulting pass snapshots are compared in pipeline order without running
    the heavier mwcc-inspect front-end workflow. Pass `--source-inspect` to
    run mwcc-inspect for `.c` inputs, or pass `--inspect-a/--inspect-b` to
    include pre-captured front-end snapshots in the same staged lowering
    report.
    """
    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        read_inspect_input_if_available,
        read_or_compile_input,
    )
    if function is None:
        typer.echo("--fn/--function is required for mwcc-debug diff MVP.", err=True)
        raise typer.Exit(2)
    if (inspect_a is None) != (inspect_b is None):
        typer.echo("--inspect-a and --inspect-b must be passed together.", err=True)
        raise typer.Exit(2)
    if inspect_a is not None and not inspect_a.is_file():
        typer.echo(f"--inspect-a not found: {inspect_a}", err=True)
        raise typer.Exit(2)
    if inspect_b is not None and not inspect_b.is_file():
        typer.echo(f"--inspect-b not found: {inspect_b}", err=True)
        raise typer.Exit(2)

    melee_root = DEFAULT_MELEE_ROOT
    try:
        resolved_a = resolve_diff_input("A", input_a, function=function, melee_root=melee_root)
        resolved_b = resolve_diff_input("B", input_b, function=function, melee_root=melee_root)
        text_a = read_or_compile_input(
            resolved_a,
            function=function,
            melee_root=melee_root,
            timeout=timeout,
        )
        text_b = read_or_compile_input(
            resolved_b,
            function=function,
            melee_root=melee_root,
            timeout=timeout,
        )
        if inspect_a is not None and inspect_b is not None:
            inspect_text_a = inspect_a.read_text(encoding="utf-8", errors="replace")
            inspect_text_b = inspect_b.read_text(encoding="utf-8", errors="replace")
        elif source_inspect:
            inspect_text_a = read_inspect_input_if_available(
                resolved_a,
                function=function,
                melee_root=melee_root,
                timeout=timeout,
            )
            inspect_text_b = read_inspect_input_if_available(
                resolved_b,
                function=function,
                melee_root=melee_root,
                timeout=timeout,
            )
        else:
            if resolved_a.kind == "source" or resolved_b.kind == "source":
                typer.echo(
                    "[mwcc-debug] source inputs are using local pcdump-only diff; "
                    "pass --source-inspect or --inspect-a/--inspect-b to include "
                    "mwcc-inspect front-end snapshots.",
                    err=True,
                )
            inspect_text_a = None
            inspect_text_b = None
        if (inspect_text_a is None) != (inspect_text_b is None):
            typer.echo(
                "[mwcc-debug] mwcc-inspect snapshot unavailable for one side; "
                "comparing backend pcdump passes only.",
                err=True,
            )
            inspect_text_a = None
            inspect_text_b = None
        report = compare_function_dumps(
            text_a,
            text_b,
            function=function,
            label_a=resolved_a.label if resolved_a.label != "A" else input_a,
            label_b=resolved_b.label if resolved_b.label != "B" else input_b,
            inspect_text_a=inspect_text_a,
            inspect_text_b=inspect_text_b,
        )
    except CompileFailure as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(e.returncode or 1)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2)

    typer.echo(render_text_report(report))
def _get_asm_hunks(
    function: str, melee_root: Path, top_n: int = 5,
) -> Optional[list[list[str]]]:
    """Run checkdiff in JSON mode and group its unified-diff lines into
    hunks of consecutive +/- changes. Each hunk gets a small context
    window around it for readability.

    Returns:
        list of hunks (each a list of lines), or None if checkdiff
        couldn't run / produce JSON / find a meaningful diff.

    The 'top N' selection is by hunk size — longest hunks first, since
    those tend to encode the most informative differences.
    """
    from src.cli.debug import _checkdiff_env_without_fingerprint
    try:
        proc = subprocess.run(
            ["python", "tools/checkdiff.py", function,
             "--format", "json", "--no-build"],
            cwd=melee_root, capture_output=True, text=True, timeout=60,
            env=_checkdiff_env_without_fingerprint(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    # checkdiff returns 1 when there's a mismatch (expected for stuck fns)
    if proc.returncode not in (0, 1) or not proc.stdout:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    diff_lines = data.get("diff", [])
    if not diff_lines:
        return None

    # Group lines into hunks. A hunk = a span containing +/- lines with
    # up to 1 line of intermediate context. checkdiff produces unified-
    # diff format, so context lines start with ' ' and change lines
    # start with '+'/'-'. The first 3 lines are the file header.
    body = diff_lines[3:] if len(diff_lines) >= 3 else diff_lines
    hunks: list[list[str]] = []
    cur: list[str] = []
    blank_run = 0
    for line in body:
        if line.startswith("@@"):
            # objdiff hunk header — boundary
            if cur:
                hunks.append(cur)
                cur = []
            blank_run = 0
            continue
        if line.startswith("+") or line.startswith("-"):
            cur.append(line)
            blank_run = 0
        elif cur:
            # Context line inside a hunk — keep tightly bound (one line
            # of slack), then close on the next.
            cur.append(line)
            blank_run += 1
            if blank_run >= 2:
                hunks.append(cur[:-1])  # drop the trailing context lines
                cur = []
                blank_run = 0
    if cur:
        hunks.append(cur)

    if not hunks:
        return None
    # Score by number of change lines (longer = more interesting)
    def _score(h: list[str]) -> int:
        return sum(1 for l in h if l.startswith("+") or l.startswith("-"))
    hunks.sort(key=_score, reverse=True)
    return hunks[:top_n]
def _get_checkdiff_classification(
    function: str,
    melee_root: Path,
) -> dict | None:
    from src.cli.debug import _checkdiff_env_without_fingerprint
    try:
        proc = subprocess.run(
            [
                "python",
                "tools/checkdiff.py",
                function,
                "--format",
                "json",
                "--no-build",
                "--no-name-magic",
                "--no-fingerprint",
            ],
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=60,
            env=_checkdiff_env_without_fingerprint(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1) or not proc.stdout:
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    classification = payload.get("classification")
    return classification if isinstance(classification, dict) else None
def _frame_residual_hint_from_checkdiff_classification(
    function: str,
    classification: dict | None,
    *,
    unit: str | None,
) -> dict | None:
    if not classification:
        return None
    primary = classification.get("primary")
    reasons = classification.get("reasons") or []
    reason_text = "\n".join(str(reason).lower() for reason in reasons)
    src_arg = _frame_source_path_for_unit(unit) or "<source.c>"
    taxonomy = classify_frame_taxonomy(
        function,
        classification=classification,
        source_path=_frame_source_path_for_unit(unit),
    )

    if primary == "stack-layout" and (
        "frame reservation gap" in reason_text
        or "pad_stack" in reason_text
        or "frame size" in reason_text
    ):
        hint = {
            "kind": "frame-size",
            "origin": "checkdiff-classification",
            "subcategory": _frame_subcategory_from_taxonomy(
                classification,
                taxonomy or {},
            ),
            "message": (
                f"{function}: checkdiff reports a stack frame-size residual. "
                "Decl-order probes can move local slots but cannot change the "
                "reserved frame size, so prefer frame-reservation tools first."
            ),
            "summary": "frame-size residual from checkdiff classification",
            "next_steps": (
                _frame_taxonomy_next_steps(function, taxonomy, unit=unit)
                if taxonomy is not None
                else [
                    f"melee-agent debug inspect frame-reservations -f {function}",
                    f"melee-agent debug suggest frame -f {function}",
                    (
                        f"melee-agent debug dump local {src_arg} -f {function} "
                        "--diff --force-frame-from-diff"
                    ),
                ]
            ),
        }
        if taxonomy is not None:
            _attach_frame_taxonomy_hint_fields(hint, taxonomy)
        return hint

    if primary == "stack-slot-layout":
        reserved_ceiling = (
            taxonomy is not None
            and taxonomy.get("cause") == "reserved-unused-low-spill-region"
        )
        same_slot_message = (
            f"{function}: checkdiff reports same-frame stack-slot "
            "placement differences. Inspect the stack-home assignment "
            "order first, then use lifetime/layout probes; decl-order "
            "search is usually neutral on this class."
        )
        if (
            not reserved_ceiling
            and isinstance(taxonomy, Mapping)
            and taxonomy.get("match_relevance") == "match-neutral"
        ):
            same_slot_message = (
                f"{function}: checkdiff reports same-frame stack-slot "
                "placement differences. This is a match-neutral frame "
                "residual: closing the offset-only frame delta should not be "
                "treated as the match gate. Inspect the stack-home assignment "
                "order first, then use lifetime/layout probes only if you need "
                "to explain the offset noise."
            )
        hint = {
            "kind": "same-frame-stack-slot-placement",
            "origin": "checkdiff-classification",
            "subcategory": "same-frame-stack-slot-placement",
            "message": (
                (
                    f"{function}: checkdiff reports a reserved-but-unused "
                    "low spill region. Treat this as a CURRENT-STRUCTURE frame "
                    "residual (not a verdict on the function): inspect the frame "
                    "model, and try structural source levers + a permuter sweep "
                    "before concluding it is exhausted."
                )
                if reserved_ceiling
                else same_slot_message
            ),
            "summary": (
                "reserved low spill region from checkdiff classification"
                if reserved_ceiling
                else "same-frame stack-slot residual from checkdiff classification"
            ),
            "next_steps": (
                _frame_taxonomy_next_steps(function, taxonomy, unit=unit)
                if taxonomy is not None
                else [
                    f"melee-agent debug inspect frame-reservations -f {function}",
                    (
                        f"melee-agent debug mutate lifetime-layout -f {function} "
                        "--compile-probes"
                    ),
                ]
            ),
        }
        if taxonomy is not None:
            _attach_frame_taxonomy_hint_fields(hint, taxonomy)
        return hint
    return None
def _format_asm_hunks(hunks: list[list[str]], max_lines_per_hunk: int = 12) -> str:
    """Render hunks compactly: cap each hunk at max_lines_per_hunk
    (with a '...(N more)' footer if truncated). Returns the formatted
    block, ready to print after a header.
    """
    out: list[str] = []
    for i, hunk in enumerate(hunks):
        if i > 0:
            out.append("  ---")
        n_show = min(len(hunk), max_lines_per_hunk)
        for line in hunk[:n_show]:
            out.append(f"  {line}")
        if len(hunk) > n_show:
            out.append(f"  ...({len(hunk) - n_show} more lines)")
    return "\n".join(out)
@inspect_app.command("asm")
def inspect_asm(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to disassemble"),
    ],
    no_build: Annotated[
        bool,
        typer.Option(
            "--no-build",
            help="Skip rebuilding and show the current compiled .o as-is.",
        ),
    ] = False,
    build_timeout: Annotated[
        float,
        typer.Option(
            "--build-timeout",
            help="Timeout in seconds for each checkdiff build/report step.",
        ),
    ] = 60.0,
) -> None:
    """Show the current compiled assembly for a function."""
    from src.cli.debug import DEFAULT_MELEE_ROOT, _checkdiff_env_without_fingerprint
    cmd = [
        "python",
        "tools/checkdiff.py",
        function,
        "--format",
        "json",
    ]
    if no_build:
        cmd.append("--no-build")
    else:
        cmd.extend(["--build-timeout", f"{build_timeout:g}"])

    proc = subprocess.run(
        cmd,
        cwd=DEFAULT_MELEE_ROOT,
        capture_output=True,
        text=True,
        env=_checkdiff_env_without_fingerprint(),
    )
    if proc.returncode not in (0, 1):
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        if proc.stdout:
            typer.echo(proc.stdout.rstrip(), err=True)
        raise typer.Exit(proc.returncode)

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        typer.echo(f"checkdiff did not emit JSON: {exc}", err=True)
        if proc.stderr:
            typer.echo(proc.stderr.rstrip(), err=True)
        raise typer.Exit(2)

    current_asm = payload.get("current_asm")
    if not isinstance(current_asm, list) or not all(
        isinstance(line, str) for line in current_asm
    ):
        typer.echo("checkdiff JSON did not include current_asm lines", err=True)
        raise typer.Exit(2)
    typer.echo("\n".join(current_asm))
def _read_stack_home_probe_results_json(
    path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not path.exists():
        raise typer.BadParameter(f"probe results JSON not found: {path}")
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"invalid probe results JSON: {exc}") from exc
    metadata: dict[str, Any] = {}
    if isinstance(payload, list):
        variants = payload
    elif isinstance(payload, dict):
        variants = payload.get("variants")
        if variants is None:
            evaluation = payload.get("stack_home_probe_evaluation")
            if isinstance(evaluation, dict):
                variants = evaluation.get("variants")
        semantic_status = payload.get("semantic_lever_status")
        if not isinstance(semantic_status, Mapping):
            frame_report = payload.get("frame_report")
            if isinstance(frame_report, Mapping):
                semantic_status = frame_report.get("semantic_lever_status")
        if isinstance(semantic_status, Mapping):
            metadata["semantic_lever_status"] = dict(semantic_status)
    else:
        variants = None
    if not isinstance(variants, list):
        raise typer.BadParameter(
            "probe results JSON must be a variants array or an object with variants"
        )
    return [
        dict(item) for item in variants
        if isinstance(item, Mapping)
    ], metadata
def _format_stack_range(item: Mapping[str, object]) -> str:
    start = int(item["start"])
    end = int(item["end"])
    size = int(item["size"])
    return f"0x{start:x}-0x{end:x} ({size} bytes)"
def _print_unused_ranges(label: str, ranges: list[dict]) -> None:
    print(f"{label} unused ranges:")
    if not ranges:
        print("  none")
        return
    for item in ranges:
        print(f"  {_format_stack_range(item)}")
def _format_words_suffix(item: Mapping[str, object]) -> str:
    word_count = item.get("word_count")
    if isinstance(word_count, int):
        return f", {word_count} words"
    return ""
def _format_byte_word_delta(byte_count: object, word_count: object) -> str:
    if not isinstance(byte_count, int):
        return "unknown bytes"
    if isinstance(word_count, int):
        return f"{byte_count} bytes ({word_count} words)"
    return f"{byte_count} bytes"
def _print_outgoing_parameter_area_floor(floor: object) -> None:
    if not isinstance(floor, Mapping):
        return
    current = floor.get("current_floor")
    expected = floor.get("expected_floor")
    if not isinstance(current, Mapping) or not isinstance(expected, Mapping):
        return
    print()
    print(f"outgoing parameter area floor: {floor.get('status')}")
    print(
        "current floor: "
        f"{_format_stack_range(current)}{_format_words_suffix(current)}"
    )
    print(
        "expected floor: "
        f"{_format_stack_range(expected)}{_format_words_suffix(expected)}"
    )
    print(
        "floor delta: "
        + _format_byte_word_delta(
            floor.get("floor_delta_bytes"),
            floor.get("floor_delta_words"),
        )
    )
    word_model = floor.get("parameter_word_count_model")
    if isinstance(word_model, Mapping):
        current_words = word_model.get("current_parameter_words")
        expected_words = word_model.get("expected_parameter_words")
        extra_words = word_model.get("extra_parameter_words")
        if isinstance(current_words, int) and isinstance(expected_words, int):
            suffix = f" (+{extra_words})" if isinstance(extra_words, int) else ""
            print(
                "parameter words: "
                f"{current_words} current vs {expected_words} expected{suffix}"
            )
        non_param = word_model.get("current_low_unused_non_parameter_words")
        if isinstance(non_param, int) and non_param > 0:
            print(f"non-parameter low gap: {non_param} word(s)")
        reason = word_model.get("reason")
        if isinstance(reason, str) and reason:
            print(f"sizing reason: {reason}")
    unused_delta = floor.get("unused_range_delta_bytes")
    if isinstance(unused_delta, int) and unused_delta != floor.get("floor_delta_bytes"):
        print(f"unused-range delta: {unused_delta} bytes")
    shifted = floor.get("first_shifted_stack_home")
    if isinstance(shifted, Mapping):
        current_offset = shifted.get("current_offset")
        expected_offset = shifted.get("expected_offset")
        delta = shifted.get("offset_delta")
        if isinstance(current_offset, int) and isinstance(expected_offset, int):
            sign = "+" if isinstance(delta, int) and delta > 0 else ""
            print(
                "first shifted stack home: "
                f"{shifted.get('symbol')} "
                f"0x{current_offset:x}->0x{expected_offset:x} "
                f"({sign}{delta})"
            )
    attribution = floor.get("call_attribution")
    if isinstance(attribution, Mapping) and attribution.get("status"):
        reason = attribution.get("reason")
        print(f"call attribution: {attribution.get('status')}")
        if reason:
            print(f"reason: {reason}")
def _print_stack_home_order_summary(current: Mapping[str, object]) -> None:
    summary = current.get("stack_home_order_summary")
    if not isinstance(summary, Mapping) or summary.get("status") != "computed":
        return
    assignments = summary.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        return
    status = "mismatch" if summary.get("has_order_mismatch") else "matches offsets"
    print()
    print(f"stack-home assignment order: {status}")
    print(
        "assignments: "
        f"{summary.get('assignment_count')}, "
        f"max order delta: {summary.get('max_abs_order_delta')}"
    )
    ranked = sorted(
        (item for item in assignments if isinstance(item, Mapping)),
        key=lambda item: (
            abs(int(item.get("order_delta") or 0)),
            -int(item.get("assignment_order") or 0),
        ),
        reverse=True,
    )
    for item in ranked[:5]:
        delta = int(item.get("order_delta") or 0)
        sign = "+" if delta > 0 else ""
        offset = item.get("offset")
        offset_text = "?" if offset is None else f"0x{int(offset):x}"
        print(
            f"  {item.get('symbol')}: "
            f"assign #{item.get('assignment_order')}, "
            f"offset #{item.get('offset_order')}, "
            f"delta {sign}{delta}, "
            f"offset {offset_text}"
        )
    expected_summary = current.get("stack_home_expected_order_summary")
    if (
        isinstance(expected_summary, Mapping)
        and expected_summary.get("status") == "computed"
    ):
        expected_assignments = expected_summary.get("assignments")
        if isinstance(expected_assignments, list) and expected_assignments:
            target_status = (
                "mismatch"
                if expected_summary.get("has_expected_offset_mismatch")
                else "matches target"
            )
            print(f"target stack-home offsets: {target_status}")
            print(
                "target assignments: "
                f"{expected_summary.get('assignment_count')}, "
                "max target order delta: "
                f"{expected_summary.get('max_abs_expected_order_delta')}, "
                "max offset delta: "
                f"{expected_summary.get('max_abs_offset_delta')}"
            )
            target_ranked = sorted(
                (
                    item for item in expected_assignments
                    if isinstance(item, Mapping)
                ),
                key=lambda item: (
                    abs(int(item.get("offset_delta") or 0)),
                    abs(int(item.get("expected_order_delta") or 0)),
                    -int(item.get("assignment_order") or 0),
                ),
                reverse=True,
            )
            for item in target_ranked[:5]:
                offset_delta = int(item.get("offset_delta") or 0)
                order_delta = int(item.get("expected_order_delta") or 0)
                offset_sign = "+" if offset_delta > 0 else ""
                order_sign = "+" if order_delta > 0 else ""
                current_offset = item.get("offset")
                expected_offset = item.get("expected_offset")
                current_text = (
                    "?" if current_offset is None else f"0x{int(current_offset):x}"
                )
                expected_text = (
                    "?" if expected_offset is None else f"0x{int(expected_offset):x}"
                )
                print(
                    f"  {item.get('symbol')}: "
                    f"assign #{item.get('assignment_order')}, "
                    f"target offset #{item.get('expected_offset_order')}, "
                    f"target order delta {order_sign}{order_delta}, "
                    f"offset {current_text} -> {expected_text} "
                    f"({offset_sign}{offset_delta})"
                )
            permutation = current.get("stack_home_target_permutation")
            if (
                isinstance(permutation, Mapping)
                and permutation.get("status") == "computed"
                and permutation.get("needs_permutation")
            ):
                current_order = permutation.get("current_offset_order")
                expected_order = permutation.get("expected_offset_order")
                if isinstance(current_order, list) and isinstance(expected_order, list):
                    print(
                        "target permutation: "
                        f"{', '.join(str(item) for item in current_order)} -> "
                        f"{', '.join(str(item) for item in expected_order)}"
                    )
                cycles = permutation.get("cycles")
                if isinstance(cycles, list):
                    for cycle in cycles[:3]:
                        if not isinstance(cycle, Mapping):
                            continue
                        symbols = cycle.get("symbols")
                        if isinstance(symbols, list) and symbols:
                            print(
                                "  cycle: "
                                + " -> ".join(str(symbol) for symbol in symbols)
                            )
    guidance = current.get("stack_home_reorder_guidance")
    if not isinstance(guidance, Mapping):
        return
    verdict = guidance.get("verdict")
    if verdict:
        print(f"reorder verdict: {verdict}")
    validated_verdict = guidance.get("validated_verdict")
    if isinstance(validated_verdict, Mapping) and validated_verdict.get("status"):
        print(
            "validated reorder verdict: "
            f"{validated_verdict.get('status')} - "
            f"{validated_verdict.get('reason')}"
        )
    probe_plan = guidance.get("probe_plan")
    if isinstance(probe_plan, Mapping):
        operators = probe_plan.get("operator_priority")
        if isinstance(operators, list) and operators:
            print(
                "probe operators: "
                + ", ".join(str(operator) for operator in operators)
            )
        commands = probe_plan.get("suggested_commands")
        if isinstance(commands, list):
            for command_item in commands:
                if not isinstance(command_item, Mapping):
                    continue
                command = command_item.get("command")
                if command:
                    print(f"next probe: {command}")
                    break
    levers = guidance.get("candidate_levers")
    if isinstance(levers, list) and levers:
        kinds = [
            str(item.get("kind"))
            for item in levers
            if isinstance(item, Mapping) and item.get("kind")
        ]
        if kinds:
            print(f"candidate reorder levers: {', '.join(kinds)}")
def _print_frame_reservation_report(report: dict) -> None:
    print(report["summary"])
    current = report["current"]
    expected = report.get("expected")
    print(f"current frame: {current.get('frame_size')}")
    if expected is not None:
        print(f"expected frame: {expected.get('frame_size')}")
        print(f"frame delta: {report.get('frame_delta')}")
    timeline = report.get("pass_frame_timeline")
    if isinstance(timeline, Mapping):
        print(f"frame pass timeline: {timeline.get('pass_count')} pass(es)")
        first_change = timeline.get("first_change")
        if isinstance(first_change, Mapping):
            status = first_change.get("status")
            if status == "changed":
                print(
                    "first frame-model change: "
                    f"{first_change.get('previous_pass')} -> "
                    f"{first_change.get('pass')} "
                    f"({first_change.get('reason')})"
                )
            elif status:
                print(f"first frame-model change: {status}")
    cascade = report.get("register_coloring_cascade")
    if isinstance(cascade, Mapping) and cascade.get("status") == "dominant":
        print("dominant residual: register-coloring cascade")
        print(
            "register-only paired lines: "
            f"{cascade.get('register_only_paired_line_count')}; "
            "stack-slot paired lines: "
            f"{cascade.get('stack_slot_paired_line_count')}"
        )
        reason = cascade.get("reason")
        if reason:
            print(f"reason: {reason}")
        first = cascade.get("first_register_only_mismatch")
        if isinstance(first, Mapping):
            print(
                "first register-only mismatch: "
                f"{first.get('expected')}  /  {first.get('current')}"
            )
        focus = cascade.get("recommended_focus")
        if focus:
            print(f"recommended focus: {focus}")
    _print_frame_allocation_trace_summary(current.get("frame_allocation_trace"))
    _print_unused_ranges("current", current.get("unused_ranges", []))
    if expected is not None:
        _print_unused_ranges("expected", expected.get("unused_ranges", []))
    _print_outgoing_parameter_area_floor(
        report.get("outgoing_parameter_area_floor")
    )
    _print_stack_home_order_summary(current)
    probe_evaluation = report.get("stack_home_probe_evaluation")
    if isinstance(probe_evaluation, Mapping):
        print()
        print(f"stack-home probe verdict: {probe_evaluation.get('verdict')}")
        stop_condition = probe_evaluation.get("stop_condition")
        if isinstance(stop_condition, Mapping):
            print(
                "stop condition: "
                f"{stop_condition.get('status')} "
                f"({stop_condition.get('kind')})"
            )
        best = probe_evaluation.get("best_variant")
        if isinstance(best, Mapping):
            print(
                "best probe: "
                f"{best.get('label')} [{best.get('operator')}] "
                f"fixed {best.get('fixed_count')}/{best.get('target_count')}"
            )
    frame_evaluation = report.get("frame_transform_probe_evaluation")
    if isinstance(frame_evaluation, Mapping):
        print()
        print(f"frame-transform probe verdict: {frame_evaluation.get('verdict')}")
        stop_condition = frame_evaluation.get("stop_condition")
        if isinstance(stop_condition, Mapping):
            print(
                "frame stop condition: "
                f"{stop_condition.get('status')} "
                f"({stop_condition.get('kind')})"
            )
        best = frame_evaluation.get("best_variant")
        if isinstance(best, Mapping):
            print(
                "best frame probe: "
                f"{best.get('label')} [{best.get('operator')}] "
                f"frame={best.get('candidate_frame_size')} "
                f"remaining_delta={best.get('remaining_frame_delta')}"
            )

    first_divergence = report.get("frame_first_divergence")
    if first_divergence:
        print()
        print(f"first frame divergence: {first_divergence.get('status')}")
        reason = first_divergence.get("reason")
        if reason:
            print(f"reason: {reason}")
        cause = first_divergence.get("cause_hypothesis") or {}
        if isinstance(cause, Mapping) and cause.get("kind"):
            confidence = cause.get("confidence")
            suffix = f" ({confidence})" if confidence else ""
            print(f"cause: {cause.get('kind')}{suffix}")
        attribution = first_divergence.get("source_attribution")
        if isinstance(attribution, Mapping):
            primary = attribution.get("primary_source_object")
            if isinstance(primary, Mapping) and primary.get("symbol"):
                current_offset = primary.get("current_offset")
                expected_offset = primary.get("expected_offset")
                current_text = (
                    "?" if current_offset is None else f"0x{int(current_offset):x}"
                )
                expected_text = (
                    "?" if expected_offset is None else f"0x{int(expected_offset):x}"
                )
                print(
                    "source object: "
                    f"{primary.get('symbol')} "
                    f"({attribution.get('confidence')}, "
                    f"{primary.get('kind')}, "
                    f"{current_text}->{expected_text})"
                )
            elif attribution.get("status"):
                print(
                    "source object: "
                    f"{attribution.get('status')} "
                    f"({attribution.get('unresolved_dependency')})"
                )
        probe_plan = first_divergence.get("frame_transform_probe_plan") or {}
        if isinstance(probe_plan, Mapping):
            operators = [
                str(operator)
                for operator in probe_plan.get("operator_priority") or []
                if operator
            ]
            if operators:
                print(f"frame probe operators: {', '.join(operators)}")
            commands = probe_plan.get("suggested_commands") or []
            first_command = next(
                (
                    item.get("command")
                    for item in commands
                    if isinstance(item, Mapping)
                    and isinstance(item.get("command"), str)
                ),
                None,
            )
            if first_command:
                print(f"next frame probe: {first_command}")
        current_obj = first_divergence.get("current")
        expected_obj = first_divergence.get("expected")
        if current_obj:
            print(
                "current object: "
                f"{current_obj.get('kind')} "
                f"{_format_stack_range(current_obj)}"
            )
        if expected_obj:
            print(
                "expected object: "
                f"{expected_obj.get('kind')} "
                f"{_format_stack_range(expected_obj)}"
            )
        verdict = first_divergence.get("verdict") or {}
        if verdict.get("status"):
            print(f"verdict: {verdict.get('status')} - {verdict.get('reason')}")
        validated_verdict = first_divergence.get("validated_verdict") or {}
        if validated_verdict.get("status"):
            print(
                "validated verdict: "
                f"{validated_verdict.get('status')} - "
                f"{validated_verdict.get('reason')}"
            )

    current_low = report.get("current_low_frame_expansion")
    if current_low is not None:
        print()
        print(f"current low-frame expansion: {_format_stack_range(current_low)}")
        print(f"origin: {current_low.get('origin')}")
        print(f"frame growth bytes: {current_low.get('frame_growth_bytes')}")
        print(f"alignment growth bytes: {current_low.get('alignment_growth_bytes')}")
        accesses = current_low.get("current_accesses_in_range") or []
        if not accesses:
            print("current non-save stack accesses in range: none")
        else:
            print("current non-save stack accesses in range:")
            for access in accesses:
                print(
                    f"  {access.get('opcode')} {access.get('operands')} "
                    f"at 0x{int(access['offset']):x} "
                    f"({access.get('kind')})"
                )

    extra = report.get("extra_low_frame_reservation")
    if extra is None:
        return
    print()
    print(f"extra low-frame reservation: {_format_stack_range(extra)}")
    print(f"origin: {extra.get('origin')}")
    accesses = extra.get("current_accesses_in_range") or []
    if not accesses:
        print("current non-save stack accesses in range: none")
        return
    print("current non-save stack accesses in range:")
    for access in accesses:
        print(
            f"  {access.get('opcode')} {access.get('operands')} "
            f"at 0x{int(access['offset']):x} "
            f"({access.get('kind')})"
        )
def _print_frame_allocation_trace_summary(trace: object) -> None:
    if not isinstance(trace, Mapping):
        return
    status = trace.get("status")
    object_count = trace.get("object_count")
    count_text = (
        f" ({object_count} object(s))"
        if isinstance(object_count, int)
        else ""
    )
    print(f"frame allocation trace: {status}{count_text}")
    allocator_status = trace.get("allocator_pass_status")
    if allocator_status:
        print(f"allocator pass: {allocator_status}")
    validation = trace.get("validation")
    if isinstance(validation, Mapping):
        frame_status = (
            "ok" if validation.get("frame_size_matches") is True else "mismatch"
        )
        full_layout_status = (
            "ok"
            if validation.get("full_interval_coverage_matches") is True
            else "mismatch"
        )
        non_overlap_status = (
            "ok"
            if validation.get("object_non_overlap_matches") is True
            else "mismatch"
        )
        access_status = (
            "ok"
            if validation.get("r1_access_coverage_matches") is True
            else "mismatch"
        )
        print(
            "frame allocation validation: "
            f"frame-size {frame_status}, full-layout {full_layout_status}, "
            f"non-overlap {non_overlap_status}, "
            f"r1-access coverage {access_status}"
        )
    objects = trace.get("objects")
    if not isinstance(objects, list):
        return
    for obj in objects[:6]:
        if not isinstance(obj, Mapping):
            continue
        layout_order = obj.get("layout_order")
        origin_tag = obj.get("origin_tag")
        label = obj.get("symbol") or obj.get("kind")
        print(
            f"  #{layout_order} {origin_tag} "
            f"{_format_stack_range(obj)} {label}"
        )
@inspect_app.command(name="frame-reservations")
def frame_reservations(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to inspect"),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    expected_asm: Annotated[
        Optional[Path],
        typer.Option(
            "--expected-asm",
            help="Path to expected target asm. Omit to extract via "
                 "`melee-agent extract get <function> --full`.",
        ),
    ] = None,
    no_expected: Annotated[
        bool,
        typer.Option(
            "--no-expected",
            help="Inspect only the current pcdump without extracting target asm.",
        ),
    ] = False,
    probe_results_json: Annotated[
        Optional[Path],
        typer.Option(
            "--probe-results-json",
            help=(
                "Path to lifetime-layout --json output or a variants array. "
                "Attaches stack-home and frame-transform validation."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit the report as JSON."),
    ] = False,
) -> None:
    """Inspect stack-frame gaps and implicit reserved ranges."""
    from src.cli.debug import DEFAULT_MELEE_ROOT, _abort_frame_function_not_in_dump, _attach_frame_function_aliases, _frame_source_context, _pcdump_has_symbolic_stack_homes, _read_frame_reservation_current_asm, _read_frame_reservation_expected_asm
    from src.cli.debug import _resolve_frame_function_names, _resolve_pcdump_path
    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    pcdump_text = pcdump_path.read_text()
    names = _resolve_frame_function_names(function, pcdump_text, melee_root)
    if names is None:
        _abort_frame_function_not_in_dump(function, pcdump_text)
    expected_text = _read_frame_reservation_expected_asm(
        names.report_function,
        expected_asm=expected_asm,
        no_expected=no_expected,
        melee_root=melee_root,
    )
    current_text = (
        _read_frame_reservation_current_asm(
            names.report_function,
            melee_root=melee_root,
        )
        if _pcdump_has_symbolic_stack_homes(pcdump_text)
        else None
    )
    source_context = _frame_source_context(
        names.aliases,
        melee_root=melee_root,
    )
    try:
        report = analyze_frame_reservations(
            pcdump_text,
            names.pcdump_function,
            expected_asm_text=expected_text,
            current_asm_text=current_text,
            display_function=function,
            **source_context,
        )
    except ValueError as exc:
        if "not found in pcdump" in str(exc):
            _abort_frame_function_not_in_dump(function, pcdump_text)
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    _attach_frame_function_aliases(report, names)

    if probe_results_json is not None:
        variants, probe_metadata = _read_stack_home_probe_results_json(
            probe_results_json
        )
        semantic_status = probe_metadata.get("semantic_lever_status")
        if isinstance(semantic_status, Mapping):
            report["semantic_lever_status"] = dict(semantic_status)
        report["stack_home_probe_evaluation"] = evaluate_stack_home_probe_results(
            report,
            variants,
        )
        _attach_stack_home_validated_verdict(report)
        report["frame_transform_probe_evaluation"] = (
            evaluate_frame_transform_probe_results(report, variants)
        )
        _attach_frame_transform_validated_verdict(report)

    if json_out:
        print(json.dumps(report, indent=2))
        return
    _print_frame_reservation_report(report)
def _attach_stack_home_validated_verdict(report: dict) -> None:
    current = report.get("current")
    evaluation = report.get("stack_home_probe_evaluation")
    if not isinstance(current, dict) or not isinstance(evaluation, Mapping):
        return
    guidance = current.get("stack_home_reorder_guidance")
    if not isinstance(guidance, dict):
        return
    verdict = evaluation.get("verdict")
    stop_condition = evaluation.get("stop_condition")
    if verdict == "source-reachable-reorder":
        guidance["validated_verdict"] = {
            "status": "source-reachable-reorder",
            "confidence": "high",
            "probe_verdict": verdict,
            "reason": (
                "stack-home probe evidence validates a source-reachable reorder"
            ),
            "stop_condition": stop_condition,
        }
    elif verdict == "partial-source-reachable-reorder":
        guidance["validated_verdict"] = {
            "status": "partial-source-reachable-reorder",
            "confidence": "medium",
            "probe_verdict": verdict,
            "reason": (
                "stack-home probe evidence partially reorders target homes"
            ),
            "stop_condition": stop_condition,
        }
    elif verdict == "internal-tiebreak-ceiling-candidate":
        guidance["validated_verdict"] = {
            "status": "internal-tiebreak-ceiling-candidate",
            "confidence": "medium",
            "probe_verdict": verdict,
            "reason": (
                "bounded stack-home reorder probes left target placement unchanged"
            ),
            "stop_condition": stop_condition,
        }
def _attach_frame_transform_validated_verdict(report: dict) -> None:
    first_divergence = report.get("frame_first_divergence")
    evaluation = report.get("frame_transform_probe_evaluation")
    if not isinstance(first_divergence, dict) or not isinstance(evaluation, Mapping):
        return
    verdict = evaluation.get("verdict")
    stop_condition = evaluation.get("stop_condition")
    if verdict == "source-reachable-frame-transform":
        first_divergence["validated_verdict"] = {
            "status": "source-reachable-validated",
            "confidence": "high",
            "probe_verdict": verdict,
            "reason": (
                "frame transform probe evidence validates a source-reachable "
                "change for the first frame divergence"
            ),
            "stop_condition": stop_condition,
        }
    elif verdict == "partial-source-reachable-frame-transform":
        first_divergence["validated_verdict"] = {
            "status": "partial-source-reachable-validated",
            "confidence": "medium",
            "probe_verdict": verdict,
            "reason": (
                "frame transform probe evidence partially reduces the first "
                "frame divergence"
            ),
            "stop_condition": stop_condition,
        }
    elif verdict == "frame-transform-ceiling-candidate":
        attribution = first_divergence.get("source_attribution")
        source_object = (
            attribution.get("primary_source_object")
            if isinstance(attribution, Mapping)
            else None
        )
        if isinstance(source_object, Mapping) and source_object.get("symbol"):
            first_divergence["validated_verdict"] = {
                "status": "attributed-frame-unchanged",
                "confidence": "medium",
                "probe_verdict": verdict,
                "reason": (
                    "bounded frame-size transform probes left the frame delta "
                    "unchanged for an attributed source-object divergence"
                ),
                "source_object_symbol": source_object.get("symbol"),
                "stop_condition": stop_condition,
            }
        else:
            unresolved_dependency = (
                attribution.get("unresolved_dependency")
                if isinstance(attribution, Mapping)
                else "mwcc-stack-home-origin-tags"
            )
            first_divergence["validated_verdict"] = {
                "status": "internal-tiebreak-ceiling",
                "confidence": "medium",
                "probe_verdict": verdict,
                "reason": (
                    "bounded frame transform probes left an unattributed "
                    "divergence unchanged; likely compiler-internal layout "
                    "tiebreak or missing stack-home origin instrumentation"
                ),
                "unresolved_dependency": unresolved_dependency,
                "stop_condition": stop_condition,
            }
def _frame_source_path_for_unit(unit: str | None) -> str | None:
    return f"src/{unit}.c" if unit else None
def _frame_taxonomy_next_steps(
    function: str,
    taxonomy: Mapping[str, Any],
    *,
    unit: str | None,
) -> list[str]:
    steps: list[str] = []
    command = taxonomy.get("next_command")
    if isinstance(command, str) and command:
        cause = taxonomy.get("cause")
        if taxonomy.get("closability_tier") == "ceiling" and cause:
            steps.append(
                f"[current-structure residual: {cause} — try structural levers "
                f"+ permuter before banking] {command}")
        else:
            steps.append(command)

    inspect_command = f"melee-agent debug inspect frame-reservations -f {function}"
    if not any(inspect_command in step for step in steps):
        steps.append(inspect_command)

    if taxonomy.get("closability_tier") != "ceiling":
        src_arg = _frame_source_path_for_unit(unit) or "<source.c>"
        steps.append(
            f"melee-agent debug dump local {src_arg} -f {function} "
            "--diff --force-frame-from-diff"
        )
    return steps
def _attach_frame_taxonomy_hint_fields(
    hint: dict[str, Any],
    taxonomy: Mapping[str, Any],
) -> dict[str, Any]:
    hint.update(
        {
            "cause": taxonomy.get("cause"),
            "raw_cause": taxonomy.get("raw_cause"),
            "verdict": taxonomy.get("verdict"),
            "raw_verdict": taxonomy.get("raw_verdict"),
            "closability_tier": taxonomy.get("closability_tier"),
            "attribution_status": taxonomy.get("attribution_status"),
            "source_object": taxonomy.get("source_object"),
            "source_object_symbol": taxonomy.get("source_object_symbol"),
            "next_command": taxonomy.get("next_command"),
            "taxonomy_reason": taxonomy.get("reason"),
            "match_relevance": taxonomy.get("match_relevance"),
            "match_relevance_reason": taxonomy.get("match_relevance_reason"),
        }
    )
    return hint
def _frame_subcategory_from_taxonomy(
    classification: Mapping[str, Any] | None,
    taxonomy: Mapping[str, Any],
) -> str:
    primary = (
        classification.get("primary")
        if isinstance(classification, Mapping)
        else None
    )
    cause = taxonomy.get("cause")
    if primary == "stack-slot-layout":
        return "same-frame-stack-slot-placement"
    if cause == "pure-reservation":
        return "frame-too-small"
    if cause == "frame-too-large":
        return "frame-too-large"
    return "frame-size-delta"
def _frame_residual_hint_from_report(
    report: dict,
    *,
    unit: str | None = None,
) -> dict | None:
    """Return next-step guidance for frame-only/local-area residuals."""
    function = report.get("function")
    if not function:
        return None
    low_expansion = report.get("current_low_frame_expansion")
    extra_reservation = report.get("extra_low_frame_reservation")
    residual = None
    if isinstance(low_expansion, dict):
        residual = low_expansion
    elif isinstance(extra_reservation, dict):
        residual = extra_reservation
    if residual is None:
        return None
    if residual.get("current_accesses_in_range"):
        return None

    summary = report.get("summary") or (
        f"{function}: frame/local-area reservation differs from target"
    )
    src_arg = f"src/{unit}.c" if unit else "<source.c>"
    taxonomy = classify_frame_taxonomy(
        function,
        frame_report=report,
        source_path=_frame_source_path_for_unit(unit),
    )
    message = (
        f"{summary}; this residual is frame/local-area, not register "
        "allocation. Prefer frame-reservation inspection or a frame patch "
        "before register allocator tools."
    )
    if taxonomy is not None:
        message = (
            f"{message} Normalized frame cause: {taxonomy['cause']} "
            f"({taxonomy['closability_tier']})."
        )
    hint = {
        "kind": "frame-local-area",
        "message": message,
        "summary": summary,
        "next_steps": (
            _frame_taxonomy_next_steps(function, taxonomy, unit=unit)
            if taxonomy is not None
            else [
                f"melee-agent debug inspect frame-reservations -f {function}",
                (
                    f"melee-agent debug dump local {src_arg} -f {function} "
                    "--diff --force-frame-from-diff"
                ),
            ]
        ),
    }
    if taxonomy is not None:
        _attach_frame_taxonomy_hint_fields(hint, taxonomy)
    return hint
def _validate_signature_checkdiff_function(
    payload: Mapping[str, Any],
    function: str,
) -> None:
    payload_function = payload.get("function")
    if payload_function is None:
        return
    if str(payload_function) == function:
        return
    typer.echo(
        (
            "checkdiff JSON function mismatch: "
            f"payload is {payload_function!r}, requested {function!r}"
        ),
        err=True,
    )
    raise typer.Exit(2)
def _run_signature_candidate_checkdiff_many_rebuild(
    *,
    functions: list[str],
    candidate_source: str,
    source_path: Path,
    unit: str,
    melee_root: Path,
    timeout: float,
) -> dict[str, dict]:
    from src.cli.debug import _acquire_checkdiff_repo_lock
    unit_for_o = unit[:-2] if unit.endswith(".c") else unit
    unit_for_o = unit_for_o.removeprefix("src/")
    validation_source_path = melee_root / "src" / f"{unit_for_o}.c"
    build_obj = melee_root / "build" / "GALE01" / "src" / f"{unit_for_o}.o"
    report_json = melee_root / "build" / "GALE01" / "report.json"
    payloads: dict[str, dict] = {}
    build_timeout = max(0.1, timeout * 0.4)
    with _acquire_checkdiff_repo_lock(
        melee_root,
        label="signature-audit validation",
    ):
        original_source = validation_source_path.read_text()
        build_obj_existed = build_obj.exists()
        saved_obj = build_obj.read_bytes() if build_obj_existed else None
        report_existed = report_json.exists()
        saved_report = report_json.read_bytes() if report_existed else None
        try:
            validation_source_path.write_text(candidate_source)
            for function in functions:
                checkdiff_proc = subprocess.run(
                    [
                        sys.executable,
                        str(melee_root / "tools" / "checkdiff.py"),
                        function,
                        "--format",
                        "json",
                        "--no-fingerprint",
                        "--build-timeout",
                        f"{build_timeout:g}",
                    ],
                    cwd=melee_root,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=_checkdiff_env_for_locked_child(disable_fingerprint=True),
                )
                if (
                    checkdiff_proc.returncode not in (0, 1)
                    or not checkdiff_proc.stdout.strip()
                ):
                    detail = (
                        checkdiff_proc.stderr
                        or checkdiff_proc.stdout
                        or ""
                    ).strip()
                    raise RuntimeError(
                        "candidate checkdiff failed for "
                        f"{function} with exit {checkdiff_proc.returncode}"
                        + (f": {detail}" if detail else "")
                    )
                try:
                    payload = json.loads(checkdiff_proc.stdout)
                except json.JSONDecodeError as exc:
                    detail = (
                        checkdiff_proc.stderr
                        or checkdiff_proc.stdout
                        or str(exc)
                    ).strip()
                    raise RuntimeError(
                        "candidate checkdiff emitted non-json for "
                        f"{function}: {detail}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise RuntimeError(
                        "candidate checkdiff JSON root was not an object "
                        f"for {function}"
                    )
                payloads[function] = payload
        finally:
            _restore_signature_candidate_validation_state(
                source_path=validation_source_path,
                source_text=original_source,
                build_obj=build_obj,
                build_obj_existed=build_obj_existed,
                build_obj_bytes=saved_obj,
                report_json=report_json,
                report_existed=report_existed,
                report_bytes=saved_report,
            )

    return payloads
def _restore_signature_candidate_validation_state(
    *,
    source_path: Path,
    source_text: str,
    build_obj: Path,
    build_obj_existed: bool,
    build_obj_bytes: bytes | None,
    report_json: Path,
    report_existed: bool,
    report_bytes: bytes | None,
) -> None:
    errors: list[str] = []
    try:
        source_path.write_text(source_text)
    except OSError as exc:
        errors.append(f"source: {exc}")
    try:
        if build_obj_existed and build_obj_bytes is not None:
            build_obj.parent.mkdir(parents=True, exist_ok=True)
            build_obj.write_bytes(build_obj_bytes)
        elif not build_obj_existed and build_obj.exists():
            build_obj.unlink()
    except OSError as exc:
        errors.append(f"object: {exc}")
    try:
        if report_existed and report_bytes is not None:
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_json.write_bytes(report_bytes)
        elif not report_existed and report_json.exists():
            report_json.unlink()
    except OSError as exc:
        errors.append(f"report: {exc}")
    if errors:
        message = (
            "failed to restore signature validation state: " + "; ".join(errors)
        )
        active_exc = sys.exc_info()[1]
        if active_exc is not None:
            active_exc.add_note(message)
        else:
            raise RuntimeError(message)
def _signature_report_return_width_helpers(report: Any | None) -> set[str]:
    helpers: set[str] = set()
    if report is None:
        return helpers
    for finding in getattr(report, "findings", []) or []:
        for action in getattr(finding, "actions", []) or []:
            if getattr(action, "kind", None) != "call-site-local-return-width":
                continue
            for candidate in (
                getattr(action, "candidate", None),
                getattr(getattr(action, "source_variant", None), "candidate", None),
            ):
                if not isinstance(candidate, dict):
                    continue
                helper = candidate.get("helper")
                if helper:
                    helpers.add(str(helper))
    return helpers
@inspect_app.command("guide")
def guide(
    function: Annotated[
        str,
        typer.Option("--function", "-f",
                     help="Function name to analyze (required)"),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec file (YAML or JSON). If omitted, all virtuals "
                 "currently mapped to non-target physicals are shown.",
        ),
    ] = None,
    asm_hunks: Annotated[
        int,
        typer.Option(
            "--asm-hunks",
            help="Also show the top N asm-diff hunks from checkdiff. "
                 "0 (default) omits. Useful when an allocator suggestion "
                 "is hard to interpret without seeing the actual text-"
                 "level diff (e.g. unexpected clrlwi from a missing "
                 "cast). Caps each hunk at ~12 lines for readability.",
        ),
    ] = 0,
) -> None:
    """Tier 4: human-readable diagnostic for stuck-function debugging.

    Reports which virtuals are at the wrong physical, why (interference,
    spill, iteration order), and suggests directions for C-source nudges.
    Hints, not guarantees — interpret in source context.

    Pass --asm-hunks N to also dump the top N asm-diff hunks from
    checkdiff. Saves switching tools when allocator-only analysis
    doesn't explain the mismatch (e.g. text diffs from a stray cast).
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT, _abort_function_not_in_dump, _load_target_spec, _resolve_pcdump_path, find_function, format_suggestions, parse_hook_events, parse_pcdump, score_function
    from ...mwcc_debug import suggest as score_suggestions
    pcdump = _resolve_pcdump_path(pcdump, function)
    text = pcdump.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])

    events_list = parse_hook_events(text)
    events = find_function(events_list, function)

    if target is None:
        # No target — score against an empty target spec, just to surface
        # SPILLED markers and other red flags.
        spec: dict = {"virtuals": {}}
    else:
        spec = _load_target_spec(target)

    result = score_function(fn, spec, events=events)
    suggestions = score_suggestions(fn, result, events=events)

    print(f"Function: {function}")
    print(f"Targeted virtuals: {result.targeted}")
    print(f"  Matched: {result.matched}")
    print(f"  Wrong:   {result.virtual_distance}")
    if result.spill_unexpected:
        print(f"  Unexpected SPILLED: r{', r'.join(str(v) for v in result.spill_unexpected)}")
    if result.spill_missing:
        print(f"  Expected-but-missing SPILLED: r{', r'.join(str(v) for v in result.spill_missing)}")
    print()
    no_target = target is None and result.targeted == 0
    target_matches_current = (
        target is not None
        and result.targeted > 0
        and result.virtual_distance == 0
        and not result.spill_unexpected
        and not result.spill_missing
    )
    if no_target:
        print(
            "No target spec was provided, so this guide cannot determine whether "
            "the current coloring matches a reference or forced allocation."
        )
        print(
            "Actionable flow: "
            "pass a reference/forced target spec with --target, or first run "
            f"`melee-agent debug inspect diagnose {function}` to test whether "
            "force-phys can reach a useful target."
        )
        print(
            "Do not derive a target from this same current pcdump as the "
            "next step; that only captures the current allocation and usually "
            "produces no diagnostic signal."
        )
        print()
    elif target_matches_current:
        print(
            "Target spec currently matches this pcdump. If the function is "
            "still nonmatching, this target was probably derived from the "
            "current source rather than from reference or a forced-allocation "
            "probe."
        )
        print(
            "Pass a reference/forced target spec before using guide output to "
            "diagnose allocator mismatch."
        )
        print()
    print("Suggestions (highest severity first):")
    if no_target and not suggestions:
        print("No allocator issues can be ranked without a target spec.")
    else:
        print(format_suggestions(suggestions))

    if asm_hunks > 0:
        print()
        hunks = _get_asm_hunks(function, DEFAULT_MELEE_ROOT, top_n=asm_hunks)
        if hunks is None:
            print(f"== asm hunks ==")
            print("  (checkdiff didn't produce a diff — either the .o "
                  "isn't built yet, the function matches, or checkdiff "
                  "errored. Run `tools/checkdiff.py {fn}` for details.)"
                  .replace("{fn}", function))
        elif not hunks:
            print(f"== asm hunks ==")
            print("  (no diff)")
        else:
            print(f"== top {len(hunks)} asm hunks (by diff size) ==")
            print(_format_asm_hunks(hunks))
def _fn_addr_from_name(name: str) -> int | None:
    match = re.fullmatch(r"fn_([0-9A-Fa-f]{8})", name)
    if match is None:
        return None
    return int(match.group(1), 16)
def _format_fn_addr(addr: int) -> str:
    return f"fn_{addr:08X}"
def _parse_int_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None
def _report_function_virtual_address(function: Mapping[str, Any]) -> int | None:
    metadata = function.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    return _parse_int_value(metadata.get("virtual_address"))
def _append_unique(items: list[str], value: str | None) -> None:
    if value and value not in items:
        items.append(value)
def _source_file_melee_root(source_file: Path) -> Path | None:
    from src.cli.debug import _looks_like_melee_root
    source_file = source_file.expanduser()
    source_path = source_file.resolve() if source_file.exists() else source_file
    for candidate in (source_path.parent, *source_path.parents):
        if _looks_like_melee_root(candidate):
            return candidate
    return None
def _bootstrap_melee_root_candidates(source_file: Path | None) -> list[Path]:
    from src.cli.debug import DEFAULT_MELEE_ROOT, _package_melee_root
    candidates: list[Path] = []
    env_root = os.environ.get("MELEE_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    if source_file is not None:
        source_root = _source_file_melee_root(source_file)
        if source_root is not None:
            candidates.append(source_root)
    candidates.append(DEFAULT_MELEE_ROOT)
    cwd = Path.cwd()
    candidates.extend([cwd, *cwd.parents])
    candidates.append(_package_melee_root())

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            resolved = candidate.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped
def _resolve_bootstrap_melee_root(
    function: str,
    *,
    source_file: Path | None,
    melee_root: Path | None,
) -> Path:
    from src.cli.debug import DEFAULT_MELEE_ROOT, _find_unit_for_function, _looks_like_melee_root
    if melee_root is not None:
        root = melee_root.expanduser().resolve()
        if not _looks_like_melee_root(root):
            raise typer.BadParameter(
                f"--melee-root does not look like a Melee checkout: {root}"
            )
        return root

    fallback: Path | None = None
    for candidate in _bootstrap_melee_root_candidates(source_file):
        if not _looks_like_melee_root(candidate):
            continue
        if fallback is None:
            fallback = candidate
        if _find_unit_for_function(function, candidate) is not None:
            return candidate
    return fallback or DEFAULT_MELEE_ROOT
def _tmp_asm_path_for_function(function: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", function)
    return Path("/tmp") / f"{safe_name}.s"
_PERMUTER_PERM_MACRO_RE = re.compile(r"\bPERM_[A-Za-z0-9_]*\b")
def _source_contains_perm_macros(text: str) -> bool:
    return _PERMUTER_PERM_MACRO_RE.search(text) is not None
def _read_bootstrap_source_file(source_file: Path, function: str) -> str:
    source_file = source_file.expanduser()
    if not source_file.is_file():
        raise typer.BadParameter(f"source file not found: {source_file}")
    text = source_file.read_text(encoding="utf-8")
    if find_source_function(text, function) is None:
        typer.echo(
            f"source file does not contain function {function!r}: {source_file}",
            err=True,
        )
        raise typer.Exit(2)
    return text
@contextmanager
def _staged_permuter_import_source(
    repo_source: Path,
    source_file: Path | None,
) -> Iterator[tuple[Path, bool]]:
    if source_file is None:
        yield repo_source, False
        return

    source_file = source_file.expanduser()
    if not source_file.is_file():
        raise typer.BadParameter(f"source file not found: {source_file}")
    if source_file.resolve() == repo_source.resolve():
        yield repo_source, False
        return

    original = repo_source.read_bytes()
    replacement = source_file.read_bytes()
    try:
        repo_source.write_bytes(replacement)
        yield repo_source, True
    finally:
        repo_source.write_bytes(original)
def _permuter_import_dirs(
    function: str,
    *,
    perm_root: Path,
    melee_root: Path,
) -> set[Path]:
    pattern = re.compile(rf"^{re.escape(function)}(?:-\d+)?$")
    roots = {perm_root, melee_root}
    dirs: set[Path] = set()
    for root in roots:
        nonmatchings = root / "nonmatchings"
        if not nonmatchings.is_dir():
            continue
        for child in nonmatchings.iterdir():
            if child.is_dir() and pattern.match(child.name):
                dirs.add(child)
    return dirs
def _detect_new_permuter_import_dir(
    function: str,
    before: set[Path],
    *,
    perm_root: Path,
    melee_root: Path,
) -> Optional[Path]:
    new_dirs = _permuter_import_dirs(
        function,
        perm_root=perm_root,
        melee_root=melee_root,
    ) - before
    if not new_dirs:
        return None
    return max(new_dirs, key=lambda path: path.stat().st_mtime)
def _replace_path_from(src: Path, dst: Path) -> None:
    if dst.exists():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    shutil.move(str(src), str(dst))
def _promote_permuter_import_dir(
    imported_dir: Path,
    *,
    function: str,
    perm_root: Path,
    keep_existing_settings: bool,
) -> Path:
    """Move fresh import.py output into <perm_root>/nonmatchings/<function>.

    decomp-permuter's import.py chooses the output root from the imported source
    path, so importing a Melee source normally writes to the matcher worktree's
    nonmatchings directory. Normalize the fresh import into the decomp-permuter
    checkout and refresh generated files without deleting existing output-* dirs.
    """
    dest_dir = perm_root / "nonmatchings" / function
    if imported_dir.resolve() == dest_dir.resolve():
        return dest_dir

    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    if not dest_dir.exists():
        shutil.move(str(imported_dir), str(dest_dir))
        return dest_dir

    imported_names = {child.name for child in imported_dir.iterdir()}
    for child in imported_dir.iterdir():
        if (
            child.name == "settings.toml"
            and keep_existing_settings
            and (dest_dir / child.name).exists()
        ):
            continue
        _replace_path_from(child, dest_dir / child.name)
    if "base.c" in imported_names and "base.o" not in imported_names:
        stale_base_o = dest_dir / "base.o"
        if stale_base_o.exists():
            stale_base_o.unlink()
    shutil.rmtree(imported_dir, ignore_errors=True)
    return dest_dir
def _looks_like_decomp_permuter_root(path: Path) -> bool:
    return (path / "permuter.py").is_file() and (path / "src" / "compiler.py").is_file()
_BOOTSTRAP_SOURCE_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_BOOTSTRAP_TARGET_REL24_RE = re.compile(r"\bR_PPC_REL24\s+([A-Za-z_]\w*)")
_BOOTSTRAP_TARGET_BL_RE = re.compile(r"\bbl\s+([A-Za-z_]\w*)")
_BOOTSTRAP_TARGET_B_RE = re.compile(r"\bb\s+([A-Za-z_]\w*)")
_BOOTSTRAP_INLINE_RE = re.compile(r"^(?:static\s+)?inline\b")
_BOOTSTRAP_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_]\w*\b")
_BOOTSTRAP_INCLUDE_RE = re.compile(
    r"^[ \t]*#[ \t]*include[ \t]+(?:\"([^\"]+)\"|<([^>]+)>)",
    re.MULTILINE,
)
_BOOTSTRAP_CALL_KEYWORDS = {
    "case",
    "for",
    "if",
    "return",
    "sizeof",
    "switch",
    "while",
}
_BOOTSTRAP_IDENTIFIER_KEYWORDS = {
    *_BOOTSTRAP_CALL_KEYWORDS,
    "char",
    "const",
    "double",
    "enum",
    "extern",
    "float",
    "inline",
    "int",
    "long",
    "register",
    "return",
    "short",
    "signed",
    "static",
    "struct",
    "typedef",
    "union",
    "unsigned",
    "void",
    "volatile",
}
def _read_bootstrap_target_asm(fn_dir: Path, melee_root: Path) -> str:
    target_s = fn_dir / "target.s"
    if target_s.exists():
        return target_s.read_text(encoding="utf-8")

    target_o = fn_dir / "target.o"
    if not target_o.exists():
        return ""
    try:
        from ...mwcc_debug.dtk_objdump import disassemble_object

        return disassemble_object(
            target_o,
            melee_root=melee_root,
            name_magic=False,
        )
    except Exception:
        return ""
def _bootstrap_resolve_include(
    include: str,
    *,
    including_path: Path,
    melee_root: Path,
) -> Path | None:
    candidates = [
        including_path.parent / include,
        melee_root / "src" / "melee" / include,
        melee_root / "src" / "sysdolphin" / include,
        melee_root / "src" / include,
        melee_root / "include" / include,
        melee_root / include,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None
def _bootstrap_dependency_context(
    source_text: str,
    *,
    source_path: Path,
    melee_root: Path,
) -> str:
    """Return local include text that injected bootstrap callees may need."""
    seen: set[Path] = set()
    parts: list[str] = []

    def visit(text: str, including_path: Path, depth: int) -> None:
        if depth >= 3:
            return
        for match in _BOOTSTRAP_INCLUDE_RE.finditer(text):
            include = match.group(1) or match.group(2)
            if not include:
                continue
            resolved = _bootstrap_resolve_include(
                include,
                including_path=including_path,
                melee_root=melee_root,
            )
            if resolved is None:
                continue
            resolved = resolved.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                include_text = resolved.read_text(encoding="utf-8")
            except OSError:
                continue
            parts.append(include_text)
            visit(include_text, resolved, depth + 1)

    visit(source_text, source_path, 0)
    return "\n\n".join(parts)
def _bootstrap_source_calls(function_text: str) -> list[str]:
    calls: list[str] = []
    seen: set[str] = set()
    for match in _BOOTSTRAP_SOURCE_CALL_RE.finditer(function_text):
        name = match.group(1)
        if name in _BOOTSTRAP_CALL_KEYWORDS or name in seen:
            continue
        seen.add(name)
        calls.append(name)
    return calls
def _bootstrap_identifier_names(text: str) -> set[str]:
    return {
        match.group(0)
        for match in _BOOTSTRAP_IDENTIFIER_RE.finditer(text)
        if match.group(0) not in _BOOTSTRAP_IDENTIFIER_KEYWORDS
    }
def _bootstrap_macro_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)", line)
        if match is None:
            i += 1
            continue
        block = [line.rstrip()]
        while block[-1].endswith("\\") and i + 1 < len(lines):
            i += 1
            block.append(lines[i].rstrip())
        blocks.append((match.group(1), "\n".join(block)))
        i += 1
    return blocks
def _bootstrap_base_has_macro(text: str, name: str) -> bool:
    return (
        re.search(
            rf"^[ \t]*#[ \t]*define[ \t]+{re.escape(name)}(?:\b|\()",
            text,
            re.MULTILINE,
        )
        is not None
    )
def _bootstrap_base_has_permuter_define(text: str, name: str) -> bool:
    return (
        re.search(
            rf"^[ \t]*#[ \t]*pragma[ \t]+_permuter[ \t]+define[ \t]+"
            rf"{re.escape(name)}(?:\b|\()",
            text,
            re.MULTILINE,
        )
        is not None
    )
def _bootstrap_base_has_object_declaration(text: str, name: str) -> bool:
    return (
        re.search(
            rf"^[ \t]*(?:extern[ \t]+)?[^#\n;]*\b{re.escape(name)}\b[^;\n]*;",
            text,
            re.MULTILINE,
        )
        is not None
    )
def _bootstrap_base_has_function_declaration(text: str, name: str) -> bool:
    if find_source_function(text, name) is not None:
        return True
    return (
        re.search(
            rf"^[ \t]*(?:static[ \t]+)?(?:inline[ \t]+)?"
            rf"[^#;\n{{}}]*\b{re.escape(name)}[ \t]*\([^;{{}}]*\)[ \t]*;",
            text,
            re.MULTILINE,
        )
        is not None
    )
def _bootstrap_enum_constant_defines(text: str) -> dict[str, str]:
    from ...mwcc_debug.source_patch import _strip_c_comments

    stripped = _strip_c_comments(text)
    defines: dict[str, str] = {}
    enum_re = re.compile(r"\benum(?:\s+[A-Za-z_]\w*)?\s*\{(?P<body>.*?)\}", re.S)
    for match in enum_re.finditer(stripped):
        body = text[match.start("body") : match.end("body")]
        next_value: int | None = 0
        for raw_member in body.split(","):
            member = raw_member.strip()
            if not member:
                continue
            member_match = re.match(
                r"^(?P<name>[A-Za-z_]\w*)"
                r"(?:\s*=\s*(?P<value>[-+]?(?:0[xX][0-9A-Fa-f]+|\d+)))?\s*$",
                member,
            )
            if member_match is None:
                next_value = None
                continue
            name = member_match.group("name")
            explicit_value = member_match.group("value")
            if explicit_value is not None:
                defines[name] = explicit_value
                try:
                    next_value = int(explicit_value, 0) + 1
                except ValueError:
                    next_value = None
                continue
            if next_value is None:
                continue
            defines[name] = str(next_value)
            next_value += 1
    return defines
def _bootstrap_source_function_prototype(source_text: str, span: Any) -> str | None:
    signature = source_text[span.sig_start : span.body_open].strip()
    if not signature:
        return None
    return signature.rstrip() + ";"
def _bootstrap_injected_callee_dependencies(
    *,
    base_text: str,
    source_text: str,
    dependency_text: str,
    source_spans: Mapping[str, Any],
    insert_names: set[str],
    injected_texts: list[str],
    function: str,
) -> list[str]:
    needed_names: set[str] = set()
    for text in injected_texts:
        needed_names.update(_bootstrap_identifier_names(text))
    if not needed_names:
        return []

    dependency_context = "\n\n".join(
        part for part in (source_text, dependency_text) if part
    )
    deps: list[str] = []

    for name, block in _bootstrap_macro_blocks(dependency_context):
        if name not in needed_names:
            continue
        if _bootstrap_base_has_macro(base_text, name):
            continue
        if _bootstrap_base_has_permuter_define(base_text, name):
            continue
        if any(_bootstrap_base_has_macro(dep, name) for dep in deps):
            continue
        if any(_bootstrap_base_has_permuter_define(dep, name) for dep in deps):
            continue
        deps.append(block)

    enum_defines = _bootstrap_enum_constant_defines(dependency_context)
    bool_defines = {"true": "1", "false": "0"}
    for name, value in {**enum_defines, **bool_defines}.items():
        if name not in needed_names:
            continue
        if _bootstrap_base_has_macro(base_text, name):
            continue
        if _bootstrap_base_has_permuter_define(base_text, name):
            continue
        if any(_bootstrap_base_has_macro(dep, name) for dep in deps):
            continue
        if any(_bootstrap_base_has_permuter_define(dep, name) for dep in deps):
            continue
        deps.append(f"#pragma _permuter define {name} {value}")

    for raw_line in dependency_context.splitlines():
        line = raw_line.strip()
        if not line.startswith("extern ") or not line.endswith(";"):
            continue
        for name in sorted(needed_names):
            if re.search(rf"\b{re.escape(name)}\b", line) is None:
                continue
            if _bootstrap_base_has_object_declaration(base_text, name):
                continue
            if any(_bootstrap_base_has_object_declaration(dep, name) for dep in deps):
                continue
            deps.append(line)
            break

    for name, span in sorted(source_spans.items(), key=lambda item: item[1].sig_start):
        if name == function or name in insert_names or name not in needed_names:
            continue
        if _bootstrap_base_has_function_declaration(base_text, name):
            continue
        if any(_bootstrap_base_has_function_declaration(dep, name) for dep in deps):
            continue
        prototype = _bootstrap_source_function_prototype(source_text, span)
        if prototype is not None:
            deps.append(prototype)

    return deps
def _bootstrap_target_calls(target_asm_text: str) -> set[str]:
    calls: set[str] = set()
    for line in target_asm_text.splitlines():
        rel_match = _BOOTSTRAP_TARGET_REL24_RE.search(line)
        if rel_match is not None:
            calls.add(rel_match.group(1))
            continue
        bl_match = _BOOTSTRAP_TARGET_BL_RE.search(line)
        if bl_match is not None:
            calls.add(bl_match.group(1))
            continue
        branch_match = _BOOTSTRAP_TARGET_B_RE.search(line)
        if branch_match is not None:
            calls.add(branch_match.group(1))
    return calls
def _bootstrap_inline_definition(function_text: str) -> str:
    lines = function_text.splitlines(keepends=True)
    body_start = 0
    while body_start < len(lines):
        stripped = lines[body_start].strip()
        if not stripped or stripped.startswith("#"):
            body_start += 1
            continue
        break
    preamble = "".join(lines[:body_start])
    definition = "".join(lines[body_start:])
    if not definition:
        return function_text

    leading_len = len(definition) - len(definition.lstrip())
    leading = definition[:leading_len]
    body = definition[leading_len:]
    if _BOOTSTRAP_INLINE_RE.match(body):
        return function_text
    if body.startswith("static "):
        return preamble + leading + "static inline " + body[len("static "):]
    return preamble + leading + "inline " + body
_BOOTSTRAP_PERMUTER_ASSERT_DEFINE_RE = re.compile(
    r"^[ \t]*#[ \t]*pragma[ \t]+_permuter[ \t]+define[ \t]+HSD_ASSERT(?:\b|\()",
    re.MULTILINE,
)
_BOOTSTRAP_RAW_ASSERT_DIRECTIVE_RE = re.compile(
    r"^[ \t]*#[ \t]*(?:define|undef)[ \t]+(?:HSD_ASSERT(?:\b|\()|__FILE__\b)"
)
def _sanitize_bootstrap_assert_macros(base_text: str) -> tuple[str, bool]:
    """Remove raw assert macro directives that conflict with _permuter define.

    decomp-permuter can carry ``#pragma _permuter define HSD_ASSERT`` safely,
    but a copied C preprocessor ``#define HSD_ASSERT(... #cond)`` later in the
    base causes PERM expansion to leave a bare stringizing ``#`` token. Only
    strip the raw directives when the permuter pragma is already present.
    """
    if _BOOTSTRAP_PERMUTER_ASSERT_DEFINE_RE.search(base_text) is None:
        return base_text, False

    lines = base_text.splitlines(keepends=True)
    kept: list[str] = []
    changed = False
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if _BOOTSTRAP_RAW_ASSERT_DIRECTIVE_RE.match(line):
            changed = True
            while (
                line.rstrip("\r\n").rstrip().endswith("\\")
                and idx + 1 < len(lines)
            ):
                idx += 1
                line = lines[idx]
            idx += 1
            continue
        kept.append(line)
        idx += 1

    if not changed:
        return base_text, False
    return "".join(kept), True
def _inject_bootstrap_same_tu_inlined_callees(
    base_text: str,
    source_text: str,
    function: str,
    target_asm_text: str,
    *,
    dependency_text: str = "",
) -> tuple[str, list[str]]:
    """Inject same-TU callee definitions when target asm has no call edge."""
    if not target_asm_text.strip():
        return base_text, []

    base_function = find_source_function(base_text, function)
    source_function = find_source_function(source_text, function)
    if base_function is None or source_function is None:
        return base_text, []

    source_spans = {
        span.name: span
        for span in find_function_definitions(source_text)
    }
    same_tu_names = set(source_spans) - {function}
    target_calls = _bootstrap_target_calls(target_asm_text)
    source_function_text = source_text[
        source_function.sig_start : source_function.full_end
    ]

    queue = [
        name
        for name in _bootstrap_source_calls(source_function_text)
        if name in same_tu_names and name not in target_calls
    ]
    queued = set(queue)
    injected: list[str] = []
    insert_names: set[str] = set()
    removals: list[Any] = []

    while queue:
        name = queue.pop(0)
        if name in injected:
            continue
        span = source_spans.get(name)
        if span is None:
            continue
        source_function_text = source_text[span.sig_start : span.full_end].strip()
        existing = find_source_function(base_text, name)
        if existing is not None:
            removals.append(existing)
        insert_names.add(name)
        injected.append(name)

        for callee in _bootstrap_source_calls(source_function_text):
            if (
                callee in same_tu_names
                and callee not in target_calls
                and callee not in queued
                and callee not in injected
            ):
                queue.append(callee)
                queued.add(callee)

    if not injected:
        return base_text, []

    patched_base = base_text
    for span in sorted(removals, key=lambda item: item.sig_start, reverse=True):
        patched_base = (
            patched_base[: span.sig_start].rstrip()
            + "\n\n"
            + patched_base[span.full_end :].lstrip("\n")
        )
    base_function = find_source_function(patched_base, function)
    if base_function is None:
        return base_text, []

    injected_texts = [
        _bootstrap_inline_definition(
            source_text[
                source_spans[name].sig_start : source_spans[name].full_end
            ].strip()
        )
        for name in sorted(insert_names, key=lambda item: source_spans[item].sig_start)
    ]
    if not injected_texts:
        return patched_base, injected

    dependencies = _bootstrap_injected_callee_dependencies(
        base_text=patched_base,
        source_text=source_text,
        dependency_text=dependency_text,
        source_spans=source_spans,
        insert_names=insert_names,
        injected_texts=injected_texts,
        function=function,
    )
    insertion_parts = [*dependencies, *injected_texts]
    insertion = "\n\n".join(insertion_parts).rstrip() + "\n\n"
    patched = (
        patched_base[: base_function.sig_start]
        + insertion
        + patched_base[base_function.sig_start :]
    )
    return patched, injected
def _format_hsd_assert_override_guidance(indent: str = "") -> str:
    lines = [
        "Candidate fix: before the <baselib/jobj.h> include, add:",
        "  #include <baselib/debug.h>",
        "  #undef HSD_ASSERT",
        "  #define HSD_ASSERT(line, cond) \\",
        "      ((cond) ? ((void) 0) : __assert(<file_sym>, line, <fn_sym>))",
        "where <file_sym> / <fn_sym> are named extern char[] symbols declared in the TU.",
        "Caution: this hint means anonymous assert strings are present in the TU; it may be neutral for the current function.",
        "If jobj.h is already included transitively through another local header, a local #undef may be too late or can perturb other functions.",
        "Verify with checkdiff for the target and nearby affected functions before keeping the include-order or wrapper change.",
    ]
    return "\n".join(f"{indent}{line}" for line in lines)
def _default_decl_order_search_summary(
    source: str,
    function: str,
    *,
    strategy: str = "promote",
) -> dict:
    from src.cli.debug import _decl_order_candidate_count, _select_decl_order_scope
    scope_map = get_decl_names_by_scope(source, function)
    selected_scope, selected_scope_reason = _select_decl_order_scope(
        scope_map,
        function,
    )
    names = scope_map.get(selected_scope) or []
    available_scopes = [
        {
            "scope": "/".join(scope_path),
            "declaration_count": len(scope_names),
            "is_top_level": scope_path == (function,),
        }
        for scope_path, scope_names in scope_map.items()
    ]
    return {
        "scope": "/".join(selected_scope),
        "selected_scope_reason": selected_scope_reason,
        "declaration_count": len(names),
        "candidate_count": _decl_order_candidate_count(
            source,
            function,
            selected_scope,
            strategy,
        ),
        "strategy": strategy,
        "available_scopes": available_scopes,
    }
@inspect_app.command(name="stuck")
def stuck(
    function: Annotated[
        str,
        typer.Argument(help="Function name to diagnose"),
    ],
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Optional target spec (YAML/JSON) for guide comparisons. "
                 "If omitted, surfaces red-flag patterns without a specific "
                 "target.",
        ),
    ] = None,
    no_pcdump: Annotated[
        bool,
        typer.Option(
            "--no-pcdump",
            help="Skip the pcdump auto-generation step if the cache is "
                 "missing. Use when you already know there's no pcdump and "
                 "want a static-only digest.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit structured digest as JSON."),
    ] = False,
    asm_hunks: Annotated[
        int,
        typer.Option(
            "--asm-hunks",
            help="Also show the top N asm-diff hunks from checkdiff. "
                 "0 (default) omits. Saves switching tools when "
                 "allocator-level analysis doesn't explain the mismatch.",
        ),
    ] = 0,
) -> None:
    """One-shot diagnostic for a stuck function.

    Composes inspect analyze + inspect guide + suggest casts and recommends the next
    workflow step. Replaces what used to be 4-5 separate commands.

    Output sections (in order):
      1. Function status — match%, TU, virtual count
      2. Pcdump cache — fresh/stale/missing
      3. Coloring summary — virtuals, SPILLED markers, pass info
      4. Guidance issues — red-flag patterns from `debug inspect guide`
      5. Suspicious casts — HIGH+MEDIUM cast warnings
      6. Asm hunks (if --asm-hunks N) — text-level diff samples
      7. Next steps — ranked by cost/likelihood
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT, _detect_frame_residual_hint, _find_unit_for_function, _get_match_pct, _load_target_spec, audit_function_casts, find_function, parse_hook_events, parse_pcdump, score_function
    from ...mwcc_debug import suggest as score_suggestions
    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function '{function}' not found in report.json.\n"
            f"Try `ninja build/GALE01/report.json` to regenerate, then retry.",
            err=True,
        )
        raise typer.Exit(2)
    src = melee_root / "src" / f"{unit}.c"
    match_pct = _get_match_pct(function, melee_root)

    # Pcdump status. If missing, try to generate (unless --no-pcdump).
    entry = pcdump_cache.lookup(melee_root, unit)
    pcdump_status: str
    pcdump_path: Optional[Path] = None
    if entry is None and not no_pcdump:
        pcdump_status = "missing — would auto-generate (run `debug dump remote src/" + unit + ".c`)"
    elif entry is None:
        pcdump_status = "missing (--no-pcdump set, skipping)"
    elif entry.fresh:
        pcdump_status = f"fresh ({entry.path.name})"
        pcdump_path = entry.path
    else:
        pcdump_status = f"stale (source modified after cache; regenerate for accuracy)"
        pcdump_path = entry.path

    # Collect digest data
    digest: dict = {
        "function": function,
        "tu": str(src.relative_to(melee_root)),
        "match_pct": match_pct,
        "pcdump_status": pcdump_status,
    }

    coloring_summary: Optional[dict] = None
    guidance_issues: list = []
    cast_warnings_high_med: list = []
    frame_residual_hint: dict | None = None
    src_text = src.read_text() if src.exists() else ""
    decl_order_summary = (
        _default_decl_order_search_summary(src_text, function)
        if src_text else None
    )
    checkdiff_classification = _get_checkdiff_classification(function, melee_root)
    static_frame_residual_hint = _frame_residual_hint_from_checkdiff_classification(
        function,
        checkdiff_classification,
        unit=unit,
    )

    if pcdump_path is not None:
        text = pcdump_path.read_text()
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is not None:
            infos = analyze_function(fn)
            mapped = sum(1 for v in infos if v.physical is not None)
            unmapped = sum(1 for v in infos if v.physical is None)
            events_list = parse_hook_events(text)
            events = find_function(events_list, function)
            n_spilled = 0
            if events is not None:
                for sec in events.simplify_sections:
                    n_spilled += sum(1 for e in sec.entries if e.spilled)
            coloring_summary = {
                "n_virtuals": len(infos),
                "mapped": mapped,
                "unmapped": unmapped,
                "spilled": n_spilled,
                "pre_pass": (fn.last_precolor_pass().name
                             if fn.last_precolor_pass() else None),
            }

            # Guidance — empty target spec surfaces red-flag patterns
            if target is not None:
                spec = _load_target_spec(target)
            else:
                spec = {"virtuals": {}}
            result = score_function(fn, spec, events=events)
            suggestions = score_suggestions(fn, result, events=events)
            guidance_issues = [{
                "virtual": s.virtual,
                "category": s.category,
                "severity": s.severity,
                "description": s.description,
                "patterns": s.patterns,
            } for s in suggestions]
        frame_residual_hint = _detect_frame_residual_hint(
            function,
            unit=unit,
            melee_root=melee_root,
            pcdump_path=pcdump_path,
        )
    if frame_residual_hint is None:
        frame_residual_hint = static_frame_residual_hint

    # Cast warnings — always run regardless of pcdump
    if src_text:
        warnings = audit_function_casts(src_text, function)
        cast_warnings_high_med = [{
            "line": w.line,
            "call_target": w.call_target,
            "arg_index": w.arg_index,
            "cast_type": w.cast_type,
            "inner_expr": w.inner_expr,
            "severity": w.severity,
            "reason": w.reason,
        } for w in warnings if w.severity in ("high", "medium")]

    # HSD_ASSERT override detection — scan the compiled .o for anonymous
    # .sdata symbols whose content matches known assert filename strings
    # (jobj.h, jobj, lobj.h, etc.).  When found, the fix is to override
    # HSD_ASSERT before the jobj.h include so the inline assert uses named
    # extern char[] symbols instead of anonymous @N ones.
    hsd_assert_strings: list[tuple[str, str]] = []
    _built_o = melee_root / "build" / "GALE01" / "src" / f"{unit}.o"
    if _built_o.exists():
        try:
            from ...mwcc_debug.o_rewriter import find_anonymous_assert_strings
            hsd_assert_strings = find_anonymous_assert_strings(_built_o)
        except Exception:
            pass

    # Next steps — ranked by cost
    next_steps: list[str] = []
    if frame_residual_hint:
        next_steps.extend(frame_residual_hint["next_steps"])
    if any(w["severity"] == "high" for w in cast_warnings_high_med):
        next_steps.append(
            "[free, static] Drop suspicious casts surfaced by suggest casts. "
            "Run `melee-agent debug suggest casts " + function + "` for "
            "full details."
        )
    if coloring_summary and coloring_summary.get("spilled", 0) > 0:
        next_steps.append(
            "[medium] Try patterns from `debug util patterns` that "
            "address SPILLED markers: widen-u8-to-u32, alias-split."
        )
    if (
        decl_order_summary is not None
        and decl_order_summary["candidate_count"] > 0
    ):
        if frame_residual_hint and frame_residual_hint.get("kind") in {
            "frame-size",
            "same-frame-stack-slot-placement",
        }:
            next_steps.append(
                "[~70sec] Optional cheap probe: run `melee-agent debug mutate "
                "decl-orders " + function + "` after the headline stack-layout "
                "tool; decl-order search is often neutral on this class."
            )
        else:
            next_steps.append(
                "[~70sec] Run `melee-agent debug mutate decl-orders " + function +
                "` — brute-forces the decl-order search space, finds 1-line wins."
            )
        next_steps.append(
            "[minutes] Run `melee-agent debug inspect diagnose " + function +
            "` for a current-tooling diagnosis (combines force-phys evidence + "
            "mutate decl-orders without treating the function as impossible)."
        )
    elif decl_order_summary is not None:
        next_steps.append(
            "[free] Skip direct decl-order search: no decl-order candidates "
            f"in default scope {decl_order_summary['scope']} "
            f"({decl_order_summary['declaration_count']} declaration"
            f"{'' if decl_order_summary['declaration_count'] == 1 else 's'})."
        )
        next_steps.append(
            "[minutes] Run `melee-agent debug inspect diagnose " + function +
            " --skip-decl-orders` for the remaining current-tooling diagnosis."
        )
    else:
        next_steps.append(
            "[minutes] Run `melee-agent debug inspect diagnose " + function +
            " --skip-decl-orders` for a current-tooling diagnosis; source was "
            "unavailable for decl-order preflight."
        )
    next_steps.append(
        "[hours] As a last resort, run decomp-permuter and feed its "
        "outputs through `debug permute triage`."
    )

    digest["coloring_summary"] = coloring_summary
    digest["guidance_issues"] = guidance_issues
    digest["cast_warnings"] = cast_warnings_high_med
    digest["checkdiff_classification"] = checkdiff_classification
    digest["decl_order_summary"] = decl_order_summary
    digest["hsd_assert_strings"] = [
        {"sym": s, "string": v} for s, v in hsd_assert_strings
    ]
    digest["frame_residual"] = frame_residual_hint
    digest["next_steps"] = next_steps

    if json_out:
        print(json.dumps(digest, indent=2))
        return

    # Human-readable output
    print(f"== Function status ==")
    print(f"  {function}")
    print(f"  TU:       {digest['tu']}")
    if match_pct is not None:
        print(f"  Match:    {match_pct:.2f}%")
    else:
        print(f"  Match:    (no entry in report.json)")
    print()

    print(f"== Pcdump cache ==")
    print(f"  {pcdump_status}")
    print()

    if coloring_summary:
        s = coloring_summary
        print(f"== Coloring summary ==")
        print(f"  Virtuals:    {s['n_virtuals']} ({s['mapped']} mapped, "
              f"{s['unmapped']} unmapped)")
        print(f"  Spilled:     {s['spilled']}")
        print(f"  Pre-pass:    {s['pre_pass']}")
        print()

    if guidance_issues:
        print(f"== Guidance issues ({len(guidance_issues)}) ==")
        for issue in guidance_issues:
            marker = {"high": "!!", "medium": "!", "low": "·"}.get(
                issue["severity"], " ")
            print(f"  {marker} [r{issue['virtual']} / {issue['category']}]")
            print(f"     {issue['description']}")
            if issue["patterns"]:
                names = ", ".join(f"`{p}`" for p in issue["patterns"])
                print(f"     Patterns: {names}")
        print()
    elif coloring_summary:
        print(f"== Guidance issues ==")
        if frame_residual_hint:
            print(f"  (none from register-allocation guidance; see "
                  f"frame/local-area residual below.)")
        else:
            print(f"  (none — pcdump available but no flagged issues. Provide "
                  f"--target to compare against a specific mapping.)")
        print()

    if frame_residual_hint:
        print(f"== Frame/local-area residual ==")
        print(f"  {frame_residual_hint['message']}")
        print()

    if cast_warnings_high_med:
        print(f"== Suspicious casts ({len(cast_warnings_high_med)}) ==")
        for w in cast_warnings_high_med:
            marker = {"high": "!!", "medium": "!"}.get(w["severity"], " ")
            print(f"  {marker} line {w['line']}: ({w['cast_type']}) "
                  f"{w['inner_expr']} → {w['call_target']}")
        print()

    if hsd_assert_strings:
        syms_str = ", ".join(f"{s} ({v!r})" for s, v in hsd_assert_strings)
        print(f"== HSD_ASSERT override needed ==")
        print(f"  Anonymous .sdata assert strings detected: {syms_str}")
        print(f"  These come from HSD_ASSERT inside jobj.h (or similar) inline")
        print(f"  functions. The relocation names will differ from the target .o.")
        print(_format_hsd_assert_override_guidance("  "))
        print()

    if asm_hunks > 0:
        hunks = _get_asm_hunks(function, melee_root, top_n=asm_hunks)
        if hunks is None:
            print(f"== Asm hunks ==")
            print(f"  (checkdiff didn't produce a diff — either matching, "
                  f"not built, or errored. Try `tools/checkdiff.py "
                  f"{function}` directly.)")
            print()
        elif hunks:
            print(f"== Top {len(hunks)} asm hunks (by diff size) ==")
            print(_format_asm_hunks(hunks))
            print()

    print(f"== Next steps (ranked by cost) ==")
    for i, step in enumerate(next_steps, 1):
        print(f"  {i}. {step}")
def _ceiling_recommendations(function: str, unit: str) -> list[str]:
    """Next steps when current fast transforms found no path."""
    src_rel = f"src/{unit}.c"
    return [
        "No fast transform found from casts or decl-order. Next options:",
        "  (a) Construct a target mapping and run "
        f"`melee-agent debug dump local {src_rel} --force-phys ... "
        f"--force-phys-fn {function}` to test whether the force-target "
        "can be reached from the current IR.",
        "      If local dump support is unavailable in this environment, use "
        f"`melee-agent debug dump remote {src_rel} --force-phys ... "
        f"--force-phys-fn {function}` as the remote fallback.",
        "  (b) If force-phys reaches the target, this requires "
        "source-shape search; run decomp-permuter or a focused mutation "
        "campaign.",
        "  (c) If force-phys does not reach the target, record the "
        "force-target-not-reached evidence as unresolved by current "
        "heuristics, then move to another target until new evidence or a "
        "broader search path exists.",
    ]
def _format_force_phys_members(entries: list[DiagnoseForcePhysEntry]) -> str:
    return ", ".join(f"r{entry.virtual}->r{entry.phys}" for entry in entries)
def _cluster_entries_by_virtuals(
    entries: list[DiagnoseForcePhysEntry],
    virtuals: list[int],
) -> list[DiagnoseForcePhysEntry]:
    by_virtual = {entry.virtual: entry for entry in entries}
    return [by_virtual[v] for v in virtuals if v in by_virtual]
def _attempt_evidence_for_keywords(
    function: str,
    keywords: list[str],
) -> dict:
    from ..tracking import summarize_attempts

    summary = summarize_attempts(function)
    attempts = summary.get("attempts", [])
    matches: list[dict] = []
    lowered_keywords = [keyword.lower() for keyword in keywords]
    for attempt in attempts:
        text = " ".join(
            str(attempt.get(key) or "")
            for key in ("note", "classification", "blocker", "verdict")
        ).lower()
        if lowered_keywords and not any(keyword in text for keyword in lowered_keywords):
            continue
        matches.append(attempt)

    retained = [attempt for attempt in matches if attempt.get("retained")]
    negative = [
        attempt for attempt in matches
        if str(attempt.get("outcome") or "") in {
            "neutral", "regressed", "reverted", "blocked",
        }
    ]
    if retained:
        status = "retained-source-improvement"
    elif negative:
        status = "negative-evidence"
    elif matches:
        status = "tried"
    else:
        status = "untried"
    evidence_notes: list[str] = []
    for attempt in (retained or negative or matches)[:3]:
        note = str(attempt.get("blocker") or attempt.get("note") or "").strip()
        if not note:
            continue
        if len(note) > 220:
            note = note[:217].rstrip() + "..."
        evidence_notes.append(note)
    return {
        "status": status,
        "attempt_count": len(matches),
        "evidence": evidence_notes,
    }
def _coverage_family(
    *,
    function: str,
    name: str,
    keywords: list[str],
    expected_effect: str,
    next_probe: str,
) -> dict:
    evidence = _attempt_evidence_for_keywords(function, keywords)
    return {
        "name": name,
        "status": evidence["status"],
        "attempt_count": evidence["attempt_count"],
        "evidence": evidence["evidence"],
        "expected_effect": expected_effect,
        "next_probe": next_probe,
    }
def _force_phys_coverage_matrix(
    *,
    function: str,
    unit: str,
    clusters: list[dict],
) -> list[dict]:
    src_rel = f"src/{unit}.c"
    rows: list[dict] = []
    for cluster in clusters:
        name = cluster.get("name", "")
        holders = [
            f"ig{virtual}->r{phys}"
            for virtual, phys in zip(
                cluster.get("virtuals", []),
                cluster.get("phys", []),
                strict=False,
            )
        ]
        if function == "ftCo_8009E7B4" and "early" in name:
            rows.append({
                "cluster": name,
                "source_file": src_rel,
                "source_regions": [
                    "early flag/reload block",
                    "boolean flag temp and reload boundary",
                    "early volatile call-adjacent temps",
                ],
                "target_holders": holders,
                "transform_families": [
                    _coverage_family(
                        function=function,
                        name="flag-temp split/merge",
                        keywords=["flag", "split", "merge", "boolean"],
                        expected_effect="move volatile proof holders together",
                        next_probe="split/merge the flag temp and keep reload placement stable",
                    ),
                    _coverage_family(
                        function=function,
                        name="reload sink/hoist",
                        keywords=["reload", "sink", "hoist", "remote permuter"],
                        expected_effect="change reload live-range overlap near ig58/ig44/ig42",
                        next_probe="move the reload closer to first use or preserve it across the branch",
                    ),
                    _coverage_family(
                        function=function,
                        name="early local declaration/use order",
                        keywords=["decl", "order", "early", "local"],
                        expected_effect="change allocator tie-break order without semantic refactor",
                        next_probe="try scoped declaration/use-boundary movement in the early block",
                    ),
                ],
            })
        elif function == "ftCo_8009E7B4" and "late" in name:
            rows.append({
                "cluster": name,
                "source_file": src_rel,
                "source_regions": [
                    "x594_b4/x594_b3 field-bit tests",
                    "loop IV/tree-pointer lifetime boundary",
                    "late callee-save holder overlap",
                ],
                "target_holders": holders,
                "transform_families": [
                    _coverage_family(
                        function=function,
                        name="b4/b3 direct field test vs named temps",
                        keywords=["b4", "b3", "field", "tree probes"],
                        expected_effect="move late callee-save proof holders around field-bit tests",
                        next_probe="compare direct field tests with named temp forms",
                    ),
                    _coverage_family(
                        function=function,
                        name="loop index vs pointer-walk role split",
                        keywords=["loop", "tree", "pointer", "iv", "b4"],
                        expected_effect="change loop IV/tree-pointer holder overlap",
                        next_probe="split pointer-walk base from loop index and validate real-tree output",
                    ),
                    _coverage_family(
                        function=function,
                        name="tree-pointer reload sink/hoist",
                        keywords=["tree", "reload", "sink", "hoist"],
                        expected_effect="change r30/r29 callee-save pressure in the late cluster",
                        next_probe="sink or hoist the tree-pointer reload across the bit-test block",
                    ),
                ],
            })
        else:
            rows.append({
                "cluster": name,
                "source_file": src_rel,
                "source_regions": [
                    "proof-vector source region unresolved",
                    "run virtual-to-var or first-divergence to refine spans",
                ],
                "target_holders": holders,
                "transform_families": [
                    _coverage_family(
                        function=function,
                        name="clustered source-shape probe",
                        keywords=["source", "shape", "probe", "force"],
                        expected_effect="move all proof holders in this cluster together",
                        next_probe="instantiate one source-shape edit per mapped holder region",
                    )
                ],
            })
    return rows
def _diagnose_coupled_force_phys_guidance(
    *,
    function: str,
    unit: str,
    force_phys: str | None,
) -> dict | None:
    from src.cli.debug import _parse_diagnose_force_phys
    if not force_phys:
        return None
    entries, normalized, warnings = _parse_diagnose_force_phys(force_phys)
    if len(entries) < 3:
        return {
            "proof_force_phys": normalized,
            "warnings": warnings,
            "coupled": False,
            "reason": (
                "At least three proof assignments are needed before diagnose "
                "treats the vector as a coupled source-shape problem."
            ),
            "entries": [
                {
                    "class_id": entry.class_id,
                    "virtual": entry.virtual,
                    "phys": entry.phys,
                }
                for entry in entries
            ],
            "clusters": [],
            "experiments": [],
            "verification_commands": [],
        }

    entry_virtuals = {entry.virtual for entry in entries}
    clusters: list[dict] = []
    experiments: list[str] = []
    if function == "ftCo_8009E7B4" and (
        entry_virtuals & {58, 44, 42}
    ) and (
        entry_virtuals & {35, 56, 34}
    ):
        early = _cluster_entries_by_virtuals(entries, [58, 44, 42])
        late = _cluster_entries_by_virtuals(entries, [35, 56, 34])
        clusters = [
            {
                "name": "early flag/reload temps",
                "members": _format_force_phys_members(early),
                "virtuals": [entry.virtual for entry in early],
                "phys": [entry.phys for entry in early],
                "rationale": (
                    "These volatile-register targets sit around the early "
                    "flag/reload path; changing one temp alone leaves the "
                    "same allocator pressure for the neighboring reloads."
                ),
            },
            {
                "name": "late x594_b4/x594_b3 loop IV/tree-pointer swaps",
                "members": _format_force_phys_members(late),
                "virtuals": [entry.virtual for entry in late],
                "phys": [entry.phys for entry in late],
                "rationale": (
                    "These callee-save targets couple the late field-bit "
                    "tests with loop-index and tree-pointer lifetimes."
                ),
            },
        ]
        experiments = [
            (
                "Early cluster: try natural flag/reload variants together "
                "(split or merge the flag temp, move the reload closer to "
                "first use, and reorder the nearby boolean/reload locals)."
            ),
            (
                "Late cluster: try natural x594_b4/x594_b3 variants together "
                "(direct field tests versus named temps, swap loop IV and "
                "tree-pointer declaration/use order, and hoist/sink the "
                "tree-pointer reload)."
            ),
            (
                "Combined probe: apply one early-cluster edit and one "
                "late-cluster edit in the same candidate before judging the "
                "byte score; this is a multi-site allocator-shape hypothesis."
            ),
        ]
    else:
        volatile = [
            entry for entry in entries
            if entry.phys <= 12 or entry.virtual >= 40
        ]
        callee_save = [entry for entry in entries if entry not in volatile]
        if not volatile or not callee_save:
            mid = max(1, len(entries) // 2)
            volatile = entries[:mid]
            callee_save = entries[mid:]
        clusters = [
            {
                "name": "volatile/reload-pressure cluster",
                "members": _format_force_phys_members(volatile),
                "virtuals": [entry.virtual for entry in volatile],
                "phys": [entry.phys for entry in volatile],
                "rationale": (
                    "These assignments bias volatile or high-numbered temps; "
                    "they often move when reloads, predicates, or call-return "
                    "copies are reshaped together."
                ),
            },
            {
                "name": "callee-save/lifetime-pressure cluster",
                "members": _format_force_phys_members(callee_save),
                "virtuals": [entry.virtual for entry in callee_save],
                "phys": [entry.phys for entry in callee_save],
                "rationale": (
                    "These assignments bias longer-lived callee-save choices; "
                    "they often need loop, cursor, or pointer lifetime changes."
                ),
            },
        ]
        experiments = [
            (
                "Treat each cluster as one source-shape region, not as "
                "independent virtual nudges."
            ),
            (
                "Combine one volatile/reload edit with one lifetime-pressure "
                "edit before judging whether the allocator movement is useful."
            ),
        ]

    src_rel = f"src/{unit}.c"
    guidance = {
        "proof_force_phys": normalized,
        "warnings": warnings,
        "coupled": True,
        "entries": [
            {
                "class_id": entry.class_id,
                "virtual": entry.virtual,
                "phys": entry.phys,
            }
            for entry in entries
        ],
        "clusters": clusters,
        "partial_probe_explanation": (
            "singleton/prefix force-phys probes can no-match because each "
            "partial override preserves pressure that the other cluster must "
            "also relieve; a union byte-match is evidence for coupled source "
            "shape, not independent one-virtual nudges."
        ),
        "hypothesis": (
            "multi-site allocator-shape hypothesis: look for natural C edits "
            "that move both clusters together, then re-score assignment "
            "satisfaction and byte preservation."
        ),
        "experiments": experiments,
        "verification_commands": [
            (
                f"melee-agent debug dump local {src_rel} --force-phys "
                f"{normalized} --force-phys-fn {function}"
            ),
            (
                f"melee-agent debug inspect diagnose {function} "
                f"--skip-decl-orders --force-phys {normalized}"
            ),
        ],
    }
    guidance["coverage_matrix"] = _force_phys_coverage_matrix(
        function=function,
        unit=unit,
        clusters=clusters,
    )
    return guidance
def _print_coupled_force_phys_guidance(guidance: dict) -> None:
    if not guidance.get("coupled"):
        print("[!] Force-phys proof vector:")
        print(f"    {guidance.get('reason', 'not enough entries')}")
        print()
        return
    print("[!] Coupled force-phys proof vector:")
    print(f"    proof: {guidance['proof_force_phys']}")
    for warning in guidance.get("warnings", []):
        print(f"    warning: {warning}")
    print("    Clusters:")
    for cluster in guidance.get("clusters", []):
        print(f"      - {cluster['name']}: {cluster['members']}")
        if cluster.get("rationale"):
            print(f"        {cluster['rationale']}")
    print(f"    Why partial probes fail: {guidance['partial_probe_explanation']}")
    print(f"    Hypothesis: {guidance['hypothesis']}")
    if guidance.get("experiments"):
        print("    Source experiments:")
        for experiment in guidance["experiments"]:
            print(f"      - {experiment}")
    if guidance.get("coverage_matrix"):
        print("    Source-lever coverage matrix:")
        for row in guidance["coverage_matrix"]:
            print(f"      - {row['cluster']}:")
            print(f"        source: {row['source_file']}")
            print(f"        regions: {', '.join(row.get('source_regions') or [])}")
            print(f"        holders: {', '.join(row.get('target_holders') or [])}")
            for family in row.get("transform_families", []):
                print(
                    f"        * {family['name']} "
                    f"(status: {family['status']}, "
                    f"attempts: {family['attempt_count']})"
                )
                if family.get("evidence"):
                    print(f"          evidence: {'; '.join(family['evidence'])}")
                print(f"          expected: {family['expected_effect']}")
                print(f"          next: {family['next_probe']}")
    if guidance.get("verification_commands"):
        print("    Verify:")
        for command in guidance["verification_commands"]:
            print(f"      {command}")
    print()
def _register_tiebreak_guidance(
    *,
    function: str,
    unit: str | None,
    force_phys: str,
) -> dict:
    from src.cli.debug import _parse_diagnose_force_phys
    entries, normalized, warnings = _parse_diagnose_force_phys(force_phys)
    src_rel = f"src/{unit}.c" if unit else "<source.c>"
    targets = [
        {
            "class_id": entry.class_id,
            "ig_idx": entry.virtual,
            "target_phys": entry.phys,
            "register": f"r{entry.phys}",
            "below_registers": [f"r{reg}" for reg in range(3, entry.phys)],
        }
        for entry in entries
    ]
    primary = targets[0]
    primary_ig = primary["ig_idx"]
    primary_phys = primary["target_phys"]
    below_registers = primary["below_registers"]
    below_text = ", ".join(below_registers) if below_registers else (
        "the lower volatile register set"
    )
    levers = [
        {
            "rank": 1,
            "kind": "interference-insertion",
            "target": f"ig{primary_ig}->r{primary_phys}",
            "description": (
                f"Keep a nearby named value live across ig{primary_ig}'s first "
                f"definition so the allocator must occupy {below_text} before "
                f"the compiler temp is colored."
            ),
            "source_moves": [
                (
                    "Introduce a short-lived alias for a pointer, counter, or "
                    "table expression immediately before the temp's defining "
                    "expression, then consume it after that expression."
                ),
                (
                    "Extend an existing loop or table pointer's lifetime by "
                    "moving its last use just past the temp definition."
                ),
            ],
        },
        {
            "rank": 2,
            "kind": "simplify-order-shift",
            "target": f"ig{primary_ig}->r{primary_phys}",
            "description": (
                f"move the defining expression for ig{primary_ig} later in "
                "source order, or sink the load/use that creates the compiler "
                "temp closer to its first real use."
            ),
            "source_moves": [
                (
                    "Inline a one-use table/global expression at the store or "
                    "call site instead of materializing it before loop pressure "
                    "is established."
                ),
                (
                    "Split a combined condition or store so the temp-producing "
                    "subexpression appears after the named holder that should "
                    f"claim {below_text}."
                ),
            ],
        },
        {
            "rank": 3,
            "kind": "targeted-alias",
            "target": f"ig{primary_ig}->r{primary_phys}",
            "description": (
                "Try a scoped alias around the first defining expression to "
                "change the temp's local lifetime without changing observable C."
            ),
            "source_moves": [
                (
                    "Use `debug mutate insert-alias` on candidate holder "
                    "locals near the temp definition, then score against the "
                    "force-phys objective."
                ),
            ],
        },
    ]
    verification_commands = [
        (
            f"melee-agent debug inspect virtual-to-var -f {function} "
            f"r{primary_ig}"
        ),
        (
            f"melee-agent debug inspect first-divergence -f {function} "
            f"--force-phys {normalized} --source"
        ),
        (
            f"melee-agent debug dump local {src_rel} --force-phys "
            f"{normalized} --force-phys-fn {function}"
        ),
        (
            f"melee-agent debug mutate simplify-order --fn {function} "
            f"--force-phys {normalized} --no-preserve-precolor"
        ),
        (
            f"melee-agent debug mutate decl-orders {function} --strategy all"
        ),
    ]
    return {
        "function": function,
        "source": src_rel,
        "normalized_force_phys": normalized,
        "warnings": warnings,
        "targets": targets,
        "levers": levers,
        "verification_commands": verification_commands,
        "notes": [
            (
                "This is source guidance for Case B/C compiler-temp register "
                "tiebreaks: force-phys proves reachability, but no source "
                "variable is directly bound to the temp."
            ),
            (
                "Prefer variants that preserve the target function's current "
                "byte score until the requested physical assignment moves."
            ),
        ],
    }
def _print_register_tiebreak_guidance(guidance: dict) -> None:
    print(f"Register-tiebreak source levers for {guidance['function']}")
    print(f"  force-phys: {guidance['normalized_force_phys']}")
    print(f"  source:     {guidance['source']}")
    for warning in guidance.get("warnings", []):
        print(f"  warning:    {warning}")
    print()
    print("Targets:")
    for target in guidance["targets"]:
        below = ", ".join(target["below_registers"]) or "none below target"
        print(f"  - ig{target['ig_idx']} -> r{target['target_phys']} "
              f"(below: {below})")
    print()
    print("Source levers:")
    for lever in guidance["levers"]:
        print(f"  {lever['rank']}. {lever['kind']}: {lever['description']}")
        for move in lever.get("source_moves", []):
            print(f"     - {move}")
    print()
    print("Verify:")
    for command in guidance["verification_commands"]:
        print(f"  {command}")
def _diagnose_site_hint(site) -> dict:
    return {
        "block_idx": site.block_idx,
        "opcode": site.opcode,
        "operands": site.operands,
    }
def _diagnose_spilled_virtual_hints(
    pcdump_text: str,
    function: str,
    source_text: str,
    *,
    source_file: str | None = None,
) -> list[dict]:
    """Return source-oriented diagnose hints for SPILLED virtuals."""
    from src.cli.debug import find_function, parse_hook_events
    events = find_function(parse_hook_events(pcdump_text), function)
    spilled_virts: list[int] = []
    if events is not None:
        seen: set[int] = set()
        for section in events.simplify_sections:
            for entry in section.entries:
                if (
                    entry.spilled
                    and entry.ig_idx >= 32
                    and entry.ig_idx not in seen
                ):
                    seen.add(entry.ig_idx)
                    spilled_virts.append(entry.ig_idx)
    if not spilled_virts:
        return []

    attribution_by_virtual = {}
    try:
        from ...mwcc_debug.virtual_attribution import explain_virtuals
        report = explain_virtuals(
            pcdump_text,
            function,
            virtuals=spilled_virts,
            source_text=source_text,
            source_file=source_file,
        )
        attribution_by_virtual = {
            entry.virtual: entry
            for entry in report.virtuals
        }
    except Exception:
        attribution_by_virtual = {}

    hints: list[dict] = []
    for virtual in spilled_virts:
        hint: dict = {"virtual": virtual}
        source = getattr(attribution_by_virtual.get(virtual), "source", None)
        if source is not None:
            hint["kind"] = source.kind
            hint["confidence"] = source.confidence
            if source.name:
                hint["var_name"] = source.name
            if source.source_file:
                hint["source_file"] = source.source_file
            if source.source_line is not None:
                hint["source_line"] = source.source_line
            if source.source_col is not None:
                hint["source_col"] = source.source_col
            if source.expression:
                hint["expression"] = source.expression
            if source.call_symbol:
                hint["call_symbol"] = source.call_symbol
            if source.copy_chain:
                hint["copy_chain"] = list(source.copy_chain)
            if source.base_virtual is not None:
                hint["base_virtual"] = source.base_virtual
            if source.base_var:
                hint["base_var"] = source.base_var
            if source.field_offset is not None:
                hint["field_offset"] = source.field_offset
            if source.field_name:
                hint["field_name"] = source.field_name
            if source.first_def is not None:
                hint["first_def"] = _diagnose_site_hint(source.first_def)
            if source.use_sites:
                hint["use_sites"] = [
                    _diagnose_site_hint(site)
                    for site in source.use_sites[:3]
                ]
        first_def = hint.get("first_def")
        if (
            isinstance(first_def, dict)
            and first_def.get("opcode") == "li"
            and first_def.get("block_idx") == 0
        ):
            hint["inline_hint"] = (
                "compiler-emitted immediate (li) in "
                "entry block — likely an inlined "
                "sentinel/return value; check "
                "static-inline callees for "
                "restructurable return paths"
            )
        hints.append(hint)
    return hints
def _format_diagnose_hint_location(hint: dict) -> str:
    source_file = hint.get("source_file")
    source_line = hint.get("source_line")
    if not source_file or source_line is None:
        return ""
    loc = f" {source_file}:{source_line}"
    if hint.get("source_col") is not None:
        loc += f":{hint['source_col']}"
    return loc
def _diagnose_call_return_recommendations(
    function: str,
    hints: list[dict],
) -> list[str]:
    call_hints = [h for h in hints if h.get("kind") == "call-return"]
    if not call_hints:
        return []
    regs = ", ".join(f"r{h['virtual']}" for h in call_hints[:5])
    expressions = []
    for hint in call_hints:
        expression = hint.get("expression") or hint.get("call_symbol")
        if expression and expression not in expressions:
            expressions.append(str(expression))
    expr_text = ", ".join(expressions[:2]) if expressions else "call returns"
    return [
        f"Spilled call-return copies ({regs}) trace to {expr_text}; "
        "prioritize call-return compare-chain source probes "
        f"(`melee-agent debug mutate lifetime-layout -f {function} ...` "
        "or `debug select-order-search`) before chasing unrelated locals."
    ]
def _read_diagnose_expected_asm(
    function: str,
    unit: str,
    melee_root: Path,
) -> str | None:
    from src.cli.debug import _read_frame_reservation_expected_asm
    asm_path = melee_root / "build" / "GALE01" / "asm" / f"{unit}.s"
    if asm_path.exists():
        return asm_path.read_text()
    try:
        return _read_frame_reservation_expected_asm(
            function,
            expected_asm=None,
            no_expected=False,
            melee_root=melee_root,
        )
    except Exception:
        return None
def _value_numbering_ceiling_recommendation(finding: Mapping[str, Any]) -> str:
    recommendation = finding.get("recommendation")
    if isinstance(recommendation, str) and recommendation:
        return f"value-numbering ceiling: {recommendation}"
    return (
        "value-numbering ceiling: target rematerializes a signed "
        "magic divide while this compile CSEs the quotient; bank this as a "
        "current-tooling ceiling unless a new semantic source-transform family "
        "is added."
    )
def _print_value_numbering_ceiling(finding: Mapping[str, Any]) -> None:
    print("[!] Value-numbering ceiling:")
    kind = finding.get("kind") or "unknown"
    confidence = finding.get("confidence") or "unknown"
    print(f"    {kind} ({confidence})")
    print(
        "    target rematerializes the signed magic divide quotient; "
        "current compile reuses the value-numbered quotient before xoris"
    )
    print(f"    {_value_numbering_ceiling_recommendation(finding)}")
    print()
_IDENT_RE = r"[A-Za-z_][A-Za-z0-9_]*"
def _find_brace_close(text: str, open_idx: int) -> int | None:
    depth = 0
    for idx in range(open_idx, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx
    return None
def _find_matching_delimiter(
    text: str,
    open_idx: int,
    *,
    opener: str = "(",
    closer: str = ")",
) -> int | None:
    depth = 0
    for idx in range(open_idx, len(text)):
        ch = text[idx]
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return idx
    return None
def _loop_ranges_in_body(body: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(r"\b(?:for|while)\s*\([^{};]*\)\s*\{", body):
        open_idx = match.end() - 1
        close_idx = _find_brace_close(body, open_idx)
        if close_idx is not None:
            ranges.append((open_idx, close_idx))
    return ranges
def _loop_id_for_offset(
    ranges: list[tuple[int, int]],
    offset: int,
) -> tuple[int, int] | None:
    containing = [
        range_pair
        for range_pair in ranges
        if range_pair[0] < offset < range_pair[1]
    ]
    if not containing:
        return None
    return min(containing, key=lambda range_pair: range_pair[1] - range_pair[0])
def _loop_has_self_update(body: str, loop_id: tuple[int, int], name: str) -> bool:
    loop_text = body[loop_id[0] + 1:loop_id[1]]
    ident = re.escape(name)
    return any(
        re.search(pattern, loop_text)
        for pattern in (
            rf"(?:\+\+\s*{ident}\b|--\s*{ident}\b|\b{ident}\s*(?:\+\+|--))",
            rf"\b{ident}\s*(?:\+=|-=|\*=|/=|%=)",
            rf"\b{ident}\s*=\s*[^;]*\b{ident}\b[^;]*;",
        )
    )
def _detect_disp_form_rollback_hint(
    source_text: str,
    function: str,
) -> dict[str, Any] | None:
    """Detect the hsd_3AA7 rollback-store source shape from issue #418."""
    span = find_source_function(source_text, function)
    if span is None:
        return None
    body = source_text[span.body_open + 1:span.body_close]
    cached_base_matches = list(re.finditer(
        rf"\bCardBufEntry\s*\*\s*(?P<name>{_IDENT_RE})\s*=\s*"
        r"\(\s*CardBufEntry\s*\*\s*\)\s*hsd_804D1138\s*;",
        body,
    ))
    cached_base_names = sorted({
        match.group("name") for match in cached_base_matches
    })

    store_sites: list[dict[str, Any]] = []
    inline_store_re = re.compile(
        rf"\(\s*\(\s*CardBufEntry\s*\*\s*\)\s*hsd_804D1138\s*\)"
        rf"\s*\[\s*(?P<index>{_IDENT_RE})\s*\]\s*\.\s*x10\s*=\s*0\s*;"
    )
    for match in inline_store_re.finditer(body):
        store_sites.append({
            "kind": "inline-base-cast",
            "index": match.group("index"),
            "offset": match.start(),
        })

    for base_name in cached_base_names:
        cached_store_re = re.compile(
            rf"\b{re.escape(base_name)}\s*\[\s*(?P<index>{_IDENT_RE})\s*\]"
            r"\s*\.\s*x10\s*=\s*0\s*;"
        )
        for match in cached_store_re.finditer(body):
            store_sites.append({
                "kind": "cached-base",
                "base_name": base_name,
                "index": match.group("index"),
                "offset": match.start(),
            })

    if not store_sites:
        return None

    store_sites.sort(key=lambda site: site["offset"])
    loop_ranges = _loop_ranges_in_body(body)
    loop_ids_by_index: dict[str, set[tuple[int, int]]] = {}
    rollback_loop_ids: set[tuple[int, int]] = set()
    for site in store_sites:
        loop_id = _loop_id_for_offset(loop_ranges, site["offset"])
        site["loop_id"] = loop_id
        if loop_id is None:
            continue
        rollback_loop_ids.add(loop_id)
        loop_ids_by_index.setdefault(site["index"], set()).add(loop_id)

    rollback_store_sites = [
        site for site in store_sites if site.get("loop_id") is not None
    ]
    if not rollback_store_sites:
        return None

    cached_store_count = sum(
        1 for site in rollback_store_sites if site["kind"] == "cached-base"
    )
    inline_store_count = sum(
        1 for site in rollback_store_sites if site["kind"] == "inline-base-cast"
    )
    recommendations: list[str] = []
    if cached_store_count:
        inline_base_cast_hint = {
            "status": "recommended",
            "cached_base_names": cached_base_names,
            "message": (
                "Inline base cast at rollback stores so MWCC can select "
                "disp-form stores instead of folding the field offset into "
                "the indexed address."
            ),
        }
        recommendations.append(
            "inline base cast at each rollback store, for example "
            "`((CardBufEntry*) hsd_804D1138)[saved].x10 = 0;`, then "
            "verify because this is pressure-gated."
        )
    else:
        inline_base_cast_hint = {
            "status": "already-applied",
            "cached_base_names": cached_base_names,
            "message": "Rollback stores already use the inline CardBufEntry base cast.",
        }

    shared_index_names = sorted(
        index
        for index, loop_ids in loop_ids_by_index.items()
        if len({
            loop_id
            for loop_id in loop_ids
            if _loop_has_self_update(body, loop_id, index)
        }) >= 2
    )
    if len(rollback_loop_ids) >= 2 and shared_index_names:
        per_loop_local_split_hint = {
            "status": "recommended",
            "shared_index_names": shared_index_names,
            "rollback_loop_count": len(rollback_loop_ids),
            "message": (
                "Split shared rollback loop-carried locals into per-loop "
                "copies so MWCC can color each rollback loop independently."
            ),
        }
        recommendations.append(
            "Split shared rollback loop-carried locals into per-loop copies "
            f"({', '.join(shared_index_names)}), leaving each loop with its "
            "own snapshot/index pair."
        )
    else:
        per_loop_local_split_hint = {
            "status": "not-needed",
            "shared_index_names": shared_index_names,
            "rollback_loop_count": len(rollback_loop_ids),
            "message": (
                "Per-loop local splitting is only suggested when two or more "
                "rollback loops reuse the same loop-carried locals."
            ),
        }

    return {
        "kind": "disp-form-rollback-source-shape",
        "rollback_store_count": len(rollback_store_sites),
        "rollback_loop_count": len(rollback_loop_ids),
        "cached_store_count": cached_store_count,
        "inline_store_count": inline_store_count,
        "cached_base_names": cached_base_names,
        "inline_base_cast_hint": inline_base_cast_hint,
        "per_loop_local_split_hint": per_loop_local_split_hint,
        "pressure_gate": {
            "status": "pressure-gated",
            "message": (
                "Known good on low-register-pressure rollback functions; "
                "high-parameter/high-pressure functions can regress unless a "
                "pressure-reducing companion transform is found."
            ),
        },
        "recommendations": recommendations,
    }
def _print_disp_form_rollback_hint(hint: Mapping[str, Any]) -> None:
    print("[!] Disp-form rollback/source-shape hint:")
    inline_hint = hint.get("inline_base_cast_hint") or {}
    split_hint = hint.get("per_loop_local_split_hint") or {}
    pressure_gate = hint.get("pressure_gate") or {}
    print(f"    inline base cast: {inline_hint.get('message', '')}")
    print(f"    per-loop locals: {split_hint.get('message', '')}")
    print(f"    pressure gate: {pressure_gate.get('message', '')}")
    print()
_INT_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<literal>[+-]?(?:0[xX][0-9A-Fa-f]+|\d+))"
    r"(?![A-Za-z0-9_])"
)
def _parse_int_literal(token: str) -> int | None:
    token = token.strip().lower()
    if not token:
        return None
    try:
        return int(token, 0)
    except ValueError:
        return None
def _format_signed_hex(value: int) -> str:
    sign = "-" if value < 0 else "+"
    return f"{sign}0x{abs(value):X}"
def _split_call_args(args_text: str) -> list[str]:
    args: list[str] = []
    start = 0
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    for idx, ch in enumerate(args_text):
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth = max(0, brace_depth - 1)
        elif (
            ch == ","
            and paren_depth == 0
            and bracket_depth == 0
            and brace_depth == 0
        ):
            args.append(args_text[start:idx].strip())
            start = idx + 1
    tail = args_text[start:].strip()
    if tail:
        args.append(tail)
    return args
def _pointer_expression_constants(expression: str) -> list[int]:
    if "+" not in expression:
        return []
    if not re.search(_IDENT_RE, expression):
        return []
    constants: list[int] = []
    for match in _INT_LITERAL_RE.finditer(expression):
        literal = match.group("literal")
        value = _parse_int_literal(literal)
        if value is not None and value not in constants:
            constants.append(value)
    return constants
def _mask_c_comments_and_strings(text: str) -> str:
    chars = list(text)
    idx = 0
    state = "code"
    while idx < len(chars):
        ch = chars[idx]
        nxt = chars[idx + 1] if idx + 1 < len(chars) else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                chars[idx] = chars[idx + 1] = " "
                idx += 2
                state = "line-comment"
                continue
            if ch == "/" and nxt == "*":
                chars[idx] = chars[idx + 1] = " "
                idx += 2
                state = "block-comment"
                continue
            if ch == '"':
                chars[idx] = " "
                idx += 1
                state = "string"
                continue
            if ch == "'":
                chars[idx] = " "
                idx += 1
                state = "char"
                continue
            idx += 1
            continue
        if state == "line-comment":
            if ch == "\n":
                state = "code"
            else:
                chars[idx] = " "
            idx += 1
            continue
        if state == "block-comment":
            if ch == "*" and nxt == "/":
                chars[idx] = chars[idx + 1] = " "
                idx += 2
                state = "code"
            else:
                if ch != "\n":
                    chars[idx] = " "
                idx += 1
            continue
        if state in {"string", "char"}:
            quote = '"' if state == "string" else "'"
            if ch == "\\":
                chars[idx] = " "
                if idx + 1 < len(chars):
                    if chars[idx + 1] != "\n":
                        chars[idx + 1] = " "
                    idx += 2
                else:
                    idx += 1
                continue
            if ch == quote:
                chars[idx] = " "
                idx += 1
                state = "code"
                continue
            if ch != "\n":
                chars[idx] = " "
            idx += 1
            continue
    return "".join(chars)
def _pointer_call_source_sites(
    source_text: str,
    function: str,
) -> list[dict[str, Any]]:
    from src.cli.debug import _POINTER_REASSOC_CALL_ARG_INDEX
    span = find_source_function(source_text, function)
    if span is None:
        return []
    body_start = span.body_open + 1
    body = source_text[body_start:span.body_close]
    masked_body = _mask_c_comments_and_strings(body)
    call_re = re.compile(
        r"\b(?P<consumer>"
        + "|".join(re.escape(name) for name in _POINTER_REASSOC_CALL_ARG_INDEX)
        + r")\s*\("
    )
    sites: list[dict[str, Any]] = []
    for match in call_re.finditer(masked_body):
        consumer = match.group("consumer")
        open_idx = match.end() - 1
        close_idx = _find_matching_delimiter(masked_body, open_idx)
        if close_idx is None:
            continue
        args = _split_call_args(body[open_idx + 1:close_idx])
        arg_index = _POINTER_REASSOC_CALL_ARG_INDEX[consumer]
        if arg_index >= len(args):
            continue
        expression = args[arg_index]
        for constant in _pointer_expression_constants(expression):
            sites.append({
                "consumer": consumer,
                "constant": constant,
                "constant_hex": _format_signed_hex(constant),
                "source_expression": expression,
                "source_line": source_text.count(
                    "\n",
                    0,
                    body_start + match.start(),
                ) + 1,
            })
    return sites
def _split_asm_operands(operands: str) -> list[str]:
    return [part.strip().lower() for part in operands.split(",")]
def _parse_add_operands(operands: str) -> tuple[str, str, str] | None:
    parts = _split_asm_operands(operands)
    if len(parts) != 3:
        return None
    if not all(re.fullmatch(r"r\d+", part) for part in parts):
        return None
    return parts[0], parts[1], parts[2]
def _parse_addi_operands(operands: str) -> tuple[str, str, int] | None:
    parts = _split_asm_operands(operands)
    if len(parts) != 3:
        return None
    if not re.fullmatch(r"r\d+", parts[0]):
        return None
    if not re.fullmatch(r"r\d+", parts[1]):
        return None
    imm = _parse_int_literal(parts[2])
    if imm is None:
        return None
    return parts[0], parts[1], imm
def _call_symbol_from_operands(operands: str) -> str | None:
    cleaned = operands.split(";", 1)[0].strip()
    if not cleaned:
        return None
    token = cleaned.split(None, 1)[0]
    token = token.split("<", 1)[0]
    return token or None
def _abi_arg_reg(arg_index: int) -> str:
    return f"r{3 + arg_index}"
def _instruction_defines_reg(instruction: AsmInstruction, reg: str) -> bool:
    if not instruction.regs:
        return False
    opcode = instruction.opcode.lower()
    if opcode.startswith("st") or opcode.startswith("b") or opcode.startswith("cmp"):
        return False
    if opcode in {"mtctr", "mtlr", "mtcrf", "mcrf"}:
        return False
    first_kind, first_number = instruction.regs[0]
    return f"{first_kind}{first_number}" == reg
def _has_register_def(
    instructions: list[AsmInstruction],
    reg: str,
) -> bool:
    return any(_instruction_defines_reg(instruction, reg) for instruction in instructions)
def _expected_pointer_reassoc_evidence(
    expected_asm_text: str | None,
    function: str,
) -> dict[tuple[str, int], dict[str, Any]]:
    from src.cli.debug import _POINTER_REASSOC_CALL_ARG_INDEX
    if not expected_asm_text:
        return {}
    asm_fn = asm_extract_function(expected_asm_text, function)
    if asm_fn is None:
        return {}
    evidence: dict[tuple[str, int], dict[str, Any]] = {}
    instructions = asm_fn.instructions
    for call_idx, instruction in enumerate(instructions):
        if instruction.opcode != "bl":
            continue
        consumer = _call_symbol_from_operands(instruction.operands)
        if consumer not in _POINTER_REASSOC_CALL_ARG_INDEX:
            continue
        arg_reg = _abi_arg_reg(_POINTER_REASSOC_CALL_ARG_INDEX[consumer])
        window_start = max(0, call_idx - 8)
        window = instructions[window_start:call_idx]
        for addi_offset, addi in enumerate(window):
            if addi.opcode != "addi":
                continue
            parsed_addi = _parse_addi_operands(addi.operands)
            if parsed_addi is None:
                continue
            addi_dest, addi_src, constant = parsed_addi
            if addi_dest != arg_reg:
                continue
            if _has_register_def(window[addi_offset + 1:], arg_reg):
                continue
            for add_idx in range(addi_offset - 1, -1, -1):
                add = window[add_idx]
                if add.opcode != "add":
                    continue
                parsed_add = _parse_add_operands(add.operands)
                if parsed_add is None:
                    continue
                add_dest, add_left, add_right = parsed_add
                if add_dest != addi_src:
                    continue
                if _has_register_def(window[add_idx + 1:addi_offset], add_dest):
                    continue
                evidence.setdefault(
                    (consumer, constant),
                    {
                        "consumer": consumer,
                        "constant": constant,
                        "arg_reg": arg_reg,
                        "shape": (
                            f"add {add_dest},{add_left},{add_right} -> "
                            f"addi {addi_dest},{addi_src},{constant}"
                        ),
                    },
                )
                break
    return evidence
def _extract_pcdump_function_chunk(
    pcdump_text: str | None,
    function: str,
) -> str | None:
    if not pcdump_text:
        return None
    start_re = re.compile(
        rf"(?m)^Starting function\s+{re.escape(function)}\b"
    )
    start = start_re.search(pcdump_text)
    if start is None:
        return None
    next_start = re.search(
        r"(?m)^Starting function\s+\S+",
        pcdump_text[start.end():],
    )
    end = (
        start.end() + next_start.start()
        if next_start is not None
        else len(pcdump_text)
    )
    return pcdump_text[start.start():end]
def _parse_pcdump_instruction(line: str) -> AsmInstruction | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("Starting function"):
        return None
    stripped = stripped.split(";", 1)[0].strip()
    if not stripped or stripped.endswith(":"):
        return None
    parts = stripped.split(None, 1)
    if not parts:
        return None
    opcode = parts[0]
    operands = parts[1].strip() if len(parts) > 1 else ""
    regs = [
        (kind, int(number))
        for kind, number in re.findall(r"\b([rf])(\d+)\b", operands)
    ]
    return AsmInstruction(opcode=opcode, operands=operands, regs=regs)
def _current_pointer_reassoc_evidence(
    current_pcdump_text: str | None,
    function: str,
) -> dict[tuple[str, int], dict[str, Any]]:
    from src.cli.debug import _POINTER_REASSOC_CALL_ARG_INDEX
    chunk = _extract_pcdump_function_chunk(current_pcdump_text, function)
    if chunk is None:
        return {}
    instructions = [
        instruction
        for line in chunk.splitlines()
        if (instruction := _parse_pcdump_instruction(line)) is not None
    ]
    evidence: dict[tuple[str, int], dict[str, Any]] = {}
    for call_idx, instruction in enumerate(instructions):
        if instruction.opcode != "bl":
            continue
        consumer = _call_symbol_from_operands(instruction.operands)
        if consumer not in _POINTER_REASSOC_CALL_ARG_INDEX:
            continue
        arg_reg = _abi_arg_reg(_POINTER_REASSOC_CALL_ARG_INDEX[consumer])
        window_start = max(0, call_idx - 8)
        window = instructions[window_start:call_idx]
        for add_offset, add in enumerate(window):
            if add.opcode != "add":
                continue
            parsed_add = _parse_add_operands(add.operands)
            if parsed_add is None:
                continue
            add_dest, add_left, add_right = parsed_add
            if add_dest != arg_reg:
                continue
            if _has_register_def(window[add_offset + 1:], arg_reg):
                continue
            for addi_idx in range(add_offset - 1, -1, -1):
                addi = window[addi_idx]
                if addi.opcode != "addi":
                    continue
                parsed_addi = _parse_addi_operands(addi.operands)
                if parsed_addi is None:
                    continue
                addi_dest, addi_src, constant = parsed_addi
                if addi_dest not in {add_left, add_right}:
                    continue
                if _has_register_def(window[addi_idx + 1:add_offset], addi_dest):
                    continue
                evidence.setdefault(
                    (consumer, constant),
                    {
                        "consumer": consumer,
                        "constant": constant,
                        "arg_reg": arg_reg,
                        "shape": (
                            f"addi {addi_dest},{addi_src},{constant} -> "
                            f"add {add_dest},{add_left},{add_right}"
                        ),
                    },
                )
                break
    return evidence
def _detect_pointer_offset_reassociation_hint(
    source_text: str,
    function: str,
    *,
    expected_asm_text: str | None,
    current_pcdump_text: str | None,
) -> dict[str, Any] | None:
    source_sites = _pointer_call_source_sites(source_text, function)
    if not source_sites:
        return None
    expected_evidence = _expected_pointer_reassoc_evidence(
        expected_asm_text,
        function,
    )
    if not expected_evidence:
        return None
    current_evidence = _current_pointer_reassoc_evidence(
        current_pcdump_text,
        function,
    )
    if not current_evidence:
        return None

    matched_sites: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for source_site in source_sites:
        key = (source_site["consumer"], source_site["constant"])
        if key in seen:
            continue
        expected = expected_evidence.get(key)
        current = current_evidence.get(key)
        if expected is None or current is None:
            continue
        seen.add(key)
        matched_sites.append({
            **source_site,
            "subkind": "call-arg-split-add-addi",
            "expected_shape": expected["shape"],
            "current_shape": current["shape"],
            "confidence": "medium",
        })
    if not matched_sites:
        return None

    return {
        "kind": "pointer-offset-constant-reassociation",
        "source_lever_status": (
            "expression-spelling-alone-not-actionable-from-current-diagnose"
        ),
        "sites": matched_sites,
        "recommendations": [
            "pointer-offset reassociation: stop cycling equivalent expression "
            "spellings unless you can show current-vs-target lowering "
            "movement; next useful proof is force-phys/source-shape "
            "reachability."
        ],
    }
def _print_pointer_offset_reassociation_hint(hint: Mapping[str, Any]) -> None:
    print("[!] Pointer-offset reassociation:")
    for site in hint.get("sites", []):
        print(
            f"    {site['consumer']} {site['constant_hex']} "
            f"line {site['source_line']}: expected add->addi, "
            "current addi->add"
        )
    print()
def _classify_decl_candidate_failure(diagnostic: Optional[str]) -> str:
    from src.cli.debug import _extract_first_diagnostic
    if diagnostic and _extract_first_diagnostic("", diagnostic):
        return "invalid-probe"
    return "build-failed"
def _run_decl_candidates(
    candidates,
    *,
    reorder,
    build_and_match,
    baseline,
    max_seconds: float = 0.0,
    emit=lambda msg: None,
    now=time.monotonic,
):
    """Execute decl-order candidates, emitting per-candidate progress and
    honoring an optional wall-clock budget.

    ``reorder(perm)`` returns patched source (or None to skip a candidate);
    ``build_and_match(patched)`` compiles it and returns a match percent (or
    None/DeclCandidateFailure on failure). Returns
    ``(results, best_pct, best_label, stopped_early)``.
    """
    from src.cli.debug import DeclCandidateFailure
    results: list = []
    best_pct = baseline
    best_label = None
    total = len(candidates)
    start = now()
    stopped_early = False
    for i, (label, perm) in enumerate(candidates, 1):
        if max_seconds and (now() - start) >= max_seconds:
            emit(
                f"    time budget {max_seconds:g}s reached after {i - 1}/{total} "
                f"candidates — stopping early (raise --max-seconds, or 0 to disable)"
            )
            stopped_early = True
            break
        patched = reorder(perm)
        if patched is None:
            continue
        build_result = build_and_match(patched)
        if isinstance(build_result, DeclCandidateFailure):
            result = {
                "label": label,
                "pct": None,
                "delta": None,
                "status": build_result.status,
            }
            if build_result.candidate_path is not None:
                result["candidate_path"] = str(build_result.candidate_path)
            if build_result.diagnostic:
                result["diagnostic"] = build_result.diagnostic
            results.append(result)
            emit(f"    ({i}/{total}) {label}: {build_result.status}")
            if build_result.candidate_path is not None:
                emit(f"        candidate: {build_result.candidate_path}")
            if build_result.diagnostic:
                emit(f"        first error: {build_result.diagnostic}")
            continue
        pct = build_result
        if pct is None:
            results.append({
                "label": label,
                "pct": None,
                "delta": None,
                "status": "build-failed",
            })
            emit(f"    ({i}/{total}) {label}: build-failed")
            continue
        delta = pct - baseline
        results.append({"label": label, "pct": pct, "delta": delta})
        emit(f"    ({i}/{total}) {label}: {pct:.2f}% ({delta:+.2f}%)")
        if pct > best_pct:
            best_pct = pct
            best_label = label
    return results, best_pct, best_label, stopped_early
@inspect_app.command(name="ceiling", hidden=True)
@inspect_app.command(name="diagnose")
def ceiling(
    function: Annotated[
        str,
        typer.Argument(help="Function name to check"),
    ],
    skip_decl_orders: Annotated[
        bool,
        typer.Option(
            "--skip-decl-orders",
            help="Skip the mutate decl-orders step (saves ~1 min "
                 "but produces a less confident verdict).",
        ),
    ] = False,
    decl_strategy: Annotated[
        str,
        typer.Option(
            "--decl-strategy",
            help="Strategy passed to mutate decl-orders. 'promote' is "
                 "fast (N candidates); 'all' covers promote+demote+swap "
                 "(~3N candidates).",
        ),
    ] = "promote",
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help=(
                "Optional force-phys proof vector to explain as a coupled "
                "source-shape problem. Accepts IG:PHYS or CLASS:IG:PHYS CSV."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit verdict as JSON."),
    ] = False,
    max_seconds: Annotated[
        float,
        typer.Option(
            "--max-seconds",
            help="Wall-clock budget for the decl-order enumeration phase "
                 "(0 = unlimited). Stops early with a clear message instead "
                 "of appearing hung.",
        ),
    ] = 0.0,
) -> None:
    """Current-tooling diagnosis: is there a quick win we haven't tried?

    Combines two checks:
      1. suggest casts — static cast linter (free, milliseconds)
      2. mutate decl-orders — brute-force decl-order space (~70s)

    Verdict categories:
      - WIN AVAILABLE — a quick fix exists (casts to drop, or a decl-
        order that improves match%)
      - INTRINSIC VALUE-NUMBERING CEILING — target rematerializes a
        signed magic divide while this compile CSEs the quotient; current
        source/allocator levers are not expected to add the missing
        arithmetic instructions
      - NO FAST TRANSFORM FOUND — current fast heuristics found no
        improvement; recommends force-phys reachability testing and/or
        source-shape search as next steps

    This is the command to run when you're staring at a stuck function
    and asking what evidence-backed workflow to run next.
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT, DeclCandidateFailure, _build_and_match, _build_and_match_with_diagnostic, _detect_frame_residual_hint, _find_unit_for_function, _get_match_pct, _resolve_pcdump_path, audit_function_casts
    from src.cli.debug import _select_decl_order_scope
    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function '{function}' not found in report.json", err=True
        )
        raise typer.Exit(2)
    src = melee_root / "src" / f"{unit}.c"
    baseline = _get_match_pct(function, melee_root) or 0.0
    diagnose_pcdump_path = _resolve_pcdump_path(
        None,
        function,
        melee_root,
        require_fresh=True,
    )
    diagnose_pcdump_text = diagnose_pcdump_path.read_text()
    diagnose_expected_asm_text = _read_diagnose_expected_asm(
        function,
        unit,
        melee_root,
    )
    value_numbering_ceiling = detect_divide_rematerialization_ceiling(
        function=function,
        expected_asm_text=diagnose_expected_asm_text,
        current_pcdump_text=diagnose_pcdump_text,
    )
    frame_residual_hint = _detect_frame_residual_hint(
        function,
        unit=unit,
        melee_root=melee_root,
        pcdump_path=diagnose_pcdump_path,
    )

    if not json_out:
        print(f"== Current-tooling diagnosis for {function} ==")
        print(f"  Baseline: {baseline:.2f}%")
        print(f"  TU:       {src.relative_to(melee_root)}")
        print()

    # Step 1: suggest casts (with auto-verify for HIGH-severity findings)
    src_text = src.read_text() if src.exists() else ""
    disp_form_rollback_hint = _detect_disp_form_rollback_hint(
        src_text,
        function,
    ) if src_text else None
    pointer_offset_reassociation_hint = _detect_pointer_offset_reassociation_hint(
        src_text,
        function,
        expected_asm_text=diagnose_expected_asm_text,
        current_pcdump_text=diagnose_pcdump_text,
    ) if src_text else None
    coupled_force_phys_guidance = _diagnose_coupled_force_phys_guidance(
        function=function,
        unit=unit,
        force_phys=force_phys,
    )
    register_tiebreak_guidance = (
        _register_tiebreak_guidance(
            function=function,
            unit=unit,
            force_phys=force_phys,
        )
        if force_phys else None
    )
    cast_warnings = audit_function_casts(src_text, function)
    high_casts = [w for w in cast_warnings if w.severity == "high"]
    med_casts = [w for w in cast_warnings if w.severity == "medium"]
    cast_verify_secs = len(high_casts) * 6
    if not json_out:
        if high_casts:
            print(f"[1] Cast audit (~{cast_verify_secs}s including verify)...", flush=True)
        else:
            print(f"[1] Cast audit (free, ~ms)...", flush=True)

    # Auto-verify each HIGH cast by drop-test: patch src, compile, revert.
    # Avoids false-positive WIN AVAILABLE when the cast is heuristically
    # suspicious but removal is actually a no-op for codegen.
    cast_verify_results: list[dict] = []  # per-cast verify record
    if high_casts and src.exists():
        orig_src = src.read_text()
        try:
            with _source_restore_guard(src, orig_src):
                for w in high_casts:
                    # Build the drop pattern: remove "(cast_type) " prefix on
                    # the cast's line. We match the exact text the linter found.
                    cast_text = f"({w.cast_type}) {w.inner_expr}"
                    if cast_text not in orig_src:
                        # Fallback: maybe there's no space after the cast type.
                        cast_text = f"({w.cast_type}){w.inner_expr}"
                    if cast_text not in orig_src:
                        cast_verify_results.append({
                            "line": w.line,
                            "cast_type": w.cast_type,
                            "inner_expr": w.inner_expr,
                            "call_target": w.call_target,
                            "pct_before": baseline,
                            "pct_after": None,
                            "delta": None,
                            "note": "could not locate cast text in source",
                        })
                        continue
                    patched = orig_src.replace(cast_text, w.inner_expr, 1)
                    src.write_text(patched)
                    pct_after = _build_and_match(unit, function, melee_root)
                    src.write_text(orig_src)  # revert immediately
                    delta = (
                        (pct_after - baseline)
                        if pct_after is not None else None
                    )
                    cast_verify_results.append({
                        "line": w.line,
                        "cast_type": w.cast_type,
                        "inner_expr": w.inner_expr,
                        "call_target": w.call_target,
                        "pct_before": baseline,
                        "pct_after": pct_after,
                        "delta": delta,
                        "note": (
                            "WIN" if (delta is not None and delta > 0.0)
                            else "no change" if (delta is not None and delta == 0.0)
                            else "regression" if (delta is not None and delta < 0.0)
                            else "build failed"
                        ),
                    })
        finally:
            subprocess.run(
                ["ninja", f"build/GALE01/src/{unit}.o",
                 "build/GALE01/report.json"],
                cwd=melee_root, capture_output=True,
            )

    if not json_out:
        if high_casts:
            print(f"    ! {len(high_casts)} HIGH-severity cast(s) found — "
                  f"auto-verified:")
            for w, vr in zip(high_casts[:3], cast_verify_results[:3]):
                delta_str = ""
                if vr["delta"] is not None:
                    if vr["delta"] > 0.0:
                        delta_str = (f"  → drop test: {vr['pct_before']:.2f}% → "
                                     f"{vr['pct_after']:.2f}% "
                                     f"(+{vr['delta']:.2f}%, WIN)")
                    else:
                        delta_str = (f"  → drop test: {vr['pct_before']:.2f}% → "
                                     f"{vr['pct_after']:.2f}% "
                                     f"({vr['delta']:+.2f}%, false positive)")
                elif vr.get("note") == "could not locate cast text in source":
                    delta_str = "  → (could not locate cast in source; skipped)"
                else:
                    delta_str = "  → (build failed during verify)"
                print(f"      - line {w.line}: ({w.cast_type}) "
                      f"{w.inner_expr} → {w.call_target}")
                if delta_str:
                    print(f"      {delta_str}")
            if len(high_casts) > 3:
                print(f"      ... +{len(high_casts) - 3} more")
        else:
            print(f"    No HIGH-severity casts.")
        print()

    # Step 2: mutate decl-orders (optional)
    decl_results: list = []
    decl_best_pct: float = baseline
    decl_best_label: Optional[str] = None
    if not skip_decl_orders:
        if not json_out:
            budget_note = f", budget {max_seconds:g}s" if max_seconds else ""
            print(f"[2] Decl-order enumeration ({decl_strategy} strategy, "
                  f"~minute{budget_note})...", flush=True)
        scope_map = get_decl_names_by_scope(src_text, function) if src_text else {}
        selected_scope, selected_scope_reason = _select_decl_order_scope(
            scope_map,
            function,
        )
        names = scope_map.get(selected_scope)
        if not names:
            if not json_out:
                available = ", ".join(
                    f"{'/'.join(scope_path)} ({len(scope_names)} decls)"
                    for scope_path, scope_names in scope_map.items()
                ) or "none"
                print(
                    "    Could not find reorderable decl scope — skipping. "
                    f"Available scopes: {available}."
                )
        else:
            if not json_out:
                print(
                    f"    Scope: {'/'.join(selected_scope)} "
                    f"({selected_scope_reason})"
                )
                nested = [
                    f"{'/'.join(scope_path)} ({len(scope_names)} decls)"
                    for scope_path, scope_names in scope_map.items()
                    if scope_path != selected_scope
                ]
                if nested:
                    print(f"    Other scopes: {', '.join(nested)}")
            candidates = [
                (candidate.label.replace(" <-> ", "<->"), candidate.order)
                for candidate in build_decl_order_candidates_for_scope(
                    src_text,
                    function,
                    selected_scope,
                    decl_strategy,
                )
            ]

            orig = src.read_text()
            decl_failure_dir: Optional[Path] = None

            def _write_failed_decl_candidate(patched_src: str) -> Path:
                nonlocal decl_failure_dir
                if decl_failure_dir is None:
                    safe_function = re.sub(r"[^A-Za-z0-9_.-]+", "_", function)
                    decl_failure_dir = Path(tempfile.mkdtemp(
                        prefix=f"melee-agent-diagnose-{safe_function}-",
                    ))
                digest = hashlib.sha1(patched_src.encode()).hexdigest()[:12]
                candidate_path = decl_failure_dir / f"candidate-{digest}.c"
                candidate_path.write_text(patched_src)
                return candidate_path

            def _bm(patched_src: str):
                from src.cli.debug import DeclCandidateFailure
                src.write_text(patched_src)
                try:
                    pct, diagnostic = _build_and_match_with_diagnostic(
                        unit,
                        function,
                        melee_root,
                    )
                    if pct is not None:
                        return pct
                    candidate_path = _write_failed_decl_candidate(patched_src)
                    return DeclCandidateFailure(
                        status=_classify_decl_candidate_failure(diagnostic),
                        diagnostic=diagnostic,
                        candidate_path=candidate_path,
                    )
                finally:
                    src.write_text(orig)  # revert immediately

            try:
                with _source_restore_guard(src, orig):
                    (
                        decl_results,
                        decl_best_pct,
                        decl_best_label,
                        _stopped_early,
                    ) = _run_decl_candidates(
                        candidates,
                        reorder=lambda perm: reorder_decls_in_function_scope(
                            orig,
                            function,
                            selected_scope,
                            perm,
                        ),
                        build_and_match=_bm,
                        baseline=baseline,
                        max_seconds=max_seconds,
                        emit=(
                            (lambda msg: print(msg, flush=True))
                            if not json_out else (lambda msg: None)
                        ),
                    )
            finally:
                subprocess.run(
                    ["ninja", f"build/GALE01/src/{unit}.o",
                     "build/GALE01/report.json"],
                    cwd=melee_root, capture_output=True,
                )
            if not json_out:
                if decl_best_label is not None:
                    print(f"    WIN: {decl_best_label} → "
                          f"{decl_best_pct:.2f}% (delta "
                          f"{decl_best_pct - baseline:+.2f}%)")
                else:
                    print(f"    No decl-order win found "
                          f"({len(decl_results)} candidates).")
            print() if not json_out else None
    else:
        if not json_out:
            print(f"[2] Decl-order enumeration: SKIPPED")
            print()

    # HSD_ASSERT override detection — same as in `stuck`.
    ceiling_hsd_assert_strings: list[tuple[str, str]] = []
    _ceiling_built_o = melee_root / "build" / "GALE01" / "src" / f"{unit}.o"
    if _ceiling_built_o.exists():
        try:
            from ...mwcc_debug.o_rewriter import find_anonymous_assert_strings
            ceiling_hsd_assert_strings = find_anonymous_assert_strings(
                _ceiling_built_o)
        except Exception:
            pass
    if ceiling_hsd_assert_strings and not json_out:
        syms_str = ", ".join(
            f"{s} ({v!r})" for s, v in ceiling_hsd_assert_strings)
        print(f"[!] HSD_ASSERT override needed — anonymous .sdata assert "
              f"strings: {syms_str}")
        print(_format_hsd_assert_override_guidance("    "))
        print()

    # SPILLED virtual hints — surface compiler-introduced spills before
    # the verdict. When NO FAST TRANSFORM FOUND is reported but SPILLED
    # virtuals exist, they often point at inline-function code shape
    # (sentinel returns, etc.) that's actually fixable in C. We list each
    # SPILLED virtual along with whatever source binding or first-def IR
    # op virtual-to-var can surface, and flag candidates that look like
    # they came from an inlined callee.
    #
    # Failure modes are non-fatal: no pcdump cache, no SimplifyEntry
    # data, or no source bindings just means we surface less info.
    ceiling_spilled_hints: list[dict] = []
    _pcdump_path_for_spilled: Optional[Path] = None
    try:
        _pcdump_path_for_spilled = _resolve_pcdump_path(
            None, function, melee_root,
        )
    except (typer.Exit, Exception):
        _pcdump_path_for_spilled = None  # cache missing — skip hint pass

    if _pcdump_path_for_spilled is not None:
        try:
            _pcdump_text = (
                diagnose_pcdump_text
                if _pcdump_path_for_spilled == diagnose_pcdump_path
                else _pcdump_path_for_spilled.read_text()
            )
            _src_text = src.read_text() if src.exists() else ""
            _source_file = (
                str(src.relative_to(melee_root))
                if src.exists() else None
            )
            ceiling_spilled_hints = _diagnose_spilled_virtual_hints(
                _pcdump_text,
                function,
                _src_text,
                source_file=_source_file,
            )
        except Exception:
            # Any parse/lookup failure: drop hints; verdict still emits.
            ceiling_spilled_hints = []

    if ceiling_spilled_hints and not json_out:
        print(
            f"[!] SPILLED virtuals (compiler couldn't keep in registers):"
        )
        for _h in ceiling_spilled_hints[:8]:
            _v = _h["virtual"]
            if _h.get("kind") == "call-return":
                _expr = _h.get("expression") or _h.get("call_symbol") or "call return"
                _name = f" -> {_h['var_name']}" if "var_name" in _h else ""
                print(
                    f"    r{_v}: {_expr}{_name} "
                    f"(call-return/copy-chain)"
                    f"{_format_diagnose_hint_location(_h)}"
                )
                if _h.get("copy_chain"):
                    _chain = " <- ".join(
                        f"r{_reg}" for _reg in _h["copy_chain"]
                    )
                    print(f"        chain: {_chain}")
                for _site in _h.get("use_sites", [])[:2]:
                    print(
                        f"        use: B{_site['block_idx']}: "
                        f"`{_site['opcode']} {_site['operands']}`"
                    )
            elif "var_name" in _h:
                print(
                    f"    r{_v}: {_h['var_name']} "
                    f"({_h.get('kind', '?')}/{_h.get('confidence', '?')})"
                )
            elif _h.get("expression") and _h.get("kind") != "first-def":
                print(
                    f"    r{_v}: {_h['expression']} "
                    f"({_h.get('kind', '?')}/{_h.get('confidence', '?')})"
                    f"{_format_diagnose_hint_location(_h)}"
                )
            elif "first_def" in _h:
                _fd = _h["first_def"]
                print(
                    f"    r{_v}: compiler temp — first def in "
                    f"B{_fd['block_idx']}: `{_fd['opcode']} {_fd['operands']}`"
                )
                if "inline_hint" in _h:
                    print(f"        hint: {_h['inline_hint']}")
            else:
                print(f"    r{_v}: (no source binding or first-def found)")
        if len(ceiling_spilled_hints) > 8:
            print(f"    ... +{len(ceiling_spilled_hints) - 8} more")
        if any(_h.get("kind") == "call-return" for _h in ceiling_spilled_hints):
            print(
                "    Call-return copy chains usually need compare-order or "
                "lifetime-shape probes before unrelated local rewrites."
            )
        print(
            f"    Re-run `debug inspect virtual-to-var -f {function} <virt>` for "
            f"each row to get full context."
        )
        print()

    if coupled_force_phys_guidance and not json_out:
        _print_coupled_force_phys_guidance(coupled_force_phys_guidance)
    if register_tiebreak_guidance and not json_out:
        _print_register_tiebreak_guidance(register_tiebreak_guidance)
        print()

    if frame_residual_hint and not json_out:
        print("[!] Frame/local-area residual:")
        print(f"    {frame_residual_hint['message']}")
        print()

    if value_numbering_ceiling and not json_out:
        _print_value_numbering_ceiling(value_numbering_ceiling)

    if disp_form_rollback_hint and not json_out:
        _print_disp_form_rollback_hint(disp_form_rollback_hint)

    if pointer_offset_reassociation_hint and not json_out:
        _print_pointer_offset_reassociation_hint(pointer_offset_reassociation_hint)

    # Verdict — use verified cast results (not raw heuristic count) so we
    # don't produce false-positive WIN AVAILABLE on no-op casts.
    #
    # A cast counts as a win only if its verified delta is strictly positive.
    # If cast_verify_results is empty (no high casts, or source not found),
    # has_cast_win is False.
    verified_cast_wins = [
        vr for vr in cast_verify_results
        if vr.get("delta") is not None and vr["delta"] > 0.0
    ]
    has_cast_win = bool(verified_cast_wins)
    decl_delta = decl_best_pct - baseline if decl_best_label else 0.0
    has_decl_win = decl_delta >= 0.05

    if has_cast_win or has_decl_win:
        verdict = "WIN AVAILABLE"
        recommendations: list[str] = []
        if has_cast_win:
            win_lines = ", ".join(
                f"line {vr['line']}" for vr in verified_cast_wins[:3]
            )
            if len(verified_cast_wins) > 3:
                win_lines += f" +{len(verified_cast_wins) - 3} more"
            recommendations.append(
                f"Drop {len(verified_cast_wins)} HIGH-severity cast(s) with "
                f"verified improvement ({win_lines}). "
                f"Run `melee-agent debug suggest casts {function}` for details."
            )
        if has_decl_win:
            recommendations.append(
                f"Apply decl-order win: `melee-agent debug "
                f"mutate decl-orders {function} --strategy "
                f"{decl_strategy} --keep-best` → expected "
                f"{decl_best_pct:.2f}%."
            )
    elif frame_residual_hint:
        verdict = "FRAME/LOCAL-AREA RESIDUAL"
        recommendations = [
            frame_residual_hint["message"],
            *frame_residual_hint["next_steps"],
        ]
    elif value_numbering_ceiling:
        verdict = "INTRINSIC VALUE-NUMBERING CEILING"
        recommendations = [
            _value_numbering_ceiling_recommendation(value_numbering_ceiling)
        ]
    else:
        verdict = "NO FAST TRANSFORM FOUND"
        recommendations = _ceiling_recommendations(function, unit)
    pointer_offset_reassociation_recommendations = (
        pointer_offset_reassociation_hint.get("recommendations", [])
        if pointer_offset_reassociation_hint
        and verdict == "NO FAST TRANSFORM FOUND"
        else []
    )
    recommendations = (
        _diagnose_call_return_recommendations(function, ceiling_spilled_hints)
        + (
            disp_form_rollback_hint.get("recommendations", [])
            if disp_form_rollback_hint else []
        )
        + pointer_offset_reassociation_recommendations
        + recommendations
    )

    if json_out:
        print(json.dumps({
            "function": function,
            "baseline_pct": baseline,
            "verdict": verdict,
            "high_cast_warnings": [{
                "line": w.line, "call_target": w.call_target,
                "cast_type": w.cast_type, "inner_expr": w.inner_expr,
            } for w in high_casts],
            "med_cast_warnings": [{
                "line": w.line, "call_target": w.call_target,
                "cast_type": w.cast_type, "inner_expr": w.inner_expr,
            } for w in med_casts],
            "cast_verify_results": cast_verify_results,
            "decl_best_label": decl_best_label,
            "decl_best_pct": decl_best_pct,
            "decl_results": decl_results,
            "hsd_assert_strings": [
                {"sym": s, "string": v}
                for s, v in ceiling_hsd_assert_strings
            ],
            "spilled_virtual_hints": ceiling_spilled_hints,
            "coupled_force_phys": coupled_force_phys_guidance,
            "register_tiebreak": register_tiebreak_guidance,
            "frame_residual": frame_residual_hint,
            "value_numbering_ceiling": value_numbering_ceiling,
            "disp_form_rollback": disp_form_rollback_hint,
            "pointer_offset_reassociation": pointer_offset_reassociation_hint,
            "recommendations": recommendations,
        }, indent=2))
        return

    print(f"== VERDICT: {verdict} ==")
    for rec in recommendations:
        print(f"  {rec}")
@inspect_app.command(name="rank-callees")
def rank_callees(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze (required)",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Predict the callee-save cascade for a function before compiling.

    Lists callee-save virtuals (those that got r13-r31) sorted by
    ig_idx descending — the order MWCC's simplifygraph processes them.
    Higher ig_idx = colored first = gets r31, r30, r29, ... via
    top-down nonvolatile dispense.

    Useful for predicting the param-iter-ceiling: if your target wants
    a parameter virtual (low ig_idx) at r31 but several locals have
    higher ig_idx, the cascade will give those locals r31 first and
    the parameter will land lower. No source-level fix.
    """
    from src.cli.debug import _abort_function_not_in_dump, _resolve_pcdump_path, find_function, parse_hook_events, parse_pcdump
    pcdump = _resolve_pcdump_path(pcdump, function)
    text = pcdump.read_text()
    events_list = parse_hook_events(text)
    fn_events = find_function(events_list, function)
    if fn_events is None or not fn_events.colorgraph_sections:
        # Fall back to analyze-derived data if no hook events
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is None:
            _abort_function_not_in_dump(function, [f.name for f in fns])
        infos = analyze_function(fn)
        # No ig_idx info from this path; only sort by virtual num
        callee_saves = [v for v in infos
                        if v.physical is not None and 13 <= v.physical <= 31]
        callee_saves.sort(key=lambda v: -v.virtual)
        if json_out:
            print(json.dumps({
                "function": function,
                "source": "analyze (no hook events)",
                "callees": [{
                    "virtual": v.virtual,
                    "ig_idx": None,
                    "physical": v.physical,
                } for v in callee_saves],
            }, indent=2))
            return
        print(f"Function: {function}")
        print(f"Source:   analyze (no COLORGRAPH DECISIONS in dump)")
        print()
        if not callee_saves:
            print("No callee-save virtuals (r13-r31) found.")
            return
        print(f"{'virtual':>8}  {'phys':>4}  {'note':<30}")
        for v in callee_saves:
            note = "param-like (low virtual #)" if v.virtual <= 34 else ""
            print(f"  r{v.virtual:<6}  r{v.physical:<3}  {note}")
        return

    # Build the cascade from COLORGRAPH DECISIONS sections.
    # Decisions are emitted in iter order (which is descending ig_idx order
    # for the virtual-reg nodes).
    rows: list[dict] = []
    for sec in fn_events.colorgraph_sections:
        for d in sec.decisions:
            if d.ig_idx < 0:
                continue  # physical-reg sentinel nodes — skip
            if not (13 <= d.assigned_reg <= 31):
                continue  # not a callee-save
            rows.append({
                "iter": d.iter_idx,
                "ig_idx": d.ig_idx,
                "assigned_reg": d.assigned_reg,
                "degree": d.degree,
                "class_id": sec.class_id,
            })

    # Sort by ig_idx descending (= iter order = coloring order)
    rows.sort(key=lambda r: -r["ig_idx"])

    # Top-down dispense prediction: the i-th popped virtual gets r(31-i)
    # if workingMask is empty. (workingMask non-empty would pick a caller-
    # save first; the cascade prediction is only meaningful for callee-save-
    # bound virtuals — which is what we filtered to above.)
    expected_seq = list(range(31, 12, -1))  # r31, r30, ..., r13

    enriched = []
    for i, r in enumerate(rows):
        expected = expected_seq[i] if i < len(expected_seq) else None
        is_param_like = r["ig_idx"] <= 34
        match = (expected is not None and r["assigned_reg"] == expected)
        enriched.append({
            **r,
            "expected": expected,
            "expected_match": match,
            "is_param_like": is_param_like,
        })

    if json_out:
        print(json.dumps({
            "function": function,
            "source": "COLORGRAPH DECISIONS",
            "callees": enriched,
        }, indent=2))
        return

    print(f"Function: {function}")
    print(f"Source:   COLORGRAPH DECISIONS")
    print()
    print(
        f"  Predicting the callee-save cascade. Higher ig_idx → colored "
        f"first → gets top of dispense pool."
    )
    print()
    print(
        f"  {'ig_idx':>7}  {'phys':>4}  {'predict':>7}  {'deg':>3}  notes"
    )
    print(f"  {'-'*7}  {'-'*4}  {'-'*7}  {'-'*3}  -----")
    for r in enriched:
        notes = []
        if r["is_param_like"]:
            notes.append("param-like (low ig_idx)")
        if r["expected"] is not None and not r["expected_match"]:
            notes.append(f"got r{r['assigned_reg']} not r{r['expected']}")
        notes_str = "; ".join(notes)
        expected_str = (f"r{r['expected']}" if r["expected"] is not None
                        else "-")
        print(
            f"  {r['ig_idx']:>7}  r{r['assigned_reg']:<3}  {expected_str:>7}  "
            f"{r['degree']:>3}  {notes_str}"
        )

    # Footer: surface param-iter-ceiling if any
    params = [r for r in enriched if r["is_param_like"]]
    if any(p["assigned_reg"] != p.get("expected", -1) for p in params):
        print()
        print(
            "Note: at least one param-like virtual (low ig_idx) landed "
            "below its predicted top-down position. This is the typical "
            "param-iter-ceiling signature — see `debug util patterns "
            "param-iter-ceiling` for the full pattern."
        )
def _restore_object_report_for_unit(
    *,
    unit: str,
    melee_root: Path,
    timeout_s: float,
    max_steps: int,
    force: bool = False,
) -> tuple[subprocess.CompletedProcess[str], int]:
    from src.cli.debug import (  # noqa: PLC0415
        _make_expensive_restore_result,
        _ninja_dry_run_planned_steps,
        _restore_object_report_cmd_for_unit,
        _run_auto_verify_command_with_status,
    )
    restore_cmd = _restore_object_report_cmd_for_unit(unit)
    dry_run_cmd = ["ninja", "-n", *restore_cmd[1:]]
    try:
        dry_run = subprocess.run(
            dry_run_cmd,
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = (
            (exc.stderr or "") + "\n"
            f"[restore] ninja dry-run timed out after 30s; refusing to "
            f"launch restore without a plan."
        )
        return subprocess.CompletedProcess(dry_run_cmd, 124, exc.stdout or "", stderr), 0
    dry_output = "\n".join(
        text for text in (dry_run.stdout, dry_run.stderr) if text
    )
    planned_steps = _ninja_dry_run_planned_steps(dry_output)
    print(
        f"[auto-verify] restore dry-run: {planned_steps} ninja step(s)",
        file=sys.stderr,
    )
    if dry_run.returncode != 0:
        return dry_run, planned_steps
    if planned_steps == 0:
        return subprocess.CompletedProcess(
            restore_cmd,
            0,
            dry_run.stdout,
            dry_run.stderr,
        ), planned_steps
    if planned_steps > max_steps and not force:
        return _make_expensive_restore_result(
            restore_cmd,
            planned_steps=planned_steps,
            max_steps=max_steps,
            dry_run_output=dry_output,
        ), planned_steps
    if planned_steps > max_steps:
        print(
            f"[auto-verify] restore dry-run plans {planned_steps} steps; "
            f"running anyway because --force was requested",
            file=sys.stderr,
        )
    proc = _run_auto_verify_command_with_status(
        restore_cmd,
        cwd=melee_root,
        phase="restoring object/report",
        status_label=" ".join(restore_cmd),
        timeout_s=timeout_s,
    )
    return proc, planned_steps
@inspect_app.command(name="var-to-virtual")
def var_to_virtual(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to look up (required).",
        ),
    ],
    var_name: Annotated[
        str,
        typer.Argument(help="Source-level variable name."),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
    basis: Annotated[
        bool,
        typer.Option(
            "--basis",
            help="Also dump the heuristic's evidence: parsed params/locals, "
                 "the cursor calculation step-by-step, observed virtuals in "
                 "the pre-pass, and any red flags that lowered confidence. "
                 "Use when you suspect var-to-virtual gave you a wrong "
                 "mapping — the basis tells you whether the cursor "
                 "shifted, a macro hid a decl, or the function has nested "
                 "blocks the parser skipped.",
        ),
    ] = False,
    all_matches: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Return ALL bindings matching the name. Default picks "
                 "the highest-confidence top-level binding for back-compat.",
        ),
    ] = False,
    scope_filter: Annotated[
        Optional[str],
        typer.Option(
            "--scope",
            help="Filter bindings by scope path. Exact match by default; "
                 "trailing '/' for prefix (e.g. 'fn_X/' matches the "
                 "function and all nested blocks inside it).",
        ),
    ] = None,
) -> None:
    """Bridge: given a source variable name, predict its MWCC virtual.

    Reports `confidence`: best-guess (heuristic matched, no concerns),
    low-confidence (matched but red flags present — cursor may be
    wrong), ambiguous (no observed virtual for this variable), or
    unsupported (e.g., variable lives in a macro the tokenizer can't
    see). Pass `--basis` to see the underlying evidence.
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT, _abort_function_not_in_dump, _find_unit_for_function, _resolve_pcdump_path, parse_pcdump
    from ...mwcc_debug.symbol_bridge import (
        find_virtual_for_var,
        find_all_virtuals_for_var,
        list_bindings_with_basis,
    )
    from ...mwcc_debug.scope_path import format_for_display, is_nested_within

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    text = pcdump_path.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre = fn.last_precolor_pass()
    if pre is None:
        typer.echo(
            f"no pre-coloring pass for {function}", err=True,
        )
        raise typer.Exit(3)

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    source = (melee_root / "src" / f"{unit}.c").read_text()
    bindings, basis_data = list_bindings_with_basis(source, function, pre)
    # Phase 1 nested-block awareness: scope-aware lookup with optional
    # --all and --scope filters. Default behavior (single binding,
    # highest confidence) preserves back-compat.
    matches = find_all_virtuals_for_var(bindings, var_name)

    if scope_filter is not None:
        scope_value = scope_filter.rstrip("/")
        prefix_mode = scope_filter.endswith("/")
        target = tuple(scope_value.split("/")) if scope_value else ()
        if prefix_mode:
            matches = [b for b in matches if is_nested_within(b.scope_path, target)]
        else:
            matches = [b for b in matches if b.scope_path == target]

    binding = matches[0] if matches else None

    if all_matches:
        # New --all output path — emit the full match list, then return.
        if not matches:
            if json_out:
                print(json.dumps(
                    {"var_name": var_name, "found": False, "bindings": []},
                    indent=2,
                ))
            else:
                typer.echo(
                    f"variable {var_name!r} not found in {function}",
                    err=True,
                )
            raise typer.Exit(1)
        if json_out:
            payload = {
                "var_name": var_name,
                "found": True,
                "bindings": [
                    {
                        "virtual": b.virtual,
                        "decl_line": b.decl_line,
                        "kind": b.kind,
                        "type": b.type_str,
                        "confidence": b.confidence,
                        "scope_path": list(b.scope_path),
                    } for b in matches
                ],
            }
            if basis and basis_data is not None:
                payload["basis"] = _basis_to_dict(basis_data)
            print(json.dumps(payload, indent=2))
        else:
            print(f"{var_name} ({len(matches)} matches):")
            for b in matches:
                scope_str = format_for_display(b.scope_path) or "(top)"
                print(
                    f"  -> r{b.virtual}  ({b.confidence}, "
                    f"type={b.type_str}, scope={scope_str}, "
                    f"line {b.decl_line})"
                )
        return

    if binding is None:
        if json_out:
            payload: dict = {"var_name": var_name, "found": False}
            if basis and basis_data is not None:
                payload["basis"] = _basis_to_dict(basis_data)
            print(json.dumps(payload, indent=2))
        else:
            typer.echo(
                f"variable {var_name!r} not found in {function}",
                err=True,
            )
            if basis and basis_data is not None:
                _print_basis(basis_data, bindings)
        raise typer.Exit(1)

    if json_out:
        payload = {
            "var_name": binding.var_name,
            "virtual": binding.virtual,
            "kind": binding.kind,
            "type": binding.type_str,
            "confidence": binding.confidence,
            "found": True,
        }
        if basis and basis_data is not None:
            payload["basis"] = _basis_to_dict(basis_data)
        print(json.dumps(payload, indent=2))
    else:
        scope_str = format_for_display(binding.scope_path) or "(top)"
        print(
            f"{binding.var_name} -> r{binding.virtual}  "
            f"({binding.confidence}, type={binding.type_str}, "
            f"scope={scope_str}, line {binding.decl_line})"
        )
        if basis and basis_data is not None:
            print()
            _print_basis(basis_data, bindings)
def _basis_to_dict(basis) -> dict:
    """Render a BindingBasis as a JSON-compatible dict."""
    return {
        "parsed_params": [
            {"name": p.name, "type": p.type_str, "decl_index": p.decl_index}
            for p in basis.parsed_params
        ],
        "parsed_locals": [
            {"name": ld.name, "type": ld.type_str, "decl_index": ld.decl_index}
            for ld in basis.parsed_locals
        ],
        "observed_virtuals": basis.observed_virtuals,
        "unrecognized_decls": basis.unrecognized_decls,
        "red_flags": basis.red_flags,
    }
def _print_basis(basis, bindings) -> None:
    """Human-readable dump of a BindingBasis + how the cursor mapped."""
    print("=== basis ===")
    if basis.red_flags:
        print(f"red flags: {', '.join(basis.red_flags)}")
        print("  (these demote 'best-guess' → 'low-confidence' for locals)")
    else:
        print("red flags: (none)")
    print()
    print(f"parsed params ({len(basis.parsed_params)}):")
    if not basis.parsed_params:
        print("  (none)")
    for p in basis.parsed_params:
        print(f"  [{p.decl_index}] {p.type_str:<22s} {p.name}")
    print()
    print(f"parsed locals ({len(basis.parsed_locals)}):")
    if not basis.parsed_locals:
        print("  (none)")
    for ld in basis.parsed_locals:
        print(f"  [{ld.decl_index}] {ld.type_str:<22s} {ld.name}")
    if basis.unrecognized_decls:
        print()
        print("unrecognized decl-shaped statements (parser couldn't handle):")
        for s in basis.unrecognized_decls:
            print(f"  • {s}")
    print()
    obs = basis.observed_virtuals
    obs_str = (
        ", ".join(f"r{v}" for v in obs[:16])
        + (f", ... (+{len(obs) - 16} more)" if len(obs) > 16 else "")
    ) if obs else "(none)"
    print(f"observed virtuals in pre-pass ({len(obs)}): {obs_str}")
    print()
    print("predicted bindings (cursor = 32 + position):")
    for b in bindings:
        marker = "✓" if b.virtual in obs else "·" if b.kind == "param" else "✗"
        print(f"  {marker} {b.var_name:<22s} r{b.virtual:<5d} "
              f"[{b.kind}/{b.confidence}]")
def _parse_virtual_reg_token(token: str) -> int:
    vstr = token.strip()
    if vstr.lower().startswith(("r", "f")):
        vstr = vstr[1:]
    try:
        return int(vstr)
    except ValueError:
        raise typer.BadParameter(
            f"invalid virtual register {token!r}; expected an integer "
            "or a register token like r108/f108"
        )
@inspect_app.command(name="virtual-to-ig")
def virtual_to_ig(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to look up.",
        ),
    ],
    virtual: Annotated[
        str,
        typer.Option(
            "--virtual",
            help="Visible pcode virtual register, e.g. r108 or 108.",
        ),
    ],
    reg_class: Annotated[
        Optional[str],
        typer.Option(
            "--class",
            help="Register class to select when an ig_idx is ambiguous "
                 "(gpr/int or fp/fpr). Inferred from r*/f* tokens when omitted.",
        ),
    ] = None,
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Map a visible pcode virtual register to allocator graph identity."""
    from src.cli.debug import DEFAULT_MELEE_ROOT, _effective_reg_class, _resolve_pcdump_path
    from ...mwcc_debug.copy_trace import find_virtual_to_ig

    virtual_int = _parse_virtual_reg_token(virtual)
    effective_class = _effective_reg_class(reg_class, virtual)
    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    result = find_virtual_to_ig(
        pcdump_path.read_text(),
        function,
        virtual_int,
        reg_class=effective_class,
    )

    if json_out:
        print(json.dumps(result.to_dict(), indent=2))
        return

    print(f"Function: {function}")
    print(f"Virtual:  r{virtual_int}")
    print(f"Status:   {result.status}")
    if result.note:
        print(f"Note:     {result.note}")
    if result.class_id is not None:
        print(f"Class:    {result.class_id}")
    if result.candidate_class_ids:
        classes = ", ".join(str(class_id) for class_id in result.candidate_class_ids)
        print(f"Classes:  {classes}")
    if result.ig_idx is not None:
        print(f"ig_idx:   {result.ig_idx}")
    if result.simplify_iter is not None:
        print(f"Simplify: iter {result.simplify_iter}")
    if result.color_iter is not None:
        assigned = (
            "?" if result.assigned_reg is None else f"r{result.assigned_reg}"
        )
        print(f"Color:    iter {result.color_iter}, assigned {assigned}")
    if result.live_range is not None:
        print(
            f"Live:     {result.live_range[0]}..{result.live_range[1]} "
            f"({result.use_count} use(s))"
        )
    if result.first_occurrence is not None:
        occ = result.first_occurrence
        print(
            "First:    "
            f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
            f"{occ.opcode} {occ.operands}"
        )
    if result.last_occurrence is not None:
        occ = result.last_occurrence
        print(
            "Last:     "
            f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
            f"{occ.opcode} {occ.operands}"
        )
def _retained_source_sibling_for_pcdump(pcdump_path: Path) -> Path | None:
    name = pcdump_path.name
    for suffix in (".pcdump.txt", ".pcdump"):
        if name.endswith(suffix):
            candidate = pcdump_path.with_name(f"{name[:-len(suffix)]}.c")
            if candidate.is_file():
                return candidate
    return None
@inspect_app.command(name="trace-copy")
def trace_copy(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function containing the pcode copy.",
        ),
    ],
    from_reg: Annotated[
        Optional[str],
        typer.Option(
            "--from",
            help="Source virtual register for the copy, e.g. r50.",
        ),
    ] = None,
    to_reg: Annotated[
        Optional[str],
        typer.Option(
            "--to",
            help="Destination virtual register for the copy, e.g. r108.",
        ),
    ] = None,
    list_copies: Annotated[
        bool,
        typer.Option(
            "--list-copies",
            help="Discover and trace all virtual-register copies in the function.",
        ),
    ] = False,
    involving: Annotated[
        Optional[str],
        typer.Option(
            "--involving",
            help="Discovery filter: only copies with this source or destination virtual.",
        ),
    ] = None,
    near_block: Annotated[
        Optional[int],
        typer.Option(
            "--near-block",
            help="Discovery filter: only copies observed in this basic block.",
        ),
    ] = None,
    reg_class: Annotated[
        Optional[str],
        typer.Option(
            "--class",
            help="Register class for virtual-to-IG lookup (gpr/int or fp/fpr).",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "C source file used to map call-return copy chains back to "
                "source expressions. Defaults to the repo source for the "
                "function when available."
            ),
        ),
    ] = None,
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Trace where a pcode copy appears and why it disappears."""
    from src.cli.debug import DEFAULT_MELEE_ROOT, _effective_reg_class, _find_unit_for_function, _resolve_pcdump_path
    from ...mwcc_debug.copy_trace import list_copy_lifetimes, trace_copy_lifetime

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    pcdump_text = pcdump_path.read_text()
    effective_class = _effective_reg_class(
        reg_class,
        from_reg,
        to_reg,
        involving,
        default="gpr",
    )
    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        retained_source = _retained_source_sibling_for_pcdump(pcdump_path)
        if retained_source is not None:
            source_text = retained_source.read_text(
                encoding="utf-8",
                errors="replace",
            )
            source_label = str(retained_source)
        else:
            unit = _find_unit_for_function(function, melee_root)
            if unit is not None:
                candidate = melee_root / "src" / f"{unit}.c"
                if candidate.is_file():
                    source_text = candidate.read_text()
                    try:
                        source_label = str(candidate.relative_to(melee_root))
                    except ValueError:
                        source_label = str(candidate)

    if list_copies or involving is not None or near_block is not None:
        involving_virtual = (
            None if involving is None else _parse_virtual_reg_token(involving)
        )
        reports = list_copy_lifetimes(
            pcdump_text,
            function,
            involving=involving_virtual,
            near_block=near_block,
            reg_class=effective_class,
            source_text=source_text,
            source_file=source_label,
        )
        if json_out:
            print(json.dumps([report.to_dict() for report in reports], indent=2))
            return
        print(f"Function: {function}")
        print(f"Copies:   {len(reports)}")
        for report in reports:
            to_token = report.to_token or f"r{report.to_virtual}"
            from_token = report.from_token or f"r{report.from_virtual}"
            print(f"- {to_token} <- {from_token}")
            print(f"  status: {report.status}")
            print(f"  likely: {report.likely_cause}")
            if report.transform_category:
                print(f"  transform: {report.transform_category}")
            if report.first_copy is not None:
                occ = report.first_copy
                print(
                    "  first: "
                    f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
                    f"{occ.opcode} {occ.operands}"
                )
            if report.last_copy is not None:
                occ = report.last_copy
                print(
                    "  last:  "
                    f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
                    f"{occ.opcode} {occ.operands}"
                )
            if report.first_absent_pass is not None:
                print(f"  first absent: {report.first_absent_pass}")
            origin = report.to_mapping.call_return_origin
            if origin is not None:
                expr = origin.expression or f"{origin.call_symbol}(...)"
                loc = (
                    ""
                    if origin.source_file is None or origin.source_line is None
                    else f" {origin.source_file}:{origin.source_line}"
                )
                print(f"  source:{loc} {expr}")
        return

    if from_reg is None or to_reg is None:
        typer.echo(
            "--from and --to are required unless using --list-copies, "
            "--involving, or --near-block.",
            err=True,
        )
        raise typer.Exit(2)

    from_virtual = _parse_virtual_reg_token(from_reg)
    to_virtual = _parse_virtual_reg_token(to_reg)
    report = trace_copy_lifetime(
        pcdump_text,
        function,
        from_virtual=from_virtual,
        to_virtual=to_virtual,
        reg_class=effective_class,
        source_text=source_text,
        source_file=source_label,
    )

    if json_out:
        print(json.dumps(report.to_dict(), indent=2))
        return

    to_token = report.to_token or f"r{to_virtual}"
    from_token = report.from_token or f"r{from_virtual}"
    reg_prefix = "f" if report.register_class == "fpr" else "r"
    print(f"Function: {function}")
    print(f"Copy:     {to_token} <- {from_token}")
    print(f"Status:   {report.status}")
    print(f"Likely:   {report.likely_cause}")
    if report.transform_category:
        print(f"Transform: {report.transform_category}")
    if report.note:
        print(f"Note:     {report.note}")
    if report.first_copy is not None:
        occ = report.first_copy
        print(
            "First:    "
            f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
            f"{occ.opcode} {occ.operands}"
        )
    if report.last_copy is not None:
        occ = report.last_copy
        print(
            "Last:     "
            f"{occ.pass_name} B{occ.block_idx}:{occ.instr_idx} "
            f"{occ.opcode} {occ.operands}"
        )
    if report.first_absent_pass is not None:
        print(f"Absent:   first absent in {report.first_absent_pass}")
    print()
    print("Source virtual:")
    print(f"  status: {report.from_mapping.status}")
    if report.from_mapping.ig_idx is not None:
        print(f"  ig_idx: {report.from_mapping.ig_idx}")
    if report.from_mapping.assigned_reg is not None:
        print(f"  phys:   {reg_prefix}{report.from_mapping.assigned_reg}")
    if report.from_mapping.call_return_origin is not None:
        origin = report.from_mapping.call_return_origin
        expr = origin.expression or f"{origin.call_symbol}(...)"
        print(f"  source: {expr}")
    print("Destination virtual:")
    print(f"  status: {report.to_mapping.status}")
    if report.to_mapping.ig_idx is not None:
        print(f"  ig_idx: {report.to_mapping.ig_idx}")
    if report.to_mapping.assigned_reg is not None:
        print(f"  phys:   {reg_prefix}{report.to_mapping.assigned_reg}")
    if report.to_mapping.call_return_origin is not None:
        origin = report.to_mapping.call_return_origin
        expr = origin.expression or f"{origin.call_symbol}(...)"
        print(f"  source: {expr}")
def _parse_virtual_csv(value: str) -> list[int]:
    out: list[int] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        out.append(_parse_virtual_reg_token(token))
    return out
def _register_class_name_from_id(class_id: int | None) -> str | None:
    if class_id == 0:
        return "gpr"
    if class_id == 1:
        return "fpr"
    return None
_TRACE_COPY_REGISTER_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])([rf])(\d+)\b",
    re.IGNORECASE,
)
def _trace_register_class_name(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise typer.BadParameter("trace-copy JSON register_class must be a string")
    key = str(value).strip().lower()
    if key in {"0", "gpr", "int", "r"}:
        return "gpr"
    if key in {"1", "fpr", "fp", "f", "float"}:
        return "fpr"
    raise typer.BadParameter(
        "trace-copy JSON register_class must be gpr/r/0 or fpr/f/1"
    )
def _trace_copy_json_int(
    value: Any,
    *,
    label: str,
    required: bool = True,
) -> int | None:
    if value is None:
        if required:
            raise typer.BadParameter(f"trace-copy JSON missing {label}")
        return None
    if isinstance(value, bool):
        raise typer.BadParameter(f"trace-copy JSON {label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            pass
    raise typer.BadParameter(f"trace-copy JSON {label} must be an integer")
def _trace_mapping_int(
    mapping: object,
    key: str,
) -> int | None:
    if not isinstance(mapping, Mapping):
        return None
    return _trace_copy_json_int(
        mapping.get(key),
        label=f"{key}",
        required=False,
    )
def _trace_copy_json_occurrence(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return dict(value)
def _trace_occurrence_register_class_for_virtuals(
    value: object,
    virtuals: Iterable[int | None],
) -> str | None:
    if not isinstance(value, Mapping):
        return None
    operands = value.get("operands")
    if not isinstance(operands, str):
        return None
    target_virtuals = {virtual for virtual in virtuals if virtual is not None}
    if not target_virtuals:
        return None
    classes = set()
    for match in _TRACE_COPY_REGISTER_TOKEN_RE.finditer(operands):
        virtual = int(match.group(2), 10)
        if virtual not in target_virtuals:
            continue
        classes.add("fpr" if match.group(1).lower() == "f" else "gpr")
    if len(classes) > 1:
        raise typer.BadParameter(
            "trace-copy JSON occurrence operands contain conflicting "
            "register classes for target virtuals"
        )
    return next(iter(classes), None)
def _trace_copy_inferred_register_class(
    payload: Mapping[str, Any],
    *,
    from_mapping: object,
    to_mapping: object,
    from_virtual: int | None,
    to_virtual: int | None,
) -> str | None:
    mapping_classes = set()
    for mapping, virtual in (
        (from_mapping, from_virtual),
        (to_mapping, to_virtual),
    ):
        if not isinstance(mapping, Mapping):
            continue
        for key in ("first_occurrence", "last_occurrence"):
            register_class = _trace_occurrence_register_class_for_virtuals(
                mapping.get(key),
                (virtual,),
            )
            if register_class is not None:
                mapping_classes.add(register_class)
    if len(mapping_classes) > 1:
        raise typer.BadParameter(
            "trace-copy JSON occurrence operands contain conflicting "
            "register classes"
        )
    if mapping_classes:
        return next(iter(mapping_classes))

    copy_classes = set()
    for key in ("first_copy", "last_copy"):
        register_class = _trace_occurrence_register_class_for_virtuals(
            payload.get(key),
            (from_virtual, to_virtual),
        )
        if register_class is not None:
            copy_classes.add(register_class)
    if len(copy_classes) > 1:
        raise typer.BadParameter(
            "trace-copy JSON occurrence operands contain conflicting "
            "register classes"
        )
    return next(iter(copy_classes), None)
def _trace_copy_operand_expression(
    *,
    first_occurrence: Mapping[str, Any] | None,
    call_return_origin: Mapping[str, Any] | None,
) -> str | None:
    if call_return_origin is not None:
        expression = call_return_origin.get("expression")
        if expression:
            return str(expression)
        call_symbol = call_return_origin.get("call_symbol")
        if call_symbol:
            return str(call_symbol)
    if first_occurrence is None:
        return None
    opcode = first_occurrence.get("opcode")
    operands = first_occurrence.get("operands")
    if opcode and operands:
        return f"{opcode} {operands}"
    if opcode:
        return str(opcode)
    return None
def _trace_mapping_string(
    mapping: Mapping[str, Any],
    *keys: str,
) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
def _trace_mapping_nested_string(
    mapping: Mapping[str, Any],
    nested_key: str,
    *keys: str,
) -> str | None:
    nested = mapping.get(nested_key)
    if not isinstance(nested, Mapping):
        return None
    return _trace_mapping_string(nested, *keys)
def _trace_mapping_source_local(mapping: Mapping[str, Any]) -> str | None:
    return (
        _trace_mapping_string(
            mapping,
            "source_local",
            "source_var",
            "var_name",
            "local",
            "name",
        )
        or _trace_mapping_nested_string(
            mapping,
            "binding",
            "var_name",
            "source_local",
            "name",
        )
        or _trace_mapping_nested_string(
            mapping,
            "source",
            "name",
            "var_name",
            "source_local",
        )
        or _trace_mapping_nested_string(
            mapping,
            "call_return_origin",
            "assigned_local",
            "source_local",
        )
    )
def _trace_mapping_source_type(mapping: Mapping[str, Any]) -> str | None:
    return (
        _trace_mapping_string(mapping, "source_type", "type", "type_str")
        or _trace_mapping_nested_string(mapping, "binding", "type_str", "type")
        or _trace_mapping_nested_string(mapping, "source", "type", "type_str")
    )
def _trace_copy_source_operand(
    mapping: object,
    *,
    virtual: int | None,
    register_class: str | None,
) -> dict[str, Any]:
    mapping_dict = mapping if isinstance(mapping, Mapping) else {}
    class_id = _trace_mapping_int(mapping_dict, "class_id")
    effective_class = register_class or _register_class_name_from_id(class_id) or "gpr"
    reg_prefix = "f" if effective_class == "fpr" else "r"
    first_occurrence = _trace_copy_json_occurrence(
        mapping_dict.get("first_occurrence")
    )
    last_occurrence = _trace_copy_json_occurrence(
        mapping_dict.get("last_occurrence")
    )
    raw_origin = mapping_dict.get("call_return_origin")
    call_return_origin = dict(raw_origin) if isinstance(raw_origin, Mapping) else None
    source_file = (
        call_return_origin.get("source_file")
        if call_return_origin is not None
        else None
    )
    source_line = (
        call_return_origin.get("source_line")
        if call_return_origin is not None
        else None
    )
    expression = _trace_copy_operand_expression(
        first_occurrence=first_occurrence,
        call_return_origin=call_return_origin,
    )
    mapped_to_source = bool(source_file and source_line is not None)
    return {
        "virtual": virtual,
        "token": None if virtual is None else f"{reg_prefix}{virtual}",
        "expression": expression,
        "source_file": source_file,
        "source_line": source_line,
        "confidence": (
            mapping_dict.get("confidence")
            or ("source-mapped" if mapped_to_source else "pcode-first-occurrence")
        ),
        "first_occurrence": first_occurrence,
        "last_occurrence": last_occurrence,
        "call_return_origin": call_return_origin,
        "mapped_to_source": mapped_to_source,
        "source_local": _trace_mapping_source_local(mapping_dict),
        "source_type": _trace_mapping_source_type(mapping_dict),
    }
def _retained_c_source_variant_hit(variant: Mapping[str, Any]) -> bool:
    from src.cli.debug import _copy_survived_variant_hit
    if not _copy_survived_variant_hit(variant):
        return False
    source_retained = variant.get("source_retained")
    path = variant.get("path")
    if variant.get("generated_probe"):
        pcdump_path = variant.get("pcdump_path")
        if not isinstance(pcdump_path, str):
            return False
        if (
            isinstance(source_retained, str)
            and "melee_coalesce_search_" in source_retained
        ):
            return False
        if isinstance(path, str) and "melee_coalesce_search_" in path:
            return False
    return (
        isinstance(source_retained, str)
        and source_retained.endswith(".c")
        and isinstance(path, str)
        and path.endswith(".c")
    )
def _coalesce_cli_path_arg(path: str | Path, melee_root: Path) -> str:
    raw_path = Path(path)
    try:
        display = str(raw_path.resolve().relative_to(melee_root.resolve()))
    except (OSError, ValueError):
        display = str(raw_path)
    return display.replace(os.sep, "/")
def _coalesce_trace_assignment_for_ig(
    trace_target: Mapping[str, Any],
    ig_idx: int,
) -> int | None:
    for prefix in ("from", "to"):
        if trace_target.get(f"{prefix}_ig_idx") == ig_idx:
            assigned = trace_target.get(f"{prefix}_assigned_reg")
            if isinstance(assigned, int):
                return assigned
    return None
def _coalesce_primary_force_target(
    trace_target: Mapping[str, Any],
    force_phys: Mapping[int, int],
) -> tuple[int | None, int | None, int | None]:
    for key in ("from_ig_idx", "to_ig_idx"):
        ig_idx = trace_target.get(key)
        if isinstance(ig_idx, int) and ig_idx in force_phys:
            return (
                ig_idx,
                force_phys[ig_idx],
                _coalesce_trace_assignment_for_ig(trace_target, ig_idx),
            )
    if force_phys:
        ig_idx, desired = next(iter(sorted(force_phys.items())))
        return ig_idx, desired, _coalesce_trace_assignment_for_ig(trace_target, ig_idx)
    for key in ("from_ig_idx", "to_ig_idx"):
        ig_idx = trace_target.get(key)
        if isinstance(ig_idx, int):
            return ig_idx, None, _coalesce_trace_assignment_for_ig(
                trace_target,
                ig_idx,
            )
    return None, None, None
def _coalesce_generated_local_source_attribution(
    source_retained: str,
    function: str,
    generated_local: str | None,
) -> dict[str, Any] | None:
    from src.cli.debug import _coalesce_find_function_body_span, _coalesce_line_no
    if generated_local is None:
        return None
    try:
        source_text = Path(source_retained).read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    span = _coalesce_find_function_body_span(source_text, function)
    if span is None:
        return None
    body_start, body_end = span
    body = source_text[body_start:body_end]
    match = re.search(
        r"(?m)^(?P<indent>[ \t]*)"
        r"(?P<type>(?:const\s+|volatile\s+|static\s+|register\s+)*"
        r"(?:struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*)"
        r"(?:\s+[A-Za-z_]\w*)*\s*\*+)\s*"
        rf"(?P<name>{re.escape(generated_local)})\s*=\s*"
        r"(?P<initializer>[^;\n]+)\s*;\s*$",
        body,
    )
    if match is None:
        return None
    abs_start = body_start + match.start()
    abs_end = body_start + match.end()
    return {
        "kind": "generated-pointer-walk-local",
        "name": generated_local,
        "type": re.sub(r"\s*\*\s*", "*", match.group("type")).strip(),
        "initializer": match.group("initializer").strip(),
        "source_line": _coalesce_line_no(source_text, abs_start),
        "source_hunk": {
            "line_start": _coalesce_line_no(source_text, abs_start),
            "line_end": _coalesce_line_no(source_text, max(abs_start, abs_end - 1)),
            "original": source_text[abs_start:abs_end],
        },
    }
def _coalesce_generated_local_source_cli_payload(
    generated_local_source: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(generated_local_source, Mapping):
        return None
    payload: dict[str, Any] = {}
    for key in ("kind", "name", "type", "initializer", "source_line"):
        value = generated_local_source.get(key)
        if value is not None:
            payload[key] = value
    return payload or None
def _copy_repair_candidate_summary(variant: Mapping[str, Any]) -> dict[str, Any]:
    summary = {
        "rank": variant.get("rank"),
        "label": variant.get("label"),
        "operator": variant.get("operator"),
        "path": variant.get("path"),
        "source_retained": variant.get("source_retained"),
        "objective": variant.get("objective"),
    }
    for key in (
        "pcdump_path",
        "original_path",
        "probe",
        "provenance",
        "description",
        "generated_probe",
        "generated_local",
        "source_hunk",
        "continuation",
    ):
        if key in variant:
            summary[key] = variant.get(key)
    return summary
def _trace_copy_pair_token(trace_target: Mapping[str, Any]) -> str:
    register_class = trace_target.get("register_class")
    reg_prefix = "f" if register_class == "fpr" else "r"
    return (
        f"{reg_prefix}{trace_target.get('from_virtual')}/"
        f"{reg_prefix}{trace_target.get('to_virtual')}"
    )
def _copy_propagation_repair_applies(trace_target: Mapping[str, Any]) -> bool:
    first_absent = str(trace_target.get("first_absent_pass") or "").upper()
    if first_absent == "AFTER COPY PROPAGATION":
        return True
    for key in ("likely_cause", "transform_category"):
        value = trace_target.get(key)
        if isinstance(value, str) and "copy-propagation" in value.lower():
            return True
    return False
def _copy_propagation_ranked_source_repairs(
    from_operand: Mapping[str, Any],
    to_operand: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not (
        from_operand.get("mapped_to_source")
        and to_operand.get("mapped_to_source")
    ):
        return []
    return [{
        "rank": 1,
        "kind": "source-expression-copy-shape",
        "source_actionable": False,
        "from": {
            "token": from_operand.get("token"),
            "expression": from_operand.get("expression"),
            "source_file": from_operand.get("source_file"),
            "source_line": from_operand.get("source_line"),
        },
        "to": {
            "token": to_operand.get("token"),
            "expression": to_operand.get("expression"),
            "source_file": to_operand.get("source_file"),
            "source_line": to_operand.get("source_line"),
        },
        "note": (
            "advisory only; source-actionable requires a scored retained .c "
            "candidate that changes the target relation"
        ),
    }]
def _copy_propagation_unmapped_operands(
    operands: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    unmapped = []
    for operand in operands:
        if operand.get("mapped_to_source"):
            continue
        unmapped.append({
            "virtual": operand.get("virtual"),
            "token": operand.get("token"),
            "expression": operand.get("expression"),
        })
    return unmapped
def _copy_propagation_terminal_blocker(
    unmapped_operands: list[Mapping[str, Any]],
) -> str:
    if unmapped_operands:
        rendered = ", ".join(
            f"{entry.get('token')}={entry.get('expression') or '?'}"
            for entry in unmapped_operands
        )
        return (
            "copy-propagation source repair blocked by unmapped source "
            f"operands: {rendered}"
        )
    return (
        "copy-propagation source repair has source-mapped operands, but no "
        "scored retained .c source candidate changed the target relation"
    )
def _copy_propagation_retained_source_shape_candidates(
    ranked_variants: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for variant in ranked_variants:
        if variant.get("operator") != "call-return-use-shape":
            continue
        if variant.get("status") != "ok":
            continue
        source_retained = variant.get("source_retained")
        pcdump_path = variant.get("pcdump_path")
        path = variant.get("path")
        if not (
            isinstance(source_retained, str)
            and source_retained.endswith(".c")
            and isinstance(pcdump_path, str)
            and isinstance(path, str)
            and "melee_coalesce_search_" not in source_retained
            and "melee_coalesce_search_" not in path
        ):
            continue
        candidates.append(_copy_repair_candidate_summary(variant))
    return candidates
def _copy_propagation_source_expression(
    from_operand: Mapping[str, Any],
    to_operand: Mapping[str, Any],
) -> str | None:
    from_expr = from_operand.get("expression")
    to_expr = to_operand.get("expression")
    if isinstance(from_expr, str) and from_expr.strip():
        if not isinstance(to_expr, str) or not to_expr.strip() or to_expr == from_expr:
            return from_expr
    if isinstance(to_expr, str) and to_expr.strip():
        return to_expr
    return None
def _copy_propagation_assigned_local(
    from_operand: Mapping[str, Any],
    to_operand: Mapping[str, Any],
) -> str | None:
    for operand in (from_operand, to_operand):
        source_local = operand.get("source_local")
        if isinstance(source_local, str) and source_local.strip():
            return source_local.strip()
        origin = operand.get("call_return_origin")
        if isinstance(origin, Mapping):
            assigned = origin.get("assigned_local")
            if isinstance(assigned, str) and assigned.strip():
                return assigned.strip()
    return None
def _copy_propagation_source_shape_terminal_summary(
    *,
    trace_target: Mapping[str, Any],
    from_operand: Mapping[str, Any],
    to_operand: Mapping[str, Any],
    retained_candidates: list[Mapping[str, Any]],
) -> dict[str, Any]:
    force_progress_values: set[str] = set()
    for candidate in retained_candidates:
        objective = candidate.get("objective")
        if not isinstance(objective, Mapping):
            continue
        progress = objective.get("force_phys_progress_kind")
        if progress:
            force_progress_values.add(str(progress))
    force_progress = sorted(force_progress_values)
    terminal_blocker = (
        "call-return/use-shape probes were retained and scored, but none "
        "changed the copy-propagation target relation"
    )
    if force_progress:
        terminal_blocker += (
            "; force-phys progress kinds: " + ", ".join(force_progress)
        )
    return {
        "kind": "call-return-use-shape-no-progress",
        "status": "terminal-no-progress",
        "target_pair": _trace_copy_pair_token(trace_target),
        "from_virtual": trace_target.get("from_virtual"),
        "to_virtual": trace_target.get("to_virtual"),
        "from_ig_idx": trace_target.get("from_ig_idx"),
        "to_ig_idx": trace_target.get("to_ig_idx"),
        "source_expression": _copy_propagation_source_expression(
            from_operand,
            to_operand,
        ),
        "assigned_local": _copy_propagation_assigned_local(
            from_operand,
            to_operand,
        ),
        "retained_candidate_count": len(retained_candidates),
        "force_phys_progress_kinds": force_progress,
        "terminal_blocker": terminal_blocker,
    }
def _preserve_source_restore_backup(
    path: Path,
    original: bytes,
    *,
    melee_root: Path,
) -> tuple[Path | None, str | None]:
    try:
        backup_dir = melee_root / "build" / "source-restore-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", path.name).strip(".-")
        fd, raw_backup = tempfile.mkstemp(
            prefix=f"{safe_name or 'source'}-",
            suffix=".bak",
            dir=backup_dir,
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(original)
        return Path(raw_backup), None
    except Exception as exc:
        return None, f"failed to preserve source restore backup: {type(exc).__name__}: {exc}"
def _restore_source_bytes_snapshot(
    path: Path,
    original: bytes,
    *,
    melee_root: Path,
) -> None:
    from src.cli.debug import _SourceRestoreBytesError  # noqa: PLC0415
    restore_error: str | None = None
    try:
        path.write_bytes(original)
        restored = path.read_bytes()
    except Exception as exc:
        restore_error = (
            f"failed to restore {path}: {type(exc).__name__}: {exc}"
        )
    else:
        if restored != original:
            restore_error = (
                f"failed to restore {path}: restored byte hash mismatch"
            )

    if restore_error is None:
        return

    backup_path, backup_error = _preserve_source_restore_backup(
        path,
        original,
        melee_root=melee_root,
    )
    if backup_error:
        restore_error = f"{restore_error}; {backup_error}"
    elif backup_path is not None:
        restore_error = f"{restore_error}; original bytes preserved at {backup_path}"
    raise _SourceRestoreBytesError(restore_error, backup_path)
@contextmanager
def _source_restore_byte_guard(
    path: Path | None,
    *,
    melee_root: Path,
) -> Iterator[None]:
    if path is None or not path.exists():
        yield
        return

    original = path.read_bytes()
    registered_signal_restore = False
    try:
        try:
            _register_active_source_restore(path, original.decode("utf-8"))
            registered_signal_restore = True
        except UnicodeDecodeError:
            pass

        yield
    finally:
        if registered_signal_restore:
            _unregister_active_source_restore(path)
        try:
            current = path.read_bytes() if path.exists() else None
        except Exception:
            current = None
        if current == original:
            return

        _restore_source_bytes_snapshot(
            path,
            original,
            melee_root=melee_root,
        )
def _unique_existing_source_restore_paths(
    paths: Iterable[Path | None],
) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        if path is None or not path.exists():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out
def _restore_active_sources_for_signal(signum: int, _frame: object) -> None:
    from src.cli.debug import _restore_source_snapshot, _ACTIVE_SOURCE_RESTORES
    errors: list[str] = []
    for path, originals in list(_ACTIVE_SOURCE_RESTORES.items()):
        if not originals:
            _ACTIVE_SOURCE_RESTORES.pop(path, None)
            continue
        original = originals[0]
        error = _restore_source_snapshot(path, original)
        if error:
            errors.append(error)
        else:
            _ACTIVE_SOURCE_RESTORES.pop(path, None)
    for error in errors:
        print(f"[source-restore] {error}", file=sys.stderr)
    if signum == signal.SIGINT:
        raise KeyboardInterrupt
    raise SystemExit(128 + signum)
def _ensure_source_restore_signal_handlers() -> None:
    from src.cli.debug import _SOURCE_RESTORE_SIGNAL_HANDLERS
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        if signum in _SOURCE_RESTORE_SIGNAL_HANDLERS:
            continue
        _SOURCE_RESTORE_SIGNAL_HANDLERS[signum] = signal.getsignal(signum)
        signal.signal(signum, _restore_active_sources_for_signal)
def _register_active_source_restore(path: Path, original: str) -> None:
    from src.cli.debug import _ACTIVE_SOURCE_RESTORES
    _ensure_source_restore_signal_handlers()
    _ACTIVE_SOURCE_RESTORES.setdefault(path, []).append(original)
def _unregister_active_source_restore(path: Path) -> None:
    from src.cli.debug import _ACTIVE_SOURCE_RESTORES
    originals = _ACTIVE_SOURCE_RESTORES.get(path)
    if not originals:
        _ACTIVE_SOURCE_RESTORES.pop(path, None)
        return
    originals.pop()
    if not originals:
        _ACTIVE_SOURCE_RESTORES.pop(path, None)
@contextmanager
def _source_restore_guard(path: Path, original: str) -> Iterator[None]:
    from src.cli.debug import _restore_source_snapshot
    _register_active_source_restore(path, original)
    try:
        yield
    finally:
        error = _restore_source_snapshot(path, original)
        _unregister_active_source_restore(path)
        if error is not None:
            raise RuntimeError(error)
def _fresh_pcdump_cache_path_for_restore(
    *,
    unit: str | None,
    melee_root: Path,
) -> Path | None:
    if unit is None:
        return None
    entry = pcdump_cache.lookup(melee_root, unit)
    if entry is None or not entry.fresh:
        return None
    return entry.path
def _preserve_pcdump_cache_freshness_after_restore(
    *,
    cache_path: Path | None,
    source_path: Path,
    original: str,
) -> None:
    if cache_path is None:
        return
    try:
        if source_path.read_text() != original:
            return
        pcdump_cache.write_hash_sidecar(cache_path, source_path)
    except OSError:
        pass
def _new_external_function_definitions(
    candidate_text: str,
    original_text: str,
    *,
    function: str,
) -> list[str]:
    candidate_names = {
        span.name for span in find_function_definitions(candidate_text)
    }
    original_names = {
        span.name for span in find_function_definitions(original_text)
    }
    return sorted(candidate_names - original_names - {function})
def _find_stack_slot_localizer_in_json(value: object) -> dict | None:
    if isinstance(value, dict):
        localizer = value.get("stack_slot_localizer")
        if isinstance(localizer, dict):
            return localizer
        for child in value.values():
            found = _find_stack_slot_localizer_in_json(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_stack_slot_localizer_in_json(child)
            if found is not None:
                return found
    return None
def _run_checkdiff_stack_slot_localizer(
    *,
    function: str,
    melee_root: Path,
    timeout: float | None = None,
) -> tuple[dict | None, str | None]:
    payload, error = _run_checkdiff_stack_slot_payload(
        function=function,
        melee_root=melee_root,
        timeout=timeout,
    )
    if error is not None:
        return None, error
    localizer = _find_stack_slot_localizer_in_json(payload)
    if localizer is not None:
        return localizer, None
    return None, None
def _run_checkdiff_stack_slot_payload(
    *,
    function: str,
    melee_root: Path,
    timeout: float | None = None,
) -> tuple[dict | None, str | None]:
    return _run_checkdiff_json(
        function,
        melee_root=melee_root,
        timeout=timeout,
        no_build=True,
        label="checkdiff stack-slot analysis",
    )


def _stack_homes_terminal_payload(
    *,
    function: str,
    pcdump_path: Path,
    reason: str,
    detail: str | None = None,
    checkdiff_json: Path | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "terminal",
        "terminal": True,
        "kind": "stack-home-localizer-unavailable",
        "terminal_reason": reason,
        "function": function,
        "pcdump": str(pcdump_path),
        "fallback_routes": [
            {
                "tool": "debug inspect frame-reservations",
                "reason": "inspect frame/local-area reservations without requiring stack_slot_localizer",
                "command": (
                    "melee-agent debug inspect frame-reservations "
                    f"-f {function} {pcdump_path} --json"
                ),
            },
            {
                "tool": "debug mutate frame-transform-search",
                "reason": "generate bounded frame-layout probes from the retained pcdump",
                "command": (
                    "melee-agent debug mutate frame-transform-search "
                    f"-f {function} --pcdump {pcdump_path} --json"
                ),
            },
            {
                "tool": "debug mutate lifetime-layout",
                "reason": "explore lifetime/source-layout levers when stack homes are unavailable",
                "command": (
                    "melee-agent debug mutate lifetime-layout "
                    f"-f {function} --pcdump {pcdump_path} --json"
                ),
            },
        ],
    }
    if detail:
        payload["detail"] = detail
    if checkdiff_json is not None:
        payload["checkdiff_json"] = str(checkdiff_json)
    return payload


def _abort_stack_homes_terminal(
    *,
    function: str,
    pcdump_path: Path,
    reason: str,
    message: str,
    json_out: bool,
    checkdiff_json: Path | None = None,
) -> None:
    if json_out:
        print(json.dumps(_stack_homes_terminal_payload(
            function=function,
            pcdump_path=pcdump_path,
            reason=reason,
            detail=message,
            checkdiff_json=checkdiff_json,
        ), indent=2))
    typer.echo(message, err=True)
    raise typer.Exit(3)


def _run_checkdiff_json(
    function: str,
    *,
    melee_root: Path,
    timeout: float | None = None,
    no_build: bool = True,
    label: str = "checkdiff",
    locked_child: bool = False,
    disable_fingerprint: bool = False,
) -> tuple[dict | None, str | None]:
    cmd = [
        sys.executable,
        "tools/checkdiff.py",
        function,
        "--format",
        "json",
    ]
    if no_build:
        cmd.append("--no-build")
    env = None
    if locked_child:
        env = _checkdiff_env_for_locked_child(
            disable_fingerprint=disable_fingerprint
        )
    elif disable_fingerprint:
        from src.cli.debug import _checkdiff_env_without_fingerprint
        env = _checkdiff_env_without_fingerprint()
    try:
        proc = subprocess.run(
            cmd,
            cwd=melee_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return None, f"{label} timed out"
    except Exception as exc:
        return None, f"{label} failed: {exc}"

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        detail = (proc.stderr or proc.stdout or str(exc)).strip()
        return None, f"{label} emitted non-json: {detail}"

    if proc.returncode not in (0, 1):
        detail = (proc.stderr or proc.stdout or "").strip()
        return None, (
            f"{label} failed with exit {proc.returncode}"
            + (f": {detail}" if detail else "")
        )
    return payload, None
def _first_mapping(*values: object) -> dict:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}
def _first_int(*values: object) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
    return None
def _first_float(*values: object) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None
def _shape_guard_from_checkdiff_payload(payload: dict | None) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    classification = _first_mapping(payload.get("classification"))
    structural = _first_mapping(payload.get("structural"))
    truth_gate = _first_mapping(
        classification.get("structural_truth_gate"),
        structural.get("structural_truth_gate"),
    )
    stack_sizes = _first_mapping(
        classification.get("stack_frame_sizes"),
        structural.get("stack_frame_sizes"),
    )
    stack_delta = _first_mapping(classification.get("stack_frame_delta"))

    primary = classification.get("primary")
    primary_text = str(primary) if primary is not None else None
    normalized_diff_lines = _first_int(
        truth_gate.get("normalized_diff_lines"),
        structural.get("normalized_diff_lines"),
        classification.get("normalized_diff_lines"),
    )
    opcode_similarity = _first_float(structural.get("opcode_similarity"))
    line_delta = _first_int(structural.get("line_delta"))
    if line_delta is None:
        reference_lines = _first_int(payload.get("reference_lines"))
        current_lines = _first_int(payload.get("current_lines"))
        if reference_lines is not None and current_lines is not None:
            line_delta = current_lines - reference_lines
    hunk_count = _first_int(structural.get("hunk_count"))

    expected_frame = _first_int(
        stack_sizes.get("expected_frame_size"),
        stack_delta.get("expected_frame_size"),
    )
    current_frame = _first_int(
        stack_sizes.get("current_frame_size"),
        stack_delta.get("current_frame_size"),
    )
    frame_delta = _first_int(
        stack_sizes.get("frame_growth"),
        stack_delta.get("frame_growth"),
    )
    if frame_delta is None and expected_frame is not None and current_frame is not None:
        frame_delta = current_frame - expected_frame

    effective_primaries = {
        "instruction-identical",
        "relocation-label-only",
        "normalized-structural-match",
        "register-allocation",
        "operand-register-or-offset",
        "backend-ceiling",
    }
    drift_primaries = {
        "control-flow-source-shape",
        "signature-type-mismatch",
        "inline-boundary-toolchain-artifact",
        "instruction-sequence",
        "indexed-struct-pointer-materialization",
        "stack-layout",
        "stack-slot-layout",
    }
    frame_compatible = frame_delta in (None, 0)
    normalized_preserved = normalized_diff_lines == 0
    opcode_preserved = opcode_similarity == 1.0 and frame_compatible
    shape_preserved = (
        primary_text in effective_primaries
        and primary_text not in drift_primaries
        and frame_compatible
        and (normalized_preserved or opcode_preserved)
    )
    if primary_text in {"instruction-identical", "relocation-label-only"}:
        shape_preserved = frame_compatible
    if primary_text == "normalized-structural-match":
        shape_preserved = frame_compatible

    rejection_reason = None
    if not shape_preserved:
        rejection_reason = (
            "checkdiff structural drift: "
            f"{primary_text or 'unknown-classification'}"
        )
    return {
        "accepted": bool(shape_preserved),
        "shape_preserved": bool(shape_preserved),
        "classification_primary": primary_text,
        "normalized_diff_lines": normalized_diff_lines,
        "opcode_similarity": opcode_similarity,
        "line_delta": line_delta,
        "hunk_count": hunk_count,
        "expected_frame": expected_frame,
        "current_frame": current_frame,
        "frame_delta": frame_delta,
        "rejection_reason": rejection_reason,
    }
def _name_magic_decode_anonymous_symbol(symbol: Any) -> dict[str, Any]:
    import struct

    payload: dict[str, Any] = {
        "anonymous": symbol.name,
        "name": symbol.name,
        "size": symbol.size,
        "value": symbol.value,
    }
    if symbol.size == 4:
        try:
            payload["float"] = struct.unpack(
                ">f",
                struct.pack(">I", symbol.value),
            )[0]
        except Exception:
            pass
    elif symbol.size == 8:
        try:
            from ...mwcc_debug.o_rewriter import MAGIC_S32, MAGIC_U32

            if symbol.value == MAGIC_S32:
                payload["bias"] = "s32"
            elif symbol.value == MAGIC_U32:
                payload["bias"] = "u32"
            else:
                payload["double"] = struct.unpack(
                    ">d",
                    struct.pack(">Q", symbol.value),
                )[0]
        except Exception:
            pass
    return payload
@inspect_app.command(name="stack-homes")
def inspect_stack_homes(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    checkdiff_json: Annotated[
        Optional[Path],
        typer.Option(
            "--checkdiff-json",
            help=(
                "Existing checkdiff --format json output containing a "
                "stack_slot_localizer. If omitted, checkdiff is run with "
                "--no-build to get one."
            ),
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "C source file used for source/lifetime attribution. Defaults "
                "to the repo source for the function when available."
            ),
        ),
    ] = None,
    checkdiff_timeout: Annotated[
        float,
        typer.Option(
            "--checkdiff-timeout",
            help="Timeout in seconds when auto-running checkdiff.",
        ),
    ] = 60.0,
    score_sqrt_array_variants: Annotated[
        bool,
        typer.Option(
            "--score-sqrt-array-variants",
            help=(
                "Generate local-array sqrtf variants, compile them in the "
                "current tree, and rank target stack-slot movement before "
                "overall match percent."
            ),
        ),
    ] = False,
    max_variants: Annotated[
        int,
        typer.Option(
            "--max-variants",
            help="Maximum generated sqrt-array variants to score.",
        ),
    ] = 4,
    variant_timeout: Annotated[
        float,
        typer.Option(
            "--variant-timeout",
            help="Timeout in seconds for each generated variant build/score.",
        ),
    ] = 120.0,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Explain final-only FPR stack-home targets and source-shape leads."""
    from src.cli.debug import DEFAULT_MELEE_ROOT, _find_unit_for_function, _resolve_pcdump_path, _score_source_candidate_real_tree
    from ...mwcc_debug.stack_home_explorer import (
        attach_variant_rankings,
        explore_stack_homes,
        generate_local_array_sqrt_variants,
        render_stack_home_report_text,
    )

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        melee_root,
        require_fresh=False,
    )

    if checkdiff_json is not None:
        if not checkdiff_json.is_file():
            raise typer.BadParameter(f"checkdiff JSON not found: {checkdiff_json}")
        try:
            checkdiff_payload = json.loads(checkdiff_json.read_text())
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                f"checkdiff JSON could not be parsed: {exc}"
            ) from exc
        localizer = _find_stack_slot_localizer_in_json(checkdiff_payload)
        if localizer is None:
            _abort_stack_homes_terminal(
                function=function,
                pcdump_path=pcdump_path,
                reason="no-stack-slot-localizer",
                message=f"{checkdiff_json} did not contain stack_slot_localizer",
                json_out=json_out,
                checkdiff_json=checkdiff_json,
            )
    else:
        localizer, error = _run_checkdiff_stack_slot_localizer(
            function=function,
            melee_root=melee_root,
            timeout=checkdiff_timeout,
        )
        if error is not None:
            _abort_stack_homes_terminal(
                function=function,
                pcdump_path=pcdump_path,
                reason="cannot-run-stack-home-localizer",
                message=error,
                json_out=json_out,
            )
        if localizer is None:
            _abort_stack_homes_terminal(
                function=function,
                pcdump_path=pcdump_path,
                reason="no-stack-slot-localizer",
                message=(
                    "checkdiff did not report a stack_slot_localizer for "
                    f"{function}"
                ),
                json_out=json_out,
            )

    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, melee_root)
        if unit is not None:
            candidate = melee_root / "src" / f"{unit}.c"
            if candidate.is_file():
                source_text = candidate.read_text()
                try:
                    source_label = str(candidate.relative_to(melee_root))
                except ValueError:
                    source_label = str(candidate)

    report = explore_stack_homes(
        pcdump_path.read_text(),
        function,
        localizer,
        source_text=source_text,
        source_file=source_label,
    )
    if score_sqrt_array_variants:
        if source_text is None:
            typer.echo(
                "--score-sqrt-array-variants requires source text; pass "
                "--source-file or rebuild report.json so the function source "
                "can be resolved.",
                err=True,
            )
            raise typer.Exit(2)
        variants = generate_local_array_sqrt_variants(
            source_text,
            function,
            max_variants=max_variants,
        )
        variant_results: list[dict] = []
        with tempfile.TemporaryDirectory(prefix="stack-home-variants-") as td:
            temp_dir = Path(td)
            for variant in variants:
                variant_id = variant["id"]
                candidate_path = temp_dir / f"{variant_id}.c"
                candidate_path.write_text(variant["candidate_source"])
                score = _score_source_candidate_real_tree(
                    candidate_path,
                    function=function,
                    melee_root=melee_root,
                    timeout=variant_timeout,
                    include_stack_slot=True,
                )
                variant_results.append({
                    "variant_id": variant_id,
                    "kind": variant["kind"],
                    "description": variant["description"],
                    "match_percent": score.match_percent,
                    "match_percent_error": score.match_percent_error,
                    "stack_slot_localizer": score.stack_slot_localizer,
                    "stack_slot_error": score.stack_slot_error,
                    "checkdiff_payload": getattr(score, "checkdiff_payload", None),
                    "source_patch": variant.get("source_patch"),
                })
        attach_variant_rankings(
            report,
            variant_results,
            source_text=source_text,
            function=function,
        )
    if json_out:
        print(json.dumps(report, indent=2))
    else:
        print(render_stack_home_report_text(report))
def _normalize_header_declaration(declaration: str) -> str:
    declaration = declaration.strip()
    if not declaration:
        return ""
    return declaration if declaration.endswith(";") else f"{declaration};"
def _select_order_replace_function_text(
    source_text: str,
    function: str,
    replacement_function: str,
) -> str | None:
    span = find_source_function(source_text, function)
    if span is None:
        return None
    return (
        source_text[:span.sig_start]
        + replacement_function
        + source_text[span.full_end:]
    )
def _select_order_duplicate_local_declaration_key(line: str) -> str | None:
    stripped = line.split("//", 1)[0].strip()
    if not stripped or not stripped.endswith(";"):
        return None
    if any(token in stripped for token in ("=", "(", ")", ",")):
        return None
    if re.match(
        r"^(?:const\s+|volatile\s+|register\s+|auto\s+|static\s+)*"
        r"(?:(?:struct|union|enum)\s+)?[A-Za-z_]\w*"
        r"(?:\s*\*|\s+[A-Za-z_]\w*)*"
        r"\s+[A-Za-z_]\w*(?:\s*\[[^\]]+\])?\s*;$",
        stripped,
    ) is None:
        return None
    return re.sub(r"\s+", " ", stripped)
def _select_order_dedupe_duplicate_local_declarations(function_text: str) -> str:
    lines = function_text.splitlines(keepends=True)
    if not lines:
        return function_text
    seen_by_scope: dict[tuple[int, ...], set[str]] = {}
    scope_stack: list[int] = []
    next_scope_id = 0
    kept: list[str] = []

    def update_scope_stack(line: str) -> None:
        nonlocal next_scope_id
        code = line.split("//", 1)[0]
        for char in code:
            if char == "{":
                next_scope_id += 1
                scope_stack.append(next_scope_id)
            elif char == "}" and scope_stack:
                scope_stack.pop()

    for line in lines:
        scope = tuple(scope_stack)
        key = _select_order_duplicate_local_declaration_key(line)
        if key is not None:
            seen = seen_by_scope.setdefault(scope, set())
            if key in seen:
                update_scope_stack(line)
                continue
            seen.add(key)
        kept.append(line)
        update_scope_stack(line)
    return "".join(kept)
def _select_order_expression_provenance(
    *,
    base_text: str,
    candidate_text: str,
) -> dict[str, Any]:
    call_re = re.compile(r"\b[A-Za-z_]\w*\s*\([^;\n]*?\)")
    ident_re = re.compile(r"\b[A-Za-z_]\w*\b")
    ignored = {
        "char",
        "const",
        "double",
        "float",
        "int",
        "long",
        "register",
        "s16",
        "s32",
        "s8",
        "short",
        "static",
        "struct",
        "u16",
        "u32",
        "u8",
        "unsigned",
        "volatile",
    }
    base_identifiers = {
        item for item in ident_re.findall(base_text)
        if item not in ignored
    }
    candidate_identifiers = {
        item for item in ident_re.findall(candidate_text)
        if item not in ignored
    }
    return {
        "base_calls": [item.strip() for item in call_re.findall(base_text)],
        "candidate_calls": [
            item.strip() for item in call_re.findall(candidate_text)
        ],
        "removed_identifiers": sorted(base_identifiers - candidate_identifiers),
        "added_identifiers": sorted(candidate_identifiers - base_identifiers),
    }
def _select_order_source_hunk_line_components(
    *,
    seed_label: str,
    protected_hits: Mapping[str, int],
    hunk: Mapping[str, Any],
    base_lines: list[str],
) -> list[dict[str, Any]]:
    replacement = list(hunk.get("replacement") or [])
    base_start = int(hunk["base_start"])
    base_end = int(hunk["base_end"])
    base_count = base_end - base_start
    candidate_start = int(hunk.get("candidate_start", hunk["candidate_line_range"][0] - 1))
    diff_tag = str(hunk.get("diff_tag") or "")
    components: list[dict[str, Any]] = []

    def add_component(
        *,
        sub_index: int,
        component_base_start: int,
        component_base_end: int,
        component_replacement: list[str],
        component_candidate_start: int,
        component_candidate_end: int,
    ) -> None:
        component_base = base_lines[component_base_start:component_base_end]
        if not _select_order_source_hunk_has_statement(
            [*component_base, *component_replacement]
        ):
            return
        components.append({
            "hunk_index": hunk["hunk_index"],
            "sub_hunk_index": sub_index,
            "diff_tag": diff_tag,
            "base_start": component_base_start,
            "base_end": component_base_end,
            "replacement": component_replacement,
            "base_line_range": [component_base_start + 1, component_base_end],
            "candidate_line_range": [
                component_candidate_start + 1,
                component_candidate_end,
            ],
            "base_hunk": "".join(component_base),
            "candidate_hunk": "".join(component_replacement),
            "expression_provenance": _select_order_expression_provenance(
                base_text="".join(component_base),
                candidate_text="".join(component_replacement),
            ),
            "component_kind": "line",
            "source_label": seed_label,
            "protected_hits": dict(protected_hits),
            "parent_hunk": {
                "hunk_index": hunk["hunk_index"],
                "diff_tag": diff_tag,
                "base_line_range": list(hunk["base_line_range"]),
                "candidate_line_range": list(hunk["candidate_line_range"]),
            },
        })

    if diff_tag == "replace" and base_count == len(replacement):
        for offset, line in enumerate(replacement):
            add_component(
                sub_index=offset,
                component_base_start=base_start + offset,
                component_base_end=base_start + offset + 1,
                component_replacement=[line],
                component_candidate_start=candidate_start + offset,
                component_candidate_end=candidate_start + offset + 1,
            )
    elif diff_tag == "insert":
        for offset, line in enumerate(replacement):
            add_component(
                sub_index=offset,
                component_base_start=base_start,
                component_base_end=base_end,
                component_replacement=[line],
                component_candidate_start=candidate_start + offset,
                component_candidate_end=candidate_start + offset + 1,
            )
    elif diff_tag == "delete" and base_count > 0:
        for offset in range(base_count):
            add_component(
                sub_index=offset,
                component_base_start=base_start + offset,
                component_base_end=base_start + offset + 1,
                component_replacement=[],
                component_candidate_start=candidate_start,
                component_candidate_end=candidate_start,
            )
    return components
def _select_order_source_components_overlap(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> bool:
    left_start = int(left["base_start"])
    left_end = int(left["base_end"])
    right_start = int(right["base_start"])
    right_end = int(right["base_end"])
    if left_start == left_end and right_start == right_end:
        return left_start == right_start
    return max(left_start, right_start) < min(left_end, right_end)
def _select_order_merge_protected_hits(
    components: Iterable[Mapping[str, Any]],
) -> dict[str, int] | None:
    protected: dict[str, int] = {}
    for component in components:
        for ig_idx, phys in dict(component.get("protected_hits") or {}).items():
            key = str(ig_idx)
            value = int(phys)
            if key in protected and protected[key] != value:
                return None
            protected[key] = value
    return protected
def _select_order_component_provenance(
    component: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "source_label": component["source_label"],
        "component_kind": component["component_kind"],
        "hunk_index": component["hunk_index"],
        "sub_hunk_index": component.get("sub_hunk_index"),
        "diff_tag": component["diff_tag"],
        "base_line_range": list(component["base_line_range"]),
        "candidate_line_range": list(component["candidate_line_range"]),
        "base_hunk": component["base_hunk"],
        "candidate_hunk": component["candidate_hunk"],
        "expression_provenance": component.get("expression_provenance"),
        "parent_hunk": component.get("parent_hunk"),
    }
def _select_order_source_hunk_has_statement(lines: Iterable[str]) -> bool:
    return any(";" in line and not line.lstrip().startswith("#") for line in lines)
def _select_order_real_score_sort_key(variant: dict) -> tuple[float, ...]:
    if variant.get("status") != "ok":
        return (-1.0,)
    objective = variant.get("objective") or {}
    match = objective.get("match_percent")
    match_score = float(match) if isinstance(match, (int, float)) else -1.0
    sort_key = objective.get("sort_key") or ()
    if isinstance(sort_key, list):
        objective_key = tuple(float(item) for item in sort_key)
    elif isinstance(sort_key, tuple):
        objective_key = tuple(float(item) for item in sort_key)
    else:
        objective_key = ()
    return (1.0, match_score, *objective_key)
def _select_order_source_idea_payload(source: object | None) -> dict | None:
    if source is None:
        return None
    return {
        "ig_idx": getattr(source, "ig_idx", None),
        "var_name": getattr(source, "var_name", None),
        "confidence": getattr(source, "confidence", None),
        "alternates": list(getattr(source, "alternates", ()) or ()),
        "ideas": list(getattr(source, "ideas", ()) or ()),
        "rejected": list(getattr(source, "rejected", ()) or ()),
        "first_def": getattr(source, "first_def", None),
        "blocker_ig": getattr(source, "blocker_ig", None),
        "blocker_var_name": getattr(source, "blocker_var_name", None),
        "blocker_confidence": getattr(source, "blocker_confidence", None),
        "blocker_alternates": list(
            getattr(source, "blocker_alternates", ()) or ()
        ),
        "blocker_rejected": list(getattr(source, "blocker_rejected", ()) or ()),
        "blocker_first_def": getattr(source, "blocker_first_def", None),
    }
def _select_order_force_phys_hits(variant: Mapping[str, Any]) -> set[int]:
    objective = variant.get("objective")
    if not isinstance(objective, Mapping):
        return set()
    targets = objective.get("force_phys_targets")
    if not isinstance(targets, Mapping):
        return set()
    missing = {
        int(item) for item in objective.get("force_phys_missing") or []
        if isinstance(item, (int, str)) and str(item).lstrip("-").isdigit()
    }
    mismatches_raw = objective.get("force_phys_mismatches")
    mismatches: set[int] = set()
    if isinstance(mismatches_raw, Mapping):
        for key in mismatches_raw:
            if isinstance(key, (int, str)) and str(key).lstrip("-").isdigit():
                mismatches.add(int(key))
    hits: set[int] = set()
    for key in targets:
        if isinstance(key, (int, str)) and str(key).lstrip("-").isdigit():
            ig_idx = int(key)
            if ig_idx not in missing and ig_idx not in mismatches:
                hits.add(ig_idx)
    return hits
def _select_order_frame_preserved(objective: Mapping[str, Any]) -> bool:
    frame_delta = objective.get("frame_delta")
    return frame_delta in (None, 0)
def _select_order_int_mapping(value: object) -> dict[int, int]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[int, int] = {}
    for key, raw in value.items():
        if not isinstance(key, (int, str)) or not str(key).lstrip("-").isdigit():
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            continue
        raw_text = str(raw)
        if not raw_text.lstrip("-").isdigit():
            continue
        out[int(key)] = int(raw)
    return out
def _select_order_force_phys_missing_registers(
    objective: Mapping[str, Any],
) -> dict[str, int]:
    targets = _select_order_int_mapping(objective.get("force_phys_targets"))
    missing: set[int] = set()
    for item in objective.get("force_phys_missing") or []:
        if isinstance(item, (int, str)) and str(item).lstrip("-").isdigit():
            missing.add(int(item))
    return {
        str(ig_idx): targets[ig_idx]
        for ig_idx in sorted(missing)
        if ig_idx in targets
    }
def _select_order_force_phys_mismatched_registers(
    objective: Mapping[str, Any],
) -> dict[str, dict[str, int]]:
    raw = objective.get("force_phys_mismatches")
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, dict[str, int]] = {}
    for key, value in raw.items():
        if not isinstance(key, (int, str)) or not str(key).lstrip("-").isdigit():
            continue
        if not isinstance(value, Mapping):
            continue
        expected = value.get("expected")
        actual = value.get("actual")
        if (
            isinstance(expected, bool)
            or isinstance(actual, bool)
            or not isinstance(expected, (int, str))
            or not isinstance(actual, (int, str))
            or not str(expected).lstrip("-").isdigit()
            or not str(actual).lstrip("-").isdigit()
        ):
            continue
        out[str(int(key))] = {
            "expected": int(expected),
            "actual": int(actual),
        }
    return out
def _select_order_float_sort_value(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default
def _select_order_guard_repair_kind(
    guard: Mapping[str, Any],
    objective: Mapping[str, Any],
) -> str:
    reason_parts: list[str] = []
    for key in ("rejection_reason", "classification_primary", "reason"):
        value = guard.get(key)
        if value is not None:
            reason_parts.append(str(value))
    reasons = guard.get("reasons")
    if isinstance(reasons, list):
        reason_parts.extend(str(item) for item in reasons)
    reason_text = " ".join(reason_parts).lower()
    frame_delta = guard.get("frame_delta")
    if frame_delta is None:
        frame_delta = objective.get("frame_delta")
    frame_delta_value = _select_order_float_sort_value(frame_delta, default=0.0)
    if "inline-boundary" in reason_text:
        return "inline-boundary-toolchain-artifact"
    if "stack" in reason_text or frame_delta_value != 0.0:
        return "stack-layout"
    return "structural-drift"
def _select_order_guard_repair_action(kind: str) -> dict[str, str]:
    action_kind = {
        "inline-boundary-toolchain-artifact": "restore-inline-boundary-shape",
        "stack-layout": "repair-stack-layout",
    }.get(kind, "inspect-structural-drift")
    return {
        "kind": action_kind,
        "next_command_hint": (
            "debug select-order-search --candidate LABEL:OPERATOR=path "
            "--guard-repair-depth 1"
        ),
    }
def _select_order_source_hunk_call_lines(source_hunk: str | None) -> list[str]:
    executable = _select_order_source_hunk_executable_lines(source_hunk)
    calls: list[str] = []
    for raw_line in executable:
        line = raw_line.strip()
        line = re.sub(r"^\d+:\s*", "", line)
        if "(" not in line or line.startswith(("if", "for", "while", "switch")):
            continue
        if re.search(r"\b[A-Za-z_]\w*\s*\(", line):
            calls.append(raw_line)
    return calls[:8]
def _select_order_source_hunk_executable_lines(
    source_hunk: str | None,
) -> list[str]:
    if not source_hunk:
        return []
    executable: list[str] = []
    in_block_comment = False
    for raw_line in source_hunk.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^\d+:\s*", "", line)
        if not line or line in {"{", "}", "};"}:
            continue
        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
            continue
        if line.startswith("//"):
            continue
        if line.startswith("/*") or line.startswith("*"):
            if "*/" not in line:
                in_block_comment = True
            continue
        code_line = _select_order_source_hunk_code_line(line)
        if not code_line:
            continue
        if _select_order_source_line_is_non_executable_declaration(code_line):
            continue
        executable.append(raw_line)
    return executable[:12]
def _select_order_source_hunk_code_line(line: str) -> str:
    line = re.sub(r"/\*.*?\*/", "", line)
    line = line.split("//", 1)[0]
    return line.strip()
def _select_order_source_line_is_non_executable_declaration(line: str) -> bool:
    if line.startswith(("#", "typedef ", "struct ", "enum ", "union ")):
        return True
    if line.startswith(("if", "for", "while", "switch", "return", "goto")):
        return False
    if "=" in line:
        return False
    if re.match(
        r"^(?:static\s+|extern\s+|inline\s+|const\s+|volatile\s+)*"
        r"(?:[A-Za-z_]\w*\s*\*?\s+)+"
        r"[A-Za-z_]\w*\s*\([^;{}]*\)\s*;?$",
        line,
    ):
        return True
    if re.match(
        r"^(?:static\s+|extern\s+|const\s+|volatile\s+)*"
        r"(?:[A-Za-z_]\w*\s*\*?\s+)+"
        r"[A-Za-z_]\w*(?:\[[^\]]*\])?\s*;$",
        line,
    ):
        return True
    return False
def _select_order_inline_boundary_repair_routes(
    *,
    function: str | None,
    source_path: str | None,
    force_phys: Mapping[int, int] | Mapping[str, int] | None = None,
    target_orders: list[tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    command_parts = [
        "melee-agent",
        "debug",
        "search",
        "structure",
    ]
    if function:
        command_parts.extend(["-f", function])
    command_parts.extend(["--axis", "inline-boundary"])
    if source_path:
        command_parts.extend(["--source-file", source_path])
    command_parts.extend(["--max-candidates", "24", "--score", "--json"])
    routes: list[dict[str, Any]] = [{
        "rank": 1,
        "kind": "run-inline-boundary-structure-search",
        "axis": "inline-boundary",
        "command": " ".join(shlex.quote(part) for part in command_parts),
    }]
    if function:
        routes.append({
            "rank": 2,
            "kind": "retry-select-order-guard-repair-from-retained-source",
            "command": (
                "melee-agent debug select-order-search "
                f"-f {shlex.quote(function)} "
                "--candidate LABEL:OPERATOR=path --guard-repair-depth 1"
            ),
        })
        force_csv = _select_order_force_phys_csv(force_phys)
        target_csv = _select_order_target_order_csv(target_orders)
        unit = _select_order_unit_hint_from_source_path(source_path)
        plan_parts = [
            "melee-agent",
            "debug",
            "search",
            "plan-transforms",
            "-f",
            function,
            "--unit",
            unit or "<unit>",
        ]
        if source_path:
            plan_parts.extend(["--source-file", source_path])
        plan_parts.extend(["--force-phys", force_csv or "<IG:PHYS,...>", "--json"])
        routes.append({
            "rank": 3,
            "kind": "inspect-transform-corpus-plan",
            "command": " ".join(shlex.quote(part) for part in plan_parts),
        })
        repair_parts = [
            "melee-agent",
            "debug",
            "select-order-search",
            "-f",
            function,
            "--target",
            target_csv or "<TARGET_ORDER>",
            "--include-transform-corpus",
            "--transform-family",
            "helper_shape",
            "--transform-family",
            "independent_statement_order",
            "--transform-family",
            "coloring_register_steering",
            "--transform-force-phys",
            force_csv or "<IG:PHYS,...>",
            "--guard-repair-depth",
            "1",
            "--json",
        ]
        if source_path:
            repair_parts.extend(["--source-file", source_path])
        routes.append({
            "rank": 4,
            "kind": "run-select-order-transform-corpus-repair",
            "command": " ".join(shlex.quote(part) for part in repair_parts),
        })
    return routes
def _select_order_force_phys_csv(
    force_phys: Mapping[int, int] | Mapping[str, int] | None,
) -> str | None:
    if not force_phys:
        return None
    parts: list[tuple[int, int]] = []
    for key, value in force_phys.items():
        try:
            ig_idx = int(key)
            phys = int(value)
        except (TypeError, ValueError):
            continue
        parts.append((ig_idx, phys))
    if not parts:
        return None
    return ",".join(f"{ig_idx}:{phys}" for ig_idx, phys in sorted(parts))
def _select_order_target_order_csv(
    target_orders: list[tuple[int, int]] | None,
) -> str | None:
    if not target_orders:
        return None
    return ",".join(f"r{first}<r{second}" for first, second in target_orders)
def _select_order_unit_hint_from_source_path(source_path: str | None) -> str | None:
    if not source_path:
        return None
    path = Path(source_path)
    parts = path.parts
    if "src" not in parts or path.suffix != ".c":
        return None
    src_index = parts.index("src")
    rel_parts = parts[src_index + 1:]
    if not rel_parts:
        return None
    return str(Path(*rel_parts).with_suffix(""))
def _select_order_checkdiff_drift_summary(
    payload: Any,
) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    classification = payload.get("classification")
    classification = classification if isinstance(classification, Mapping) else {}
    artifact = classification.get("inline_boundary_artifact")
    target_asm = _select_order_payload_asm_lines(
        payload,
        "target_asm",
        fallback_key="reference_asm",
    )
    current_asm = _select_order_payload_asm_lines(payload, "current_asm")
    diff_hunk = _select_order_first_unified_diff_hunk(payload.get("diff"))
    opcode_hunk = _select_order_opcode_hunk_from_asm(target_asm, current_asm)
    if artifact is None and not diff_hunk and opcode_hunk.get("status") == "unavailable":
        return None
    summary: dict[str, Any] = {
        "opcode_hunk": opcode_hunk,
    }
    if isinstance(artifact, Mapping):
        summary["inline_boundary_artifact"] = dict(artifact)
    if diff_hunk:
        summary["diff_hunk"] = diff_hunk
    return summary
def _select_order_payload_asm_lines(
    payload: Mapping[str, Any],
    key: str,
    *,
    fallback_key: str | None = None,
) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) and fallback_key is not None:
        value = payload.get(fallback_key)
    if not isinstance(value, list):
        return []
    return [line for line in value if isinstance(line, str)]
def _select_order_first_unified_diff_hunk(value: Any, max_lines: int = 24) -> list[str]:
    if isinstance(value, list):
        lines = [str(line) for line in value]
    elif isinstance(value, str):
        lines = value.splitlines()
    else:
        return []
    start = next(
        (idx for idx, line in enumerate(lines) if line.startswith("@@")),
        0 if lines else None,
    )
    if start is None:
        return []
    out: list[str] = []
    for line in lines[start:]:
        if out and line.startswith("@@"):
            break
        out.append(line)
        if len(out) >= max_lines:
            break
    return out
def _select_order_opcode_hunk_from_asm(
    target_asm: list[str],
    current_asm: list[str],
    *,
    context: int = 2,
) -> dict[str, Any]:
    target_rows = _select_order_asm_signature_rows(target_asm)
    current_rows = _select_order_asm_signature_rows(current_asm)
    if not target_rows or not current_rows:
        return {"status": "unavailable", "reason": "asm lines unavailable"}
    target_signatures = [row["signature"] for row in target_rows]
    current_signatures = [row["signature"] for row in current_rows]
    matcher = difflib.SequenceMatcher(None, target_signatures, current_signatures)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        target_start = max(0, i1 - context)
        target_end = min(len(target_rows), i2 + context)
        current_start = max(0, j1 - context)
        current_end = min(len(current_rows), j2 + context)
        return {
            "status": "localized",
            "tag": tag,
            "target_range": [target_start, target_end],
            "current_range": [current_start, current_end],
            "target": target_rows[target_start:target_end],
            "current": current_rows[current_start:current_end],
        }
    return {"status": "matched", "reason": "opcode/call signatures match"}
def _select_order_asm_signature_rows(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_index, line in enumerate(lines):
        instr = _parse_checkdiff_asm_instruction(line)
        if instr is None:
            continue
        rows.append({
            "line_index": line_index,
            "raw": line,
            "opcode": instr.opcode,
            "signature": _select_order_asm_signature(instr),
        })
    return rows
def _select_order_asm_signature(instr: AsmInstruction) -> str:
    opcode = instr.opcode
    operands = instr.operands.split(";", 1)[0].strip()
    if opcode.startswith("b") and operands:
        return f"{opcode} {operands}"
    return opcode
def _select_order_inline_boundary_score_probe(
    *,
    function: str | None,
    source_path: str | None,
) -> dict[str, Any]:
    command_parts = ["melee-agent", "debug", "search", "structure"]
    if function:
        command_parts.extend(["-f", function])
    command_parts.extend(["--axis", "inline-boundary"])
    if source_path:
        command_parts.extend(["--source-file", source_path])
    command_parts.extend(["--max-candidates", "24", "--score", "--json"])
    return {
        "rank": 1,
        "kind": "score-retained-inline-boundary-source",
        "axis": "inline-boundary",
        "command": " ".join(shlex.quote(part) for part in command_parts),
    }
def _select_order_source_body_executable_spans(
    source_path: str | None,
    *,
    function: str | None,
    max_lines_per_span: int = 4,
) -> list[dict[str, Any]]:
    if not function or not source_path or not source_path.endswith(".c"):
        return []
    path = Path(source_path)
    try:
        source_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    span = find_source_function(source_text, function)
    if span is None:
        return []

    lines = source_text.splitlines()
    body_start_line = source_text[:span.body_open].count("\n") + 1
    body_end_line = source_text[:span.body_close].count("\n") + 1
    executable: list[dict[str, Any]] = []
    in_block_comment = False
    for line_no in range(body_start_line, min(body_end_line, len(lines)) + 1):
        raw_line = lines[line_no - 1]
        stripped = raw_line.strip()
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("/*") or stripped.startswith("*"):
            if "*/" not in stripped:
                in_block_comment = True
            continue
        code_line = _select_order_source_hunk_code_line(stripped)
        if not code_line or code_line in {"{", "}", "};"}:
            continue
        if code_line.startswith("//"):
            continue
        if _select_order_source_line_is_non_executable_declaration(code_line):
            continue
        executable.append({
            "line": line_no,
            "text": raw_line.strip(),
        })

    if not executable:
        return []
    spans = [{
        "kind": "first-executable-source-lines",
        "source": source_path,
        "lines": executable[:max_lines_per_span],
    }]
    tail = executable[-max_lines_per_span:]
    if tail[0]["line"] > spans[0]["lines"][-1]["line"]:
        spans.append({
            "kind": "last-executable-source-lines",
            "source": source_path,
            "lines": tail,
        })
    return spans
def _select_order_inline_boundary_drift_summary(
    candidate: Mapping[str, Any],
    *,
    function: str | None,
    force_phys: Mapping[int, int] | Mapping[str, int] | None = None,
    target_orders: list[tuple[int, int]] | None = None,
) -> dict[str, Any] | None:
    guard = candidate.get("guard")
    if not isinstance(guard, Mapping):
        return None
    reason_text = " ".join(
        str(value)
        for value in (
            guard.get("classification_primary"),
            guard.get("rejection_reason"),
            guard.get("reason"),
        )
        if value is not None
    ).lower()
    if "inline-boundary" not in reason_text:
        return None

    from src.cli.debug import _select_order_variant_source_hunk  # noqa: PLC0415
    source_path = candidate.get("source_retained") or candidate.get("path")
    source_path_text = str(source_path) if source_path is not None else None
    source_hunk = _select_order_variant_source_hunk(candidate, function=function)
    repair_routes = _select_order_inline_boundary_repair_routes(
        function=function,
        source_path=source_path_text,
        force_phys=force_phys,
        target_orders=target_orders,
    )
    executable_lines = _select_order_source_hunk_executable_lines(source_hunk)
    source_call_lines = _select_order_source_hunk_call_lines(source_hunk)
    nearest_spans: list[dict[str, Any]] = []
    terminal_blocker = None
    if source_hunk and not executable_lines:
        status = "unmapped"
        source_attribution_status = "unmapped"
        terminal_blocker = "source-hunk-no-executable-lines"
        nearest_spans = _select_order_source_body_executable_spans(
            source_path_text,
            function=function,
        )
        next_probe = _select_order_inline_boundary_score_probe(
            function=function,
            source_path=source_path_text,
        )
        hunk_status = "metrics-only"
    else:
        status = "localized" if source_hunk else "coarse"
        source_attribution_status = status
        next_probe = repair_routes[0]
        hunk_status = (
            "source-hunk-executable" if executable_lines else "metrics-only"
        )
    result = {
        "status": status,
        "source_attribution_status": source_attribution_status,
        "terminal_blocker": terminal_blocker,
        "candidate_label": candidate.get("label"),
        "chain": list(candidate.get("chain") or []),
        "classification_primary": guard.get("classification_primary"),
        "rejection_reason": guard.get("rejection_reason"),
        "normalized_diff_lines": guard.get("normalized_diff_lines"),
        "opcode_similarity": guard.get("opcode_similarity"),
        "line_delta": guard.get("line_delta"),
        "frame_delta": candidate.get("frame_delta"),
        "source_retained": source_path_text,
        "source_hunk": source_hunk,
        "executable_source_lines": executable_lines,
        "source_call_lines": source_call_lines,
        "nearest_executable_source_spans": nearest_spans,
        "opcode_drift": {
            "classification_primary": guard.get("classification_primary"),
            "normalized_diff_lines": guard.get("normalized_diff_lines"),
            "opcode_similarity": guard.get("opcode_similarity"),
            "line_delta": guard.get("line_delta"),
            "frame_delta": candidate.get("frame_delta"),
            "hunk_status": hunk_status,
        },
        "repair_routes": repair_routes,
        "next_probe": next_probe,
    }
    checkdiff_drift = candidate.get("checkdiff_drift")
    if isinstance(checkdiff_drift, Mapping):
        result["checkdiff_drift"] = dict(checkdiff_drift)
    return result
def _select_order_spill_delta(
    variant: Mapping[str, Any],
) -> dict[str, list[Any]]:
    delta = variant.get("delta")
    if not isinstance(delta, Mapping):
        delta = {}

    def list_value(key: str) -> list[Any]:
        value = delta.get(key)
        return list(value) if isinstance(value, list) else []

    return {
        "spill_unexpected": list_value("spill_unexpected"),
        "spill_missing": list_value("spill_missing"),
        "spill_added": list_value("spill_added"),
        "spill_removed": list_value("spill_removed"),
    }
def _select_order_saved_register_delta(
    variant: Mapping[str, Any],
) -> dict[str, list[str]]:
    delta = variant.get("delta")
    if not isinstance(delta, Mapping):
        delta = {}
    saved_added = [
        str(reg) for reg in delta.get("saved_added") or []
        if isinstance(reg, (str, int))
    ]
    saved_removed = [
        str(reg) for reg in delta.get("saved_removed") or []
        if isinstance(reg, (str, int))
    ]

    def fprs(regs: list[str]) -> list[str]:
        return [
            reg for reg in regs
            if reg.lower().startswith("f") and reg[1:].isdigit()
        ]

    return {
        "saved_added": saved_added,
        "saved_removed": saved_removed,
        "saved_fpr_added": fprs(saved_added),
        "saved_fpr_removed": fprs(saved_removed),
    }
def _select_order_guard_repair_result_summary(
    variant: Mapping[str, Any],
) -> dict[str, Any] | None:
    from src.cli.debug import _select_order_force_phys_hit_registers
    if variant.get("repair_seed_label") is None:
        return None

    def _with_protected_preservation(result: dict[str, Any]) -> dict[str, Any]:
        preservation = variant.get("protected_preservation")
        if not isinstance(preservation, Mapping):
            return result
        copied = dict(preservation)
        result["protected_preservation"] = copied
        for key in (
            "protected_register_count",
            "protected_preserved_count",
            "preserved_protected_registers",
            "lost_protected_registers",
        ):
            if key in copied:
                result[key] = copied[key]
        return result

    if variant.get("status") != "ok":
        return _with_protected_preservation({
            "label": variant.get("label"),
            "status": variant.get("status"),
            "repair_seed_label": variant.get("repair_seed_label"),
            "path": variant.get("path"),
            "source_retained": variant.get("source_retained"),
            "chain": list(variant.get("chain") or []),
            "error": variant.get("error"),
            "probe": variant.get("probe"),
            "source_hunk": variant.get("source_hunk"),
            "objective": variant.get("objective"),
            "spill_delta": _select_order_spill_delta(variant),
            "saved_register_delta": _select_order_saved_register_delta(variant),
        })
    objective = variant.get("objective")
    guard = variant.get("structural_guard")
    if not isinstance(objective, Mapping):
        return None
    frame_delta = objective.get("frame_delta")
    normalized_diff_lines = None
    if isinstance(guard, Mapping):
        normalized_diff_lines = guard.get("normalized_diff_lines")
        frame_delta = guard.get("frame_delta", frame_delta)
    return _with_protected_preservation({
        "label": variant.get("label"),
        "status": variant.get("status"),
        "repair_seed_label": variant.get("repair_seed_label"),
        "parent_label": variant.get("parent_label"),
        "rank": variant.get("rank"),
        "path": variant.get("path"),
        "source_retained": variant.get("source_retained"),
        "chain": list(variant.get("chain") or []),
        "match_percent": objective.get("match_percent"),
        "force_phys_satisfied_count": objective.get(
            "force_phys_satisfied_count"
        ),
        "force_phys_distance": objective.get("force_phys_distance"),
        "achieved_registers": _select_order_force_phys_hit_registers(variant),
        "missing_registers": _select_order_force_phys_missing_registers(objective),
        "mismatched_registers": (
            _select_order_force_phys_mismatched_registers(objective)
        ),
        "guard": dict(guard) if isinstance(guard, Mapping) else None,
        "guard_accepted": (
            guard.get("accepted") if isinstance(guard, Mapping) else None
        ),
        "normalized_diff_lines": normalized_diff_lines,
        "opcode_similarity": (
            guard.get("opcode_similarity") if isinstance(guard, Mapping) else None
        ),
        "frame_delta": frame_delta,
        "spill_delta": _select_order_spill_delta(variant),
        "saved_register_delta": _select_order_saved_register_delta(variant),
        "probe": variant.get("probe"),
        "source_hunk": variant.get("source_hunk"),
        "objective": dict(objective),
    })
def _select_order_guard_repair_candidate_sort_key(
    candidate: Mapping[str, Any],
) -> tuple[float, float, float]:
    count = _select_order_float_sort_value(
        candidate.get("force_phys_satisfied_count"),
        default=0.0,
    )
    distance = _select_order_float_sort_value(
        candidate.get("force_phys_distance"),
        default=1_000_000.0,
    )
    match_percent = _select_order_float_sort_value(
        candidate.get("match_percent"),
        default=-1.0,
    )
    return (-count, distance, -match_percent)
def _select_order_source_reference_score(candidate: Mapping[str, Any]) -> int:
    score = len(candidate.get("chain") or [])
    if isinstance(candidate.get("probe"), Mapping):
        score += 8
    if isinstance(candidate.get("source_provenance"), Mapping):
        score += 4
    if candidate.get("source_hunk") is not None:
        score += 1
    return score
def _select_order_complement_candidate_summary(
    candidate: Mapping[str, Any],
    *,
    protected_registers: Mapping[str, int],
) -> dict[str, Any]:
    achieved = candidate.get("achieved_registers")
    achieved = achieved if isinstance(achieved, Mapping) else {}
    preserved = {
        str(ig_idx): phys
        for ig_idx, phys in protected_registers.items()
        if achieved.get(str(ig_idx)) == phys
    }
    lost = {
        str(ig_idx): phys
        for ig_idx, phys in protected_registers.items()
        if achieved.get(str(ig_idx)) != phys
    }
    summary = {
        "label": candidate.get("label"),
        "repair_seed_label": candidate.get("repair_seed_label"),
        "parent_label": candidate.get("parent_label"),
        "source_retained": candidate.get("source_retained"),
        "chain": list(candidate.get("chain") or []),
        "guard_accepted": candidate.get("guard_accepted"),
        "match_percent": candidate.get("match_percent"),
        "force_phys_satisfied_count": candidate.get("force_phys_satisfied_count"),
        "force_phys_distance": candidate.get("force_phys_distance"),
        "normalized_diff_lines": candidate.get("normalized_diff_lines"),
        "opcode_similarity": candidate.get("opcode_similarity"),
        "frame_delta": candidate.get("frame_delta"),
        "achieved_registers": dict(achieved),
        "missing_registers": dict(candidate.get("missing_registers") or {}),
        "mismatched_registers": dict(candidate.get("mismatched_registers") or {}),
        "preserved_registers": preserved,
        "lost_protected_registers": lost,
        "preserved_protected_count": len(preserved),
        "protected_count": len(protected_registers),
        "spill_delta": dict(candidate.get("spill_delta") or {}),
        "saved_register_delta": dict(candidate.get("saved_register_delta") or {}),
    }
    if candidate.get("source_hunk") is not None:
        summary["source_hunk"] = candidate.get("source_hunk")
    if candidate.get("guard") is not None:
        summary["guard"] = candidate.get("guard")
    return summary
def _select_order_complement_candidate_target_status(
    candidate: Mapping[str, Any],
    *,
    complement_targets: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    achieved = dict(candidate.get("achieved_registers") or {})
    missing = dict(candidate.get("missing_registers") or {})
    mismatched = dict(candidate.get("mismatched_registers") or {})
    out: dict[str, dict[str, Any]] = {}
    for ig_idx, target in complement_targets.items():
        expected = target.get("expected")
        if achieved.get(ig_idx) == expected:
            out[ig_idx] = {
                "expected": expected,
                "actual": achieved.get(ig_idx),
                "status": "hit",
            }
        elif ig_idx in missing:
            out[ig_idx] = {
                "expected": expected,
                "actual": None,
                "status": "missing",
            }
        elif isinstance(mismatched.get(ig_idx), Mapping):
            out[ig_idx] = {
                "expected": expected,
                "actual": mismatched[ig_idx].get("actual"),
                "status": "mismatched",
            }
        else:
            out[ig_idx] = {
                "expected": expected,
                "actual": None,
                "status": "unhit",
            }
    return out
def _select_order_complement_source_provenance(
    candidate: Mapping[str, Any],
) -> dict[str, Any] | None:
    probe = candidate.get("probe")
    if not isinstance(probe, Mapping):
        return None
    provenance = probe.get("provenance")
    if not isinstance(provenance, Mapping):
        return None
    return dict(provenance)
_SELECT_ORDER_INTERFERENCE_INTENT_KINDS = frozenset({
    "remove-interference",
    "add-interference",
    "reduce-degree",
    "increase-degree",
})
def _select_order_candidate_probe_intents(
    candidate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    objective = candidate.get("objective")
    if not isinstance(objective, Mapping):
        return []
    target_orders = objective.get("target_orders")
    if not isinstance(target_orders, list):
        return []
    intents: list[dict[str, Any]] = []
    for pair in target_orders:
        if not isinstance(pair, Mapping):
            continue
        raw_intents = pair.get("probe_intents")
        if not isinstance(raw_intents, list):
            continue
        for intent in raw_intents:
            if not isinstance(intent, Mapping):
                continue
            kind = intent.get("kind")
            virtual = intent.get("virtual")
            if (
                kind not in _SELECT_ORDER_INTERFERENCE_INTENT_KINDS
                or isinstance(virtual, bool)
                or not isinstance(virtual, (int, str))
                or not str(virtual).lstrip("-").isdigit()
            ):
                continue
            normalized = dict(intent)
            normalized["kind"] = str(kind)
            normalized["virtual"] = int(virtual)
            interferer = normalized.get("interferer")
            if (
                not isinstance(interferer, bool)
                and isinstance(interferer, (int, str))
                and str(interferer).lstrip("-").isdigit()
            ):
                normalized["interferer"] = int(interferer)
            elif interferer is not None:
                normalized.pop("interferer", None)
            intents.append(normalized)
    return intents
def _select_order_source_attribution_for_target(
    *,
    target_ig: int,
    candidate: Mapping[str, Any],
    complement_source_diagnostics: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    diagnostic = complement_source_diagnostics.get(str(target_ig))
    if isinstance(diagnostic, Mapping):
        source = diagnostic.get("source_attribution")
        if isinstance(source, Mapping) and source:
            return dict(source)
    provenance = candidate.get("source_provenance")
    if not isinstance(provenance, Mapping):
        return None
    source = provenance.get("source_attribution")
    if isinstance(source, Mapping) and source:
        raw_ig = (
            source.get("target_ig")
            or source.get("ig_idx")
            or source.get("virtual")
        )
        if raw_ig is None or (
            not isinstance(raw_ig, bool)
            and isinstance(raw_ig, (int, str))
            and str(raw_ig).lstrip("-").isdigit()
            and int(raw_ig) == target_ig
        ):
            return dict(source)
    raw_components = provenance.get("source_components")
    if not isinstance(raw_components, list):
        return None
    for component in raw_components:
        if not isinstance(component, Mapping):
            continue
        expression_provenance = component.get("expression_provenance")
        if not isinstance(expression_provenance, Mapping):
            continue
        raw_ig = (
            expression_provenance.get("target_ig")
            or expression_provenance.get("ig_idx")
            or expression_provenance.get("virtual")
        )
        if (
            isinstance(raw_ig, bool)
            or not isinstance(raw_ig, (int, str))
            or not str(raw_ig).lstrip("-").isdigit()
            or int(raw_ig) != target_ig
        ):
            continue
        source = {
            key: value
            for key, value in expression_provenance.items()
            if key in {
                "kind",
                "name",
                "expression",
                "base_var",
                "source_file",
                "source_line",
                "source_col",
                "type",
                "source_type",
            }
            and value is not None
        }
        if source:
            return source
    return None
def _select_order_targeted_interference_transform_plan(
    *,
    function: str | None,
    class_id: int,
    candidate: Mapping[str, Any],
    protected_registers: Mapping[str, int],
    complement_targets: Mapping[str, Mapping[str, Any]],
    complement_source_diagnostics: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    intents = _select_order_candidate_probe_intents(candidate)
    if not intents:
        return None
    reg_prefix = "f" if class_id == 1 else "r"
    desired_by_virtual = {
        int(ig_idx): int(phys)
        for ig_idx, phys in protected_registers.items()
        if str(ig_idx).lstrip("-").isdigit()
    }
    for ig_idx, target in complement_targets.items():
        expected = target.get("expected") if isinstance(target, Mapping) else None
        if (
            str(ig_idx).lstrip("-").isdigit()
            and not isinstance(expected, bool)
            and isinstance(expected, (int, str))
            and str(expected).lstrip("-").isdigit()
        ):
            desired_by_virtual[int(ig_idx)] = int(expected)
    if not desired_by_virtual:
        return None

    achieved = candidate.get("achieved_registers")
    achieved = achieved if isinstance(achieved, Mapping) else {}
    mismatched = candidate.get("mismatched_registers")
    mismatched = mismatched if isinstance(mismatched, Mapping) else {}
    missing_virtuals: list[dict[str, Any]] = []
    seen_virtuals: set[int] = set()
    terminal_blockers: list[str] = []
    for intent in intents:
        virtual = int(intent["virtual"])
        if virtual not in desired_by_virtual or virtual in seen_virtuals:
            continue
        seen_virtuals.add(virtual)
        desired = desired_by_virtual[virtual]
        current = achieved.get(str(virtual))
        mismatch = mismatched.get(str(virtual))
        if current is None and isinstance(mismatch, Mapping):
            current = mismatch.get("actual")
        entry: dict[str, Any] = {
            "target_ig": virtual,
            "current_virtual": f"{reg_prefix}{virtual}",
            "desired_registers": [f"{reg_prefix}{desired}"],
            "interference_action": intent["kind"],
            "probe_intent": dict(intent),
            "missing_virtual": (
                "select-order probe intent asks for a source transform that "
                f"changes {reg_prefix}{virtual} interference while preserving "
                "the force-phys objective"
            ),
        }
        if (
            not isinstance(current, bool)
            and isinstance(current, (int, str))
            and str(current).lstrip("-").isdigit()
        ):
            entry["current_register"] = f"{reg_prefix}{int(current)}"
        interferer = intent.get("interferer")
        if isinstance(interferer, int):
            entry["interferer"] = interferer
            entry["conflicts"] = [{
                "kind": intent["kind"],
                "ig_idx": virtual,
                "interferer": interferer,
                "description": intent.get("description"),
            }]
        source = _select_order_source_attribution_for_target(
            target_ig=virtual,
            candidate=candidate,
            complement_source_diagnostics=complement_source_diagnostics,
        )
        if source is not None:
            entry["source"] = source
        else:
            terminal_blockers.append(f"source-attribution-missing-for-{reg_prefix}{virtual}")
        entry["source_action"] = intent.get("description") or (
            f"{intent['kind']} for {reg_prefix}{virtual}"
        )
        missing_virtuals.append(entry)

    if not missing_virtuals:
        return None
    node_set_delta = {
        "kind": "node-set-delta",
        "blocker": "select-order-targeted-interference",
        "function": function,
        "class_id": class_id,
        "register_prefix": reg_prefix,
        "source": "select-order-probe-intents",
        "missing_virtuals": missing_virtuals,
    }
    return {
        "status": "planned",
        "candidate_label": candidate.get("label"),
        "source_retained": candidate.get("source_retained"),
        "chain": list(candidate.get("chain") or []),
        "target_assignments": {
            "protected": dict(protected_registers),
            "lost_protected": dict(candidate.get("lost_protected_registers") or {}),
            "complement": {
                str(key): dict(value)
                for key, value in complement_targets.items()
                if isinstance(value, Mapping)
            },
        },
        "probe_intents": intents,
        "node_set_delta": node_set_delta,
        "terminal_blockers": sorted(set(terminal_blockers)),
    }
def _select_order_target_key(value: object) -> str | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, str))
        or not str(value).lstrip("-").isdigit()
    ):
        return None
    return str(int(value))
def _select_order_source_is_raw_pcode(source: Mapping[str, Any]) -> bool:
    kind = source.get("kind")
    if kind in {"implicit-temp", "fpr-temp"}:
        return True
    expression = source.get("expression")
    if not isinstance(expression, str):
        return False
    if source.get("confidence") == "pcode-first-def":
        return True
    return re.match(r"^[A-Za-z.]+\s+[rf]\d+(?:,|\s)", expression.strip()) is not None
def _select_order_causal_target_for_ig(
    causal_targets: Mapping[str, Mapping[str, Any]] | None,
    target_ig: object,
) -> Mapping[str, Any] | None:
    if not isinstance(causal_targets, Mapping):
        return None
    key = _select_order_target_key(target_ig)
    if key is None:
        return None
    target = causal_targets.get(key)
    return target if isinstance(target, Mapping) else None
def _select_order_owner_split_candidates(
    causal_target: Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    if not isinstance(causal_target, Mapping):
        return []
    candidates: list[Mapping[str, Any]] = []
    raw_probe = causal_target.get("synthetic_source_probe")
    if isinstance(raw_probe, Mapping):
        candidates.append(raw_probe)
    raw_candidates = causal_target.get("synthetic_source_candidates")
    if isinstance(raw_candidates, list):
        candidates.extend(
            item for item in raw_candidates if isinstance(item, Mapping)
        )
    causal_source = causal_target.get("causal_source")
    if isinstance(causal_source, Mapping):
        raw_probe = causal_source.get("synthetic_source_probe")
        if isinstance(raw_probe, Mapping):
            candidates.append(raw_probe)
    return candidates
def _select_order_owner_split_safe_source(
    causal_target: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(causal_target, Mapping):
        return None
    labels = causal_target.get("materialized_probe_labels")
    if causal_target.get("source_actionable") is not True or not labels:
        return None
    for candidate in _select_order_owner_split_candidates(causal_target):
        expression = None
        for key in (
            "safe_source_expression",
            "split_expression",
            "owner_expression",
            "owner_local",
        ):
            value = candidate.get(key)
            if (
                isinstance(value, str)
                and value.strip()
                and _select_order_expression_safe_to_bind(value)
            ):
                expression = value.strip()
                break
        if expression is None:
            value = candidate.get("expression")
            if (
                candidate.get("kind") == "synthetic-owner-split"
                and isinstance(value, str)
                and value.strip()
                and _select_order_expression_safe_to_bind(value)
            ):
                expression = value.strip()
        if expression is None or _select_order_expression_looks_pcode(expression):
            continue

        source_type = None
        for key in ("type", "source_type", "owner_type"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                source_type = value.strip()
                break
        if source_type is None:
            owner_source = candidate.get("operand_source_attribution")
            if isinstance(owner_source, Mapping):
                value = owner_source.get("type")
                if isinstance(value, str) and value.strip():
                    source_type = value.strip()
        if source_type is None:
            continue
        return {
            "kind": "synthetic-owner-split",
            "expression": expression,
            "type": source_type,
            "introduce_binding": True,
        }
    return None
def _select_order_expression_looks_pcode(expression: str) -> bool:
    text = expression.strip()
    return re.match(r"^[A-Za-z.]+\s+[rf]\d+(?:,|\s)", text) is not None
def _select_order_expression_safe_to_bind(expression: str) -> bool:
    from ...mwcc_debug.node_set_split import _source_expression_is_safe_to_bind

    return _source_expression_is_safe_to_bind(expression)
def _select_order_materialized_targeted_interference_delta(
    plan: Mapping[str, Any] | None,
    *,
    causal_targets: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(plan, Mapping):
        return None
    embedded = plan.get("materialized_node_set_delta")
    if isinstance(embedded, Mapping):
        return dict(embedded)
    node_set_delta = plan.get("node_set_delta")
    if not isinstance(node_set_delta, Mapping):
        return None
    entries = node_set_delta.get("missing_virtuals")
    if not isinstance(entries, list):
        return None
    materializable: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        source = entry.get("source")
        if not isinstance(source, Mapping):
            continue
        copied = dict(entry)
        source_copy = dict(source)
        if _select_order_source_is_raw_pcode(source_copy):
            causal_target = _select_order_causal_target_for_ig(
                causal_targets,
                entry.get("target_ig"),
            )
            safe_source = _select_order_owner_split_safe_source(causal_target)
            if safe_source is None:
                continue
            copied["source"] = safe_source
            copied["raw_source"] = source_copy
            copied["source_provenance"] = {
                "kind": "synthetic-owner-split-materialization",
                "raw_source": source_copy,
                "materialized_probe_labels": list(
                    causal_target.get("materialized_probe_labels") or []
                ) if isinstance(causal_target, Mapping) else [],
            }
        else:
            copied["source"] = source_copy
        materializable.append(copied)
    if not materializable:
        return None
    payload = dict(node_set_delta)
    payload["missing_virtuals"] = materializable
    payload["materialized_from"] = "select-order-targeted-interference"
    payload["source_plan_candidate_label"] = plan.get("candidate_label")
    return payload
def _select_order_mixed_source_repair_plan(
    plan: Mapping[str, Any] | None,
    *,
    causal_targets: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    entries: list[dict[str, Any]] = []
    blocked_reasons: set[str] = set()
    delta = _select_order_materialized_targeted_interference_delta(
        plan,
        causal_targets=causal_targets,
    )
    materialized_by_target: dict[str, Mapping[str, Any]] = {}
    if isinstance(delta, Mapping):
        for entry in delta.get("missing_virtuals") or []:
            if not isinstance(entry, Mapping):
                continue
            key = _select_order_target_key(entry.get("target_ig"))
            if key is not None:
                materialized_by_target[key] = entry

    node_set_delta = plan.get("node_set_delta") if isinstance(plan, Mapping) else None
    raw_entries = (
        node_set_delta.get("missing_virtuals")
        if isinstance(node_set_delta, Mapping) else None
    )
    saw_raw_pcode = False
    if isinstance(raw_entries, list):
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, Mapping):
                continue
            target_key = _select_order_target_key(raw_entry.get("target_ig"))
            target_ig = int(target_key) if target_key is not None else None
            source = raw_entry.get("source")
            source = source if isinstance(source, Mapping) else {}
            materialized = (
                materialized_by_target.get(target_key)
                if target_key is not None else None
            )
            entry_plan: dict[str, Any] = {
                "target_ig": target_ig,
                "desired_registers": list(raw_entry.get("desired_registers") or []),
                "status": "materialized" if materialized is not None else "blocked",
                "provenance": {},
            }
            if _select_order_source_is_raw_pcode(source):
                saw_raw_pcode = True
                entry_plan["provenance"]["raw_source"] = dict(source)
                if materialized is None:
                    entry_plan["blocker"] = "implicit-temp-not-materializable"
                    blocked_reasons.add("implicit-temp-not-materializable")
                else:
                    safe_source = materialized.get("source")
                    if isinstance(safe_source, Mapping):
                        entry_plan["safe_source_expression"] = (
                            safe_source.get("expression")
                        )
                        entry_plan["source_type"] = safe_source.get("type")
                        entry_plan["source_kind"] = safe_source.get("kind")
                    raw_source = materialized.get("raw_source")
                    if isinstance(raw_source, Mapping):
                        entry_plan["provenance"]["raw_source"] = dict(raw_source)
                    source_provenance = materialized.get("source_provenance")
                    if isinstance(source_provenance, Mapping):
                        entry_plan["provenance"].update(source_provenance)
            elif materialized is not None:
                entry_plan["source"] = dict(materialized.get("source") or {})
            else:
                entry_plan["blocker"] = "source-attribution-missing"
                blocked_reasons.add("source-attribution-missing")
            if not entry_plan["provenance"]:
                entry_plan.pop("provenance", None)
            entries.append(entry_plan)
    if not saw_raw_pcode:
        return None

    request_count = 0
    if delta is not None:
        try:
            from ...mwcc_debug.node_set_split import requests_from_node_set_delta

            request_count = len(requests_from_node_set_delta(
                delta,
                include_introducible=True,
                max_requests=0,
            ))
        except Exception:
            request_count = len(materialized_by_target)

    if delta is not None and request_count >= 2:
        status = "ready"
    else:
        status = "blocked"
        if delta is not None and request_count < 2:
            blocked_reasons.add("no-coupled-probes")
    payload: dict[str, Any] = {
        "status": status,
        "candidate_label": plan.get("candidate_label")
        if isinstance(plan, Mapping) else None,
        "entries": entries,
        "materialized_request_count": request_count,
        "blocked_reasons": sorted(blocked_reasons),
    }
    if delta is not None and request_count >= 2:
        payload["materialized_node_set_delta"] = delta
    return payload
def _select_order_protected_complement_candidate_summary(
    candidate: Mapping[str, Any],
    *,
    protected_registers: Mapping[str, int],
    complement_targets: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    summary = _select_order_complement_candidate_summary(
        candidate,
        protected_registers=protected_registers,
    )
    target_status = _select_order_complement_candidate_target_status(
        candidate,
        complement_targets=complement_targets,
    )
    complement_hit_count = sum(
        1 for status in target_status.values()
        if status.get("status") == "hit"
    )
    summary["complement_targets"] = target_status
    summary["complement_hit_count"] = complement_hit_count
    summary["complement_count"] = len(complement_targets)
    summary["protected_loss_count"] = len(summary["lost_protected_registers"])
    source_provenance = _select_order_complement_source_provenance(candidate)
    if source_provenance is not None:
        summary["source_provenance"] = source_provenance
    objective = candidate.get("objective")
    if isinstance(objective, Mapping):
        summary["objective"] = dict(objective)
    return summary
def _select_order_complement_preserving_sort_key(
    candidate: Mapping[str, Any],
) -> tuple[float, float, float, float]:
    return (
        _select_order_float_sort_value(
            candidate.get("preserved_protected_count"),
            default=0.0,
        ),
        1.0 if candidate.get("guard_accepted") is True else 0.0,
        -_select_order_float_sort_value(
            candidate.get("force_phys_distance"),
            default=1_000_000.0,
        ),
        _select_order_float_sort_value(candidate.get("match_percent"), default=-1.0),
    )
def _select_order_complement_structural_sort_key(
    candidate: Mapping[str, Any],
) -> tuple[float, float, float, float]:
    return (
        1.0 if candidate.get("guard_accepted") is True else 0.0,
        _select_order_float_sort_value(
            candidate.get("preserved_protected_count"),
            default=0.0,
        ),
        -_select_order_float_sort_value(
            candidate.get("normalized_diff_lines"),
            default=1_000_000.0,
        ),
        _select_order_float_sort_value(candidate.get("match_percent"), default=-1.0),
    )
def _select_order_protected_complement_sort_key(
    candidate: Mapping[str, Any],
) -> tuple[float, float, float, float, float]:
    return (
        _select_order_float_sort_value(
            candidate.get("complement_hit_count"),
            default=0.0,
        ),
        -_select_order_float_sort_value(
            candidate.get("protected_loss_count"),
            default=1_000_000.0,
        ),
        1.0 if candidate.get("guard_accepted") is True else 0.0,
        -abs(_select_order_float_sort_value(
            candidate.get("frame_delta"),
            default=1_000_000.0,
        )),
        _select_order_float_sort_value(candidate.get("match_percent"), default=-1.0),
    )
def _select_order_protected_complement_preserving_sort_key(
    candidate: Mapping[str, Any],
) -> tuple[float, float, float, float, float]:
    return (
        _select_order_float_sort_value(
            candidate.get("preserved_protected_count"),
            default=0.0,
        ),
        _select_order_float_sort_value(
            candidate.get("complement_hit_count"),
            default=0.0,
        ),
        1.0 if candidate.get("guard_accepted") is True else 0.0,
        -abs(_select_order_float_sort_value(
            candidate.get("frame_delta"),
            default=1_000_000.0,
        )),
        _select_order_float_sort_value(candidate.get("match_percent"), default=-1.0),
    )
def _select_order_lead_diagnostics_by_target(
    diagnostics: Mapping[str, Any] | None,
) -> dict[int, list[dict[str, Any]]]:
    if not isinstance(diagnostics, Mapping):
        return {}
    raw = diagnostics.get("lead_diagnostics")
    if not isinstance(raw, list):
        return {}
    out: dict[int, list[dict[str, Any]]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        target = item.get("target_ig")
        if not isinstance(target, (int, str)) or not str(target).lstrip("-").isdigit():
            continue
        out.setdefault(int(target), []).append(dict(item))
    return out
def _select_order_source_excerpt(
    *,
    source_file: object,
    source_line: object,
    context: int = 1,
) -> list[dict[str, Any]]:
    from src.cli.debug import DEFAULT_MELEE_ROOT
    if (
        not isinstance(source_file, str)
        or not source_file
        or isinstance(source_line, bool)
        or not isinstance(source_line, (int, str))
        or not str(source_line).lstrip("-").isdigit()
    ):
        return []
    line_no = int(source_line)
    if line_no <= 0:
        return []
    path = Path(source_file)
    if not path.is_absolute():
        repo_path = DEFAULT_MELEE_ROOT / path
        if repo_path.exists():
            path = repo_path
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    start = max(1, line_no - max(0, context))
    end = min(len(lines), line_no + max(0, context))
    return [
        {"line": idx, "text": lines[idx - 1]}
        for idx in range(start, end + 1)
    ]
def _select_order_complement_source_diagnostics(
    *,
    complement_targets: Mapping[str, Mapping[str, Any]],
    window_order_source_attributions: Mapping[int, Any] | Mapping[str, Any] | None,
    window_order_probe_diagnostics: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    from src.cli.debug import _solve_source_attribution_dict
    if not complement_targets:
        return {}
    lead_diagnostics = _select_order_lead_diagnostics_by_target(
        window_order_probe_diagnostics
    )
    diagnostics: dict[str, dict[str, Any]] = {}
    for key, target in complement_targets.items():
        if not str(key).lstrip("-").isdigit():
            continue
        target_ig = int(key)
        probe_diags = lead_diagnostics.get(target_ig, [])
        raw_source = None
        for probe_diag in probe_diags:
            raw_source = probe_diag.get("source_attribution")
            if raw_source is not None:
                break
        if raw_source is None:
            raw_source = _select_order_source_attr_for_ig(
                window_order_source_attributions or {},
                target_ig,
            )
        source = _solve_source_attribution_dict(raw_source)
        raw_source_for_first_def: Mapping[str, Any] | None = None
        if isinstance(raw_source, Mapping):
            raw_source_for_first_def = raw_source
        elif raw_source is not None:
            raw_source_for_first_def = {
                "first_def": getattr(raw_source, "first_def", None),
                "expression": getattr(raw_source, "expression", None),
                "confidence": getattr(raw_source, "confidence", None),
            }
        pcode_first_def = _select_order_pcode_first_def_payload(
            target_ig=target_ig,
            source=raw_source_for_first_def,
            probe_diag=None,
        )
        materialized_labels: list[str] = []
        terminal_blockers: set[str] = set()
        for probe_diag in probe_diags:
            raw_labels = probe_diag.get("materialized_probe_labels")
            if isinstance(raw_labels, list):
                materialized_labels.extend(
                    str(label)
                    for label in raw_labels
                    if isinstance(label, str) and label
                )
            raw_blocker = probe_diag.get("terminal_blocker")
            if isinstance(raw_blocker, str) and raw_blocker:
                terminal_blockers.add(raw_blocker)
        materialized_labels = sorted(set(materialized_labels))
        source_actionable = bool(
            any(
                probe_diag.get("status") == "materialized"
                for probe_diag in probe_diags
            )
            and materialized_labels
        )
        blocked_lead_terminal_blockers = sorted(terminal_blockers)
        target_is_hit = target.get("status") == "hit"
        if source_actionable or target_is_hit:
            terminal_blockers = set()
        elif not terminal_blockers and not source:
            terminal_blockers.add("source-attribution-missing")
        elif not terminal_blockers and not source_actionable:
            terminal_blockers.add("source-probe-not-materialized")
        terminal_blocker = sorted(terminal_blockers)[0] if terminal_blockers else None

        entry: dict[str, Any] = {
            "target_ig": target_ig,
            "target": dict(target),
            "source_actionable": source_actionable,
        }
        if source:
            entry["source_attribution"] = source
            excerpt = _select_order_source_excerpt(
                source_file=source.get("source_file"),
                source_line=source.get("source_line"),
            )
            if excerpt:
                entry["source_excerpt"] = excerpt
        if pcode_first_def is not None:
            entry["pcode_first_def"] = pcode_first_def
        if terminal_blocker:
            entry["terminal_blocker"] = terminal_blocker
        if terminal_blockers:
            entry["terminal_blockers"] = sorted(terminal_blockers)
        if source_actionable and blocked_lead_terminal_blockers:
            entry["blocked_lead_terminal_blockers"] = (
                blocked_lead_terminal_blockers
            )
        if materialized_labels:
            entry["materialized_probe_labels"] = materialized_labels
        if probe_diags:
            entry["lead_diagnostics"] = [dict(item) for item in probe_diags]
            primary_diag = next(
                (
                    probe_diag for probe_diag in probe_diags
                    if probe_diag.get("status") == "materialized"
                ),
                probe_diags[0],
            )
            entry["source_probe_diagnostic"] = dict(primary_diag)
        diagnostics[str(target_ig)] = entry
    return diagnostics
def _select_order_pcode_first_def_payload(
    *,
    target_ig: int,
    source: Mapping[str, Any] | None,
    probe_diag: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    raw_first_def: Any = None
    if isinstance(source, Mapping):
        raw_first_def = source.get("pcode_first_def") or source.get("first_def")
    if raw_first_def is None and isinstance(probe_diag, Mapping):
        raw_first_def = (
            probe_diag.get("pcode_first_def")
            or probe_diag.get("first_def")
        )
        if raw_first_def is None:
            synthetic_probe = probe_diag.get("synthetic_source_probe")
            if isinstance(synthetic_probe, Mapping):
                raw_first_def = synthetic_probe.get("first_def")
    payload: dict[str, Any] | None = None
    if isinstance(raw_first_def, Mapping):
        payload = {
            "target_ig": target_ig,
            "pass_name": raw_first_def.get("pass_name"),
            "block_idx": raw_first_def.get("block_idx", raw_first_def.get("block")),
            "instr_idx": raw_first_def.get("instr_idx"),
            "opcode": raw_first_def.get("opcode"),
            "operands": raw_first_def.get("operands"),
        }
    elif raw_first_def is not None and dataclasses.is_dataclass(raw_first_def):
        first_def_payload = dataclasses.asdict(raw_first_def)
        payload = {
            "target_ig": target_ig,
            "pass_name": first_def_payload.get("pass_name"),
            "block_idx": first_def_payload.get("block_idx"),
            "instr_idx": first_def_payload.get("instr_idx"),
            "opcode": first_def_payload.get("opcode"),
            "operands": first_def_payload.get("operands"),
        }
    elif raw_first_def is not None and any(
        hasattr(raw_first_def, field)
        for field in ("pass_name", "block_idx", "instr_idx", "opcode", "operands")
    ):
        payload = {
            "target_ig": target_ig,
            "pass_name": getattr(raw_first_def, "pass_name", None),
            "block_idx": getattr(raw_first_def, "block_idx", None),
            "instr_idx": getattr(raw_first_def, "instr_idx", None),
            "opcode": getattr(raw_first_def, "opcode", None),
            "operands": getattr(raw_first_def, "operands", None),
        }
    elif raw_first_def is not None:
        payload = {
            "target_ig": target_ig,
            "text": str(raw_first_def),
        }
    elif isinstance(source, Mapping):
        expression = source.get("expression")
        confidence = source.get("confidence")
        if isinstance(expression, str) and expression and confidence == "pcode-first-def":
            opcode, _, operands = expression.partition(" ")
            payload = {
                "target_ig": target_ig,
                "pass_name": None,
                "block_idx": None,
                "instr_idx": None,
                "opcode": opcode or None,
                "operands": operands or None,
            }
    if payload is None:
        return None
    if isinstance(source, Mapping):
        if source.get("expression") is not None:
            payload["expression"] = source.get("expression")
        if source.get("confidence") is not None:
            payload["confidence"] = source.get("confidence")
    return payload
def _select_order_source_span_payload(
    source: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(source, Mapping):
        return None
    source_file = source.get("source_file")
    source_line = source.get("source_line")
    if source_file is None and source_line is None:
        return None
    return {
        "source_file": source_file,
        "source_line": source_line,
        "source_col": source.get("source_col"),
    }
def _select_order_causal_target_plans(
    complement_source_diagnostics: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}
    for key, diagnostic in complement_source_diagnostics.items():
        if not isinstance(diagnostic, Mapping):
            continue
        target = diagnostic.get("target")
        target = target if isinstance(target, Mapping) else {}
        raw_source = diagnostic.get("source_attribution")
        source = raw_source if isinstance(raw_source, Mapping) else None
        raw_probe_diag = diagnostic.get("source_probe_diagnostic")
        probe_diag = raw_probe_diag if isinstance(raw_probe_diag, Mapping) else None
        pcode_first_def = diagnostic.get("pcode_first_def")
        if not isinstance(pcode_first_def, Mapping):
            pcode_first_def = _select_order_pcode_first_def_payload(
                target_ig=int(diagnostic.get("target_ig") or key),
                source=source,
                probe_diag=probe_diag,
            )
        plan: dict[str, Any] = {
            "target_ig": diagnostic.get("target_ig"),
            "expected_phys": target.get("expected"),
            "actual_phys": target.get("actual"),
            "status": target.get("status"),
            "source_actionable": diagnostic.get("source_actionable") is True,
            "materialized_probe_labels": list(
                diagnostic.get("materialized_probe_labels") or []
            ),
        }
        if source is not None:
            plan["source_attribution"] = dict(source)
        source_span = _select_order_source_span_payload(source)
        if source_span is not None:
            plan["source_span"] = source_span
        if diagnostic.get("source_excerpt"):
            plan["source_excerpt"] = list(diagnostic.get("source_excerpt") or [])
        if pcode_first_def is not None:
            plan["pcode_first_def"] = pcode_first_def
        else:
            plan["first_def_missing_reason"] = (
                diagnostic.get("terminal_blocker")
                or "pcode-first-def-unavailable"
            )
        if isinstance(probe_diag, Mapping):
            synthetic_probe = probe_diag.get("synthetic_source_probe")
            if isinstance(synthetic_probe, Mapping):
                plan["synthetic_source_probe"] = dict(synthetic_probe)
            synthetic_candidates = probe_diag.get("synthetic_source_candidates")
            if isinstance(synthetic_candidates, list):
                plan["synthetic_source_candidates"] = [
                    dict(item)
                    for item in synthetic_candidates
                    if isinstance(item, Mapping)
                ]
            plan["source_probe_diagnostic"] = dict(probe_diag)
        if diagnostic.get("terminal_blocker") is not None:
            plan["terminal_blocker"] = diagnostic.get("terminal_blocker")
        if diagnostic.get("terminal_blockers") is not None:
            plan["terminal_blockers"] = list(
                diagnostic.get("terminal_blockers") or []
            )
        causal_source: dict[str, Any] = {}
        if source is not None:
            causal_source["source_attribution"] = dict(source)
        if pcode_first_def is not None:
            causal_source["pcode_first_def"] = pcode_first_def
        if "first_def_missing_reason" in plan:
            causal_source["first_def_missing_reason"] = plan[
                "first_def_missing_reason"
            ]
        if "source_span" in plan:
            causal_source["source_span"] = plan["source_span"]
        if "synthetic_source_probe" in plan:
            causal_source["synthetic_source_probe"] = plan[
                "synthetic_source_probe"
            ]
        if causal_source:
            plan["causal_source"] = causal_source
        plans[str(key)] = plan
    return plans
def _select_order_source_hunks_from_provenance(
    provenance: Mapping[str, Any] | None,
    *,
    fallback_source_hunk: Any = None,
) -> list[dict[str, Any]]:
    hunks: list[dict[str, Any]] = []
    if isinstance(provenance, Mapping):
        if provenance.get("candidate_hunk") is not None:
            hunks.append({
                "role": "candidate",
                "repair_action": provenance.get("repair_action"),
                "base_hunk": provenance.get("base_hunk"),
                "candidate_hunk": provenance.get("candidate_hunk"),
                "source_label": provenance.get("source_label"),
            })
        for role_key in ("recipient_hunks", "donor_hunks"):
            raw_hunks = provenance.get(role_key)
            if not isinstance(raw_hunks, list):
                continue
            role = role_key.removesuffix("_hunks")
            for raw_hunk in raw_hunks:
                if not isinstance(raw_hunk, Mapping):
                    continue
                hunks.append({
                    "role": role,
                    "repair_action": provenance.get("repair_action"),
                    "base_line_range": raw_hunk.get("base_line_range"),
                    "candidate_line_range": raw_hunk.get("candidate_line_range"),
                    "base_hunk": raw_hunk.get("base_hunk"),
                    "candidate_hunk": raw_hunk.get("candidate_hunk"),
                    "diff_tag": raw_hunk.get("diff_tag"),
                    "hunk_index": raw_hunk.get("hunk_index"),
                })
        raw_components = provenance.get("source_components")
        if isinstance(raw_components, list):
            for raw_component in raw_components:
                if not isinstance(raw_component, Mapping):
                    continue
                hunks.append({
                    "role": "component",
                    "source_label": raw_component.get("source_label"),
                    "component_kind": raw_component.get("component_kind"),
                    "base_line_range": raw_component.get("base_line_range"),
                    "candidate_line_range": raw_component.get("candidate_line_range"),
                    "base_hunk": raw_component.get("base_hunk"),
                    "candidate_hunk": raw_component.get("candidate_hunk"),
                    "expression_provenance": raw_component.get(
                        "expression_provenance"
                    ),
                })
    if not hunks and fallback_source_hunk is not None:
        hunks.append({
            "role": "candidate",
            "candidate_hunk": fallback_source_hunk,
        })
    return hunks
def _select_order_source_composition_payload(
    candidate: Mapping[str, Any],
) -> dict[str, Any] | None:
    provenance = candidate.get("source_provenance")
    if not isinstance(provenance, Mapping):
        provenance = None
    source_hunks = _select_order_source_hunks_from_provenance(
        provenance,
        fallback_source_hunk=candidate.get("source_hunk"),
    )
    if provenance is None and not source_hunks:
        return None
    source_components = []
    if provenance is not None and isinstance(provenance.get("source_components"), list):
        source_components = [
            dict(item) for item in provenance.get("source_components") or []
            if isinstance(item, Mapping)
        ]
    payload: dict[str, Any] = {
        "kind": (
            provenance.get("kind") if provenance is not None else "source-hunk"
        ),
        "repair_action": (
            provenance.get("repair_action") if provenance is not None else None
        ),
        "component_depth": (
            provenance.get("component_depth") if provenance is not None else None
        ),
        "source_components": source_components,
        "source_hunks": source_hunks,
    }
    if provenance is not None:
        for key in (
            "recipient_label",
            "donor_label",
            "component_labels",
            "protected_force_phys_hits",
        ):
            if key in provenance:
                payload[key] = provenance.get(key)
    return payload
def _select_order_composition_candidate_payload(
    candidate: Mapping[str, Any],
    *,
    protected_registers: Mapping[str, int],
) -> dict[str, Any]:
    source_composition = _select_order_source_composition_payload(candidate)
    complement_targets = dict(candidate.get("complement_targets") or {})
    lost_protected = dict(candidate.get("lost_protected_registers") or {})
    preserved = dict(candidate.get("preserved_registers") or {})
    if int(candidate.get("complement_hit_count") or 0) > 0 and lost_protected:
        selection_reason = "complement-hit candidate lost protected force-phys hits"
    elif int(candidate.get("preserved_protected_count") or 0) == len(
        protected_registers
    ):
        selection_reason = "candidate preserved protected force-phys hits"
    else:
        selection_reason = "candidate scored for protected/complement composition"
    payload: dict[str, Any] = {
        "candidate_label": candidate.get("label"),
        "label": candidate.get("label"),
        "rank": candidate.get("rank"),
        "path": candidate.get("path"),
        "source_retained": candidate.get("source_retained"),
        "chain": list(candidate.get("chain") or []),
        "status": candidate.get("status"),
        "guard_accepted": candidate.get("guard_accepted"),
        "match_percent": candidate.get("match_percent"),
        "protected_registers": dict(protected_registers),
        "target_assignments": {
            "protected": dict(protected_registers),
            "preserved": preserved,
            "lost_protected": lost_protected,
            "complement": complement_targets,
        },
        "preserved_registers": preserved,
        "lost_protected_registers": lost_protected,
        "complement_targets": complement_targets,
        "complement_hit_count": candidate.get("complement_hit_count"),
        "normalized_diff_lines": candidate.get("normalized_diff_lines"),
        "opcode_similarity": candidate.get("opcode_similarity"),
        "frame_delta": candidate.get("frame_delta"),
        "spill_delta": dict(candidate.get("spill_delta") or {}),
        "saved_register_delta": dict(candidate.get("saved_register_delta") or {}),
        "selection_reason": selection_reason,
    }
    if candidate.get("error") is not None:
        payload["error"] = candidate.get("error")
    source_hunks = (
        source_composition.get("source_hunks")
        if isinstance(source_composition, Mapping) else None
    )
    if source_composition is not None:
        payload["source_composition"] = source_composition
    if source_hunks:
        payload["source_hunks"] = list(source_hunks)
    return payload
def _select_order_composition_coverage(
    candidates: list[Mapping[str, Any]],
    *,
    guard_repair_ledger: object | None = None,
) -> dict[str, Any]:
    ledger = _select_order_guard_repair_ledger_mapping(guard_repair_ledger)
    entries = ledger.get("entries") if isinstance(ledger, Mapping) else None
    deduped = ledger.get("deduped") if isinstance(ledger, Mapping) else None
    stop_condition = ledger.get("stop_condition") if isinstance(ledger, Mapping) else None
    timed_out = bool(ledger.get("timed_out")) if isinstance(ledger, Mapping) else False
    max_probes = ledger.get("max_probes") if isinstance(ledger, Mapping) else None
    if not isinstance(max_probes, int):
        max_probes = (
            ledger.get("max_probes_per_generation")
            if isinstance(ledger, Mapping) else None
        )
    if not isinstance(max_probes, int):
        max_probes = None
    bounded_by: dict[str, int] = {}
    if isinstance(ledger, Mapping):
        for key in ("effective_depth", "width"):
            value = ledger.get(key)
            if isinstance(value, int):
                bounded_by[key] = value
    if max_probes is not None:
        bounded_by["max_probes"] = max_probes
    if stop_condition == "timeout":
        timed_out = True
    failed_candidates = [
        candidate for candidate in candidates
        if candidate.get("status") not in (None, "ok")
    ]
    if timed_out:
        coverage_status = "timed-out"
    elif stop_condition == "depth-exhausted":
        coverage_status = "bounded-depth-exhausted"
    elif stop_condition == "frontier-empty":
        coverage_status = "frontier-empty"
    elif stop_condition == "no-repair-probes":
        coverage_status = "no-probes"
    elif stop_condition:
        coverage_status = str(stop_condition)
    else:
        coverage_status = "summary-candidates-only"
    generated_candidates = (
        len(entries) if isinstance(entries, list) else len(candidates)
    )
    if max_probes is None:
        truncated_by_max_probes = False
    else:
        truncated_by_max_probes = (
            str(stop_condition).startswith("max-probes")
            or (
                generated_candidates >= max_probes
                and stop_condition != "no-repair-probes"
            )
        )
    payload = {
        "coverage_status": coverage_status,
        "generated_candidates": generated_candidates,
        "scored_candidates": len(candidates),
        "failed_candidates": len(failed_candidates),
        "build_failed_candidates": sum(
            1 for candidate in failed_candidates
            if "build" in str(candidate.get("error") or "").lower()
            or "compile" in str(candidate.get("error") or "").lower()
        ),
        "deduped_candidates": len(deduped) if isinstance(deduped, list) else 0,
        "truncated_by_max_probes": truncated_by_max_probes,
        "timed_out": timed_out,
        "stop_condition": stop_condition,
    }
    if bounded_by:
        payload["bounded_by"] = bounded_by
    return payload
def _select_order_guard_repair_ledger_mapping(
    guard_repair_ledger: object | None,
) -> Mapping[str, Any] | None:
    if isinstance(guard_repair_ledger, Mapping):
        return guard_repair_ledger
    if guard_repair_ledger is None:
        return None
    try:
        path = Path(guard_repair_ledger)
        if path.is_file():
            payload = json.loads(path.read_text())
            if isinstance(payload, Mapping):
                return payload
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return None
def _select_order_strings_in(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        strings: set[str] = set()
        for item in value.values():
            strings.update(_select_order_strings_in(item))
        return strings
    if isinstance(value, (list, tuple, set)):
        strings: set[str] = set()
        for item in value:
            strings.update(_select_order_strings_in(item))
        return strings
    return set()
def _select_order_structural_ndiff(candidate: Mapping[str, Any]) -> int | None:
    value = candidate.get("normalized_diff_lines")
    if value is None:
        guard = candidate.get("guard")
        if isinstance(guard, Mapping):
            value = guard.get("normalized_diff_lines")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return None
def _select_order_structural_plateau_sort_key(
    candidate: Mapping[str, Any],
) -> tuple[float, float, float, float, float, str]:
    ndiff = _select_order_structural_ndiff(candidate)
    return (
        float(ndiff) if ndiff is not None else 1_000_000.0,
        abs(_select_order_float_sort_value(
            candidate.get("frame_delta"),
            default=1_000_000.0,
        )),
        _select_order_float_sort_value(
            candidate.get("force_phys_distance"),
            default=1_000_000.0,
        ),
        -_select_order_float_sort_value(
            candidate.get("opcode_similarity"),
            default=-1.0,
        ),
        -_select_order_float_sort_value(
            candidate.get("force_phys_satisfied_count"),
            default=0.0,
        ),
        str(candidate.get("label") or ""),
    )
def _select_order_candidate_hits_force_phys(
    candidate: Mapping[str, Any],
    force_phys: Mapping[int, int],
) -> bool:
    targets = _select_order_int_mapping(force_phys)
    hits = candidate.get("achieved_registers")
    if not isinstance(hits, Mapping) or not targets:
        return False
    for ig_idx, expected in targets.items():
        actual = hits.get(str(ig_idx), hits.get(ig_idx))
        if actual != expected:
            return False
    return True
def _select_order_repair_preserves_force_phys(
    candidate: Mapping[str, Any],
    force_phys: Mapping[int, int],
) -> bool:
    targets = _select_order_int_mapping(force_phys)
    lost = candidate.get("lost_protected_registers")
    if not isinstance(lost, Mapping) or lost:
        return False
    protected_count = candidate.get("protected_register_count")
    preserved_count = candidate.get("protected_preserved_count")
    if not isinstance(protected_count, int) or not isinstance(preserved_count, int):
        return False
    if protected_count != preserved_count or protected_count != len(targets):
        return False
    preserved = candidate.get("preserved_protected_registers")
    if not isinstance(preserved, Mapping):
        return False
    for ig_idx, expected in targets.items():
        if preserved.get(str(ig_idx), preserved.get(ig_idx)) != expected:
            return False
    return _select_order_candidate_hits_force_phys(candidate, targets)
def _select_order_structural_plateau_attempt(
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "label": candidate.get("label"),
        "repair_seed_label": candidate.get("repair_seed_label"),
        "status": candidate.get("status"),
        "chain": list(candidate.get("chain") or []),
        "source_retained": candidate.get("source_retained"),
        "guard_accepted": candidate.get("guard_accepted"),
        "normalized_diff_lines": _select_order_structural_ndiff(candidate),
        "opcode_similarity": candidate.get("opcode_similarity"),
        "frame_delta": candidate.get("frame_delta"),
        "force_phys_distance": candidate.get("force_phys_distance"),
        "force_phys_satisfied_count": candidate.get(
            "force_phys_satisfied_count"
        ),
        "protected_preserved_count": candidate.get(
            "protected_preserved_count"
        ),
        "protected_register_count": candidate.get("protected_register_count"),
        "lost_protected_registers": dict(
            candidate.get("lost_protected_registers") or {}
        ),
    }
    if candidate.get("source_hunk") is not None:
        payload["source_hunk"] = candidate.get("source_hunk")
    return payload
def _select_order_structural_plateau_source_components(
    seed: Mapping[str, Any],
    candidates: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    evidence_items: list[dict[str, Any]] = []
    for item in [seed, *candidates]:
        for text in _select_order_strings_in({
            "label": item.get("label"),
            "chain": item.get("chain"),
            "source_retained": item.get("source_retained"),
            "source_hunk": item.get("source_hunk"),
            "probe": item.get("probe"),
            "source_composition": item.get("source_composition"),
        }):
            evidence_items.append({
                "text": text,
                "label": item.get("label"),
                "source_retained": item.get("source_retained"),
                "chain": list(item.get("chain") or []),
            })

    def evidence_for(
        *needles: str,
        all_terms: bool = False,
    ) -> dict[str, Any] | None:
        lowered_needles = [needle.lower() for needle in needles]
        for item in sorted(evidence_items, key=lambda value: len(value["text"])):
            text = item["text"]
            lower = text.lower()
            if (
                all(needle in lower for needle in lowered_needles)
                if all_terms
                else any(needle in lower for needle in lowered_needles)
            ):
                return {
                    "label": item.get("label"),
                    "source_retained": item.get("source_retained"),
                    "chain": item.get("chain"),
                    "text": text[:240],
                }
        return None

    component_specs = [
        (
            "pointer-walk-store",
            evidence_for("ll_probe_iter", "dst_iter", "pointer-walk"),
        ),
        (
            "condition-temp-owner-split",
            evidence_for("condition_temp", "condition-owner", "condition", "temp"),
        ),
        (
            "indexed-byte-address-temp-steering",
            evidence_for("indexed_byte_address_temp_steering", "indexed-byte"),
        ),
        ("loop-index-declaration", evidence_for("s32 i", "int i")),
        ("max-index-declaration-placement", evidence_for("max_idx")),
        (
            "direct-global-dst",
            evidence_for("mndiagram_804a076c", "sorted_names", "direct-global"),
        ),
    ]
    components: list[dict[str, Any]] = []
    seen: set[str] = set()
    for component, evidence in component_specs:
        if evidence is None or component in seen:
            continue
        seen.add(component)
        components.append({
            "component": component,
            "kind": "source-hunk-pattern",
            "candidate_label": evidence.get("label"),
            "source_retained": evidence.get("source_retained"),
            "chain": evidence.get("chain"),
            "evidence": evidence.get("text"),
        })
    return components
def _select_order_protected_structural_plateau_summary(
    seed_candidates: list[dict[str, Any]],
    repair_candidates: list[dict[str, Any]],
    *,
    force_phys: Mapping[int, int],
    guard_repair_ledger: object | None = None,
) -> dict[str, Any] | None:
    targets = _select_order_int_mapping(force_phys)
    if not targets or not repair_candidates:
        return None

    coverage = _select_order_composition_coverage(
        repair_candidates,
        guard_repair_ledger=guard_repair_ledger,
    )
    terminal_coverage_statuses = {
        "bounded-depth-exhausted",
        "frontier-empty",
        "no-probes",
    }
    if (
        coverage.get("timed_out") is True
        or coverage.get("coverage_status") not in terminal_coverage_statuses
    ):
        return None

    groups: list[dict[str, Any]] = []
    for seed in seed_candidates:
        seed_label = seed.get("label")
        if seed_label is None:
            continue
        if not _select_order_candidate_hits_force_phys(seed, targets):
            continue
        seed_ndiff = _select_order_structural_ndiff(seed)
        if seed_ndiff is None:
            continue
        seed_repairs = [
            candidate for candidate in repair_candidates
            if candidate.get("repair_seed_label") == seed_label
        ]
        if not seed_repairs:
            continue
        preserving = [
            candidate for candidate in seed_repairs
            if _select_order_repair_preserves_force_phys(candidate, targets)
        ]
        preserving_with_ndiff = [
            candidate for candidate in preserving
            if _select_order_structural_ndiff(candidate) is not None
        ]
        if not preserving_with_ndiff:
            continue
        best_preserving = sorted(
            preserving_with_ndiff,
            key=_select_order_structural_plateau_sort_key,
        )[0]
        best_preserving_ndiff = _select_order_structural_ndiff(best_preserving)
        if best_preserving_ndiff is not None and best_preserving_ndiff < seed_ndiff:
            continue
        discarded_improvements = [
            candidate for candidate in seed_repairs
            if not _select_order_repair_preserves_force_phys(candidate, targets)
            and (
                (candidate_ndiff := _select_order_structural_ndiff(candidate))
                is not None
            )
            and candidate_ndiff < seed_ndiff
        ]
        attempted = sorted(
            seed_repairs,
            key=_select_order_structural_plateau_sort_key,
        )
        blockers = ["preserving-repair-did-not-improve-structural-drift"]
        if discarded_improvements:
            blockers.append("lower-ndiff-candidates-lost-protected-registers")
        if coverage.get("coverage_status") in terminal_coverage_statuses:
            blockers.append(str(coverage["coverage_status"]))
        groups.append({
            "seed_label": seed_label,
            "status": "terminal-plateau",
            "reason": (
                "bounded guard repair preserved all protected force-phys hits, "
                "but did not reduce structural drift below the seed"
            ),
            "terminal_blocker": "protected-structural-plateau",
            "terminal_blockers": blockers,
            "protected_registers": {
                str(ig_idx): phys for ig_idx, phys in sorted(targets.items())
            },
            "required_force_phys": {
                str(ig_idx): phys for ig_idx, phys in sorted(targets.items())
            },
            "seed_candidate": _select_order_structural_plateau_attempt(seed),
            "seed_normalized_diff_lines": seed_ndiff,
            "required_normalized_diff_lines_below": seed_ndiff,
            "best_preserving_candidate": (
                _select_order_structural_plateau_attempt(best_preserving)
            ),
            "discarded_non_preserving_improvements": [
                _select_order_structural_plateau_attempt(candidate)
                for candidate in sorted(
                    discarded_improvements,
                    key=_select_order_structural_plateau_sort_key,
                )[:4]
            ],
            "attempted_replacements": [
                _select_order_structural_plateau_attempt(candidate)
                for candidate in attempted[:8]
            ],
            "source_components": (
                _select_order_structural_plateau_source_components(
                    seed,
                    seed_repairs,
                )
            ),
            "coverage": coverage,
        })
    if not groups:
        return None
    primary = sorted(
        groups,
        key=lambda group: (
            int(group.get("seed_normalized_diff_lines") or 1_000_000),
            str(group.get("seed_label") or ""),
        ),
    )[0]
    return {
        "status": primary["status"],
        "reason": primary["reason"],
        "terminal_blocker": primary["terminal_blocker"],
        "terminal_blockers": primary["terminal_blockers"],
        "seed_label": primary["seed_label"],
        "required_force_phys": primary["required_force_phys"],
        "protected_registers": primary["protected_registers"],
        "seed_candidate": primary["seed_candidate"],
        "seed_normalized_diff_lines": primary["seed_normalized_diff_lines"],
        "required_normalized_diff_lines_below": primary[
            "required_normalized_diff_lines_below"
        ],
        "best_preserving_candidate": primary["best_preserving_candidate"],
        "discarded_non_preserving_improvements": primary[
            "discarded_non_preserving_improvements"
        ],
        "attempted_replacements": primary["attempted_replacements"],
        "source_components": primary["source_components"],
        "coverage": primary["coverage"],
        "groups": groups,
    }
def _select_order_causal_lane_coverage(
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    coverage_status = str(coverage.get("coverage_status") or "")
    incomplete_statuses = {
        "timed-out",
        "frontier-empty",
        "bounded-depth-exhausted",
    }
    complete = (
        coverage_status not in incomplete_statuses
        and coverage.get("truncated_by_max_probes") is not True
    )
    payload = {
        "complete": complete,
        "coverage_status": coverage.get("coverage_status"),
        "timed_out": coverage.get("timed_out"),
        "stop_condition": coverage.get("stop_condition"),
        "truncated_by_max_probes": coverage.get("truncated_by_max_probes"),
    }
    if not complete:
        payload["incomplete_reason"] = (
            coverage_status
            if coverage_status in incomplete_statuses
            else "max-probes-truncated"
        )
    if coverage.get("bounded_by") is not None:
        payload["bounded_by"] = dict(coverage.get("bounded_by") or {})
    return payload
def _select_order_validated_materialized_delta(
    delta: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(delta, Mapping):
        return None
    missing = delta.get("missing_virtuals")
    if not isinstance(missing, list):
        return None
    expected_targets = [
        int(entry["target_ig"])
        for entry in missing
        if isinstance(entry, Mapping)
        and not isinstance(entry.get("target_ig"), bool)
        and str(entry.get("target_ig", "")).lstrip("-").isdigit()
    ]
    if not expected_targets:
        return None
    try:
        from ...mwcc_debug.node_set_split import requests_from_node_set_delta

        requests = requests_from_node_set_delta(
            dict(delta),
            include_introducible=True,
            max_requests=0,
        )
    except Exception:
        return None
    request_targets = [int(request.target_ig) for request in requests]
    if any(target not in request_targets for target in expected_targets):
        return None
    payload = dict(delta)
    payload["materialized_request_count"] = len(requests)
    payload["materialized_request_targets"] = request_targets
    return payload
def _select_order_entry_target_ig(entry: Mapping[str, Any]) -> int | None:
    target_ig = entry.get("target_ig")
    if (
        isinstance(target_ig, bool)
        or not isinstance(target_ig, (int, str))
        or not str(target_ig).lstrip("-").isdigit()
    ):
        return None
    return int(target_ig)
def _select_order_filter_materialized_delta_for_targets(
    delta: Mapping[str, Any],
    *,
    requested: set[int],
    causal_targets: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    missing = delta.get("missing_virtuals")
    if not isinstance(missing, list):
        return None
    causal_igs = {
        int(key)
        for key in causal_targets
        if str(key).lstrip("-").isdigit()
    }
    entries: list[dict[str, Any]] = []
    retained_requested: set[int] = set()
    for entry in missing:
        if not isinstance(entry, Mapping):
            continue
        target_ig = _select_order_entry_target_ig(entry)
        if target_ig is None:
            continue
        if target_ig not in requested and target_ig in causal_igs:
            continue
        copied = dict(entry)
        source = copied.get("source")
        if isinstance(source, Mapping):
            copied["source"] = dict(source)
        entries.append(copied)
        if target_ig in requested:
            retained_requested.add(target_ig)
    if requested - retained_requested:
        return None
    payload = dict(delta)
    payload["missing_virtuals"] = entries
    return payload
def _select_order_causal_delta_entry(
    target: Mapping[str, Any],
    *,
    target_ig: int,
    reg_prefix: str,
) -> dict[str, Any] | None:
    expected = target.get("expected_phys")
    if (
        isinstance(expected, bool)
        or not isinstance(expected, (int, str))
        or not str(expected).lstrip("-").isdigit()
    ):
        return None
    safe_source = _select_order_owner_split_safe_source(target)
    if safe_source is None:
        return None
    entry: dict[str, Any] = {
        "target_ig": target_ig,
        "current_virtual": f"{reg_prefix}{target_ig}",
        "desired_registers": [f"{reg_prefix}{int(expected)}"],
        "interference_action": "materialize-causal-owner-split",
        "source": safe_source,
        "source_action": (
            f"materialize owner-split source for {reg_prefix}{target_ig}"
        ),
        "probe_intent": {
            "kind": "materialize-causal-owner-split",
            "virtual": target_ig,
            "materialized_probe_labels": list(
                target.get("materialized_probe_labels") or []
            ),
        },
    }
    actual = target.get("actual_phys")
    if (
        not isinstance(actual, bool)
        and isinstance(actual, (int, str))
        and str(actual).lstrip("-").isdigit()
    ):
        entry["current_register"] = f"{reg_prefix}{int(actual)}"
    raw_source = target.get("source_attribution")
    if isinstance(raw_source, Mapping):
        entry["raw_source"] = dict(raw_source)
    return entry
def _select_order_materialized_causal_delta(
    *,
    function: str | None,
    class_id: int,
    causal_targets: Mapping[str, Mapping[str, Any]],
    target_igs: Iterable[int],
    targeted_interference: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    requested = {
        int(target)
        for target in target_igs
        if not isinstance(target, bool)
    }
    if not requested:
        return None
    if targeted_interference is not None:
        targeted_delta = _select_order_materialized_targeted_interference_delta(
            targeted_interference,
            causal_targets=causal_targets,
        )
        if isinstance(targeted_delta, Mapping):
            filtered_delta = _select_order_filter_materialized_delta_for_targets(
                targeted_delta,
                requested=requested,
                causal_targets=causal_targets,
            )
            if filtered_delta is not None:
                validated = _select_order_validated_materialized_delta(
                    filtered_delta
                )
                if validated is not None:
                    return validated

    reg_prefix = "f" if class_id == 1 else "r"
    entries: list[dict[str, Any]] = []
    for target_ig in sorted(requested):
        target = _select_order_causal_target_for_ig(causal_targets, target_ig)
        if target is None:
            continue
        entry = _select_order_causal_delta_entry(
            target,
            target_ig=target_ig,
            reg_prefix=reg_prefix,
        )
        if entry is not None:
            entries.append(entry)
    if not entries:
        return None
    delta = {
        "kind": "node-set-delta",
        "blocker": "select-order-causal-composition",
        "function": function,
        "class_id": class_id,
        "register_prefix": reg_prefix,
        "source": "select-order-causal-complement-composition",
        "missing_virtuals": entries,
    }
    return _select_order_validated_materialized_delta(delta)
def _select_order_materialized_causal_candidate_combos(
    actionable_igs: list[int],
) -> list[list[int]]:
    if not actionable_igs:
        return []
    if len(actionable_igs) == 1:
        return [actionable_igs]
    return [actionable_igs, *[[target] for target in actionable_igs]]
def _select_order_sorted_numeric_keys(mapping: Mapping[str, Any]) -> list[int]:
    return [
        int(key)
        for key in sorted(
            mapping,
            key=lambda item: int(item) if str(item).lstrip("-").isdigit() else 0,
        )
        if str(key).lstrip("-").isdigit()
    ]
def _select_order_materialized_causal_candidates(
    *,
    function: str | None,
    class_id: int,
    causal_targets: Mapping[str, Mapping[str, Any]],
    actionable_igs: list[int],
    label_to_targets: Mapping[str, set[int]],
    all_labels: list[str],
    protected_registers: Mapping[str, int],
    targeted_interference: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for combo in _select_order_materialized_causal_candidate_combos(actionable_igs):
        labels = [
            label for label in all_labels
            if any(target in combo for target in label_to_targets.get(label, set()))
        ]
        if not labels:
            continue
        delta = _select_order_materialized_causal_delta(
            function=function,
            class_id=class_id,
            causal_targets=causal_targets,
            target_igs=combo,
            targeted_interference=targeted_interference,
        )
        if delta is None:
            continue
        candidate_label = "materialized-causal-composition-" + "-".join(
            f"ig{target}" for target in combo
        )
        target_assignments = {
            str(target): {
                "expected": causal_targets.get(str(target), {}).get("expected_phys"),
                "actual": causal_targets.get(str(target), {}).get("actual_phys"),
                "status": "materialized",
            }
            for target in combo
        }
        candidates.append({
            "candidate_label": candidate_label,
            "rank": None,
            "chain": labels,
            "target_igs": combo,
            "referenced_materialized_labels": labels,
            "source_retained": None,
            "status": "materialized-not-compiled",
            "score_status": "materialized-not-compiled",
            "candidate_kind": "synthesized-causal-composition",
            "compiled": False,
            "guard_accepted": None,
            "match_percent": None,
            "complement_hit_count": None,
            "protected_requirements": dict(protected_registers),
            "target_assignments": {
                "protected": dict(protected_registers),
                "causal": target_assignments,
            },
            "normalized_diff_lines": None,
            "opcode_similarity": None,
            "frame_delta": None,
            "spill_delta": {},
            "saved_register_delta": {},
            "source_hunks": [],
            "node_set_delta": delta,
        })
    return candidates
def _select_order_causal_complement_composition_lane(
    *,
    function: str | None,
    class_id: int,
    causal_targets: Mapping[str, Mapping[str, Any]],
    ranked_candidates: list[Mapping[str, Any]],
    protected_registers: Mapping[str, int],
    coverage: Mapping[str, Any],
    targeted_interference: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    actionable: dict[str, dict[str, Any]] = {}
    blocked: dict[str, dict[str, Any]] = {}
    all_labels: list[str] = []
    label_to_targets: dict[str, set[int]] = {}

    for key, target in sorted(
        causal_targets.items(),
        key=lambda item: int(item[0]) if str(item[0]).lstrip("-").isdigit() else 0,
    ):
        if not isinstance(target, Mapping):
            continue
        target_key = _select_order_target_key(key)
        if target_key is None:
            continue
        target_ig = int(target_key)
        labels = [
            str(label)
            for label in target.get("materialized_probe_labels") or []
            if isinstance(label, str) and label
        ]
        for label in labels:
            if label not in all_labels:
                all_labels.append(label)
            label_to_targets.setdefault(label, set()).add(target_ig)
        entry = {
            "target_ig": target_ig,
            "expected_phys": target.get("expected_phys"),
            "actual_phys": target.get("actual_phys"),
            "status": target.get("status"),
            "materialized_probe_labels": labels,
        }
        if target.get("causal_source") is not None:
            entry["causal_source"] = dict(target.get("causal_source") or {})
        if target.get("source_actionable") is True and labels:
            actionable[target_key] = entry
            continue
        blocker = target.get("terminal_blocker")
        raw_blockers = target.get("terminal_blockers")
        if blocker is None and isinstance(raw_blockers, list) and raw_blockers:
            blocker = raw_blockers[0]
        if blocker is not None:
            entry["terminal_blocker"] = blocker
        if target.get("terminal_blockers") is not None:
            entry["terminal_blockers"] = list(target.get("terminal_blockers") or [])
        blocked[target_key] = entry

    scored: list[dict[str, Any]] = []
    scored_keys: set[tuple[str, tuple[str, ...], tuple[int, ...]]] = set()
    for candidate in ranked_candidates:
        candidate_strings = _select_order_strings_in({
            "candidate_label": candidate.get("candidate_label"),
            "label": candidate.get("label"),
            "chain": candidate.get("chain"),
            "source_composition": candidate.get("source_composition"),
            "source_hunks": candidate.get("source_hunks"),
        })
        referenced = [
            label for label in all_labels
            if label in candidate_strings
        ]
        if not referenced:
            continue
        target_igs = sorted({
            target_ig
            for label in referenced
            for target_ig in label_to_targets.get(label, set())
        })
        candidate_label = candidate.get("candidate_label") or candidate.get("label")
        scored_key = (
            str(candidate_label or ""),
            tuple(referenced),
            tuple(target_igs),
        )
        if scored_key in scored_keys:
            continue
        scored_keys.add(scored_key)
        scored.append({
            "candidate_label": candidate_label,
            "rank": candidate.get("rank"),
            "chain": list(candidate.get("chain") or []),
            "target_igs": target_igs,
            "referenced_materialized_labels": referenced,
            "source_retained": candidate.get("source_retained"),
            "status": candidate.get("status"),
            "guard_accepted": candidate.get("guard_accepted"),
            "match_percent": candidate.get("match_percent"),
            "complement_hit_count": candidate.get("complement_hit_count"),
            "target_assignments": dict(candidate.get("target_assignments") or {}),
            "normalized_diff_lines": candidate.get("normalized_diff_lines"),
            "opcode_similarity": candidate.get("opcode_similarity"),
            "frame_delta": candidate.get("frame_delta"),
            "spill_delta": dict(candidate.get("spill_delta") or {}),
            "saved_register_delta": dict(candidate.get("saved_register_delta") or {}),
            "source_hunks": list(candidate.get("source_hunks") or []),
        })

    lane_coverage = _select_order_causal_lane_coverage(coverage)
    pair_hints: list[dict[str, Any]] = []
    actionable_igs = sorted(int(key) for key in actionable)
    synthesized = False
    if not scored and actionable_igs:
        scored = _select_order_materialized_causal_candidates(
            function=function,
            class_id=class_id,
            causal_targets=causal_targets,
            actionable_igs=actionable_igs,
            label_to_targets=label_to_targets,
            all_labels=all_labels,
            protected_registers=protected_registers,
            targeted_interference=targeted_interference,
        )
        synthesized = bool(scored)
    if len(actionable_igs) >= 2:
        pair_labels = [
            label for label in all_labels
            if any(target in actionable_igs for target in label_to_targets[label])
        ]
        hint = {
            "target_igs": actionable_igs,
            "materialized_probe_labels": pair_labels,
            "status": (
                "bounded-search-incomplete"
                if lane_coverage.get("complete") is False
                else "ready"
            ),
        }
        if synthesized:
            hint["protected_igs"] = _select_order_sorted_numeric_keys(
                protected_registers
            )
        pair_hints.append(hint)
    elif synthesized and actionable_igs:
        pair_hints.append({
            "target_igs": actionable_igs,
            "protected_igs": _select_order_sorted_numeric_keys(protected_registers),
            "materialized_probe_labels": [
                label for label in all_labels
                if any(target in actionable_igs for target in label_to_targets[label])
            ],
            "status": "materialized-not-compiled",
        })

    return {
        "status": "actionable" if actionable else "blocked",
        "protected_requirements": dict(protected_registers),
        "blocked_targets": blocked,
        "actionable_targets": actionable,
        "all_materialized_probe_labels": all_labels,
        "scored_causal_candidates": scored,
        "bounded_pair_hints": pair_hints,
        "coverage": lane_coverage,
    }
def _select_order_protected_hit_composition_summary(
    *,
    lane_status: str,
    register_class: str,
    function: str | None = None,
    class_id: int = 0,
    protected_registers: Mapping[str, int],
    complement_targets: Mapping[str, Mapping[str, Any]],
    candidates: list[Mapping[str, Any]],
    best_preserving: Mapping[str, Any],
    best_complement: Mapping[str, Any],
    complement_source_diagnostics: Mapping[str, Mapping[str, Any]],
    terminal_blockers: list[str],
    targeted_interference_source_diagnostics: (
        Mapping[str, Mapping[str, Any]] | None
    ) = None,
    guard_repair_ledger: object | None = None,
) -> dict[str, Any]:
    coverage = _select_order_composition_coverage(
        candidates,
        guard_repair_ledger=guard_repair_ledger,
    )
    ranked = [
        _select_order_composition_candidate_payload(
            candidate,
            protected_registers=protected_registers,
        )
        for candidate in sorted(
            candidates,
            key=_select_order_protected_complement_sort_key,
            reverse=True,
        )
    ]
    terminal_reason = terminal_blockers[0] if terminal_blockers else None
    if lane_status == "repair-found":
        status = "resolved"
    elif coverage.get("coverage_status") == "timed-out":
        status = "timed-out"
        terminal_reason = terminal_reason or "timed-out"
    else:
        status = "blocked"
        terminal_reason = terminal_reason or {
            "bounded-depth-exhausted": "bounded-depth-exhausted",
            "frontier-empty": "frontier-empty",
            "no-probes": "no-repair-probes",
        }.get(str(coverage.get("coverage_status")))
    causal_targets = _select_order_causal_target_plans(
        complement_source_diagnostics
    )
    targeted_interference = (
        _select_order_targeted_interference_transform_plan(
            function=function,
            class_id=class_id,
            candidate=best_complement,
            protected_registers=protected_registers,
            complement_targets=best_complement.get("complement_targets")
            if isinstance(best_complement.get("complement_targets"), Mapping)
            else complement_targets,
            complement_source_diagnostics=(
                targeted_interference_source_diagnostics
                or complement_source_diagnostics
            ),
        )
    )
    if targeted_interference is not None:
        mixed_source_repair = _select_order_mixed_source_repair_plan(
            targeted_interference,
            causal_targets=causal_targets,
        )
        if mixed_source_repair is not None:
            materialized_delta = mixed_source_repair.get("materialized_node_set_delta")
            if isinstance(materialized_delta, Mapping):
                targeted_interference["materialized_node_set_delta"] = dict(
                    materialized_delta
                )
            targeted_interference["mixed_source_repair_plan"] = mixed_source_repair
    payload = {
        "status": status,
        "register_class": register_class,
        "protected_registers": dict(protected_registers),
        "complement_targets": {
            str(key): dict(value)
            for key, value in complement_targets.items()
        },
        "causal_targets": causal_targets,
        "source_action_plan": causal_targets,
        "ranked_source_hunks": ranked,
        "ranked_compositions": ranked,
        "best_preserving_candidate": dict(best_preserving),
        "best_complement_candidate": dict(best_complement),
        "composition_coverage": coverage,
        "terminal_reason": terminal_reason,
        "terminal_blockers": list(terminal_blockers),
    }
    if causal_targets:
        payload["causal_complement_composition_lane"] = (
            _select_order_causal_complement_composition_lane(
                function=function,
                class_id=class_id,
                causal_targets=causal_targets,
                ranked_candidates=ranked,
                protected_registers=protected_registers,
                coverage=coverage,
                targeted_interference=targeted_interference,
            )
        )
    if targeted_interference is not None:
        payload["targeted_interference_source_transforms"] = targeted_interference
    return payload
def _select_order_targeted_interference_source_diagnostics(
    *,
    candidate: Mapping[str, Any],
    complement_source_diagnostics: Mapping[str, Mapping[str, Any]],
    window_order_source_attributions: (
        Mapping[int, Any] | Mapping[str, Any] | None
    ),
    window_order_probe_diagnostics: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    candidate_targets = candidate.get("complement_targets")
    targeted_targets = {
        str(ig_idx): dict(target)
        for ig_idx, target in (
            candidate_targets.items()
            if isinstance(candidate_targets, Mapping) else []
        )
        if isinstance(target, Mapping) and target.get("status") == "hit"
    }
    achieved = candidate.get("achieved_registers")
    achieved = achieved if isinstance(achieved, Mapping) else {}
    lost_protected = candidate.get("lost_protected_registers")
    if isinstance(lost_protected, Mapping):
        for ig_idx, expected in lost_protected.items():
            if not str(ig_idx).lstrip("-").isdigit():
                continue
            targeted_targets[str(ig_idx)] = {
                "expected": expected,
                "actual": achieved.get(str(ig_idx)),
                "status": "lost-protected",
            }
    if not targeted_targets:
        return {
            str(key): dict(value)
            for key, value in complement_source_diagnostics.items()
            if isinstance(value, Mapping)
        }
    diagnostics = _select_order_complement_source_diagnostics(
        complement_targets=targeted_targets,
        window_order_source_attributions=window_order_source_attributions,
        window_order_probe_diagnostics=window_order_probe_diagnostics,
    )
    merged = {
        str(key): dict(value)
        for key, value in complement_source_diagnostics.items()
        if isinstance(value, Mapping)
    }
    merged.update(diagnostics)
    return merged
def _select_order_downhill_complement_summary(
    seed_candidates: list[dict[str, Any]],
    repair_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not repair_candidates:
        return None
    seeds_by_label = {
        str(seed.get("label")): seed
        for seed in seed_candidates
        if seed.get("label") is not None and seed.get("achieved_registers")
    }
    groups: list[dict[str, Any]] = []
    for seed_label, seed in seeds_by_label.items():
        protected = seed.get("achieved_registers")
        if not isinstance(protected, Mapping) or not protected:
            continue
        protected_registers = {
            str(key): value
            for key, value in protected.items()
            if isinstance(key, str) and isinstance(value, int)
        }
        if not protected_registers:
            continue
        seed_repairs = [
            candidate for candidate in repair_candidates
            if candidate.get("repair_seed_label") == seed_label
        ]
        if not seed_repairs:
            continue
        enriched = [
            _select_order_complement_candidate_summary(
                candidate,
                protected_registers=protected_registers,
            )
            for candidate in seed_repairs
        ]
        best_preserving = max(
            enriched,
            key=_select_order_complement_preserving_sort_key,
        )
        best_structural = max(
            enriched,
            key=_select_order_complement_structural_sort_key,
        )
        protected_count = len(protected_registers)
        preserving_structural = [
            candidate for candidate in enriched
            if candidate.get("guard_accepted") is True
            and candidate.get("preserved_protected_count") == protected_count
        ]
        structural_candidates = [
            candidate for candidate in enriched
            if candidate.get("guard_accepted") is True
        ]
        if preserving_structural:
            status = "repair-preserves-protected-hits"
            reason = (
                "at least one guard repair candidate preserved all protected "
                "downhill force-phys hits"
            )
        elif structural_candidates:
            status = "terminal-complement-ceiling"
            reason = (
                "guard repair found structural candidates, but none preserved the "
                "protected downhill force-phys hits"
            )
        else:
            status = "terminal-complement-ceiling"
            reason = (
                "guard repair candidates were scored, but none repaired the "
                "structural guard while preserving protected downhill force-phys hits"
            )
        groups.append({
            "seed_label": seed_label,
            "status": status,
            "reason": reason,
            "protected_registers": protected_registers,
            "protected_count": protected_count,
            "repair_candidate_count": len(enriched),
            "repair_preserves_protected_hits": bool(preserving_structural),
            "repair_trades_off_protected_hits": (
                bool(structural_candidates) and not preserving_structural
            ),
            "best_preserving_candidate": best_preserving,
            "best_structural_candidate": best_structural,
            "candidates": sorted(
                enriched,
                key=_select_order_complement_structural_sort_key,
                reverse=True,
            )[:6],
        })
    if not groups:
        return {
            "status": "unavailable",
            "reason": "repair candidates did not map back to protected downhill seeds",
        }
    status_order = {
        "repair-preserves-protected-hits": 0,
        "terminal-complement-ceiling": 1,
        "repair-trades-off-protected-hits": 2,
    }
    primary = sorted(
        groups,
        key=lambda group: status_order.get(str(group.get("status")), 99),
    )[0]
    return {
        "status": primary["status"],
        "reason": primary["reason"],
        "seed_count": len(groups),
        "protected_registers": primary["protected_registers"],
        "repair_preserves_protected_hits": primary[
            "repair_preserves_protected_hits"
        ],
        "repair_trades_off_protected_hits": primary[
            "repair_trades_off_protected_hits"
        ],
        "best_preserving_candidate": primary["best_preserving_candidate"],
        "best_structural_candidate": primary["best_structural_candidate"],
        "groups": groups,
    }
def _select_order_node_set_delta_targets(delta: Mapping[str, Any] | None) -> list[int]:
    if not isinstance(delta, Mapping):
        return []
    explicit = delta.get("materialized_request_targets")
    if isinstance(explicit, list):
        targets = [
            int(target)
            for target in explicit
            if not isinstance(target, bool)
            and isinstance(target, (int, str))
            and str(target).lstrip("-").isdigit()
        ]
        if targets:
            return sorted(set(targets))
    missing = delta.get("missing_virtuals")
    if not isinstance(missing, list):
        return []
    targets = []
    for entry in missing:
        if not isinstance(entry, Mapping):
            continue
        target_ig = entry.get("target_ig")
        if (
            isinstance(target_ig, bool)
            or not isinstance(target_ig, (int, str))
            or not str(target_ig).lstrip("-").isdigit()
        ):
            continue
        targets.append(int(target_ig))
    return sorted(set(targets))
def _select_order_orientation_reconciliation_lane(
    group: Mapping[str, Any],
    *,
    group_index: int,
) -> dict[str, Any]:
    composition = group.get("protected_hit_composition")
    composition = composition if isinstance(composition, Mapping) else {}
    causal = composition.get("causal_complement_composition_lane")
    causal = causal if isinstance(causal, Mapping) else {}
    actionable_targets = causal.get("actionable_targets")
    actionable_targets = (
        actionable_targets if isinstance(actionable_targets, Mapping) else {}
    )
    scored = causal.get("scored_causal_candidates")
    scored_candidates = scored if isinstance(scored, list) else []
    materialized_labels: list[str] = []
    materialized_delta_paths: list[str] = []
    materialized_targets: set[int] = set()
    for candidate_index, candidate in enumerate(scored_candidates):
        if not isinstance(candidate, Mapping):
            continue
        delta = candidate.get("node_set_delta")
        if not isinstance(delta, Mapping):
            continue
        label = candidate.get("candidate_label")
        if isinstance(label, str) and label:
            materialized_labels.append(label)
        materialized_delta_paths.append(
            f"/groups/{group_index}/protected_hit_composition/"
            "causal_complement_composition_lane/scored_causal_candidates/"
            f"{candidate_index}/node_set_delta"
        )
        materialized_targets.update(_select_order_node_set_delta_targets(delta))

    targeted = composition.get("targeted_interference_source_transforms")
    targeted = targeted if isinstance(targeted, Mapping) else {}
    mixed_plan = targeted.get("mixed_source_repair_plan")
    mixed_plan = mixed_plan if isinstance(mixed_plan, Mapping) else {}
    mixed_delta = mixed_plan.get("materialized_node_set_delta")
    mixed_targets = _select_order_node_set_delta_targets(
        mixed_delta if isinstance(mixed_delta, Mapping) else None
    )
    if isinstance(mixed_delta, Mapping):
        materialized_delta_paths.append(
            f"/groups/{group_index}/protected_hit_composition/"
            "targeted_interference_source_transforms/"
            "mixed_source_repair_plan/materialized_node_set_delta"
        )
        materialized_targets.update(mixed_targets)

    causal_payload = {
        "status": causal.get("status"),
        "actionable_target_ids": _select_order_sorted_numeric_keys(
            actionable_targets
        ),
        "scored_candidate_count": len(scored_candidates),
        "materialized_candidate_count": len(materialized_labels),
        "materialized_candidate_labels": materialized_labels,
        "all_materialized_probe_labels": list(
            causal.get("all_materialized_probe_labels") or []
        ),
    }
    if causal.get("coverage") is not None:
        causal_payload["coverage"] = dict(causal.get("coverage") or {})
    if causal.get("bounded_pair_hints") is not None:
        causal_payload["bounded_pair_hints"] = list(
            causal.get("bounded_pair_hints") or []
        )

    mixed_payload = {
        "status": mixed_plan.get("status"),
        "node_set_target_ids": mixed_targets,
    }
    if mixed_plan.get("reason") is not None:
        mixed_payload["reason"] = mixed_plan.get("reason")

    source_actionable = bool(materialized_delta_paths) or (
        mixed_payload.get("status") == "ready"
    )
    return {
        "group_index": group_index,
        "seed_label": group.get("seed_label"),
        "status": group.get("status"),
        "reason": group.get("reason"),
        "protected_registers": dict(group.get("protected_registers") or {}),
        "complement_targets": {
            str(key): dict(value)
            for key, value in (group.get("complement_targets") or {}).items()
            if isinstance(value, Mapping)
        },
        "terminal_blockers": list(group.get("terminal_blockers") or []),
        "causal_lane": causal_payload,
        "mixed_source_repair": mixed_payload,
        "materialized_request_targets": sorted(materialized_targets),
        "materialized_delta_paths": materialized_delta_paths,
        "source_actionable": source_actionable,
    }
def _select_order_protected_complement_summary(
    seed_candidates: list[dict[str, Any]],
    repair_candidates: list[dict[str, Any]],
    *,
    force_phys: Mapping[int, int],
    function: str | None = None,
    class_id: int = 0,
    window_order_source_attributions: (
        Mapping[int, Any] | Mapping[str, Any] | None
    ) = None,
    window_order_probe_diagnostics: Mapping[str, Any] | None = None,
    guard_repair_ledger: object | None = None,
) -> dict[str, Any] | None:
    from src.cli.debug import _select_order_complement_target_summary
    if not repair_candidates:
        return None
    seeds_by_label = {
        str(seed.get("label")): seed
        for seed in seed_candidates
        if seed.get("label") is not None and seed.get("achieved_registers")
    }
    groups: list[dict[str, Any]] = []
    for seed_label, seed in seeds_by_label.items():
        protected = seed.get("achieved_registers")
        if not isinstance(protected, Mapping) or not protected:
            continue
        protected_registers = {
            str(key): int(value)
            for key, value in protected.items()
            if isinstance(key, str) and isinstance(value, int)
        }
        complement_targets = _select_order_complement_target_summary(
            force_phys=force_phys,
            seed_candidate=seed,
            protected_registers=protected_registers,
        )
        if not protected_registers or not complement_targets:
            continue
        seed_repairs = [
            candidate for candidate in repair_candidates
            if candidate.get("repair_seed_label") == seed_label
        ]
        if not seed_repairs:
            continue
        enriched = [
            _select_order_protected_complement_candidate_summary(
                candidate,
                protected_registers=protected_registers,
                complement_targets=complement_targets,
            )
            for candidate in seed_repairs
        ]
        protected_count = len(protected_registers)
        complement_count = len(complement_targets)
        preserving = [
            candidate for candidate in enriched
            if candidate.get("preserved_protected_count") == protected_count
        ]
        exact = [
            candidate for candidate in preserving
            if candidate.get("complement_hit_count") == complement_count
            and candidate.get("guard_accepted") is True
        ]
        best_preserving = max(
            preserving or enriched,
            key=_select_order_protected_complement_preserving_sort_key,
        )
        best_complement = max(
            enriched,
            key=_select_order_protected_complement_sort_key,
        )
        diagnostic_targets = best_preserving.get("complement_targets")
        if not isinstance(diagnostic_targets, Mapping):
            diagnostic_targets = complement_targets
        complement_source_diagnostics = _select_order_complement_source_diagnostics(
            complement_targets=diagnostic_targets,
            window_order_source_attributions=window_order_source_attributions,
            window_order_probe_diagnostics=window_order_probe_diagnostics,
        )
        targeted_interference_source_diagnostics = (
            _select_order_targeted_interference_source_diagnostics(
                candidate=best_complement,
                complement_source_diagnostics=complement_source_diagnostics,
                window_order_source_attributions=window_order_source_attributions,
                window_order_probe_diagnostics=window_order_probe_diagnostics,
            )
        )
        blockers: list[str] = []
        if exact:
            status = "repair-found"
            reason = (
                "guard repair found a candidate that preserved protected "
                "force-phys hits and hit the complement targets"
            )
        else:
            status = "terminal-protected-complement-ceiling"
            reason = (
                "guard repair did not hit all complement force-phys targets "
                "while preserving protected hits"
            )
            if best_preserving.get("complement_hit_count") != complement_count:
                blockers.append("complement-target-not-hit-while-protected")
            if best_complement.get("protected_loss_count", 0) > 0:
                blockers.append("protected-hit-lost-by-best-complement")
            if best_preserving.get("guard_accepted") is not True:
                blockers.append("structural-guard-not-accepted")
            for diagnostic in complement_source_diagnostics.values():
                target = diagnostic.get("target")
                if (
                    isinstance(target, Mapping)
                    and target.get("status") == "hit"
                ):
                    continue
                if diagnostic.get("source_actionable") is True:
                    continue
                blocker = diagnostic.get("terminal_blocker")
                if isinstance(blocker, str) and blocker:
                    blockers.append(blocker)
        protected_hit_composition = (
            _select_order_protected_hit_composition_summary(
                lane_status=status,
                register_class="fpr" if class_id == 1 else "gpr",
                function=function,
                class_id=class_id,
                protected_registers=protected_registers,
                complement_targets=complement_targets,
                candidates=enriched,
                best_preserving=best_preserving,
                best_complement=best_complement,
                complement_source_diagnostics=complement_source_diagnostics,
                targeted_interference_source_diagnostics=(
                    targeted_interference_source_diagnostics
                ),
                terminal_blockers=blockers,
                guard_repair_ledger=guard_repair_ledger,
            )
        )
        groups.append({
            "seed_label": seed_label,
            "status": status,
            "reason": reason,
            "protected_registers": protected_registers,
            "protected_count": protected_count,
            "complement_targets": complement_targets,
            "complement_count": complement_count,
            "repair_candidate_count": len(enriched),
            "best_preserving_candidate": best_preserving,
            "best_complement_candidate": best_complement,
            "complement_source_diagnostics": complement_source_diagnostics,
            "protected_hit_composition": protected_hit_composition,
            "terminal_blocker": blockers[0] if blockers else None,
            "terminal_blockers": blockers,
            "candidates": sorted(
                enriched,
                key=_select_order_protected_complement_preserving_sort_key,
                reverse=True,
            )[:8],
        })
    if not groups:
        return _select_order_partial_protected_complement_summary(
            seed_candidates,
            repair_candidates,
            force_phys=force_phys,
            function=function,
            class_id=class_id,
            window_order_source_attributions=window_order_source_attributions,
            window_order_probe_diagnostics=window_order_probe_diagnostics,
            guard_repair_ledger=guard_repair_ledger,
        )
    primary = sorted(
        groups,
        key=lambda group: (
            0 if group.get("status") == "repair-found" else 1,
            -int(group.get("protected_count") or 0),
            -int(group.get("complement_count") or 0),
        ),
    )[0]
    terminal_blockers = sorted({
        blocker
        for group in groups
        for blocker in group.get("terminal_blockers", [])
        if isinstance(blocker, str)
    })
    primary_blockers = [
        blocker for blocker in primary.get("terminal_blockers", [])
        if isinstance(blocker, str)
    ]
    orientation_lanes = [
        _select_order_orientation_reconciliation_lane(
            group,
            group_index=index,
        )
        for index, group in enumerate(groups)
    ]
    source_actionable_orientations = [
        lane for lane in orientation_lanes
        if lane.get("source_actionable") is True
    ]
    primary_orientation_index = groups.index(primary)
    return {
        "status": primary["status"],
        "reason": primary["reason"],
        "register_class": "fpr" if class_id == 1 else "gpr",
        "seed_count": len(groups),
        "protected_registers": primary["protected_registers"],
        "protected_count": primary["protected_count"],
        "complement_targets": primary["complement_targets"],
        "complement_count": primary["complement_count"],
        "best_preserving_candidate": primary["best_preserving_candidate"],
        "best_complement_candidate": primary["best_complement_candidate"],
        "complement_source_diagnostics": primary.get(
            "complement_source_diagnostics",
            {},
        ),
        "protected_hit_composition": primary.get("protected_hit_composition", {}),
        "terminal_blocker": (
            primary_blockers[0] if primary_blockers else None
        ),
        "terminal_blockers": terminal_blockers,
        "primary_orientation_index": primary_orientation_index,
        "orientation_reconciliation_lanes": orientation_lanes,
        "source_actionable_orientations": source_actionable_orientations,
        "groups": groups,
    }
def _select_order_partial_protected_complement_summary(
    seed_candidates: list[dict[str, Any]],
    repair_candidates: list[dict[str, Any]],
    *,
    force_phys: Mapping[int, int],
    function: str | None,
    class_id: int,
    window_order_source_attributions: (
        Mapping[int, Any] | Mapping[str, Any] | None
    ),
    window_order_probe_diagnostics: Mapping[str, Any] | None,
    guard_repair_ledger: object | None,
) -> dict[str, Any] | None:
    from src.cli.debug import _select_order_complement_target_summary
    targets = _select_order_int_mapping(force_phys)
    if not targets:
        return None
    by_label: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate([*seed_candidates, *repair_candidates]):
        hit_count = candidate.get("force_phys_satisfied_count")
        if not isinstance(hit_count, int) or hit_count <= 0:
            continue
        if hit_count >= len(targets):
            continue
        label = str(candidate.get("label") or f"candidate-{index}")
        current = by_label.get(label)
        candidate_key = _select_order_guard_repair_candidate_sort_key(candidate)
        current_key = (
            _select_order_guard_repair_candidate_sort_key(current)
            if current is not None else None
        )
        if (
            current is None
            or candidate_key < current_key
            or (
                candidate_key == current_key
                and _select_order_source_reference_score(candidate)
                > _select_order_source_reference_score(current)
            )
        ):
            by_label[label] = candidate
    if not by_label:
        return None

    candidates = sorted(
        by_label.values(),
        key=_select_order_guard_repair_candidate_sort_key,
    )
    best_candidate = candidates[0]
    protected_registers = {
        str(ig_idx): int(phys)
        for ig_idx, phys in dict(
            best_candidate.get("achieved_registers") or {}
        ).items()
        if str(ig_idx).lstrip("-").isdigit()
    }
    complement_targets = _select_order_complement_target_summary(
        force_phys=targets,
        seed_candidate=best_candidate,
        protected_registers=protected_registers,
    )
    if not protected_registers or not complement_targets:
        return None

    enriched = [
        _select_order_protected_complement_candidate_summary(
            candidate,
            protected_registers=protected_registers,
            complement_targets=complement_targets,
        )
        for candidate in candidates
    ]
    best_enriched = enriched[0]
    complement_source_diagnostics = _select_order_complement_source_diagnostics(
        complement_targets=complement_targets,
        window_order_source_attributions=window_order_source_attributions,
        window_order_probe_diagnostics=window_order_probe_diagnostics,
    )
    terminal_blockers = ["partial-protected-complement-no-seed-pair"]
    coverage = _select_order_composition_coverage(
        enriched,
        guard_repair_ledger=guard_repair_ledger,
    )
    status = (
        "timed-out"
        if coverage.get("coverage_status") == "timed-out"
        else "blocked"
    )
    reason = (
        "partial force-phys hit evidence exists, but no protected/complement "
        "seed-repair pair was formed"
    )
    protected_hit_composition = _select_order_protected_hit_composition_summary(
        lane_status=status,
        register_class="fpr" if class_id == 1 else "gpr",
        function=function,
        class_id=class_id,
        protected_registers=protected_registers,
        complement_targets=complement_targets,
        candidates=enriched,
        best_preserving=best_enriched,
        best_complement=best_enriched,
        complement_source_diagnostics=complement_source_diagnostics,
        terminal_blockers=terminal_blockers,
        guard_repair_ledger=guard_repair_ledger,
    )
    return {
        "status": status,
        "reason": reason,
        "register_class": "fpr" if class_id == 1 else "gpr",
        "seed_count": 0,
        "protected_registers": protected_registers,
        "protected_count": len(protected_registers),
        "complement_targets": complement_targets,
        "complement_count": len(complement_targets),
        "best_preserving_candidate": best_enriched,
        "best_complement_candidate": best_enriched,
        "complement_source_diagnostics": complement_source_diagnostics,
        "protected_hit_composition": protected_hit_composition,
        "terminal_blocker": terminal_blockers[0],
        "terminal_blockers": terminal_blockers,
        "groups": [],
    }
def _select_order_source_attr_for_ig(
    attrs: Mapping[int, Any] | Mapping[str, Any],
    target_ig: int,
) -> Any | None:
    if target_ig in attrs:
        return attrs[target_ig]  # type: ignore[index]
    key = str(target_ig)
    if key in attrs:
        return attrs[key]  # type: ignore[index]
    return None
def _select_order_window_order_lead_key(
    lead: Mapping[str, Any],
) -> tuple[int, tuple[str, ...]] | None:
    source = lead
    nested = lead.get("lead")
    if isinstance(nested, Mapping):
        source = nested
    target = source.get("target_ig", lead.get("target_ig"))
    if isinstance(target, bool) or not isinstance(target, (int, str)):
        return None
    target_text = str(target)
    if not target_text.lstrip("-").isdigit():
        return None
    raw_order = source.get("order_move", lead.get("order_move"))
    order_move: tuple[str, ...]
    if isinstance(raw_order, (list, tuple)):
        order_move = tuple(str(item) for item in raw_order)
    else:
        order_move = ()
    return int(target_text), order_move
def _select_order_window_order_lead_diagnostic_by_key(
    diagnostics: Mapping[str, Any],
) -> dict[tuple[int, tuple[str, ...]], dict[str, Any]]:
    raw = diagnostics.get("lead_diagnostics")
    if not isinstance(raw, list):
        return {}
    out: dict[tuple[int, tuple[str, ...]], dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        key = _select_order_window_order_lead_key(item)
        if key is None:
            continue
        out.setdefault(key, dict(item))
    return out
def _select_order_source_bridge_leads(
    *,
    window_order_fallback: Mapping[str, Any] | None,
    window_order_source_attributions: Mapping[int, Any] | Mapping[str, Any],
    window_order_probe_diagnostics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    from src.cli.debug import _solve_source_attribution_dict
    raw_leads = (
        window_order_fallback.get("leads")
        if isinstance(window_order_fallback, Mapping) else []
    )
    if not isinstance(raw_leads, list):
        return []
    lead_diagnostics = _select_order_window_order_lead_diagnostic_by_key(
        window_order_probe_diagnostics
    )
    leads: list[dict[str, Any]] = []
    for lead in raw_leads:
        if not isinstance(lead, Mapping):
            continue
        try:
            target_ig = int(lead["target_ig"])
        except (KeyError, TypeError, ValueError):
            continue
        source = _solve_source_attribution_dict(
            _select_order_source_attr_for_ig(
                window_order_source_attributions,
                target_ig,
            )
        )
        lead_key = _select_order_window_order_lead_key(lead)
        probe_diag = lead_diagnostics.get(lead_key) if lead_key is not None else None
        if probe_diag is None and lead_key is not None and not lead_key[1]:
            probe_diag = lead_diagnostics.get((target_ig, ()))
        materialized_labels: list[str] = []
        if isinstance(probe_diag, Mapping):
            raw_labels = probe_diag.get("materialized_probe_labels")
            if isinstance(raw_labels, list):
                materialized_labels = [
                    str(label) for label in raw_labels
                    if isinstance(label, str) and label
                ]
        source_actionable = bool(
            probe_diag
            and probe_diag.get("status") == "materialized"
            and materialized_labels
        )
        lead_payload = {
            "target_ig": target_ig,
            "order_move": list(lead.get("order_move") or []),
            "move_distance": lead.get("move_distance"),
            "perturbed_reg": lead.get("perturbed_reg"),
            "source": source,
            "source_attributed": bool(source),
            "source_actionable": source_actionable,
        }
        if probe_diag is not None:
            lead_payload["source_probe_diagnostic"] = dict(probe_diag)
            terminal_blocker = probe_diag.get("terminal_blocker")
            if isinstance(terminal_blocker, str) and terminal_blocker:
                lead_payload["terminal_blocker"] = terminal_blocker
            if materialized_labels:
                lead_payload["materialized_probe_labels"] = materialized_labels
            if isinstance(probe_diag.get("source_diff"), str):
                lead_payload["source_diff"] = probe_diag.get("source_diff")
        leads.append({
            **lead_payload,
        })
    return leads
def _select_order_source_bridge_variant_registers(
    variant: Mapping[str, Any],
) -> dict[str, Any]:
    from src.cli.debug import _select_order_force_phys_hit_registers
    objective = variant.get("objective")
    if not isinstance(objective, Mapping):
        return {}
    return {
        "achieved": _select_order_force_phys_hit_registers(variant),
        "missing": _select_order_force_phys_missing_registers(objective),
        "mismatched": _select_order_force_phys_mismatched_registers(objective),
        "force_phys_satisfied_count": objective.get(
            "force_phys_satisfied_count"
        ),
        "force_phys_distance": objective.get("force_phys_distance"),
        "match_percent": objective.get("match_percent"),
    }
def _select_order_variant_pcdump_path(
    variant: Mapping[str, Any],
) -> str | None:
    for container in (variant, variant.get("objective")):
        if not isinstance(container, Mapping):
            continue
        value = container.get("pcdump_path")
        if isinstance(value, str) and value:
            return value
        value = container.get("pcdump")
        if isinstance(value, str) and value.endswith(".txt"):
            return value
    return None
def _select_order_bridge_force_phys_target_score(
    variant: Mapping[str, Any],
    force_phys: Mapping[int, int] | None,
) -> dict[str, Any] | None:
    from src.cli.debug import _select_order_variant_target_score
    existing = _select_order_variant_target_score(variant)
    if existing is not None:
        return existing
    if not force_phys:
        return None
    objective = variant.get("objective")
    if not isinstance(objective, Mapping):
        return None
    targets = _select_order_int_mapping(objective.get("force_phys_targets"))
    requested = _select_order_int_mapping(force_phys)
    if not targets:
        targets = requested
    mismatches_raw = objective.get("force_phys_mismatches")
    mismatches = mismatches_raw if isinstance(mismatches_raw, Mapping) else {}
    missing = {
        int(item) for item in objective.get("force_phys_missing") or []
        if isinstance(item, (int, str)) and str(item).lstrip("-").isdigit()
    }
    virtuals: dict[str, dict[str, Any]] = {}
    matched = 0
    for virtual, expected in sorted((requested or targets).items()):
        actual: int | None
        hit = False
        mismatch = mismatches.get(str(virtual), mismatches.get(virtual))
        if isinstance(mismatch, Mapping):
            raw_expected = mismatch.get("expected", expected)
            raw_actual = mismatch.get("actual")
            expected = _first_int(raw_expected, expected) or expected
            actual = _first_int(raw_actual)
        elif virtual in missing:
            actual = None
        elif virtual in targets:
            actual = targets[virtual]
            hit = actual == expected
        else:
            actual = None
        if actual == expected and virtual not in missing:
            hit = True
            matched += 1
        virtuals[str(virtual)] = {
            "expected": expected,
            "actual": actual,
            "hit": hit,
            "matched": hit,
        }
    return {
        "matched": matched,
        "total": len(virtuals),
        "targeted": len(virtuals),
        "virtuals": virtuals,
    }
def _select_order_bridge_actual_registers(
    target_score: Mapping[str, Any] | None,
) -> dict[str, int | None]:
    if not isinstance(target_score, Mapping):
        return {}
    virtuals = target_score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return {}
    registers: dict[str, int | None] = {}
    for key, value in virtuals.items():
        if not isinstance(value, Mapping):
            continue
        actual = _first_int(value.get("actual"))
        registers[str(key)] = actual
    return registers
def _select_order_bridge_probe_payload(
    variant: Mapping[str, Any],
) -> dict[str, Any]:
    probe = variant.get("probe")
    if not isinstance(probe, Mapping):
        return {}
    provenance = probe.get("provenance")
    payload: dict[str, Any] = {}
    if isinstance(provenance, Mapping):
        raw_payload = provenance.get("payload")
        if isinstance(raw_payload, Mapping):
            payload.update(dict(raw_payload))
        for key in (
            "mutator_key",
            "family_id",
            "family_label",
            "source_region",
            "generated_probe_form",
            "span",
        ):
            if key in provenance:
                payload.setdefault(key, provenance.get(key))
    raw_payload = probe.get("payload")
    if isinstance(raw_payload, Mapping):
        payload.update(dict(raw_payload))
    for key in ("mutator_key", "operator", "label"):
        if key in probe:
            payload.setdefault(key, probe.get(key))
    return payload
def _select_order_bridge_lead_source_candidates(
    leads: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    local_candidates: list[dict[str, Any]] = []
    indexed_candidates: list[dict[str, Any]] = []
    for lead in leads:
        diag = lead.get("source_probe_diagnostic")
        if not isinstance(diag, Mapping):
            continue
        raw_local = diag.get("ranked_source_owner_candidates")
        if isinstance(raw_local, list):
            local_candidates.extend(
                dict(item) for item in raw_local if isinstance(item, Mapping)
            )
        synthetic = diag.get("synthetic_source_probe")
        if isinstance(synthetic, Mapping):
            raw_indexed = synthetic.get("ranked_indexed_byte_source_candidates")
            if isinstance(raw_indexed, list):
                indexed_candidates.extend(
                    dict(item)
                    for item in raw_indexed
                    if isinstance(item, Mapping)
                )
    return local_candidates, indexed_candidates
def _select_order_bridge_source_owner(
    *,
    probe_payload: Mapping[str, Any],
    local_candidates: list[dict[str, Any]],
    indexed_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for key in ("array_base", "index_expr", "target_local", "span_text"):
        if key in probe_payload:
            owner = {
                candidate_key: probe_payload.get(candidate_key)
                for candidate_key in (
                    "array_base",
                    "index_expr",
                    "target_local",
                    "temp_local",
                    "span_text",
                    "strategy",
                    "mutator_key",
                )
                if probe_payload.get(candidate_key) is not None
            }
            if owner:
                owner.setdefault("kind", "transform-probe-payload")
                return owner
    mutator_key = probe_payload.get("mutator_key")
    for candidate in indexed_candidates:
        mutator_keys = candidate.get("mutator_keys")
        if (
            isinstance(mutator_key, str)
            and isinstance(mutator_keys, list)
            and mutator_key in mutator_keys
        ):
            return dict(candidate)
    if indexed_candidates:
        return dict(indexed_candidates[0])
    if local_candidates:
        return dict(local_candidates[0])
    return None
def _select_order_bridge_force_distance(
    target_score: Mapping[str, Any] | None,
) -> int:
    if not isinstance(target_score, Mapping):
        return 1_000_000
    virtuals = target_score.get("virtuals")
    if not isinstance(virtuals, Mapping):
        return 1_000_000
    distance = 0
    for value in virtuals.values():
        if not isinstance(value, Mapping):
            continue
        expected = _first_int(value.get("expected"))
        actual = _first_int(value.get("actual"))
        if expected is None or actual is None:
            distance += 100
        else:
            distance += abs(expected - actual)
    return distance
def _select_order_bridge_probe_sort_key(
    probe: Mapping[str, Any],
) -> tuple[Any, ...]:
    guard = probe.get("guard")
    guard_rejected = (
        isinstance(guard, Mapping)
        and guard.get("accepted") is False
    )
    frame_delta = abs(_first_int(probe.get("frame_delta"), 0) or 0)
    target_score = probe.get("target_score")
    matched = (
        _first_int(target_score.get("matched"))
        if isinstance(target_score, Mapping) else 0
    ) or 0
    distance = _select_order_bridge_force_distance(
        target_score if isinstance(target_score, Mapping) else None
    )
    registers = probe.get("registers")
    ig44_missing = (
        isinstance(registers, Mapping)
        and "44" in registers
        and registers.get("44") is None
    )
    match_percent = _select_order_float_sort_value(
        (probe.get("objective") or {}).get("match_percent")
        if isinstance(probe.get("objective"), Mapping) else None,
        default=0.0,
    )
    return (
        1 if guard_rejected else 0,
        frame_delta,
        distance,
        1 if ig44_missing else 0,
        -matched,
        -match_percent,
        _first_int(probe.get("rank"), 1_000_000) or 1_000_000,
    )
def _select_order_bridge_probe_intent(
    registers: Mapping[str, int | None],
    force_phys: Mapping[int, int],
) -> str:
    parts: list[str] = []
    for virtual, expected in sorted(_select_order_int_mapping(force_phys).items()):
        actual = registers.get(str(virtual))
        if actual == expected:
            parts.append(f"keep-ig{virtual}-at-r{expected}")
        elif actual is None:
            parts.append(f"materialize-ig{virtual}-toward-r{expected}")
        else:
            parts.append(f"move-ig{virtual}-off-r{actual}-toward-r{expected}")
    return "-".join(parts) if parts else "score-retained-source"
def _select_order_bridge_score_command_hint(
    *,
    source_retained: str,
    function: str,
) -> str:
    from src.cli.debug import DEFAULT_MELEE_ROOT, _find_unit_for_function
    command = [
        "melee-agent",
        "debug",
        "target",
        "score-source",
        source_retained,
        "--function",
        function,
        "--target",
        "<target-spec.json>",
    ]
    unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
    if unit is not None:
        command.extend(["--cflags-from", f"src/{unit}.c"])
    command.extend(["--json", "--retain-pcdump"])
    return shlex.join(command)
def _select_order_bridge_ranked_source_probes(
    *,
    ranked_variants: list[Mapping[str, Any]],
    leads: list[Mapping[str, Any]],
    terminal_blockers: list[str],
    force_phys: Mapping[int, int],
    function: str | None,
    max_probes: int = 8,
) -> list[dict[str, Any]]:
    source_blockers = {
        "local-source-owner-no-unique-assignment",
        "synthetic-temp-operands-unattributed",
    }
    linked_blockers = [
        blocker for blocker in terminal_blockers if blocker in source_blockers
    ]
    if not linked_blockers:
        return []
    local_candidates, indexed_candidates = _select_order_bridge_lead_source_candidates(
        leads
    )
    probes: list[dict[str, Any]] = []
    for variant in ranked_variants:
        source_retained = variant.get("source_retained") or variant.get("path")
        if not isinstance(source_retained, str) or not source_retained.endswith(".c"):
            continue
        blockers = _select_order_source_bridge_blocker_classes(variant)
        if not blockers & {
            "indexed-byte-address-temp-shape",
            "stack-layout",
            "guard-rejected-structural-drift",
            "wrong-register",
        }:
            continue
        target_score = _select_order_bridge_force_phys_target_score(
            variant,
            force_phys,
        )
        registers = _select_order_bridge_actual_registers(target_score)
        probe_payload = _select_order_bridge_probe_payload(variant)
        source_owner = _select_order_bridge_source_owner(
            probe_payload=probe_payload,
            local_candidates=local_candidates,
            indexed_candidates=indexed_candidates,
        )
        objective = variant.get("objective")
        frame_delta = (
            objective.get("frame_delta") if isinstance(objective, Mapping) else None
        )
        entry: dict[str, Any] = {
            "label": variant.get("label"),
            "rank": variant.get("rank"),
            "operator": variant.get("operator"),
            "mutator_key": probe_payload.get("mutator_key"),
            "source_retained": source_retained,
            "pcdump_path": _select_order_variant_pcdump_path(variant),
            "target_score": target_score,
            "registers": registers,
            "frame_delta": frame_delta,
            "guard": variant.get("structural_guard"),
            "blocker_classes": sorted(blockers),
            "linked_terminal_blockers": linked_blockers,
            "source_provenance": probe_payload,
            "source_owner": source_owner,
            "intent": _select_order_bridge_probe_intent(registers, force_phys),
        }
        if function:
            entry["score_command_hint"] = _select_order_bridge_score_command_hint(
                source_retained=source_retained,
                function=function,
            )
        probes.append(entry)
    probes.sort(key=_select_order_bridge_probe_sort_key)
    for index, probe in enumerate(probes[:max_probes], start=1):
        probe["rank"] = index
    return probes[:max_probes]
def _select_order_source_bridge_lane(
    *,
    ranked_variants: list[Mapping[str, Any]],
    leads: list[Mapping[str, Any]],
    terminal_blockers: list[str],
    force_phys: Mapping[int, int],
    function: str | None,
) -> dict[str, Any]:
    ranked_probes = _select_order_bridge_ranked_source_probes(
        ranked_variants=ranked_variants,
        leads=leads,
        terminal_blockers=terminal_blockers,
        force_phys=force_phys,
        function=function,
    )
    if not ranked_probes:
        return {
            "status": "not-applicable",
            "reason": "no-ranked-source-bridge-probes",
            "ranked_probes": [],
            "actions": [],
        }
    actions: list[dict[str, Any]] = []
    for probe in ranked_probes[:3]:
        action: dict[str, Any] = {
            "kind": "score-ranked-retained-source",
            "candidate_label": probe.get("label"),
            "source_retained": probe.get("source_retained"),
            "pcdump_path": probe.get("pcdump_path"),
            "linked_terminal_blockers": probe.get("linked_terminal_blockers"),
        }
        if isinstance(probe.get("score_command_hint"), str):
            action["command_hint"] = probe["score_command_hint"]
        actions.append(action)
    return {
        "status": "available",
        "reason": "terminal-blockers-source-actionable",
        "ranked_probes": ranked_probes,
        "actions": actions,
    }
def _select_order_source_bridge_blocker_classes(
    variant: Mapping[str, Any],
) -> set[str]:
    blockers: set[str] = set()
    status = variant.get("status")
    if status != "ok":
        blockers.add("unscored-or-build-failed")
        return blockers
    operator = str(variant.get("operator") or "")
    objective = variant.get("objective")
    guard = variant.get("structural_guard")
    if "indexed_byte_address" in operator or "indexed-byte" in operator:
        blockers.add("indexed-byte-address-temp-shape")
    if any(
        key in operator
        for key in (
            "declaration",
            "lifetime",
            "block-scope",
            "call-return-compare-chain",
        )
    ):
        blockers.add("declaration-lifetime-order")
    if isinstance(objective, Mapping):
        frame_delta = _select_order_float_sort_value(
            objective.get("frame_delta"),
            default=0.0,
        )
        if frame_delta != 0.0:
            blockers.add("stack-layout")
        if objective.get("force_phys_satisfied") is not True:
            blockers.add("wrong-register")
    if isinstance(guard, Mapping) and guard.get("accepted") is False:
        reason = " ".join(
            str(value)
            for value in (
                guard.get("rejection_reason"),
                guard.get("classification_primary"),
            )
            if value is not None
        ).lower()
        if "stack" in reason:
            blockers.add("stack-layout")
        else:
            blockers.add("guard-rejected-structural-drift")
    return blockers
def _select_order_source_bridge_action_for_blocker(
    blocker: str,
) -> dict[str, str]:
    action_kind = {
        "indexed-byte-address-temp-shape": (
            "inspect-indexed-byte-address-temp-shape"
        ),
        "stack-layout": "repair-stack-layout",
        "declaration-lifetime-order": "adjust-declaration-lifetime-order",
        "guard-rejected-structural-drift": "inspect-structural-drift",
        "unscored-or-build-failed": "score-retained-source",
        "wrong-register": "record-terminal-allocator-ceiling",
    }.get(blocker, "inspect-allocator-residual")
    return {
        "kind": action_kind,
        "blocker": blocker,
    }
def _select_order_source_bridge_dominant_nonterminal_blocker(
    blocker_classes: set[str],
) -> str:
    for blocker in (
        "stack-layout",
        "indexed-byte-address-temp-shape",
        "declaration-lifetime-order",
        "guard-rejected-structural-drift",
        "unscored-or-build-failed",
    ):
        if blocker in blocker_classes:
            return blocker
    return "terminal-allocator-ceiling"
def _select_order_source_bridge_terminal_next_lane(
    *,
    ranked_variants: list[Mapping[str, Any]],
    leads: list[Mapping[str, Any]],
    force_phys: Mapping[int, int] | None = None,
    function: str | None = None,
    base_source_path: Path | str | None = None,
    campaign_dir: Path | str | None = None,
) -> dict[str, Any]:
    from src.cli.debug import _select_order_variant_target_score
    terminal_blockers = sorted({
        str(lead.get("terminal_blocker"))
        for lead in leads
        if isinstance(lead.get("terminal_blocker"), str)
        and lead.get("terminal_blocker")
    })
    if not terminal_blockers:
        return {"status": "not-applicable", "reason": "no-terminal-leads"}

    candidates: list[dict[str, Any]] = []
    for variant in ranked_variants:
        source_retained = variant.get("source_retained") or variant.get("path")
        if not isinstance(source_retained, str) or not source_retained.endswith(".c"):
            continue
        blockers = _select_order_source_bridge_blocker_classes(variant)
        if not blockers & {
            "indexed-byte-address-temp-shape",
            "stack-layout",
            "guard-rejected-structural-drift",
        }:
            continue
        objective = variant.get("objective")
        frame_delta = (
            objective.get("frame_delta") if isinstance(objective, Mapping) else None
        )
        candidate = {
            "label": variant.get("label"),
            "rank": variant.get("rank"),
            "operator": variant.get("operator"),
            "path": variant.get("path"),
            "source_retained": source_retained,
            "pcdump_path": _select_order_variant_pcdump_path(variant),
            "blocker_classes": sorted(blockers),
            "registers": _select_order_source_bridge_variant_registers(variant),
            "frame_delta": frame_delta,
            "guard": variant.get("structural_guard"),
            "frame_transform_probe_evaluation": variant.get(
                "frame_transform_probe_evaluation"
            ),
        }
        target_score = _select_order_variant_target_score(variant)
        if target_score is not None:
            candidate["target_score"] = target_score
        candidates.append(candidate)
        if len(candidates) >= 4:
            break

    if not candidates:
        return {
            "status": "not-applicable",
            "reason": "no-retained-structural-near-candidates",
            "terminal_blockers": terminal_blockers,
        }

    actions: list[dict[str, Any]] = []
    if len(candidates) >= 2:
        base_arg = (
            shlex.quote(str(base_source_path))
            if base_source_path is not None
            else "REAL_TU"
        )
        candidate_args = " ".join(
            "--candidate "
            + shlex.quote(
                f"{candidate.get('label') or f'candidate{idx}'}="
                f"{candidate['source_retained']}"
            )
            for idx, candidate in enumerate(candidates[:3], start=1)
        )
        actions.append({
            "kind": "try-retained-variant-recombine",
            "command_hint": (
                f"melee-agent debug search combine --base {base_arg} "
                f"{candidate_args} --json"
            ),
        })
    else:
        func_arg = shlex.quote(function) if function else "FUNCTION"
        actions.append({
            "kind": "inspect-single-retained-candidate",
            "command_hint": (
                f"melee-agent debug search structure -f {func_arg} "
                f"--source-file {shlex.quote(candidates[0]['source_retained'])} "
                "--json"
            ),
        })
    if any("stack-layout" in candidate["blocker_classes"] for candidate in candidates):
        actions.append({
            "kind": "try-natural-stack-frame-repair",
            "command_hint": (
                "rerun debug select-order-search with a retained candidate and "
                "--frame-reservation-bytes set to the observed frame delta"
            ),
        })

    source_bridge_lane = _select_order_source_bridge_lane(
        ranked_variants=ranked_variants,
        leads=leads,
        terminal_blockers=terminal_blockers,
        force_phys=force_phys or {},
        function=function,
    )
    if source_bridge_lane.get("status") == "available":
        actions = [
            *list(source_bridge_lane.get("actions") or []),
            *actions,
        ]

    return {
        "status": "available",
        "reason": "terminal-bridge-structural-near-candidates",
        "terminal_blockers": terminal_blockers,
        "candidates": candidates,
        "actions": actions,
        "source_bridge_lane": source_bridge_lane,
        "frame_repair_lane": _select_order_source_bridge_frame_repair_lane(
            candidates,
            function=function,
            campaign_dir=campaign_dir,
        ),
    }
def _select_order_source_bridge_frame_repair_lane(
    candidates: list[Mapping[str, Any]],
    *,
    function: str | None,
    campaign_dir: Path | str | None,
) -> dict[str, Any]:
    from src.cli.debug import _select_order_safe_label
    frame_candidates: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for candidate in candidates:
        blockers = candidate.get("blocker_classes")
        if not isinstance(blockers, list) or "stack-layout" not in blockers:
            continue
        frame_delta = _first_int(candidate.get("frame_delta"))
        source_retained = candidate.get("source_retained")
        if not isinstance(source_retained, str):
            continue
        hint = frame_delta if frame_delta is not None and frame_delta > 0 else None
        frame_candidate = {
            "label": candidate.get("label"),
            "rank": candidate.get("rank"),
            "source_retained": source_retained,
            "pcdump_path": candidate.get("pcdump_path"),
            "candidate_frame_delta": frame_delta,
            "remaining_frame_delta": frame_delta,
            "frame_reservation_bytes_hint": hint,
            "registers": candidate.get("registers"),
            "evaluation": candidate.get("frame_transform_probe_evaluation"),
        }
        target_score = candidate.get("target_score")
        if isinstance(target_score, Mapping):
            frame_candidate["target_score"] = dict(target_score)
        frame_candidates.append(frame_candidate)
        command_parts = [
            "melee-agent",
            "debug",
            "mutate",
            "frame-transform-search",
        ]
        if function:
            command_parts.extend(["-f", function])
        command_parts.extend(["--source-file", source_retained])
        if hint is not None:
            command_parts.extend(["--frame-reservation-bytes", str(hint)])
        if campaign_dir is not None:
            label = _select_order_safe_label(str(candidate.get("label") or "candidate"))
            command_parts.extend([
                "--output-dir",
                str(Path(campaign_dir) / "frame-repair" / label),
            ])
        command_parts.append("--json")
        actions.append({
            "kind": "run-frame-transform-search",
            "candidate_label": candidate.get("label"),
            "command_hint": " ".join(shlex.quote(part) for part in command_parts),
        })

    if not frame_candidates:
        return {
            "status": "not-applicable",
            "reason": "no-stack-layout-terminal-candidates",
            "candidates": [],
            "actions": [],
        }
    if any(candidate.get("evaluation") for candidate in frame_candidates):
        status = "evaluated"
        terminal_blocker = None
    else:
        status = "blocked"
        terminal_blocker = "frame-transform-not-materialized"
    return {
        "status": status,
        "terminal_blocker": terminal_blocker,
        "candidates": frame_candidates,
        "actions": actions,
    }
def _select_order_terminal_owner_probe_summary(
    leads: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    summary = {
        "ranked_local_candidates": 0,
        "materialized_local_candidates": 0,
        "ranked_indexed_byte_candidates": 0,
        "materialized_indexed_byte_candidates": 0,
        "field_load_source_candidates": 0,
        "materialized_field_load_source_candidates": 0,
        "field_load_terminal_blockers": [],
        "param_alias_source_candidates": 0,
        "materialized_param_alias_source_candidates": 0,
        "param_alias_terminal_blockers": [],
        "reasons": {},
    }

    def add_reasons(raw: object) -> None:
        if not isinstance(raw, Mapping):
            return
        reasons = raw.get("reasons")
        if not isinstance(reasons, Mapping):
            return
        counts = summary["reasons"]
        assert isinstance(counts, dict)
        for reason, count in reasons.items():
            if not isinstance(reason, str) or not reason:
                continue
            counts[reason] = counts.get(reason, 0) + (_first_int(count, 0) or 0)

    for lead in leads:
        diag = lead.get("source_probe_diagnostic")
        if not isinstance(diag, Mapping):
            continue
        raw_local = diag.get("ranked_source_owner_candidates")
        if isinstance(raw_local, list):
            summary["ranked_local_candidates"] += len([
                item for item in raw_local if isinstance(item, Mapping)
            ])
        materialized_local = diag.get("materialized_ranked_source_owner_candidates")
        if isinstance(materialized_local, list):
            summary["materialized_local_candidates"] += len([
                item for item in materialized_local if isinstance(item, Mapping)
            ])
        add_reasons(diag.get("ranked_source_owner_materialization_summary"))

        synthetic = diag.get("synthetic_source_probe")
        if isinstance(synthetic, Mapping):
            raw_indexed = synthetic.get("ranked_indexed_byte_source_candidates")
            if isinstance(raw_indexed, list):
                summary["ranked_indexed_byte_candidates"] += len([
                    item for item in raw_indexed if isinstance(item, Mapping)
                ])
            materialized_indexed = synthetic.get(
                "materialized_ranked_indexed_byte_source_candidates"
            )
            if isinstance(materialized_indexed, list):
                summary["materialized_indexed_byte_candidates"] += len([
                    item for item in materialized_indexed
                    if isinstance(item, Mapping)
                ])
            add_reasons(
                synthetic.get("ranked_indexed_byte_materialization_summary")
            )
        else:
            add_reasons(diag.get("ranked_indexed_byte_materialization_summary"))

        raw_field_load = diag.get("field_load_source_candidates")
        if isinstance(raw_field_load, list):
            summary["field_load_source_candidates"] += len([
                item for item in raw_field_load if isinstance(item, Mapping)
            ])
        materialized_field_load = diag.get(
            "materialized_field_load_source_candidates"
        )
        if isinstance(materialized_field_load, list):
            materialized_count = len([
                item for item in materialized_field_load
                if isinstance(item, Mapping)
            ])
            summary["materialized_field_load_source_candidates"] += materialized_count
            if not isinstance(raw_field_load, list):
                summary["field_load_source_candidates"] += materialized_count
        add_reasons(diag.get("field_load_materialization_summary"))
        terminal_blocker = diag.get("terminal_blocker")
        if (
            isinstance(terminal_blocker, str)
            and terminal_blocker.startswith("field-load-")
        ):
            summary["field_load_terminal_blockers"].append(terminal_blocker)
        raw_param_alias = diag.get("param_alias_source_candidates")
        if isinstance(raw_param_alias, list):
            summary["param_alias_source_candidates"] += len([
                item for item in raw_param_alias if isinstance(item, Mapping)
            ])
        materialized_param_alias = diag.get(
            "materialized_param_alias_source_candidates"
        )
        if isinstance(materialized_param_alias, list):
            materialized_count = len([
                item for item in materialized_param_alias
                if isinstance(item, Mapping)
            ])
            summary[
                "materialized_param_alias_source_candidates"
            ] += materialized_count
            if not isinstance(raw_param_alias, list):
                summary["param_alias_source_candidates"] += materialized_count
        add_reasons(diag.get("param_alias_materialization_summary"))
        if isinstance(terminal_blocker, str) and terminal_blocker.startswith("param-"):
            summary["param_alias_terminal_blockers"].append(terminal_blocker)

    if summary["field_load_terminal_blockers"]:
        summary["field_load_terminal_blockers"] = sorted(
            set(summary["field_load_terminal_blockers"])
        )
    if summary["param_alias_terminal_blockers"]:
        summary["param_alias_terminal_blockers"] = sorted(
            set(summary["param_alias_terminal_blockers"])
        )

    ranked_total = (
        int(summary["ranked_local_candidates"])
        + int(summary["ranked_indexed_byte_candidates"])
        + int(summary["field_load_source_candidates"])
        + int(summary["param_alias_source_candidates"])
    )
    if ranked_total <= 0:
        return None
    materialized_total = (
        int(summary["materialized_local_candidates"])
        + int(summary["materialized_indexed_byte_candidates"])
        + int(summary["materialized_field_load_source_candidates"])
        + int(summary["materialized_param_alias_source_candidates"])
    )
    summary["ranked_candidates"] = ranked_total
    summary["materialized_candidates"] = materialized_total
    summary["status"] = (
        "materialized" if materialized_total > 0 else "blocked"
    )
    if materialized_total == 0:
        field_load_blockers = summary["field_load_terminal_blockers"]
        param_alias_blockers = summary["param_alias_terminal_blockers"]
        summary["terminal_blocker"] = (
            field_load_blockers[0]
            if field_load_blockers
            else param_alias_blockers[0]
            if param_alias_blockers
            else "ranked-owner-candidates-not-materializable"
        )
    return summary
def _select_order_target_order_actionability(
    *,
    ranked_variants: Iterable[Mapping[str, Any]],
    force_phys: Mapping[int, int],
    diagnostic_buckets: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, Any]:
    by_pair: dict[tuple[int, int], dict[str, Any]] = {}
    any_improved = False
    for variant in ranked_variants:
        objective = variant.get("objective")
        if not isinstance(objective, Mapping):
            continue
        any_improved = any_improved or objective.get("target_order_improved") is True
        target_orders = objective.get("target_orders")
        if not isinstance(target_orders, list):
            continue
        for row in target_orders:
            if not isinstance(row, Mapping):
                continue
            first = _select_order_coerce_int(row.get("first_virtual"))
            second = _select_order_coerce_int(row.get("second_virtual"))
            if first is None or second is None:
                continue
            pair = (first, second)
            item = by_pair.setdefault(
                pair,
                {
                    "target_order": [first, second],
                    "baseline_satisfied": False,
                    "candidate_satisfied": False,
                    "improved": False,
                },
            )
            item["baseline_satisfied"] = (
                item["baseline_satisfied"]
                or row.get("baseline_satisfied") is True
            )
            item["candidate_satisfied"] = (
                item["candidate_satisfied"]
                or row.get("candidate_satisfied") is True
            )
            item["improved"] = item["improved"] or row.get("improved") is True
            any_improved = any_improved or row.get("improved") is True
    ordered = [by_pair[pair] for pair in sorted(by_pair)]
    already = [
        item["target_order"]
        for item in ordered
        if item["baseline_satisfied"]
    ]
    non_satisfied = [
        item["target_order"]
        for item in ordered
        if not item["baseline_satisfied"]
    ]
    force_hits = sorted(
        int(key.removeprefix("force-phys-hit-"))
        for key, rows in diagnostic_buckets.items()
        if key.startswith("force-phys-hit-") and rows
        and key.removeprefix("force-phys-hit-").isdigit()
    )
    suggested = _select_order_suggest_non_satisfied_targets(
        already_satisfied=already,
        force_phys=force_phys,
    )
    return {
        "already_satisfied_target_orders": already,
        "non_satisfied_target_orders": non_satisfied,
        "all_baseline_satisfied": bool(ordered) and len(already) == len(ordered),
        "any_target_order_improved": any_improved,
        "force_phys_hits": force_hits,
        "suggested_target_orders": suggested,
    }
def _select_order_suggest_non_satisfied_targets(
    *,
    already_satisfied: Sequence[Sequence[int]],
    force_phys: Mapping[int, int],
) -> list[list[int]]:
    pairs = [
        (int(pair[0]), int(pair[1]))
        for pair in already_satisfied
        if len(pair) == 2
    ]
    if not pairs:
        return []
    second_counts: dict[int, int] = {}
    for _, second in pairs:
        second_counts[second] = second_counts.get(second, 0) + 1
    product = max(second_counts, key=lambda key: (second_counts[key], -key))
    supports = [first for first, second in pairs if second == product]
    force_keys = [
        key for key in sorted(_select_order_int_mapping(force_phys))
        if key != product and key not in supports
    ]
    suggestions: list[list[int]] = []
    if force_keys:
        suggestions.append([product, force_keys[0]])
    suggestions.extend([product, support] for support in supports)
    deduped: list[list[int]] = []
    for pair in suggestions:
        if pair not in deduped:
            deduped.append(pair)
    return deduped
def _select_order_coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return None
def _select_order_already_satisfied_support_order_action(
    actionability: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "kind": "derive-non-satisfied-sticky-pool-targets",
        "avoid_target_orders": list(
            actionability.get("already_satisfied_target_orders") or []
        ),
        "suggested_target_orders": list(
            actionability.get("suggested_target_orders") or []
        ),
        "reason": (
            "support-before-product orders are already baseline-satisfied; "
            "use product-before-row or inverse support orders"
        ),
    }
def _select_order_terminal_summary_blocker_classes(
    *,
    dominant_blocker: str | None,
    source_bridge_summary: Mapping[str, Any],
    class_id: int | None,
) -> list[str]:
    raw_classes = source_bridge_summary.get("blocker_classes")
    blocker_classes: set[str] = set()
    if isinstance(raw_classes, list):
        blocker_classes = {
            str(item) for item in raw_classes
            if isinstance(item, str) and item
    }
    if dominant_blocker == "source-probes-exhausted":
        blocker_classes.add("transform-family-exhausted")
    if (
        dominant_blocker == "terminal-allocator-ceiling"
        or "wrong-register" in blocker_classes
    ):
        blocker_classes.add("current-source-shape-allocator-ceiling")
    if class_id != 1:
        blocker_classes.add("missing-degree-zero-fpr-attribution")
    return sorted(blocker_classes)
def _select_order_terminal_summary_best_retained_variants(
    ranked_variants: Iterable[Mapping[str, Any]],
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    from src.cli.debug import _select_order_variant_target_score
    retained: list[dict[str, Any]] = []
    for variant in ranked_variants:
        if variant.get("status") != "ok":
            continue
        source_retained = variant.get("source_retained") or variant.get("path")
        if not isinstance(source_retained, str) or not source_retained.endswith(".c"):
            continue
        item = {
            "label": variant.get("label"),
            "rank": variant.get("rank"),
            "operator": variant.get("operator"),
            "path": variant.get("path"),
            "source_retained": source_retained,
            "registers": _select_order_source_bridge_variant_registers(variant),
            "residual_analysis": variant.get("residual_analysis"),
            "source_hunk": variant.get("source_hunk"),
        }
        target_score = _select_order_variant_target_score(variant)
        if target_score is not None:
            item["target_score"] = target_score
        retained.append(item)
        if len(retained) >= limit:
            break
    return retained
_SELECT_ORDER_VIRTUAL_OPERAND_RE = re.compile(r"(?<![A-Za-z0-9_])([rf])(\d+)\b")
def _select_order_virtual_operands_from_expression(expression: object) -> list[int]:
    if not isinstance(expression, str):
        return []
    operands = [
        int(value)
        for _kind, value in _SELECT_ORDER_VIRTUAL_OPERAND_RE.findall(expression)
    ]
    return operands[1:] if len(operands) > 1 else []
@inspect_app.command(name="tiebreak")
def inspect_tiebreak(
    function: Annotated[str, typer.Option("--function", "-f")],
    pcdump: Annotated[Optional[Path], typer.Option("--pcdump")] = None,
    register_class: Annotated[str, typer.Option(
        "--class", help="Register class to analyze: auto, gpr/r/0, or fpr/f/1.")] = "auto",
    ig_targets: Annotated[str, typer.Option(
        "--ig", help="Function/class-scoped COLORGRAPH ig_idx values to report, "
        "e.g. 88,f48,1:48. Same ig_idx values can appear in other functions.")] = "",
    what_if: Annotated[str, typer.Option(
        "--what-if", help="Perturbation: 'add-interferer T:N', 'remove-edge "
        "A:B', 'move T:before:M', or 'move T:after:M' (before/after differ by "
        "one select slot). Predicts T's register under it.")] = "",
    validate_only: Annotated[bool, typer.Option("--validate-only")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Register-coloring tiebreak surrogate: predict assignments from the
    interference graph (G1, validated 100% on non-truncated functions) and run
    what-ifs (add/remove an interference edge, or move a node in select order)
    to find a source-actionable lever for a coloring tiebreak. Abstains
    (exit 3) when the function's G1 isn't perfect (e.g. interferer-list
    truncation corrupts the dispense), so what-ifs are never trusted blindly."""
    from src.cli.debug import DEFAULT_MELEE_ROOT, _resolve_pcdump_path
    from ...mwcc_debug import tiebreak as tb

    pcdump_path = _resolve_pcdump_path(pcdump, function, DEFAULT_MELEE_ROOT)
    try:
        class_id = _resolve_tiebreak_class(tb, register_class, ig_targets, what_if)
    except ValueError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2)

    ig = tb.load_ig(
        pcdump_path.read_text(),
        function,
        class_id=class_id,
        fallback_first=register_class.strip().lower() == "auto" and class_id == 0,
    )
    if ig is None:
        label = _tiebreak_class_label(tb, class_id)
        typer.secho(f"{function}: no {label} COLORGRAPH section in pcdump",
                    fg="red", err=True)
        raise typer.Exit(2)
    g1 = tb.validate_g1(ig, function)
    trunc = sum(1 for n in ig.nodes.values() if n.incomplete)

    if json_out:
        import json as _json
        out = {"function": function, "class_id": ig.class_id,
               "register_class": _tiebreak_class_label(tb, ig.class_id),
               "ig_scope": {
                   "function": function,
                   "class_id": ig.class_id,
                   "note": (
                       "COLORGRAPH ig_idx values are scoped to the selected "
                       "function and register class; the same ig_idx values can "
                       "appear in other functions in the same TU dump."
                   ),
               },
               "g1_rate": g1.rate, "g1_total": g1.total,
               "truncated_nodes": trunc, "mismatches": g1.mismatches}
        if not validate_only and what_if:
            wf = _parse_and_run_tiebreak_whatif(tb, ig, what_if)
            out["what_if"] = _tiebreak_whatif_payload(wf) if wf else None
        print(_json.dumps(out, indent=2))
        return

    prefix = tb.register_prefix(ig.class_id)
    typer.echo(f"tiebreak {function}: class {ig.class_id} ({prefix}) "
               f"G1 {g1.correct}/{g1.total} "
               f"({g1.rate*100:.1f}%), {trunc} truncated node(s)")
    typer.echo(
        f"  ig_idx scope: function={function} class={ig.class_id}; "
        "same ig_idx values can appear in other functions in this TU dump"
    )
    if validate_only:
        for ig_i, pred, obs in g1.mismatches[:20]:
            typer.echo(
                f"  mismatch ig{ig_i}: pred {_format_tiebreak_reg(tb, ig, pred)} "
                f"obs {_format_tiebreak_reg(tb, ig, obs)}"
            )
        raise typer.Exit(0 if g1.rate == 1.0 else 3)

    # report requested nodes' baseline prediction vs observed
    base = tb.predict_assignments(ig)
    for tok in (t.strip() for t in ig_targets.split(",") if t.strip()):
        n = _parse_tiebreak_token_for_ig(tb, ig, tok)
        if n is None:
            typer.secho(f"could not parse --ig token {tok!r}", fg="red", err=True)
            raise typer.Exit(2)
        node = ig.nodes.get(n)
        if node is None:
            typer.echo(f"  ig{n}: not in graph")
            continue
        typer.echo(f"  ig{n}: observed {_format_tiebreak_reg(tb, ig, node.observed_reg)} "
                   f"predicted {_format_tiebreak_reg(tb, ig, base.get(n))} "
                   f"degree={node.array_size}"
                   f"{' [TRUNCATED]' if node.incomplete else ''}")

    if what_if:
        if g1.rate != 1.0:
            typer.secho(f"ABSTAIN: G1 is {g1.rate*100:.0f}% for {function} "
                        f"(truncation/spill) — what-if not trustworthy here.",
                        fg="yellow", err=True)
            raise typer.Exit(3)
        wf = _parse_and_run_tiebreak_whatif(tb, ig, what_if)
        if wf is None:
            typer.secho(f"could not parse --what-if {what_if!r}", fg="red", err=True)
            raise typer.Exit(2)
        verb = "FLIPS" if wf.flips else "no change"
        typer.echo(f"  what-if [{wf.description}] on ig{wf.target_ig}: "
                   f"predicted {_format_tiebreak_reg(tb, ig, wf.predicted_reg)} "
                   f"-> {_format_tiebreak_reg(tb, ig, wf.perturbed_reg)} "
                   f"({verb}; abstract diagnostic, "
                   f"not a source-realizability proof)")
        raise typer.Exit(0)
_TIEBREAK_TOKEN_PATTERN = r"(?:[01]:)?[rRfF]?\d+"
_TIEBREAK_TOKEN_RE = re.compile(rf"^({_TIEBREAK_TOKEN_PATTERN})$")
_TIEBREAK_PAIR_RE = re.compile(
    rf"^({_TIEBREAK_TOKEN_PATTERN}):({_TIEBREAK_TOKEN_PATTERN})$"
)
_TIEBREAK_MOVE_RE = re.compile(
    rf"^({_TIEBREAK_TOKEN_PATTERN}):(before|after):({_TIEBREAK_TOKEN_PATTERN})$"
)
_TIEBREAK_WHATIF_REALIZABILITY = (
    "abstract-select-graph-not-source-realizability-proof"
)
_TIEBREAK_WHATIF_NOTE = (
    "abstract diagnostic only; not a source-realizability proof"
)
def _tiebreak_whatif_payload(wf) -> dict:
    payload = dict(wf.__dict__)
    payload["diagnostic_only"] = True
    payload["realizability"] = _TIEBREAK_WHATIF_REALIZABILITY
    payload["note"] = _TIEBREAK_WHATIF_NOTE
    return payload
def _tiebreak_class_label(tb, class_id: int) -> str:
    if class_id == 1:
        return "class-1/FPR"
    if class_id == 0:
        return "class-0/GPR"
    return f"class-{class_id}"
def _format_tiebreak_reg(tb, ig, reg: int | None) -> str:
    if reg is None:
        return "?"
    if reg == tb.SPILL:
        return "spill"
    return f"{tb.register_prefix(ig.class_id)}{reg}"
def _parse_tiebreak_token(tb, token: str, default_class: int) -> tuple[int, int] | None:
    token = token.strip()
    if _TIEBREAK_TOKEN_RE.match(token) is None:
        return None
    explicit_class: int | None = None
    if ":" in token:
        class_part, token = token.split(":", 1)
        try:
            explicit_class = tb.parse_register_class(class_part)
        except ValueError:
            return None
    prefix_class: int | None = None
    if token[:1].lower() in {"r", "f"}:
        prefix_class = 1 if token[0].lower() == "f" else 0
        token = token[1:]
    if explicit_class is not None and prefix_class is not None and explicit_class != prefix_class:
        return None
    class_id = explicit_class if explicit_class is not None else (
        prefix_class if prefix_class is not None else default_class
    )
    return class_id, int(token)
def _parse_tiebreak_token_for_ig(tb, ig, token: str) -> int | None:
    parsed = _parse_tiebreak_token(tb, token, ig.class_id)
    if parsed is None:
        return None
    class_id, idx = parsed
    return idx if class_id == ig.class_id else None
def _infer_tiebreak_class(tb, ig_targets: str, what_if: str) -> int:
    inferred = 0
    for token in re.findall(_TIEBREAK_TOKEN_PATTERN, ",".join([ig_targets, what_if])):
        parsed = _parse_tiebreak_token(tb, token, inferred)
        if parsed is None:
            continue
        class_id, _idx = parsed
        if class_id == 1:
            inferred = 1
    return inferred
def _resolve_tiebreak_class(tb, register_class: str, ig_targets: str, what_if: str) -> int:
    value = register_class.strip().lower()
    if value in {"", "auto"}:
        return _infer_tiebreak_class(tb, ig_targets, what_if)
    return tb.parse_register_class(value)
def _parse_and_run_tiebreak_whatif(tb, ig, spec_str):
    """Parse a --what-if DSL token and run it. Returns a WhatIf or None."""
    parts = spec_str.strip().split()
    if not parts:
        return None
    kind = parts[0]
    arg = parts[1] if len(parts) > 1 else ""
    try:
        if kind == "add-interferer":
            m = _TIEBREAK_PAIR_RE.match(arg)
            if m is None:
                return None
            t = _parse_tiebreak_token_for_ig(tb, ig, m.group(1))
            n = _parse_tiebreak_token_for_ig(tb, ig, m.group(2))
            if t is None or n is None:
                return None
            return tb.what_if(ig, t, add_interferers={n})
        if kind == "remove-edge":
            m = _TIEBREAK_PAIR_RE.match(arg)
            if m is None:
                return None
            a = _parse_tiebreak_token_for_ig(tb, ig, m.group(1))
            b = _parse_tiebreak_token_for_ig(tb, ig, m.group(2))
            if a is None or b is None:
                return None
            return tb.what_if(ig, a, remove_edges={frozenset((a, b))})
        if kind == "move":
            # "move T:before:M" / "move T:after:M". The middle token is
            # semantic — before and after differ by one select slot and can
            # yield different registers; reject anything else loudly.
            match = _TIEBREAK_MOVE_RE.match(arg)
            if match is None:
                return None
            t = _parse_tiebreak_token_for_ig(tb, ig, match.group(1))
            where = match.group(2)
            m = _parse_tiebreak_token_for_ig(tb, ig, match.group(3))
            if t is None or m is None:
                return None
            if where == "before":
                return tb.what_if(ig, t, move_before=m)
            if where == "after":
                return tb.what_if(ig, t, move_after=m)
            return None
    except (ValueError, KeyError):
        return None
    return None
def _register_window_rotation_desired_regs(
    classification: Mapping[str, Any] | None,
    *,
    class_id: int,
) -> set[int]:
    if class_id != 0 or not isinstance(classification, Mapping):
        return set()

    regs: set[int] = set()
    guidance = classification.get("register_allocation_guidance")
    if isinstance(guidance, Mapping):
        pairs = guidance.get("callee_swap_pairs")
        if isinstance(pairs, list):
            for pair in pairs:
                if not isinstance(pair, list):
                    continue
                for reg_name in pair:
                    if (
                        isinstance(reg_name, str)
                        and len(reg_name) > 1
                        and reg_name[0] == "r"
                        and reg_name[1:].isdigit()
                    ):
                        regs.add(int(reg_name[1:]))

    rotation = classification.get("register_window_rotation")
    if isinstance(rotation, Mapping):
        window = rotation.get("saved_gpr_window")
        if isinstance(window, Mapping):
            first = window.get("first_saved_reg")
            last = window.get("last_saved_reg")
            if (
                isinstance(first, str)
                and isinstance(last, str)
                and first.startswith("r")
                and last.startswith("r")
                and first[1:].isdigit()
                and last[1:].isdigit()
            ):
                start = int(first[1:])
                end = int(last[1:])
                if start <= end:
                    regs.update(range(start, end + 1))
    return regs
def _order_move_for_insertion_slot(
    order_without_target: list[int],
    slot: int,
) -> tuple[str, int] | None:
    if not order_without_target:
        return None
    if slot <= 0:
        return ("before", order_without_target[0])
    if slot >= len(order_without_target):
        return ("after", order_without_target[-1])
    return ("before", order_without_target[slot])
def _register_tiebreak_order_flip_leads(
    tb,
    ig,
    *,
    vector_targets: list[dict],
    desired_regs: set[int],
    max_leads: int = 5,
) -> list[dict]:
    """Find canonical order moves for window-rotation register flips.

    `debug solve coloring` needs a force-phys objective, but window rotations can
    leave the best suspect already assigned to its checkdiff-derived register.
    This fallback treats those force-vector targets as a suspect list, scans
    insertion slots, and reports the farthest useful slot per target/register
    pair. Slot canonicalization avoids dumping hundreds of equivalent
    before/after anchors for the same allocator window shift.
    """
    base = tb.predict_assignments(ig)
    order = list(ig.select_order)
    best_by_target_reg: dict[tuple[int, int], dict] = {}

    for target in vector_targets:
        try:
            ig_idx = int(target["ig_idx"])
        except (KeyError, TypeError, ValueError):
            continue
        node = ig.nodes.get(ig_idx)
        if node is None or node.incomplete:
            continue

        target_desired = set(desired_regs)
        if target.get("already_target") is not True:
            try:
                target_desired.add(int(target["target_reg"]))
            except (KeyError, TypeError, ValueError):
                pass
        target_desired.discard(base.get(ig_idx))
        if not target_desired:
            continue

        try:
            original_slot = order.index(ig_idx)
        except ValueError:
            continue
        order_without_target = [idx for idx in order if idx != ig_idx]
        for slot in range(len(order_without_target) + 1):
            if slot == original_slot:
                continue
            moved_order = (
                order_without_target[:slot]
                + [ig_idx]
                + order_without_target[slot:]
            )
            perturbed = tb.predict_assignments(ig, order=moved_order).get(ig_idx)
            if perturbed not in target_desired:
                continue
            move = _order_move_for_insertion_slot(order_without_target, slot)
            if move is None:
                continue
            move_distance = abs(slot - original_slot)
            key = (ig_idx, int(perturbed))
            lead = {
                "target_ig": ig_idx,
                "observed_reg": node.observed_reg,
                "predicted_reg": base.get(ig_idx),
                "perturbed_reg": int(perturbed),
                "order_move": [move[0], move[1]],
                "degree": node.array_size,
                "move_distance": move_distance,
                "already_target": bool(target.get("already_target")),
                "checkdiff_target_reg": target.get("target_reg"),
                "checkdiff_target_reg_name": target.get("target_reg_name"),
            }
            existing = best_by_target_reg.get(key)
            if existing is None or move_distance > existing["move_distance"]:
                best_by_target_reg[key] = lead

    leads = list(best_by_target_reg.values())
    leads.sort(key=lambda lead: (
        -int(lead["degree"]),
        -int(lead["move_distance"]),
        int(lead["target_ig"]),
        int(lead["perturbed_reg"]),
    ))
    return leads[:max_leads]
def _node_set_split_compile_signature_and_pcdump(
    path: Path,
    *,
    label: str,
    function: str,
    class_id: int,
    melee_root: Path,
    timeout: int,
    unit_source: Path | None = None,
    full_unit_source: bool = False,
):
    """Compile a source variant and return its allocator signature + pcdump."""
    from src.cli.debug import (  # noqa: PLC0415
        _node_set_split_same_tu_compile_path,
        find_function,
        parse_hook_events,
    )
    from ...mwcc_debug.diff_capture import DiffInput, compile_source_variant
    from ...mwcc_debug.simplify_search import baseline_signature

    with _node_set_split_same_tu_compile_path(
        path,
        function=function,
        melee_root=melee_root,
        unit_source=unit_source,
        full_unit_source=full_unit_source,
    ) as compile_path:
        diff_input = DiffInput(
            label=label,
            token=str(compile_path),
            kind="source",
            path=compile_path,
        )
        pcdump_text = compile_source_variant(
            diff_input,
            function=function,
            melee_root=melee_root,
            timeout=timeout,
            unit_source=unit_source,
        )
    events = find_function(parse_hook_events(pcdump_text), function)
    if events is None:
        raise ValueError(f"compiled pcdump has no events for {function}")
    return baseline_signature(events, class_id=class_id), pcdump_text
def _fresh_node_set_split_baseline_pct(
    *,
    unit: str,
    function: str,
    melee_root: Path,
    timeout: float | None = None,
    deadline: float | None = None,
) -> tuple[float | None, str | None]:
    """Refresh the real tree baseline before candidate delta scoring."""
    from src.cli.debug import _build_and_match_with_diagnostic
    kwargs: dict[str, Any] = {}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if deadline is not None:
        kwargs["deadline"] = deadline
    return _build_and_match_with_diagnostic(
        unit,
        function,
        melee_root,
        **kwargs,
    )
def _safe_filename(value: str, *, max_bytes: int = 180) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "candidate"
    if len(safe.encode("utf-8")) <= max_bytes:
        return safe
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    suffix = f"-{digest}"
    keep_bytes = max(1, max_bytes - len(suffix.encode("utf-8")))
    stem = safe.encode("utf-8")[:keep_bytes].decode("ascii", "ignore")
    stem = stem.rstrip("._-") or "candidate"
    return f"{stem}{suffix}"
@inspect_app.command(name="explain-diff")
def inspect_explain_diff(
    function_or_path: Annotated[
        str,
        typer.Argument(
            help="Function name (auto-runs checkdiff) or path to a checkdiff JSON file.",
        ),
    ],
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit structured diagnosis as JSON."),
    ] = False,
):
    """Unified diff diagnosis: read checkdiff JSON (or auto-generate it for a
    function) and produce a structured, ranked list of recommendations with
    specific source-level actions and estimated costs."""
    import json
    from pathlib import Path
    from ...mwcc_debug.explain_diff import (
        parse_checkdiff_json, run_checkdiff, format_diagnosis, produce_diagnosis,
    )

    # Determine whether the argument is a file path or a function name
    function = None
    if os.path.isfile(function_or_path):
        data = parse_checkdiff_json(function_or_path)
        if data:
            function = data.get("function")
    else:
        function = function_or_path
        melee_root = Path.cwd()
        data = run_checkdiff(function, str(melee_root))

    if data is None:
        typer.echo(
            f"Error: could not load checkdiff data for {function_or_path}",
            err=True,
        )
        raise typer.Exit(1)

    if json_out:
        diagnosis = produce_diagnosis(data, function)
        typer.echo(json.dumps(diagnosis, indent=2))
    else:
        text = format_diagnosis(data, function)
        typer.echo(text)
@inspect_app.command(name="explain-virtual")
def inspect_explain_virtual(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    virtuals: Annotated[
        str,
        typer.Option(
            "--virtuals",
            help="Comma-separated virtual registers to explain, e.g. r37,r40.",
        ),
    ] = "",
    pairs: Annotated[
        str,
        typer.Option(
            "--pairs",
            help=(
                "Comma-separated virtual pairs to explain, e.g. "
                "r37/r40,r43/r33."
            ),
        ),
    ] = "",
    ig: Annotated[
        str,
        typer.Option(
            "--ig",
            help=(
                "Comma-separated COLORGRAPH ig_idx values to explain, e.g. "
                "88,90. ig_idx N maps to virtual rN; this is sugar for "
                "--virtuals so you can query straight from a COLORGRAPH dump."
            ),
        ),
    ] = "",
    all_virtuals: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Explain every virtual register observed in pre-coloring pcode.",
        ),
    ] = False,
    reg_class: Annotated[
        Optional[str],
        typer.Option(
            "--class",
            help="Register class for allocator lookup (gpr/int or fp/fpr).",
        ),
    ] = "gpr",
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Path to pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "C source file used for source/interference attribution. "
                "Defaults to the repo source for the function when available."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Explain virtual-register source/interference attribution."""
    from src.cli.debug import DEFAULT_MELEE_ROOT, _find_unit_for_function, _parse_virtual_pair_csv, _resolve_pcdump_path
    from ...mwcc_debug.virtual_attribution import (
        explain_virtuals,
        list_pcode_virtuals,
        render_virtual_attribution_text,
    )

    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=False,
    )
    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            candidate = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if candidate.is_file():
                source_text = candidate.read_text()
                try:
                    source_label = str(candidate.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(candidate)

    pcdump_text = pcdump_path.read_text()
    virtual_list = _parse_virtual_csv(virtuals)
    pair_list = _parse_virtual_pair_csv(pairs)
    if ig.strip():
        # ig_idx N maps to virtual rN (the allocator node and the pre-coloring
        # virtual share the same number); accept bare or r-prefixed values.
        for tok in ig.split(","):
            tok = tok.strip().lstrip("rR")
            if tok:
                if not tok.isdigit():
                    raise typer.BadParameter(f"invalid --ig value: {tok!r}")
                vreg = int(tok)  # virtual_list holds ints; ig_idx N == virtual rN
                if vreg not in virtual_list:
                    virtual_list.append(vreg)
    if all_virtuals:
        virtual_list = list(list_pcode_virtuals(pcdump_text, function))
    if not virtual_list and not pair_list:
        typer.echo("--virtuals, --pairs, --ig, or --all is required.", err=True)
        raise typer.Exit(2)

    report = explain_virtuals(
        pcdump_text,
        function,
        virtuals=virtual_list,
        pairs=pair_list,
        source_text=source_text,
        source_file=source_label,
        reg_class=reg_class,
    )
    if json_out:
        print(json.dumps(report.to_dict(), indent=2))
        return
    print(render_virtual_attribution_text(report))
@inspect_app.command(name="explain-schedule")
def inspect_explain_schedule(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze.",
        ),
    ],
    force_schedule: Annotated[
        str,
        typer.Option(
            "--force-schedule",
            help=(
                "Target scheduler swap list to explain, e.g. "
                "'lwz:0x94>0x90,lwz:0xAC>0xA8'."
            ),
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Path to pcdump.txt. Auto-resolves from cache when omitted.",
        ),
    ] = None,
    source_file: Annotated[
        Optional[Path],
        typer.Option(
            "--source-file",
            help=(
                "C source file used for advisory IR/source provenance. "
                "Defaults to the repo source for the function when available."
            ),
        ),
    ] = None,
    checkdiff_json: Annotated[
        Optional[Path],
        typer.Option(
            "--checkdiff-json",
            help=(
                "Path to `tools/checkdiff.py <function> --format json` "
                "output; enables non-load code-offset schedule windows."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Explain observed scheduler windows for known force-schedule targets."""
    from src.cli.debug import DEFAULT_MELEE_ROOT, _find_unit_for_function, _resolve_pcdump_path, _validate_force_schedule
    from ...mwcc_debug.schedule_explain import (
        explain_schedule,
        render_json,
        render_text,
    )

    force_schedule = _validate_force_schedule(force_schedule)
    pcdump_path = _resolve_pcdump_path(
        pcdump,
        function,
        DEFAULT_MELEE_ROOT,
        require_fresh=False,
    )
    source_text = None
    source_label = None
    if source_file is not None:
        if not source_file.is_file():
            raise typer.BadParameter(f"source file not found: {source_file}")
        source_text = source_file.read_text()
        source_label = str(source_file)
    else:
        unit = _find_unit_for_function(function, DEFAULT_MELEE_ROOT)
        if unit is not None:
            candidate = DEFAULT_MELEE_ROOT / "src" / f"{unit}.c"
            if candidate.is_file():
                source_text = candidate.read_text()
                try:
                    source_label = str(candidate.relative_to(DEFAULT_MELEE_ROOT))
                except ValueError:
                    source_label = str(candidate)
    target_asm = None
    current_asm = None
    classification = None
    if checkdiff_json is not None:
        if not checkdiff_json.is_file():
            raise typer.BadParameter(f"checkdiff JSON not found: {checkdiff_json}")
        try:
            payload = json.loads(checkdiff_json.read_text())
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                f"invalid checkdiff JSON: {exc.msg}"
            ) from exc
        if not isinstance(payload, dict):
            raise typer.BadParameter("checkdiff JSON must be an object")
        payload_function = payload.get("function")
        if payload_function not in {None, function}:
            raise typer.BadParameter(
                f"checkdiff JSON is for {payload_function!r}, not {function!r}"
            )
        target_asm = payload.get("target_asm")
        current_asm = payload.get("current_asm")
        classification = payload.get("classification")
        if not isinstance(target_asm, list) or not isinstance(current_asm, list):
            raise typer.BadParameter(
                "checkdiff JSON must contain target_asm and current_asm arrays"
            )
    report = explain_schedule(
        pcdump_path.read_text(),
        function=function,
        force_schedule=force_schedule,
        source_text=source_text,
        source_file=source_label,
        target_asm=target_asm,
        current_asm=current_asm,
        checkdiff_classification=classification,
    )
    print(render_json(report) if json_out else render_text(report))
def _normalize_virtual_to_var_reg_class(value: str) -> str:
    key = value.strip().lower()
    if key in {"gpr", "int", "r", "0"}:
        return "gpr"
    if key in {"fpr", "fp", "float", "f", "1"}:
        return "fpr"
    raise typer.BadParameter(
        f"unknown register class {value!r}; expected gpr/r/0 or fpr/f/1"
    )
@inspect_app.command(name="virtual-to-var")
def virtual_to_var(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to look up (required).",
        ),
    ],
    virtual: Annotated[
        str,
        typer.Argument(
            help="Virtual register number (32+) or ig_idx. Accepts "
                 "'62' or 'r62' — the 'r' prefix is stripped so you "
                 "can copy-paste straight from analyze/guide output.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
    reg_class: Annotated[
        Optional[str],
        typer.Option(
            "--class",
            help="Register class for the inverse lookup: gpr/r/0 or fpr/f/1. "
                 "When omitted, infer from an r*/f* virtual token and "
                 "default to GPR for bare numbers.",
        ),
    ] = None,
) -> None:
    """Bridge inverse: given a virtual register, predict the source
    variable name (decl-order heuristic), including the variable's
    scope path (function-top vs nested-block). When no source variable
    binds to the requested virtual (compiler-introduced temps, spill
    nodes, etc.), falls back to showing the first defining IR op
    so you can correlate to the C source manually.
    """
    from src.cli.debug import DEFAULT_MELEE_ROOT, _abort_function_not_in_dump, _find_unit_for_function, _resolve_pcdump_path, parse_pcdump
    from ...mwcc_debug.symbol_bridge import (
        find_first_def,
        find_var_for_virtual,
    )

    # Accept 'r62' and 'f42' alongside bare numbers — easier to copy from
    # analyze/guide/explain output while preserving the old bare-GPR default.
    vstr = virtual.strip()
    inferred_class = None
    if vstr.lower().startswith("f"):
        inferred_class = "fpr"
        vstr = vstr[1:]
    elif vstr.lower().startswith("r"):
        inferred_class = "gpr"
        vstr = vstr[1:]
    try:
        virtual_int = int(vstr)
    except ValueError:
        typer.echo(
            f"invalid virtual register {virtual!r}; expected an integer "
            f"(optionally with 'r' or 'f' prefix).", err=True,
        )
        raise typer.Exit(2)
    virtual = virtual_int  # downstream code uses int form
    reg_class = _normalize_virtual_to_var_reg_class(
        reg_class or inferred_class or "gpr"
    )
    reg_kind = "f" if reg_class == "fpr" else "r"

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    text = pcdump_path.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre = fn.last_precolor_pass()
    if pre is None:
        typer.echo(
            f"no pre-coloring pass for {function}", err=True,
        )
        raise typer.Exit(3)

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    source_path = melee_root / "src" / f"{unit}.c"
    source = source_path.read_text()
    try:
        source_label = str(source_path.relative_to(melee_root))
    except ValueError:
        source_label = str(source_path)
    if reg_class == "fpr":
        from ...mwcc_debug.virtual_attribution import explain_virtuals
        report = explain_virtuals(
            text,
            function,
            virtuals=[virtual],
            source_text=source,
            source_file=source_label,
            reg_class=reg_class,
        )
        entry = report.virtuals[0]
        source_info = entry.source
        first = (
            source_info.first_def
            if source_info is not None and source_info.first_def is not None
            else entry.first_occurrence
        )
        assigned = (
            None
            if entry.assigned_reg is None
            else f"{reg_kind}{entry.assigned_reg}"
        )
        if json_out:
            payload = {
                "virtual": virtual,
                "register_class": reg_class,
                "class_id": entry.class_id,
                "ig_idx": entry.ig_idx,
                "assigned_reg": assigned,
                "status": entry.status,
                "found": False,
                "source": (
                    None if source_info is None else dataclasses.asdict(source_info)
                ),
                "first_def": None if first is None else dataclasses.asdict(first),
            }
            print(json.dumps(payload, indent=2))
        else:
            typer.echo(
                f"no source variable bound to {reg_kind}{virtual} in {function} "
                "(likely an FPR compiler-introduced temp or spill root).",
                err=True,
            )
            if first is not None:
                typer.echo("", err=True)
                typer.echo("first defining FPR op:", err=True)
                typer.echo(
                    f"  block {first.block_idx}: {first.opcode} {first.operands}",
                    err=True,
                )
            if assigned is not None:
                typer.echo(f"assigned physical: {assigned}", err=True)
        return

    binding = find_var_for_virtual(source, function, virtual, pre)

    if binding is None:
        call_return_source = _virtual_to_var_call_return_source(
            text,
            function=function,
            virtual=virtual,
            source_text=source,
            source_file=source_label,
        )
        if call_return_source is not None:
            if json_out:
                payload = {
                    "virtual": virtual,
                    "found": False,
                    "source": dataclasses.asdict(call_return_source),
                }
                print(json.dumps(payload, indent=2))
            else:
                print(
                    _render_virtual_to_var_call_return_source(
                        virtual,
                        function=function,
                        source=call_return_source,
                    )
                )
            return

        # Fallback: no source variable mapped (compiler temp, spill,
        # post-CSE intermediate, etc.). Surface the first-def IR op so
        # the agent can correlate to a C expression manually — e.g.,
        # `lwz r62, 44(r34)` means "r62 is something->field_at_0x2C
        # where something is in r34".
        first = find_first_def(virtual, pre)
        if json_out:
            payload: dict = {
                "virtual": virtual,
                "found": False,
            }
            if first is not None:
                payload["first_def"] = {
                    "block_idx": first.block_idx,
                    "opcode": first.opcode,
                    "operands": first.operands,
                    "annotations": first.annotations,
                }
            print(json.dumps(payload, indent=2))
        else:
            typer.echo(
                f"no source variable bound to r{virtual} in {function} "
                f"(likely a compiler-introduced temp — spill, CSE, or IV).",
                err=True,
            )
            if first is not None:
                typer.echo("", err=True)
                typer.echo("first defining op (in pre-coloring pass):", err=True)
                typer.echo(
                    f"  block {first.block_idx}: {first.opcode} {first.operands}",
                    err=True,
                )
                if first.annotations:
                    for a in first.annotations:
                        typer.echo(f"    {a}", err=True)
                typer.echo("", err=True)
                typer.echo(
                    "Hint: correlate the load address/offset back to a C "
                    "struct field, or trace the source register(s) to find "
                    "the originating expression.",
                    err=True,
                )
        return

    if json_out:
        from ...mwcc_debug.scope_path import format_for_display
        payload: dict = {
            "var_name": binding.var_name,
            "virtual": binding.virtual,
            "kind": binding.kind,
            "type": binding.type_str,
            "confidence": binding.confidence,
            "scope_path": list(binding.scope_path),
            "found": True,
        }
        print(json.dumps(payload, indent=2))
    else:
        from ...mwcc_debug.scope_path import format_for_display
        scope_str = format_for_display(binding.scope_path) if binding.scope_path else ""
        scope_suffix = f"  scope: {scope_str}" if scope_str else ""
        print(f"r{virtual}: {binding.var_name} ({binding.kind})")
        print(f"  type:    {binding.type_str}")
        print(f"  conf:    {binding.confidence}")
        if scope_suffix:
            print(scope_suffix)
def _virtual_to_var_call_return_source(
    pcdump_text: str,
    *,
    function: str,
    virtual: int,
    source_text: str,
    source_file: str,
):
    try:
        from ...mwcc_debug.virtual_attribution import explain_virtuals
        report = explain_virtuals(
            pcdump_text,
            function,
            virtuals=[virtual],
            source_text=source_text,
            source_file=source_file,
        )
    except Exception:
        return None
    entry = next(
        (candidate for candidate in report.virtuals if candidate.virtual == virtual),
        None,
    )
    source = None if entry is None else entry.source
    if source is None or source.kind != "call-return":
        return None
    return source
def _render_virtual_to_var_call_return_source(
    virtual: int,
    *,
    function: str,
    source,
) -> str:
    loc = ""
    if source.source_file and source.source_line is not None:
        loc = f" {source.source_file}:{source.source_line}"
        if source.source_col is not None:
            loc += f":{source.source_col}"
    expr = source.expression or source.call_symbol or "call return"
    name_suffix = f" -> {source.name}" if source.name else ""
    lines = [
        f"r{virtual}: {expr}{name_suffix} "
        f"(call-return/copy-chain){loc}",
        (
            "  note:   no declared local is bound directly to "
            f"r{virtual} in {function}; this virtual carries a copied "
            "call return."
        ),
    ]
    if source.call_symbol:
        lines.append(f"  callee: {source.call_symbol}")
    if source.first_def is not None:
        site = source.first_def
        lines.append(
            "  call:   "
            f"{site.pass_name} B{site.block_idx}:{site.instr_idx} "
            f"{site.opcode} {site.operands}"
        )
    if source.copy_chain:
        chain = " <- ".join(f"r{reg}" for reg in source.copy_chain)
        lines.append(f"  chain:  {chain}")
    if source.use_sites:
        for site in source.use_sites[:3]:
            lines.append(
                "  use:    "
                f"{site.pass_name} B{site.block_idx}:{site.instr_idx} "
                f"{site.opcode} {site.operands}"
            )
    return "\n".join(lines)
