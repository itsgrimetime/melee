from __future__ import annotations

import pytest

from src.search.directed.transform_corpus import TransformProbe
from src.search.directed.transform_probe_adapter import (
    TransformProbeConfigError,
    adapted_transform_lifetime_probes,
    filter_transform_probes,
    normalize_transform_families,
    parse_transform_force_phys,
    transform_probe_key,
    transform_probe_to_lifetime_probe,
)


def _probe(
    family_id: str = "assert_macro_expansion_shape",
    *,
    probe_id: str | None = None,
    candidate_text: str = "void demo(void) {}\n",
) -> TransformProbe:
    return TransformProbe(
        probe_id=probe_id or f"{family_id}@0",
        family_id=family_id,
        family_label="assert macro expansion",
        mutator_key="collapse_hsd_assert",
        semantic_risk="medium",
        source_region="assertion",
        expected_compiler_effect="change assert helper shape",
        generated_probe_form="collapse explicit __assert to HSD_ASSERTMSG",
        target_assignments=("ig1->r3",),
        span=(10, 20),
        payload={"line": 42},
        candidate_text=candidate_text,
    )


def test_transform_probe_to_lifetime_probe_preserves_metadata() -> None:
    converted = transform_probe_to_lifetime_probe(_probe())
    data = converted.to_dict()

    assert converted.label == "transform-corpus-assert_macro_expansion_shape-0"
    assert converted.operator == "transform-corpus:assert_macro_expansion_shape"
    assert converted.source_text == "void demo(void) {}\n"
    assert converted.provenance["kind"] == "transform-corpus"
    assert converted.provenance["family_id"] == "assert_macro_expansion_shape"
    assert converted.provenance["mutator_key"] == "collapse_hsd_assert"
    assert converted.provenance["probe_id"] == "assert_macro_expansion_shape@0"
    assert converted.provenance["span"] == [10, 20]
    assert converted.provenance["payload"] == {"line": 42}
    assert data["probe_id"] == "assert_macro_expansion_shape@0"
    assert data["family_id"] == "assert_macro_expansion_shape"
    assert data["mutator_key"] == "collapse_hsd_assert"


def test_transform_probe_to_lifetime_probe_promotes_full_unit_contract_metadata() -> None:
    probe = _probe()
    probe.payload.update({
        "requires_full_unit_source": True,
        "updated_call_sites": [
            {
                "caller": "target",
                "span": [100, 112],
                "old_arg_count": 2,
                "new_arg_count": 1,
                "replacement_text": "",
            }
        ],
    })

    converted = transform_probe_to_lifetime_probe(probe)

    assert converted.provenance["requires_full_unit_source"] is True
    assert converted.provenance["updated_call_sites"] == [
        {
            "caller": "target",
            "span": [100, 112],
            "old_arg_count": 2,
            "new_arg_count": 1,
            "replacement_text": "",
        }
    ]
    assert converted.to_dict()["provenance"]["requires_full_unit_source"] is True


def test_transform_probe_label_uses_family_and_ordinal_for_file_safe_name() -> None:
    converted = transform_probe_to_lifetime_probe(
        _probe("numeric_cast_shape", probe_id="numeric_cast_shape/unsafe@7")
    )

    assert converted.label == "transform-corpus-numeric_cast_shape-7"
    assert "/" not in converted.label
    assert "@" not in converted.label


def test_transform_probe_key_is_stable_and_not_at_suffixed() -> None:
    assert (
        transform_probe_key(_probe())
        == "transform-corpus:assert_macro_expansion_shape:0"
    )


def test_filter_transform_probes_accepts_empty_filter() -> None:
    probes = (_probe("assert_macro_expansion_shape"), _probe("numeric_cast_shape"))

    assert filter_transform_probes(probes, families=()) == probes


def test_filter_transform_probes_accepts_requested_families() -> None:
    probes = (_probe("assert_macro_expansion_shape"), _probe("numeric_cast_shape"))

    filtered = filter_transform_probes(probes, families=("numeric_cast_shape",))

    assert [probe.family_id for probe in filtered] == ["numeric_cast_shape"]


def test_normalize_transform_families_rejects_unknown_family() -> None:
    with pytest.raises(TransformProbeConfigError, match="not_a_family.*known"):
        normalize_transform_families(["not_a_family"])


def test_normalize_transform_families_accepts_record_only_family() -> None:
    assert normalize_transform_families(["helper_shape"]) == ("helper_shape",)


def test_normalize_transform_families_accepts_comma_separated_values() -> None:
    assert normalize_transform_families(
        ["helper_shape,numeric_cast_shape", "helper_shape"]
    ) == ("helper_shape", "numeric_cast_shape")


def test_adapted_transform_lifetime_probes_caps_total() -> None:
    converted = adapted_transform_lifetime_probes(
        (
            _probe("assert_macro_expansion_shape", candidate_text="void a(void) {}\n"),
            _probe("numeric_cast_shape", candidate_text="void b(void) {}\n"),
        ),
        families=(),
        max_probes=1,
    )

    assert [probe.provenance["family_id"] for probe in converted] == [
        "assert_macro_expansion_shape"
    ]


def test_adapted_transform_lifetime_probes_dedupes_candidate_text() -> None:
    duplicate = _probe("numeric_cast_shape")
    probes = (_probe("assert_macro_expansion_shape"), duplicate, duplicate)

    converted = adapted_transform_lifetime_probes(
        probes,
        families=(),
        max_probes=2,
    )

    assert [probe.provenance["family_id"] for probe in converted] == [
        "assert_macro_expansion_shape",
    ]


def test_adapted_transform_lifetime_probes_keeps_first_steering_duplicate() -> None:
    source = "void demo(void) { sink(); }\n"
    probes = (
        _probe("coloring_register_steering", candidate_text=source),
        _probe("declaration_use_boundary", candidate_text=source),
    )

    converted = adapted_transform_lifetime_probes(
        probes,
        families=(),
        max_probes=2,
    )

    assert [probe.provenance["family_id"] for probe in converted] == [
        "coloring_register_steering",
    ]


def test_parse_transform_force_phys_accepts_bare_and_class_scoped_entries() -> None:
    assert parse_transform_force_phys("ig58:r4,gpr:ig44:31,class1:ig2:f1") == {
        58: 4,
        44: 31,
        2: 1,
    }


def test_parse_transform_force_phys_accepts_empty_input() -> None:
    assert parse_transform_force_phys("") == {}
    assert parse_transform_force_phys(None) == {}


def test_parse_transform_force_phys_rejects_invalid_input() -> None:
    with pytest.raises(TransformProbeConfigError, match="IG:PHYS"):
        parse_transform_force_phys("ig58")
