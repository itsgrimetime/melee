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


def test_parse_name_magic_relocations_retains_ambiguous_compatible_alternatives() -> None:
    payload = {
        "diff": [
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
            "++038: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    evidence = parse_name_magic_relocation_evidence(payload)

    assert evidence.blocker == NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR
    assert evidence.reason == "multiple relocation lines at offset 038"
    assert [
        (reloc.offset, reloc.kind, reloc.expected_symbol, reloc.current_symbol)
        for reloc in evidence.relocations
    ] == [
        ("038", "R_PPC_ADDR16_LO", "mnDiagram_804A0750", "...bss.0"),
        ("038", "R_PPC_ADDR16_LO", "mnDiagram_804A076C", "...bss.0"),
    ]


def test_parse_name_magic_relocations_orders_ambiguous_offsets_lexicographically() -> None:
    payload = {
        "diff": [
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0788",
            "++038: R_PPC_ADDR16_LO\t...bss.0",
            "-+024: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
            "-+024: R_PPC_ADDR16_LO\tmnDiagram_804A0758",
            "++024: R_PPC_ADDR16_LO\t...bss.1",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    evidence = parse_name_magic_relocation_evidence(payload)

    assert evidence.blocker == NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR
    assert [
        (reloc.offset, reloc.expected_symbol, reloc.current_symbol)
        for reloc in evidence.relocations
    ] == [
        ("024", "mnDiagram_804A0750", "...bss.1"),
        ("024", "mnDiagram_804A0758", "...bss.1"),
        ("038", "mnDiagram_804A076C", "...bss.0"),
        ("038", "mnDiagram_804A0788", "...bss.0"),
    ]


def test_parse_name_magic_relocations_preserves_unambiguous_when_ambiguous_retains_none() -> None:
    payload = {
        "diff": [
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_HA\t...data.0",
            "-+038: R_PPC_ADDR16_LO\t@901",
            "-+038: R_PPC_ADDR16_LO\t@902",
            "++038: R_PPC_ADDR16_LO\t@267",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    evidence = parse_name_magic_relocation_evidence(payload)

    assert evidence.blocker == NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR
    assert evidence.reason == "multiple relocation lines at offset 038"
    assert [
        (reloc.offset, reloc.kind, reloc.expected_symbol, reloc.current_symbol)
        for reloc in evidence.relocations
    ] == [("024", "R_PPC_ADDR16_HA", "mn_803EAE68", "...data.0")]


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


def test_static_to_global_probe_rejects_non_declared_symbol_references() -> None:
    payload = {
        "diff": [
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_HA\t...data.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    initializer_only = textwrap.dedent(
        """\
        static u16 other_symbol[] = { mn_803EAE68 };
        void demo_fn(void) {}
        """
    )
    type_name_only = textwrap.dedent(
        """\
        static struct mn_803EAE68 other_symbol = { 1 };
        void demo_fn(void) {}
        """
    )
    array_expr_only = textwrap.dedent(
        """\
        static u8 other_symbol[sizeof(mn_803EAE68)] = { 0 };
        void demo_fn(void) {}
        """
    )

    for source in (initializer_only, type_name_only, array_expr_only):
        assert generate_name_magic_source_probes(source, "demo_fn", payload, {}) == (
            [],
            NameMagicBlocker.UNSUPPORTED_SOURCE_SITE,
        )


def test_static_to_global_probe_rejects_function_prototypes_and_tabbed_if() -> None:
    payload = {
        "diff": [
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_HA\t...data.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    prototype = "static void mn_803EAE68(void);\nvoid demo_fn(void) {}\n"
    prototype_param_only = (
        "static void unrelated(int mn_803EAE68);\nvoid demo_fn(void) {}\n"
    )
    tabbed_if = "#if\t1\nstatic u16 mn_803EAE68[] = { 1 };\n#endif\nvoid demo_fn(void) {}\n"
    paren_if = "#if(1)\nstatic u16 mn_803EAE68[] = { 1 };\n#endif\nvoid demo_fn(void) {}\n"

    for source in (prototype, prototype_param_only, tabbed_if, paren_if):
        assert generate_name_magic_source_probes(source, "demo_fn", payload, {}) == (
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
    assert "extern volatile f32 mn_804DBDA8;" not in probes[0].source_text
    assert "HSD_JObjReqAnimAll(jobj, mn_804DBDA8);" in probes[0].source_text
    assert probes[0].header_declarations == ("extern volatile f32 mn_804DBDA8;",)


def test_sdata2_float_probe_only_replaces_body_literals() -> None:
    source = textwrap.dedent(
        """\
        void demo_fn(float a[0.0F])
        {
            sink(a);
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


def test_sdata2_float_probe_rejects_preprocessor_body_literals() -> None:
    source = textwrap.dedent(
        """\
        void demo_fn(void)
        {
        #if 0.0F
            sink();
        #endif
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
    assert "extern volatile f64 mn_804DCA00;" not in probes[0].source_text
    assert "sink_double(mn_804DCA00);" in probes[0].source_text
    assert probes[0].header_declarations == ("extern volatile f64 mn_804DCA00;",)


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
    assert "extern volatile f32 mn_804DBDA8;" not in combined
    assert "HSD_JObjReqAnimAll(jobj, mn_804DBDA8);" in combined
    assert probes[2].header_declarations == ("extern volatile f32 mn_804DBDA8;",)


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


def test_parse_name_magic_relocations_pairs_named_bss_anchor() -> None:
    payload = {
        "diff": [
            "-+004: R_PPC_ADDR16_HA\tlbl_80472ED8",
            "++004: R_PPC_ADDR16_HA\t...bss.0",
            "-+014: R_PPC_ADDR16_LO\tlbl_80472ED8",
            "++014: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {"primary": "instruction-sequence"},
    }

    evidence = parse_name_magic_relocation_evidence(payload)

    assert evidence.blocker is None
    assert [
        (r.offset, r.expected_symbol, r.current_symbol)
        for r in evidence.relocations
    ] == [
        ("004", "lbl_80472ED8", "...bss.0"),
        ("014", "lbl_80472ED8", "...bss.0"),
    ]


def test_generate_name_magic_source_probes_reports_unsupported_bss_source_site() -> None:
    source = textwrap.dedent(
        """\
        void fn_80181C80(void)
        {
            sink();
        }
        """
    )
    payload = {
        "diff": [
            "-+004: R_PPC_ADDR16_HA\tlbl_80472ED8",
            "++004: R_PPC_ADDR16_HA\t...bss.0",
            "-+014: R_PPC_ADDR16_LO\tlbl_80472ED8",
            "++014: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {"primary": "instruction-sequence"},
    }

    probes, blocker = generate_name_magic_source_probes(
        source,
        "fn_80181C80",
        payload,
        {},
    )

    assert probes == []
    assert blocker == NameMagicBlocker.UNSUPPORTED_SOURCE_SITE


def test_generate_name_magic_source_probes_materializes_ambiguous_bss_binding() -> None:
    source = textwrap.dedent(
        """\
        typedef struct DemoBss {
            u8 values[0x20];
        } DemoBss;

        DemoBss mnDiagram_804A0750;

        void demo_fn(void)
        {
            sink(&mnDiagram_804A0750);
        }
        """
    )
    payload = {
        "diff": [
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
            "++038: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    probes, blocker = generate_name_magic_source_probes(
        source,
        "demo_fn",
        payload,
        {},
    )

    assert blocker is None
    assert [probe.operator for probe in probes] == ["bss-anchor-source-binding"]
    assert probes[0].source_text == source
    assert probes[0].edits == ()
    assert probes[0].provenance["expected_symbol"] == "mnDiagram_804A0750"
    assert probes[0].provenance["current_symbol"] == "...bss.0"
    assert probes[0].provenance["declaration_start"] == source.index(
        "DemoBss mnDiagram_804A0750;"
    )


def test_generate_name_magic_source_probes_orders_ambiguous_bss_offsets() -> None:
    source = textwrap.dedent(
        """\
        typedef struct DemoBss {
            u8 values[0x20];
        } DemoBss;

        DemoBss mnDiagram_804A0750;
        DemoBss mnDiagram_804A0758;
        DemoBss mnDiagram_804A076C;
        DemoBss mnDiagram_804A0788;

        void demo_fn(void)
        {
            sink(&mnDiagram_804A0750);
            sink(&mnDiagram_804A0758);
            sink(&mnDiagram_804A076C);
            sink(&mnDiagram_804A0788);
        }
        """
    )
    payload = {
        "diff": [
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0788",
            "++038: R_PPC_ADDR16_LO\t...bss.0",
            "-+024: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
            "-+024: R_PPC_ADDR16_LO\tmnDiagram_804A0758",
            "++024: R_PPC_ADDR16_LO\t...bss.1",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    probes, blocker = generate_name_magic_source_probes(
        source,
        "demo_fn",
        payload,
        {},
    )

    assert blocker is None
    assert [
        (
            probe.provenance["offset"],
            probe.provenance["expected_symbol"],
            probe.provenance["current_symbol"],
        )
        for probe in probes
    ] == [
        ("024", "mnDiagram_804A0750", "...bss.1"),
        ("024", "mnDiagram_804A0758", "...bss.1"),
        ("038", "mnDiagram_804A076C", "...bss.0"),
        ("038", "mnDiagram_804A0788", "...bss.0"),
    ]


def test_generate_name_magic_source_probes_caps_ambiguous_retention_by_max_probes() -> None:
    source = textwrap.dedent(
        """\
        typedef struct DemoBss {
            u8 values[0x20];
        } DemoBss;

        DemoBss mnDiagram_804A0760;

        void demo_fn(void)
        {
            sink(&mnDiagram_804A0760);
        }
        """
    )
    payload = {
        "diff": [
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0758",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0760",
            "++038: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }

    probes, blocker = generate_name_magic_source_probes(
        source,
        "demo_fn",
        payload,
        {},
        max_probes=2,
    )

    assert probes == []
    assert blocker == NameMagicBlocker.UNSUPPORTED_SOURCE_SITE


def test_bss_anchor_source_binding_rejects_unsafe_declarations() -> None:
    payload = {
        "diff": [
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
            "++038: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    function_local = textwrap.dedent(
        """\
        void demo_fn(void)
        {
            DemoBss mnDiagram_804A0750;
            sink(&mnDiagram_804A0750);
        }
        """
    )
    prototype = "void mnDiagram_804A0750(void);\nvoid demo_fn(void) {}\n"
    multi = "DemoBss mnDiagram_804A0750, other;\nvoid demo_fn(void) {}\n"
    macro = "#if 1\nDemoBss mnDiagram_804A0750;\n#endif\nvoid demo_fn(void) {}\n"

    for source in (function_local, prototype, multi, macro):
        assert generate_name_magic_source_probes(source, "demo_fn", payload, {}) == (
            [],
            NameMagicBlocker.UNSUPPORTED_SOURCE_SITE,
        )


def test_bss_anchor_source_binding_rejects_type_only_declarations() -> None:
    payload = {
        "diff": [
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
            "++038: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    struct_field = textwrap.dedent(
        """\
        struct DemoBss {
            int mnDiagram_804A0750;
        };
        void demo_fn(void) { sink(); }
        """
    )
    struct_forward = "struct mnDiagram_804A0750;\nvoid demo_fn(void) { sink(); }\n"
    enum_value = textwrap.dedent(
        """\
        enum Demo {
            mnDiagram_804A0750 = 1
        };
        void demo_fn(void) { sink(); }
        """
    )

    for source in (struct_field, struct_forward, enum_value):
        assert generate_name_magic_source_probes(source, "demo_fn", payload, {}) == (
            [],
            NameMagicBlocker.UNSUPPORTED_SOURCE_SITE,
        )


def test_bss_anchor_source_binding_accepts_object_declarations() -> None:
    payload = {
        "diff": [
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A0750",
            "-+038: R_PPC_ADDR16_LO\tmnDiagram_804A076C",
            "++038: R_PPC_ADDR16_LO\t...bss.0",
        ],
        "classification": {"primary": "data-symbol-or-relocation"},
    }
    sources = (
        "DemoBss mnDiagram_804A0750;\nvoid demo_fn(void) { sink(); }\n",
        "static DemoBss mnDiagram_804A0750;\nvoid demo_fn(void) { sink(); }\n",
        "struct DemoBss mnDiagram_804A0750;\nvoid demo_fn(void) { sink(); }\n",
    )

    for source in sources:
        probes, blocker = generate_name_magic_source_probes(
            source,
            "demo_fn",
            payload,
            {},
        )

        assert blocker is None
        assert [probe.operator for probe in probes] == ["bss-anchor-source-binding"]
        assert probes[0].provenance["expected_symbol"] == "mnDiagram_804A0750"


def test_generate_name_magic_source_probes_preserves_non_bss_probe_when_bss_missing() -> None:
    source = textwrap.dedent(
        """\
        static u16 mn_803EAE68[] = { 1, 2, 3 };

        void fn_80181C80(void)
        {
            sink(mn_803EAE68);
        }
        """
    )
    payload = {
        "diff": [
            "-+004: R_PPC_ADDR16_HA\tlbl_80472ED8",
            "++004: R_PPC_ADDR16_HA\t...bss.0",
            "-+014: R_PPC_ADDR16_LO\tlbl_80472ED8",
            "++014: R_PPC_ADDR16_LO\t...bss.0",
            "-+024: R_PPC_ADDR16_HA\tmn_803EAE68",
            "++024: R_PPC_ADDR16_HA\t...data.0",
        ],
        "classification": {
            "primary": "data-symbol-or-relocation",
            "bss_anchor_relocations": {"status": "ceiling"},
        },
    }

    probes, blocker = generate_name_magic_source_probes(
        source,
        "fn_80181C80",
        payload,
        {},
    )

    assert blocker is None
    assert [probe.operator for probe in probes] == ["data-symbol-static-to-global"]
