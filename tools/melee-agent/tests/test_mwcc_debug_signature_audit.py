"""Regression tests for signature call-type auditing."""

from __future__ import annotations

from src.mwcc_debug.signature_audit import (
    audit_signature_call_type,
    validate_signature_patches,
)


def _payload(target_asm: list[str], current_asm: list[str]) -> dict:
    return {
        "function": "caller_fn",
        "classification": {"primary": "signature-type-mismatch"},
        "target_asm": target_asm,
        "current_asm": current_asm,
        "diff": [],
        "fuzzy_match_percent": 97.5,
    }


def test_audit_suggests_removing_explicit_float_cast_for_gpr_target() -> None:
    source = """
void caller_fn(int rumble_setting)
{
    helper((f32) rumble_setting);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "+000: 7C 7F 1B 78    mr r3, r31",
                "+004: 48 00 00 01    bl helper",
            ],
            [
                "+000: FC 20 F8 90    fmr f1, f31",
                "+004: 48 00 00 01    bl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert report.findings[0].kind == "argument-bank-mismatch"
    action = report.findings[0].actions[0]
    assert action.kind == "remove-call-arg-cast"
    assert action.confidence == "high"
    assert action.patch is not None
    assert action.patch.old == "(f32) rumble_setting"
    assert action.patch.new == "rumble_setting"
    assert action.patch.line == 4
    assert action.rebucket is None
    assert report.summary["patch_candidate_count"] == 1
    assert report.summary["unvalidated_patch_candidate_count"] == 1
    assert report.summary["validated_patch_candidate_count"] == 0
    assert report.summary["stop_condition"]["kind"] == "unvalidated-patch-candidates"
    assert report.findings[0].affected_call_sites[0]["line"] == 4


def test_audit_does_not_patch_fixed_prototype_cast() -> None:
    source = """
static void helper(int value) {}

void caller_fn(int rumble_setting)
{
    helper((f32) rumble_setting);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
            [
                "/* 0000 */\tfmr f1, f31",
                "/* 0004 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert report.findings[0].kind == "argument-bank-mismatch"
    assert all(a.patch is None for a in report.findings[0].actions)
    assert any(
        a.kind == "same-tu-static-prototype-audit"
        for a in report.findings[0].actions
    )


def test_audit_does_not_patch_unknown_or_float_inner_expression() -> None:
    unknown_source = """
void caller_fn(void)
{
    helper((f32) unknown_expr);
}
"""
    unknown = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
            [
                "/* 0000 */\tfmr f1, f31",
                "/* 0004 */\tbl helper",
            ],
        ),
        unknown_source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert all(a.patch is None for a in unknown.findings[0].actions)

    float_source = """
void caller_fn(float value)
{
    helper((f32) value);
}
"""
    declared_float = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
            [
                "/* 0000 */\tfmr f1, f31",
                "/* 0004 */\tbl helper",
            ],
        ),
        float_source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert all(a.patch is None for a in declared_float.findings[0].actions)


def test_audit_reports_same_tu_static_helper_prototype_without_patch() -> None:
    source = """
static void helper(float value) {}

void caller_fn(int arg0)
{
    helper(arg0);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
            [
                "/* 0000 */\tfmr f1, f31",
                "/* 0004 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    actions = report.findings[0].actions
    assert any(a.kind == "same-tu-static-prototype-audit" for a in actions)
    assert all(a.patch is None for a in actions)
    assert report.summary["source_lever_action_count"] == 1
    assert report.summary["audit_only_unrebucketed"] == 0
    assert report.summary["stop_condition"]["kind"] == "source-lever-audit"


def test_audit_classifies_width_mismatch() -> None:
    source = """
void caller_fn(u8 arg0)
{
    helper(arg0);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\textsb r3, r31",
                "/* 0004 */\tbl helper",
            ],
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert report.findings[0].kind == "argument-width-mismatch"
    action = report.findings[0].actions[0]
    assert action.kind == "call-argument-type-audit"
    assert action.rebucket["reason"] == "external-prototype-unavailable"
    assert report.summary["rebucket_reason_counts"][
        "external-prototype-unavailable"
    ] == 1


