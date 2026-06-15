"""Tests for the string_data_field transform family (transform_corpus.string_data_field)."""
from __future__ import annotations

import pytest

from src.search.directed.anchors import Anchor
from src.search.directed.mutators import apply_mutator
from src.search.directed.transform_corpus import (
    DEFAULT_TRANSFORM_FAMILIES,
    generate_transform_probes,
    plan_transform_experiments,
)
from src.search.directed.transform_probe_adapter import transform_probe_key
from src.mwcc_debug.source_shape import CandidatePatch


def test_string_data_field_rejects_helper_local_symbol() -> None:
    source = (
        "void helper(void) {\n"
        "    static struct { char report_format[8]; } local_fmt = { \"x\\n\" };\n"
        "}\n"
        "void target(void) {\n"
        "    OSReport(\"x\\n\");\n"
        "}\n"
    )

    probes = generate_transform_probes(
        source,
        function="target",
        unit="melee/test/target",
        force_phys={1: 3},
        max_per_family=1,
    )

    assert "string_literal_data_blob_field_shape" not in {probe.family_id for probe in probes}
