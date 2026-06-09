"""Core harvest orchestration for taxonomy-driven harness sweeps."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Protocol

from src.attempt_evidence import (
    apply_terminal_attempt_overlay,
    is_active_terminal_attempt_row,
    load_terminal_attempt_evidence,
)
from src.mwcc_debug import cache as pcdump_cache
from src.mwcc_debug import local_safety
from src.mwcc_debug.diff_capture import (
    _env_with_child_hang_timeout,
    _run_with_process_group_timeout,
)
from src.mwcc_debug.source_patch import extract_function, replace_function

SCHEMA_VERSION = 1
TAXONOMY_RUN_STATUS_FILENAME = "run-status.json"
TAXONOMY_RECORDS_FILENAME = "taxonomy.records.jsonl"
VALIDATED_MATCH_PERCENT = 100.0
VALIDATED_EPSILON = 1e-6

HARNESS_FRAME_TRANSFORM = "frame-transform-search"
HARNESS_COALESCE = "coalesce-search"
HARNESS_SELECT_ORDER = "select-order-search"
HARNESS_INDEXED_STRUCT = "indexed-struct-search"
HARNESS_NAME_MAGIC_SOURCE = "name-magic-source-declarations"
HARNESS_CONTROL_FLOW_SHAPE = "control-flow-shape-search"
HARNESS_LIFETIME_LAYOUT = "lifetime-layout"
HARNESS_ALLOCATOR_PCDUMP_TRIAGE = "allocator-pcdump-triage"
REGISTERED_HARNESSES = {
    HARNESS_FRAME_TRANSFORM,
    HARNESS_COALESCE,
    HARNESS_SELECT_ORDER,
    HARNESS_INDEXED_STRUCT,
    HARNESS_NAME_MAGIC_SOURCE,
    HARNESS_CONTROL_FLOW_SHAPE,
    HARNESS_LIFETIME_LAYOUT,
    HARNESS_ALLOCATOR_PCDUMP_TRIAGE,
}
ALLOCATOR_PCDUMP_TRIAGE_REGS = "gpr-callee,gpr-volatile,r0"
ALLOCATOR_PCDUMP_TRIAGE_DETAIL_FIELDS = (
    "target_vector_actionability",
    "force_vector",
    "force_vector_runnable",
    "force_vector_recommended",
    "force_phys_csv",
    "force_vector_conflicts",
    "force_vector_verify",
    "force_vector_status",
    "force_vector_match",
    "unit",
    "targets",
    "results",
)
PREVIEW_FACET_FIELDS = (
    "primary",
    "subcategory",
    "source_actionability",
    "headline_tool",
    "frame_closability_tier",
    "name_magic_blocker",
)
TERMINAL_ATTEMPT_FACET_FIELDS = (
    "terminal_attempt_actionability",
    "terminal_attempt_blocker",
    "terminal_attempt_stale_check",
)
SOURCE_ACTIONABILITY_REBUCKET_FINGERPRINT_FIELDS = (
    "function",
    "match_percent",
    "primary",
    "subcategory",
    "source_actionability",
    "headline_tool",
    "actionability_reason",
    "name_magic_blocker",
    "name_magic_stop_kind",
    "name_magic_probe_count",
    "name_magic_reason",
    "file_path",
)
SOURCE_ACTIONABILITY_REBUCKET_ROW_TOOL_FIELDS = (
    "headline_tool",
    "frame_closability_tier",
    "next_command",
    "frame_next_command",
)
DATA_SYMBOL_NO_NAME_MAGIC_CANDIDATE_ACTIONABILITY = (
    "blocked-data-symbol-no-name-magic-candidate"
)
DATA_SYMBOL_BLOCKED_SOURCE_ACTIONABILITIES = {
    DATA_SYMBOL_NO_NAME_MAGIC_CANDIDATE_ACTIONABILITY,
    "blocked-data-symbol-unsupported-source-site",
    "blocked-data-symbol-ambiguous-relocation-pair",
    "blocked-data-symbol-unsupported-reloc-kind",
    "blocked-data-symbol-raw-diff-no-supported-data-symbol-pair",
    "blocked-data-symbol-no-name-magic-validation-failed",
    "blocked-data-symbol-ambiguous-sdata2-value",
    "blocked-data-symbol-sdata2-pool-order-dependent",
}

BLOCKER_UNSUPPORTED_HARNESS = "unsupported-harness"
BLOCKER_MISSING_SOURCE_FILE = "missing-source-file"
BLOCKER_MISSING_REGISTER_TARGET = "missing-register-target"
BLOCKER_HARNESS_EXIT_NONZERO = "harness-exit-nonzero"
BLOCKER_HARNESS_INVALID_JSON = "harness-invalid-json"
BLOCKER_NO_VALIDATED_CANDIDATE = "no-validated-candidate"
BLOCKER_NO_NAME_MAGIC_CANDIDATE = "no-name-magic-candidate"
BLOCKER_MALFORMED_SOURCE_CANDIDATE = "malformed-source-candidate"
BLOCKER_UNSAFE_LOCAL_PCDUMP_LANE = "unsafe-local-pcdump-lane"
MALFORMED_SOURCE_CANDIDATE_ACTIONABILITY = "candidate-generation-fidelity"
BLOCKER_APPLY_TRANSFER_FAILED = "apply-transfer-failed"
BLOCKER_APPLY_VALIDATION_FAILED = "apply-validation-failed"
BLOCKER_DECLARATION_APPLY_UNSUPPORTED = "declaration-apply-unsupported"
BLOCKER_ALLOCATOR_TARGET_VECTOR = "allocator-target-vector"
BLOCKER_ALLOCATOR_SOURCE_LIFETIME = "source-lifetime-callee-save-shape"
BLOCKER_ALLOCATOR_CURRENT_UNKNOWN = "allocator-current-unknown"
BLOCKER_ALLOCATOR_NO_TARGETS = "allocator-no-targets"
BLOCKER_ALLOCATOR_VECTOR_NOT_RUNNABLE = "allocator-vector-not-runnable"
BLOCKER_ALLOCATOR_FORCE_VECTOR_MATCH = "allocator-force-vector-match"
BLOCKER_ALLOCATOR_FORCE_VECTOR_NO_MATCH = "allocator-force-vector-no-match"
BLOCKER_ALLOCATOR_FORCE_VECTOR_VERIFY_FAILED = (
    "allocator-force-vector-verify-failed"
)
BLOCKER_ALLOCATOR_TRIAGE_UNCLASSIFIED = "allocator-triage-unclassified"
ALLOCATOR_TARGET_CONFLICT_ACTIONABILITY = "allocator-target-conflict"
FRAME_TRANSFORM_DIAGNOSTIC_ACTIONABILITY = "diagnostic-only"
FRAME_TRANSFORM_SOURCE_PROBE_ACTIONABILITY = "source-probe"
RETAINED_SOURCE_STATUSES = {"applied", "improved", "validated"}
NEGATIVE_EVIDENCE_STATUSES = {"blocked", "error", "no_match", "unsupported"}