def test_audit_generates_same_tu_static_width_prototype_patch() -> None:
    source = """
static void helper(int value) {}

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    finding = report.findings[0]
    assert finding.kind == "argument-width-mismatch"
    action = finding.actions[0]
    assert action.kind == "same-tu-static-prototype-candidate"
    assert action.candidate["kind"] == "prototype-parameter-type"
    assert action.candidate["current_type"] == "int"
    assert action.candidate["proposed_type"] == "s8"
    assert action.candidate["prototype_scope"] == "same-tu-static"
    assert action.candidate["patch_status"] == "generated"
    assert action.patch is not None
    assert action.patch.old == "int value"
    assert action.patch.new == "s8 value"
    assert report.summary["patch_candidate_count"] == 1


def test_validate_signature_prototype_patch_attaches_candidate_delta() -> None:
    source = """
static void helper(int value) {}

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    seen_sources: list[str] = []

    def fake_runner(candidate_source: str) -> dict:
        seen_sources.append(candidate_source)
        return {"match": False, "fuzzy_match_percent": 99.0}

    validate_signature_patches(report, source, fake_runner, baseline_match_percent=97.5)

    assert "static void helper(s8 value) {}" in seen_sources[0]
    assert report.findings[0].actions[0].validation["status"] == "scored"
    assert report.summary["validated_patch_candidate_count"] == 1


def test_validate_signature_patch_marks_missing_checkdiff_score_unscored() -> None:
    source = """
void caller_fn(int rumble_setting)
{
    helper((f32) rumble_setting);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "+000: 7C 7F 1B 78    mr r3, r31",
                "+004: 48 00 00 01    bl helper",
            ],
            [
                "+000: FC 20 F8 90    fmr f1, f31",
                "+004: 48 00 00 01    bl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    def fake_runner(candidate_source: str) -> dict:
        assert "helper(rumble_setting);" in candidate_source
        return {
            "match": False,
            "fuzzy_match_percent": None,
            "fuzzy_match_percent_source": "suppressed_stale_report_no_build",
            "classification": {"primary": "signature-type-mismatch"},
        }

    validate_signature_patches(
        report,
        source,
        fake_runner,
        baseline_match_percent=None,
    )

    validation = report.findings[0].actions[0].validation
    assert validation == {
        "status": "unscored",
        "match": False,
        "baseline_match_percent": None,
        "candidate_match_percent": None,
        "delta_match_percent": None,
        "classification": "signature-type-mismatch",
        "candidate_match_percent_source": "suppressed_stale_report_no_build",
        "score_reason": "candidate checkdiff did not return a match percent",
    }
    assert report.summary["validated_patch_candidate_count"] == 0
    assert report.summary["unvalidated_patch_candidate_count"] == 1
    assert report.summary["stop_condition"]["kind"] == "unvalidated-patch-candidates"


def test_audit_reports_global_width_prototype_candidate_without_patch() -> None:
    source = """
void helper(int value);

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.kind == "global-prototype-candidate"
    assert action.patch is None
    assert action.candidate["blast_radius"] == "cross-translation-unit"
    assert report.summary["source_lever_action_count"] == 1
    assert report.summary["audit_only_unrebucketed"] == 0
    assert report.summary["stop_condition"]["kind"] == "source-lever-audit"


def test_audit_reports_duplicate_same_tu_declarations_without_patch() -> None:
    source = """
static void helper(int value);
static void helper(int value) {}

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.kind == "same-tu-static-prototype-candidate"
    assert action.patch is None
    assert action.candidate["patch_status"] == "duplicate-visible-declarations"


def test_audit_rebuckets_width_mismatch_without_visible_prototype() -> None:
    source = """
void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.rebucket["reason"] == "external-prototype-unavailable"
    assert "width-prototype-candidate-missing" not in (
        report.summary["rebucket_reason_counts"]
    )


def test_audit_rebuckets_variadic_presence_mismatch_tail() -> None:
    source = """
void helper(const char *fmt, ...);

void caller_fn(int value)
{
    helper("%d", value);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ mr r4, r30",
                "/* 0008 */ bl helper",
            ],
            [
                "/* 0000 */ mr r3, r31",
                "/* 0008 */ bl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.rebucket["reason"] == "variadic-prototype-tail"


def test_audit_rebuckets_surplus_abi_prep_as_source_call_arity_mismatch() -> None:
    source = """
void helper(int first);

