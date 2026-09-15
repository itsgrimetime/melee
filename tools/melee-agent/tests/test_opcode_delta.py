from __future__ import annotations


def test_opcode_delta_signature_is_directional_bounded_and_ignores_labels_relocations() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_signature,
    )

    target = [
        "+000: 80 83 00 00  lwz r4, 0(r3)",
        "lbl_80000004:",
        "/* 0004 */ addi r3, r3, 4",
        "+008: addi r3, r3, 4",
        "+00c: R_PPC_ADDR16_HA lbl_80300000",
        "+010: blr",
    ]
    current = [
        "+000: 90 83 00 00  stw r4, 0(r3)",
        "<current+0x4>:",
        "/* 0004 */ ori r3, r3, 4",
        "+008: ori r3, r3, 4",
        "+00c: R_PPC_ADDR16_HA lbl_80400000",
        "+010: blr",
    ]

    assert derive_opcode_delta_signature(target, current) == {
        "opcode_delta_signature_status": "available",
        "opcode_delta_signature": (
            '{"dominant":[["addi","ori",2],["lwz","stw",1]],'
            '"first":["lwz","stw"],"version":1}'
        ),
    }


def test_opcode_delta_signature_handles_insertions_deletions_and_malformed_payloads() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_signature,
    )

    assert derive_opcode_delta_signature(
        ["+000: addi r3, r3, 4", "+004: blr"],
        ["+000: ori r3, r3, 4", "+004: addi r3, r3, 4", "+008: blr"],
    ) == {
        "opcode_delta_signature_status": "available",
        "opcode_delta_signature": (
            '{"dominant":[[null,"ori",1]],'
            '"first":[null,"ori"],"version":1}'
        ),
    }
    assert derive_opcode_delta_signature(
        ["+000: lwz r4, 0(r3)"],
        None,
    ) == {
        "opcode_delta_signature_status": "missing-current-asm",
        "opcode_delta_signature": "",
    }
    assert derive_opcode_delta_signature(["only_a_label:"], ["<only_a_label>"]) == {
        "opcode_delta_signature_status": "empty-normalized-opcode-stream",
        "opcode_delta_signature": "",
    }


def test_opcode_delta_signature_ranks_equal_frequency_pairs_lexically() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_signature,
    )

    assert derive_opcode_delta_signature(
        [
            "+000: addi r3, r3, 4",
            "+004: and r3, r4, r5",
            "+008: or r3, r4, r5",
            "+00c: xor r3, r4, r5",
        ],
        [
            "+000: andi. r3, r3, 4",
            "+004: nand r3, r4, r5",
            "+008: nor r3, r4, r5",
            "+00c: eqv r3, r4, r5",
        ],
    ) == {
        "opcode_delta_signature_status": "available",
        "opcode_delta_signature": (
            '{"dominant":[["addi","andi.",1],["and","nand",1],'
            '["or","nor",1]],"first":["addi","andi."],"version":1}'
        ),
    }


def test_opcode_delta_signature_preserves_bc_after_optional_machine_code() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_signature,
    )

    assert derive_opcode_delta_signature(
        ["+000: bc 12, 0, lbl_80000004"],
        ["+000: bc 12, 0, lbl_80000004"],
    ) == {
        "opcode_delta_signature_status": "no-opcode-delta",
        "opcode_delta_signature": "",
    }
    assert derive_opcode_delta_signature(
        ["+000: 40 82 00 04  bc 12, 0, lbl_80000004"],
        ["+000: 40 82 00 04  bc 12, 0, lbl_80000004"],
    ) == {
        "opcode_delta_signature_status": "no-opcode-delta",
        "opcode_delta_signature": "",
    }
    assert derive_opcode_delta_signature(
        ["+000: bc 12, 0, lbl_80000004"],
        ["+000: b lbl_80000004"],
    ) == {
        "opcode_delta_signature_status": "available",
        "opcode_delta_signature": (
            '{"dominant":[["bc","b",1]],"first":["bc","b"],"version":1}'
        ),
    }


def test_opcode_delta_evidence_emits_ordered_multilabel_families_and_direction() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_evidence,
    )

    evidence = derive_opcode_delta_evidence(
        [
            "+000: lwz r3, 0(r4)",
            "+004: fadds f1, f2, f3",
            "+008: blr",
        ],
        [
            "+000: lwzu r3, 4(r4)",
            "+004: fmuls f1, f2, f3",
            "+008: bne lbl_8000000c",
            "+00c: blr",
        ],
    )

    assert evidence["semantic_delta_families"] == [
        "floating-point-expression-storage",
        "branch-predicate-control",
        "indexed-update-memory",
        "integer-memory-width-transfer",
    ]
    assert evidence["opcode_edit_direction"] == "mixed"


def test_opcode_delta_evidence_covers_materialization_width_and_frame_families() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_evidence,
    )

    evidence = derive_opcode_delta_evidence(
        [
            "+000: stwu r1, -32(r1)",
            "+004: stmw r28, 16(r1)",
            "+008: clrlwi r3, r3, 24",
        ],
        ["+000: li r3, 0", "+004: addi r4, r4, 1"],
    )

    assert evidence["semantic_delta_families"] == [
        "address-constant-materialization",
        "integer-width-bitfield-scale",
        "indexed-update-memory",
        "frame-save-window",
        "integer-memory-width-transfer",
    ]
    assert evidence["opcode_edit_direction"] == "mixed"


