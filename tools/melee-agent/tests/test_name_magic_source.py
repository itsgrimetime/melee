from __future__ import annotations

import textwrap

from src.mwcc_debug.name_magic_source import (
    NameMagicBlocker,
    generate_name_magic_source_probes,
    parse_name_magic_relocation_evidence,
)


def test_parse_name_magic_relocations_pairs_same_offset_and_records_residual() -> None:
    payload = {
        "diff": [
            "--- expected",
            "+++ current",
            "@@ -1,4 +1,4 @@",
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_HA\t...data.0",
            "-+02c: R_PPC_ADDR16_LO\tmn_803EAE68",
            "++02c: R_PPC_ADDR16_LO\t...data.0",
            "-+984: 38 81 02 a8 \taddi    r4,r1,680",
            "++984: 38 81 02 94 \taddi    r4,r1,660",
            "-+af8: R_PPC_EMB_SDA21\tmn_804DBDA8",
            "++af8: R_PPC_EMB_SDA21\t@267",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    evidence = parse_name_magic_relocation_evidence(payload)

    assert evidence.blocker is None
    assert [
        (r.offset, r.kind, r.expected_symbol, r.current_symbol)
        for r in evidence.relocations
    ] == [
        ("024", "R_PPC_ADDR16_HA", "mn_803EAE68", "...data.0"),
        ("02c", "R_PPC_ADDR16_LO", "mn_803EAE68", "...data.0"),
        ("af8", "R_PPC_EMB_SDA21", "mn_804DBDA8", "@267"),
    ]
    assert evidence.residual_diff_count == 1


def test_parse_name_magic_relocations_blocks_without_supported_pairs() -> None:
    payload = {
        "diff": [
            "--- expected",
            "+++ current",
            "-+984: 38 81 02 a8 \taddi    r4,r1,680",
            "++984: 38 81 02 94 \taddi    r4,r1,660",
        ],
        "classification": {"primary": "operand-register-or-offset"},
    }

    evidence = parse_name_magic_relocation_evidence(payload)

    assert evidence.blocker == NameMagicBlocker.RAW_DIFF_NO_SUPPORTED_DATA_SYMBOL_PAIR
    assert evidence.relocations == []


def test_parse_name_magic_relocations_blocks_ambiguous_same_offset_pairs() -> None:
    payload = {
        "diff": [
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE70",
            "++024: R_PPC_ADDR16_HA\t...data.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    evidence = parse_name_magic_relocation_evidence(payload)

    assert evidence.blocker == NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR


def test_parse_name_magic_relocations_blocks_incompatible_kinds() -> None:
    payload = {
        "diff": [
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_LO\t...data.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    evidence = parse_name_magic_relocation_evidence(payload)

    assert evidence.blocker == NameMagicBlocker.UNSUPPORTED_RELOC_KIND


def test_parse_name_magic_relocations_requires_expected_named_symbol() -> None:
    payload = {
        "diff": [
            "-+024: R_PPC_EMB_SDA21\t@901",
            "++024: R_PPC_EMB_SDA21\t@267",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    evidence = parse_name_magic_relocation_evidence(payload)

    assert evidence.blocker == NameMagicBlocker.UNSUPPORTED_RELOC_KIND


def test_static_to_global_probe_removes_only_file_scope_static() -> None:
    source = textwrap.dedent(
        """\
        static u16 mn_803EAE68[] = { 1, 2, 3 };

        void demo_fn(void)
        {
            static u16 mn_803EAE68_local[] = { 4 };
            sink(mn_803EAE68);
        }
        """
    )
    payload = {
        "diff": [
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_HA\t...data.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    probes, blocker = generate_name_magic_source_probes(source, "demo_fn", payload, {})

    assert blocker is None
    assert [probe.operator for probe in probes] == ["data-symbol-static-to-global"]
    assert "u16 mn_803EAE68[] = { 1, 2, 3 };" in probes[0].source_text
    assert "static u16 mn_803EAE68_local[] = { 4 };" in probes[0].source_text


def test_static_to_global_probe_rejects_earlier_function_local_static() -> None:
    source = textwrap.dedent(
        """\
        void earlier(void)
        {
            static u16 mn_803EAE68[] = { 1, 2, 3 };
            sink(mn_803EAE68);
        }

        void demo_fn(void)
        {
            sink();
        }
        """
    )
    payload = {
        "diff": [
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_HA\t...data.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    probes, blocker = generate_name_magic_source_probes(source, "demo_fn", payload, {})

    assert probes == []
    assert blocker == NameMagicBlocker.UNSUPPORTED_SOURCE_SITE


def test_static_to_global_probe_rejects_multi_declarator_and_preprocessor_region() -> None:
    payload = {
        "diff": [
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_HA\t...data.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    multi = "static u16 mn_803EAE68[] = { 1 }, other[] = { 2 };\nvoid demo_fn(void) {}\n"
    macro = "#if 1\nstatic u16 mn_803EAE68[] = { 1 };\n#endif\nvoid demo_fn(void) {}\n"

    assert generate_name_magic_source_probes(multi, "demo_fn", payload, {}) == (
        [],
        NameMagicBlocker.UNSUPPORTED_SOURCE_SITE,
    )
    assert generate_name_magic_source_probes(macro, "demo_fn", payload, {}) == (
        [],
        NameMagicBlocker.UNSUPPORTED_SOURCE_SITE,
    )


def test_sdata2_float_probe_replaces_unique_literal_with_named_volatile_load() -> None:
    source = textwrap.dedent(
        """\
        void demo_fn(HSD_JObj* jobj)
        {
            HSD_JObjReqAnimAll(jobj, 0.0F);
        }
        """
    )
    payload = {
        "diff": [
            "-+af8: R_PPC_EMB_SDA21\tmn_804DBDA8",
            "++af8: R_PPC_EMB_SDA21\t@267",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    anonymous = {"@267": {"size": 4, "float": 0.0, "value": 0}}

    probes, blocker = generate_name_magic_source_probes(source, "demo_fn", payload, anonymous)

    assert blocker is None
    assert [probe.operator for probe in probes] == ["sdata2-named-float-load"]
    assert "extern volatile f32 mn_804DBDA8;" in probes[0].source_text
    assert "HSD_JObjReqAnimAll(jobj, mn_804DBDA8);" in probes[0].source_text


def test_sdata2_double_probe_replaces_unique_literal_with_named_volatile_load() -> None:
    source = textwrap.dedent(
        """\
        void demo_fn(void)
        {
            sink_double(1.5);
        }
        """
    )
    payload = {
        "diff": [
            "-+110: R_PPC_EMB_SDA21\tmn_804DCA00",
            "++110: R_PPC_EMB_SDA21\t@901",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    anonymous = {"@901": {"size": 8, "double": 1.5, "value": 0x3FF8000000000000}}

    probes, blocker = generate_name_magic_source_probes(source, "demo_fn", payload, anonymous)

    assert blocker is None
    assert [probe.operator for probe in probes] == ["sdata2-named-float-load"]
    assert "extern volatile f64 mn_804DCA00;" in probes[0].source_text
    assert "sink_double(mn_804DCA00);" in probes[0].source_text


def test_combined_probe_applies_static_and_sdata2_edits_from_original_source() -> None:
    source = textwrap.dedent(
        """\
        static u16 mn_803EAE68[] = { 1, 2, 3 };

        void demo_fn(HSD_JObj* jobj)
        {
            sink(mn_803EAE68);
            HSD_JObjReqAnimAll(jobj, 0.0F);
        }
        """
    )
    payload = {
        "diff": [
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_HA\t...data.0",
            "-+af8: R_PPC_EMB_SDA21\tmn_804DBDA8",
            "++af8: R_PPC_EMB_SDA21\t@267",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    anonymous = {"@267": {"size": 4, "float": 0.0, "value": 0}}

    probes, blocker = generate_name_magic_source_probes(source, "demo_fn", payload, anonymous)

    assert blocker is None
    assert [probe.operator for probe in probes] == [
        "data-symbol-static-to-global",
        "sdata2-named-float-load",
        "name-magic-source-combined",
    ]
    combined = probes[2].source_text
    assert "u16 mn_803EAE68[] = { 1, 2, 3 };" in combined
    assert "extern volatile f32 mn_804DBDA8;" in combined
    assert "HSD_JObjReqAnimAll(jobj, mn_804DBDA8);" in combined


def test_sdata2_float_probe_blocks_when_literal_site_is_ambiguous() -> None:
    source = textwrap.dedent(
        """\
        void demo_fn(HSD_JObj* a, HSD_JObj* b)
        {
            HSD_JObjReqAnimAll(a, 0.0F);
            HSD_JObjReqAnimAll(b, 0.0F);
        }
        """
    )
    payload = {
        "diff": [
            "-+af8: R_PPC_EMB_SDA21\tmn_804DBDA8",
            "++af8: R_PPC_EMB_SDA21\t@267",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    anonymous = {"@267": {"size": 4, "float": 0.0, "value": 0}}

    probes, blocker = generate_name_magic_source_probes(source, "demo_fn", payload, anonymous)

    assert probes == []
    assert blocker == NameMagicBlocker.UNSUPPORTED_SOURCE_SITE


def test_sdata2_float_probe_blocks_ambiguous_anonymous_value() -> None:
    source = "void demo_fn(HSD_JObj* jobj) { HSD_JObjReqAnimAll(jobj, 0.0F); }\n"
    payload = {
        "diff": [
            "-+af8: R_PPC_EMB_SDA21\tmn_804DBDA8",
            "++af8: R_PPC_EMB_SDA21\t@267",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    anonymous = {"@267": {"size": 4, "float": 0.0, "value": 0, "ambiguous": True}}

    probes, blocker = generate_name_magic_source_probes(source, "demo_fn", payload, anonymous)

    assert probes == []
    assert blocker == NameMagicBlocker.AMBIGUOUS_SDATA2_VALUE


def test_sdata2_probe_reports_stable_blockers_for_double_and_bias_first_pass() -> None:
    source = "void demo_fn(void) { sink(0.0); }\n"
    payload = {
        "diff": [
            "-+010: R_PPC_EMB_SDA21\tmn_804DBD88",
            "++010: R_PPC_EMB_SDA21\t@377",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    probes, blocker = generate_name_magic_source_probes(
        source,
        "demo_fn",
        payload,
        {"@377": {"size": 8, "value": 0x4330000080000000, "bias": "s32"}},
    )

    assert probes == []
    assert blocker == NameMagicBlocker.UNSUPPORTED_RELOC_KIND


def test_parse_blocks_section_anchor_offsets_until_field_paths_are_supported() -> None:
    payload = {
        "diff": [
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_HA\t...data.0+4",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    evidence = parse_name_magic_relocation_evidence(payload)

    assert evidence.blocker == NameMagicBlocker.UNSUPPORTED_SECTION_ANCHOR_OFFSET