void caller_fn(int first, int second)
{
    helper(first);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ mr r4, r30",
                "/* 0008 */ bl helper",
            ],
            [
                "/* 0000 */ mr r3, r31",
                "/* 0008 */ bl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert report.findings[0].kind == "argument-register-presence-mismatch"
    assert report.findings[0].arg_index == 1
    assert report.findings[0].actions[0].rebucket["reason"] == (
        "source-call-arity-mismatch"
    )


def test_audit_overall_ordinal_prototype_candidate_never_patches() -> None:
    source = """
static void source_helper(int value) {}

void caller_fn(int first, int second)
{
    first_helper(first);
    source_helper(second);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl first_helper",
                "/* 0008 */ extsb r3, r30",
                "/* 000C */ bl external_helper",
            ],
            [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ bl first_helper",
                "/* 0008 */ mr r3, r30",
                "/* 000C */ bl external_helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.candidate["localization_kind"] == "overall-ordinal"
    assert action.patch is None


def test_audit_clrlwi_width_candidate_is_unsupported_not_signed_patch() -> None:
    source = """
static void helper(int value) {}

void caller_fn(int value)
{
    helper(value);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ clrlwi r3, r31, 24", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    action = report.findings[0].actions[0]
    assert action.kind == "same-tu-static-prototype-candidate"
    assert action.patch is None
    assert action.candidate["proposed_type"] is None
    assert action.candidate["patch_status"] == "unsupported-type-shape"


def test_audit_presence_mismatch_does_not_patch_gpr_alias_type() -> None:
    source = """
static void helper(int first, int second) {}

void caller_fn(int first, int second)
{
    helper(first, second);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */ mr r3, r31",
                "/* 0004 */ mr r4, r30",
                "/* 0008 */ bl helper",
            ],
            [
                "/* 0000 */ mr r3, r31",
                "/* 0008 */ bl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    finding = report.findings[0]
    assert finding.kind == "argument-register-presence-mismatch"
    assert finding.arg_index == 1
    action = finding.actions[0]
    assert action.kind == "same-tu-static-prototype-candidate"
    assert action.patch is None
    assert action.candidate["current_type"] == "int"
    assert action.candidate["proposed_type"] == "s32"
    assert action.candidate["patch_status"] == "already-matches"


def test_audit_unsupported_parameter_shape_reports_patch_status() -> None:
    source = """
static void helper(int values[2]) {}

void caller_fn(int *values)
{
    helper(values);
}
"""
    report = audit_signature_call_type(
        _payload(
            ["/* 0000 */ extsb r3, r31", "/* 0004 */ bl helper"],
            ["/* 0000 */ mr r3, r31", "/* 0004 */ bl helper"],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.patch is None
    assert action.candidate["patch_status"] == "unsupported-parameter-shape"


def test_audit_reports_unmatched_call_target_shape() -> None:
    source = """
void caller_fn(int arg0)
{
    helper_b(arg0);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper_a",
            ],
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper_b",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    assert report.findings[0].kind == "call-target-shape-mismatch"
    assert report.findings[0].expected["call_target"] == "helper_a"
    assert report.findings[0].current["call_target"] == "helper_b"
    assert report.findings[0].affected_call_sites[0]["call_target"] == "helper_b"
    action = report.findings[0].actions[0]
    assert action.kind == "call-target-shape-audit"
    assert action.rebucket == {
        "reason": "call-offset-shift",
        "work_bucket": "structural-reconstruction",
        "subcategory": "call-target-shape",
        "explanation": (
            "The call target or ordinal differs; signature audit cannot "
            "produce a bounded type/prototype patch for this call shape."
        ),
    }
    assert report.summary["audit_only_unrebucketed"] == 0
    assert report.summary["rebucket_reason_counts"]["call-offset-shift"] == 1
    assert report.summary["stop_condition"]["kind"] == "rebucketed-audit-only"


def test_audit_rebuckets_bank_mismatch_without_source_lever() -> None:
    source = """
void caller_fn(void)
{
    helper((f32) unknown_expr);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
            [
                "/* 0000 */\tfmr f1, f31",
                "/* 0004 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.kind == "call-argument-type-audit"
    assert action.rebucket["reason"] == "prototype-candidate-missing"
    assert action.rebucket["subcategory"] == "argument-bank"
    assert report.summary["audit_only_unrebucketed"] == 0
    assert report.summary["stop_condition"]["kind"] == "rebucketed-audit-only"


def test_audit_preserves_repeated_rebucket_findings_per_call_site() -> None:
    source = """
void caller_fn(void)
{
    helper((f32) unknown_first);
    helper((f32) unknown_second);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
                "/* 0008 */\tmr r3, r30",
                "/* 000C */\tbl helper",
            ],
            [
                "/* 0000 */\tfmr f1, f31",
                "/* 0004 */\tbl helper",
                "/* 0008 */\tfmr f1, f30",
                "/* 000C */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert len(report.findings) == 2
    assert [finding.source_line for finding in report.findings] == [4, 5]
    assert report.summary["rebucketed_audit_only_count"] == 2
    assert report.summary["rebucket_reason_counts"]["prototype-candidate-missing"] == 2


def test_audit_rebuckets_argument_source_register_mismatch() -> None:
    source = """
void caller_fn(int arg0)
{
    helper(arg0);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
            [
                "/* 0000 */\tmr r3, r30",
                "/* 0004 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    action = report.findings[0].actions[0]
    assert action.rebucket["reason"] == "register-source-cascade"
    assert action.rebucket["work_bucket"] == "register-allocator"
    assert report.summary["audit_only_unrebucketed"] == 0
    assert report.summary["stop_condition"]["kind"] == "rebucketed-audit-only"


def test_summary_reports_unclassified_audit_action() -> None:
    from src.mwcc_debug.signature_audit import (
        SignatureAction,
        SignatureFinding,
        _summarize_report,
    )

    finding = SignatureFinding(
        kind="argument-load-kind-mismatch",
        confidence="low",
        call_target="helper",
        call_ordinal=1,
        arg_register="r3",
        expected={},
        current={},
        source_line=4,
        arg_index=0,
        affected_call_sites=[],
        actions=[
            SignatureAction(
                kind="call-argument-type-audit",
                confidence="low",
                affected_call_sites=[],
                reason="unclassified test action",
            )
        ],
    )

    summary = _summarize_report([finding])

    assert summary["audit_only_unrebucketed"] == 1
    assert summary["stop_condition"]["kind"] == "audit-only-unclassified"


def test_audit_maps_mixed_gpr_fpr_argument_to_correct_source_index() -> None:
    source = """
void caller_fn(float value, int count)
{
    helper(value, (f32) count);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tfmr f1, f31",
                "/* 0004 */\tmr r3, r30",
                "/* 0008 */\tbl helper",
            ],
            [
                "/* 0000 */\tfmr f1, f31",
                "/* 0004 */\tfmr f2, f30",
                "/* 0008 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    finding = report.findings[0]
    assert finding.kind == "argument-bank-mismatch"
    assert finding.arg_index == 1
    assert finding.affected_call_sites[0]["arg_text"] == "(f32) count"
    assert finding.actions[0].patch is not None
    assert finding.actions[0].patch.old == "(f32) count"


def test_audit_uses_rel24_target_for_placeholder_branch_link_call() -> None:
    source = """
void caller_fn(int arg0)
{
    helper((f32) arg0);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "+020: 7C 7F 1B 78    mr r3, r31",
                "+024: 48 00 00 01    bl <caller_fn+0x24>",
                "+024: R_PPC_REL24     helper",
            ],
            [
                "+020: FC 20 F8 90    fmr f1, f31",
                "+024: 48 00 00 01    bl <caller_fn+0x24>",
                "+024: R_PPC_REL24     helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert [finding.kind for finding in report.findings] == [
        "argument-bank-mismatch"
    ]
    finding = report.findings[0]
    assert finding.call_target == "helper"
    assert finding.source_line == 4
    assert finding.current["call_target"] == "helper"
    assert finding.current["display_target"] == "caller_fn+0x24"
    assert finding.current["relocation_target"] == "helper"
    assert finding.affected_call_sites[0]["call_target"] == "helper"
    assert finding.affected_call_sites[0]["arg_text"] == "(f32) arg0"
    assert finding.affected_call_sites[0]["localization_kind"] == "target-ordinal"


def test_audit_overall_ordinal_localization_is_diagnostic_only() -> None:
    source = """
void caller_fn(int first, int second)
{
    first_helper(first);
    source_helper((f32) second);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "+000: 7C 7F 1B 78    mr r3, r31",
                "+004: 48 00 00 01    bl first_helper",
                "+008: 7C 7E 1B 78    mr r3, r30",
                "+00C: 48 00 00 01    bl external_helper",
            ],
            [
                "+000: 7C 7F 1B 78    mr r3, r31",
                "+004: 48 00 00 01    bl first_helper",
                "+008: FC 20 F0 90    fmr f1, f30",
                "+00C: 48 00 00 01    bl external_helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert [finding.kind for finding in report.findings] == [
        "argument-bank-mismatch"
    ]
    finding = report.findings[0]
    assert finding.call_target == "external_helper"
    assert finding.source_line == 5
    assert finding.arg_index == 0
    affected = finding.affected_call_sites[0]
    assert affected["line"] == 5
    assert affected["call_target"] == "source_helper"
    assert affected["arg_text"] == "(f32) second"
    assert affected["localization_kind"] == "overall-ordinal"
    assert all(action.patch is None for action in finding.actions)
    assert finding.actions[0].rebucket["reason"] == "prototype-candidate-missing"


def test_audit_does_not_overall_localize_unresolved_local_offset_call() -> None:
    source = """
void caller_fn(int arg0)
{
    helper((f32) arg0);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "+020: 7C 7F 1B 78    mr r3, r31",
                "+024: 48 00 00 01    bl <caller_fn+0x24>",
            ],
            [
                "+020: FC 20 F8 90    fmr f1, f31",
                "+024: 48 00 00 01    bl <caller_fn+0x24>",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert [finding.kind for finding in report.findings] == [
        "argument-bank-mismatch"
    ]
    finding = report.findings[0]
    assert finding.source_line is None
    assert finding.affected_call_sites == []
    action = finding.actions[0]
    assert action.rebucket == {
        "reason": "intra-function-branch-link",
        "work_bucket": "structural-reconstruction",
        "subcategory": "branch-link-control-flow",
        "explanation": (
            "The branch-link target is an unresolved function-local offset; "
            "treat this as control-flow or structural reconstruction before "
            "auditing call argument types."
        ),
    }


def test_audit_rebuckets_relocated_call_without_source_expression() -> None:
    source = """
void caller_fn(int arg0)
{
    arg0 += 1;
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "+020: 7C 7F 1B 78    mr r3, r31",
                "+024: 48 00 00 01    bl <caller_fn+0x24>",
                "+024: R_PPC_REL24     generated_helper",
            ],
            [
                "+020: 7C 7E 1B 78    mr r3, r30",
                "+024: 48 00 00 01    bl <caller_fn+0x24>",
                "+024: R_PPC_REL24     generated_helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert [finding.kind for finding in report.findings] == [
        "argument-source-register-mismatch"
    ]
    finding = report.findings[0]
    assert finding.source_line is None
    action = finding.actions[0]
    assert action.rebucket == {
        "reason": "relocated-call-not-in-source",
        "work_bucket": "structural-reconstruction",
        "subcategory": "relocated-helper-no-source-call",
        "explanation": (
            "The ASM call resolves through R_PPC_REL24, but no matching source "
            "call expression was found; treat it as generated helper or "
            "structural call-shape work before auditing argument types."
        ),
    }


def test_audit_does_not_overall_localize_relocated_generated_helper() -> None:
    source = """
void caller_fn(int arg0)
{
    real_source_call((f32) arg0);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "+020: 7C 7F 1B 78    mr r3, r31",
                "+024: 48 00 00 01    bl <caller_fn+0x24>",
                "+024: R_PPC_REL24     generated_helper",
            ],
            [
                "+020: FC 20 F8 90    fmr f1, f31",
                "+024: 48 00 00 01    bl <caller_fn+0x24>",
                "+024: R_PPC_REL24     generated_helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    finding = report.findings[0]
    assert finding.source_line is None
    assert finding.affected_call_sites == []
    action = finding.actions[0]
    assert action.rebucket["reason"] == "relocated-call-not-in-source"
    assert action.patch is None


def test_audit_rebuckets_unresolved_local_offset_call_target_shape() -> None:
    source = """
void caller_fn(int arg0)
{
    helper(arg0);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "+020: 48 00 00 01    bl <caller_fn+0x20>",
            ],
            [
                "+024: 48 00 00 01    bl <caller_fn+0x24>",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert [finding.kind for finding in report.findings] == [
        "call-target-shape-mismatch"
    ]
    finding = report.findings[0]
    assert finding.source_line is None
    assert finding.affected_call_sites == []
    action = finding.actions[0]
    assert action.rebucket == {
        "reason": "intra-function-branch-link",
        "work_bucket": "structural-reconstruction",
        "subcategory": "branch-link-control-flow",
        "explanation": (
            "The branch-link target is an unresolved function-local offset; "
            "treat this as control-flow or structural reconstruction before "
            "auditing call argument types."
        ),
    }


def test_audit_rebuckets_one_sided_unresolved_local_offset_call_shape() -> None:
    source = """
void caller_fn(int arg0)
{
    helper(arg0);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "+020: 48 00 00 01    bl <caller_fn+0x20>",
            ],
            [
                "+020: 48 00 00 01    bl external_helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert [finding.kind for finding in report.findings] == [
        "call-target-shape-mismatch"
    ]
    action = report.findings[0].actions[0]
    assert action.rebucket["reason"] == "intra-function-branch-link"


def test_audit_filters_pad_stack_and_void_source_parser_artifacts() -> None:
    source = """
void caller_fn(int arg0)
{
    PAD_STACK(4);
    (void) arg0;
    helper((f32) arg0);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "+000: 7C 7F 1B 78    mr r3, r31",
                "+004: 48 00 00 01    bl external_helper",
            ],
            [
                "+000: FC 20 F8 90    fmr f1, f31",
                "+004: 48 00 00 01    bl external_helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert [finding.kind for finding in report.findings] == [
        "argument-bank-mismatch"
    ]
    affected = report.findings[0].affected_call_sites[0]
    assert affected["line"] == 6
    assert affected["call_target"] == "helper"
    assert affected["localization_kind"] == "overall-ordinal"


def test_audit_keeps_distinct_patches_for_repeated_call_sites() -> None:
    source = """
void caller_fn(int first, int second)
{
    helper((f32) first);
    helper((f32) second);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
                "/* 0008 */\tmr r3, r30",
                "/* 000C */\tbl helper",
            ],
            [
                "/* 0000 */\tfmr f1, f31",
                "/* 0004 */\tbl helper",
                "/* 0008 */\tfmr f1, f30",
                "/* 000C */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert len(report.findings) == 2
    patch_texts = [
        finding.actions[0].patch.old
        for finding in report.findings
        if finding.actions[0].patch is not None
    ]
    assert patch_texts == ["(f32) first", "(f32) second"]


def test_audit_stops_arg_prep_scan_at_previous_call() -> None:
    source = """
void caller_fn(int first)
{
    helper(first);
    later();
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
                "/* 0008 */\tbl later",
            ],
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
                "/* 0008 */\tbl later",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert report.findings == []


def test_audit_function_pointer_param_still_counts_as_fixed_prototype() -> None:
    source = """
static void helper(void (*cb)(int), int value) {}

void caller_fn(void (*cb)(int), int value)
{
    helper(cb, (f32) value);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tmr r4, r30",
                "/* 0008 */\tbl helper",
            ],
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tfmr f1, f30",
                "/* 0008 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert all(a.patch is None for a in report.findings[0].actions)


def test_audit_treats_pointer_casts_as_gpr_arguments() -> None:
    source = """
void caller_fn(int *ptr)
{
    helper((f32*) ptr);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert report.findings == []


def test_audit_preserves_pointer_types_in_visible_prototypes() -> None:
    source = """
static void helper(float *ptr, int value) {}
extern float *get_ptr(void);

void caller_fn(int value)
{
    helper(get_ptr(), (f32) value);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tmr r4, r30",
                "/* 0008 */\tbl helper",
            ],
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tfmr f1, f30",
                "/* 0008 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )

    assert report.findings[0].arg_index == 1
    assert all(a.patch is None for a in report.findings[0].actions)


def test_validate_signature_patch_attaches_candidate_delta() -> None:
    source = """
void caller_fn(int rumble_setting)
{
    helper((f32) rumble_setting);
}
"""
    report = audit_signature_call_type(
        _payload(
            [
                "/* 0000 */\tmr r3, r31",
                "/* 0004 */\tbl helper",
            ],
            [
                "/* 0000 */\tfmr f1, f31",
                "/* 0004 */\tbl helper",
            ],
        ),
        source,
        "caller_fn",
        source_file="src/sample.c",
    )
    seen_sources: list[str] = []

    def fake_runner(candidate_source: str) -> dict:
        seen_sources.append(candidate_source)
        return {
            "match": False,
            "fuzzy_match_percent": 99.25,
            "classification": {"primary": "argument-bank-mismatch"},
        }

    validate_signature_patches(
        report,
        source,
        fake_runner,
        baseline_match_percent=97.5,
    )

    assert len(seen_sources) == 1
    assert "helper(rumble_setting);" in seen_sources[0]
    validation = report.findings[0].actions[0].validation
    assert validation == {
        "status": "scored",
        "match": False,
        "baseline_match_percent": 97.5,
        "candidate_match_percent": 99.25,
        "delta_match_percent": 1.75,
        "classification": "argument-bank-mismatch",
    }
    assert report.summary["validated_patch_candidate_count"] == 1
    assert report.summary["unvalidated_patch_candidate_count"] == 0
    assert report.summary["stop_condition"]["kind"] == "validated-patch-candidates"