def test_opcode_delta_evidence_distinguishes_each_uniform_edit_direction() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_evidence,
    )

    assert derive_opcode_delta_evidence(
        ["+000: blr"],
        ["+000: li r3, 0", "+004: blr"],
    )["opcode_edit_direction"] == "current-extra"
    assert derive_opcode_delta_evidence(
        ["+000: li r3, 0", "+004: blr"],
        ["+000: blr"],
    )["opcode_edit_direction"] == "reference-extra"
    assert derive_opcode_delta_evidence(
        ["+000: mr r3, r4", "+004: blr"],
        ["+000: li r3, 0", "+004: blr"],
    )["opcode_edit_direction"] == "substitution"


def test_opcode_delta_evidence_treats_record_form_as_predicate_evidence() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_evidence,
    )

    assert derive_opcode_delta_evidence(
        ["+000: clrlwi. r3, r3, 24"],
        ["+000: mysteryop r3, r3, 24"],
    )["semantic_delta_families"] == [
        "integer-width-bitfield-scale",
        "branch-predicate-control",
    ]


def test_opcode_delta_evidence_falls_back_for_unknown_opcodes() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_evidence,
    )

    assert derive_opcode_delta_evidence(
        ["+000: mysteryop r3, r4"],
        ["+000: otherop r3, r4"],
    )["semantic_delta_families"] == ["other-opcode-sequence"]


def test_near_match_trigger_signature_is_exact_safe_and_versioned() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_evidence,
    )

    evidence = derive_opcode_delta_evidence(
        ["<issue-123>:", "+000: mr r3, r4", "+004: blr"],
        ["task_456:", "+000: li r3, 0", "+004: blr"],
        normalized_diff_lines=1,
    )

    assert evidence["normalized_trigger_signature_status"] == "available"
    assert evidence["normalized_trigger_signature"] == (
        '{"edit_direction":"substitution","normalized_diff_lines":1,'
        '"pairs":[["mr","li"]],"version":1}'
    )
    assert evidence["normalized_trigger_family"] == "one-line-substitution"
    assert all(
        "issue" not in str(value).lower() and "task" not in str(value).lower()
        for value in evidence.values()
    )


def test_near_match_trigger_signature_preserves_order_and_duplicate_pairs() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_evidence,
    )

    evidence = derive_opcode_delta_evidence(
        ["+000: mr r3, r4", "+004: mr r5, r6", "+008: blr"],
        ["+000: li r3, 7", "+004: li r5, 8", "+008: blr"],
        normalized_diff_lines=2,
    )

    assert evidence["normalized_trigger_signature"] == (
        '{"edit_direction":"substitution","normalized_diff_lines":2,'
        '"pairs":[["mr","li"],["mr","li"]],"version":1}'
    )
    assert evidence["normalized_trigger_family"] == "two-line-substitution"


def test_near_match_trigger_evidence_ignores_operands_labels_and_external_identity() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_evidence,
    )

    first = derive_opcode_delta_evidence(
        ["lbl_issue_17:", "+000: mr r3, r4", "+004: b lbl_task_18"],
        ["lbl_issue_19:", "+000: li r3, 123", "+004: b lbl_task_20"],
        normalized_diff_lines=1,
    )
    second = derive_opcode_delta_evidence(
        ["totally_different:", "+000: mr r28, r31", "+004: b elsewhere"],
        ["another_label:", "+000: li r9, -456", "+004: b elsewhere"],
        normalized_diff_lines=1,
    )

    assert first == second


def test_near_match_trigger_uses_operand_shape_only_when_opcodes_match() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_evidence,
    )

    evidence = derive_opcode_delta_evidence(
        ["+000: addi r3, r3, 4"],
        ["+000: addi r4, r4, 8"],
        normalized_diff_lines=1,
    )

    assert evidence["opcode_delta_signature_status"] == "no-opcode-delta"
    assert evidence["opcode_delta_signature"] == ""
    assert evidence["semantic_delta_families"] == []
    assert evidence["opcode_edit_direction"] == "operand-shape-only"
    assert evidence["normalized_trigger_signature_status"] == "available"
    assert evidence["normalized_trigger_signature"] == (
        '{"edit_direction":"operand-shape-only","normalized_diff_lines":1,'
        '"pairs":[],"version":1}'
    )
    assert evidence["normalized_trigger_family"] == "one-line-operand-shape-only"


def test_near_match_trigger_does_not_fabricate_evidence_for_bad_assembly() -> None:
    from tools.function_taxonomy_inventory.opcode_delta import (
        derive_opcode_delta_evidence,
    )

    evidence = derive_opcode_delta_evidence(
        ["+000: mr r3, r4"],
        None,
        normalized_diff_lines=1,
    )

    assert evidence == {
        "opcode_delta_signature_status": "missing-current-asm",
        "opcode_delta_signature": "",
        "semantic_delta_families": [],
        "opcode_edit_direction": "",
        "normalized_trigger_signature_status": "missing-current-asm",
        "normalized_trigger_signature": "",
        "normalized_trigger_family": "",
    }
