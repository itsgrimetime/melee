"""Regression tests for permuter candidate source auditing."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.mwcc_debug import candidate_audit

runner = CliRunner()


def test_candidate_audit_flags_placeholder_helpers() -> None:
    report = candidate_audit.audit_candidate_source(
        "void f(void) { inline_fn(); }\n"
    )

    assert report.status == "corrupt-candidate"
    assert report.semantic_risk_bucket == "repo-invalid"
    assert report.should_reject is True
    assert report.risks[0].kind == "placeholder-leak"
    assert report.risks[0].name == "inline_fn"


def test_candidate_audit_rejects_nested_assignment_to_same_scalar() -> None:
    report = candidate_audit.audit_candidate_source(
        "void f(void) { abs = (abs = -abs); }\n"
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert report.should_reject is True
    assert any(r.kind == "repeated-scalar-assignment" for r in report.risks)


def test_candidate_audit_rejects_pointer_field_self_assignment() -> None:
    report = candidate_audit.audit_candidate_source(
        "void f(void) { table->xD74 = table->xD74; }\n"
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert report.should_reject is True
    assert any(r.kind == "memory-self-assignment" for r in report.risks)


def test_candidate_audit_rejects_compound_noop_memory_writes() -> None:
    for source in [
        "void f(void) { table->xD8C += 0; }\n",
        "void f(void) { table->xD8C -= 0; }\n",
        "void f(void) { table->xD8C *= 1; }\n",
    ]:
        report = candidate_audit.audit_candidate_source(source)

        assert report.status == "unsafe-candidate"
        assert report.semantic_risk_bucket == "semantic-risk-high"
        assert report.should_reject is True
        assert any(r.kind == "memory-compound-noop" for r in report.risks)


def test_candidate_audit_rejects_scalar_self_assignment_noop() -> None:
    report = candidate_audit.audit_candidate_source(
        "void f(void) { abs = abs; }\n"
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert report.should_reject is True
    assert report.risks[0].severity == "reject"
    assert report.risks[0].kind == "scalar-self-assignment"


def test_candidate_audit_allows_scalar_self_assignment_already_in_base() -> None:
    base = "void f(int abs) { abs = abs; sink(abs); }\n"
    candidate = "void f(int abs) { abs = abs; sink(abs + 1); }\n"

    report = candidate_audit.audit_candidate_source(
        candidate,
        base_text=base,
    )

    assert report.status == "ok"
    assert report.semantic_risk_bucket == "plausible-C-shape"
    assert not any(r.kind == "scalar-self-assignment" for r in report.risks)


def test_candidate_audit_rejects_new_scalar_self_assignment_not_in_base() -> None:
    base = "void f(int abs, int x) { abs = abs; sink(x); }\n"
    candidate = "void f(int abs, int x) { abs = abs; x = x; sink(x); }\n"

    report = candidate_audit.audit_candidate_source(
        candidate,
        base_text=base,
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert any(
        r.kind == "scalar-self-assignment" and r.name == "x"
        for r in report.risks
    )
    assert not any(
        r.kind == "scalar-self-assignment" and r.name == "abs"
        for r in report.risks
    )


def test_candidate_audit_rejects_abs_call_mutations() -> None:
    base = "int f(int x) { return x < 0 ? -x : x; }\n"
    candidate = "int f(int x) { return abs(x); }\n"

    report = candidate_audit.audit_candidate_source(
        candidate,
        base_text=base,
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert report.should_reject is True
    assert any(r.kind == "abs-call-mutation" for r in report.risks)


def test_candidate_audit_rejects_negation_after_manual_abs() -> None:
    base = """
void f(float delta)
{
    float abs = delta;
    if (abs < 0.0f) {
        abs = -abs;
    }
    table->xD74 += abs;
}
"""
    candidate = """
void f(float delta)
{
    float abs = delta;
    if (abs < 0.0f) {
        abs = -abs;
    }
    abs = -abs;
    table->xD74 += abs;
}
"""

    report = candidate_audit.audit_candidate_source(
        candidate,
        base_text=base,
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert report.should_reject is True
    assert any(r.kind == "manual-abs-sign-flip" for r in report.risks)


def test_candidate_audit_rejects_local_use_before_assignment() -> None:
    report = candidate_audit.audit_candidate_source(
        """
typedef struct HSD_JObj HSD_JObj;
void f(void)
{
    HSD_JObj* jobj;
    HSD_JObjAddAnimAll(jobj, NULL, NULL, NULL);
    jobj = HSD_JObjLoadJoint(desc);
}
"""
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert report.should_reject is True
    assert any(
        r.kind == "use-before-def" and r.name == "jobj"
        for r in report.risks
    )


def test_candidate_audit_allows_local_after_assignment_or_initializer() -> None:
    report = candidate_audit.audit_candidate_source(
        """
void f(void)
{
    int loaded = make_value();
    int tmp;
    tmp = loaded + 1;
    use(tmp);
}
"""
    )

    assert report.status == "ok"
    assert report.semantic_risk_bucket == "plausible-C-shape"
    assert not any(r.kind == "use-before-def" for r in report.risks)


def test_candidate_audit_allows_struct_field_hoist_to_local() -> None:
    report = candidate_audit.audit_candidate_source(
        """
typedef unsigned char u8;
typedef struct Diagram {
    u8 is_name_mode;
} Diagram;
void f(Diagram* data)
{
    u8 result;
    result = data->is_name_mode;
    if (result != 0) {
        use(result);
    }
}
"""
    )

    assert report.status == "ok"
    assert report.semantic_risk_bucket == "plausible-C-shape"
    assert not any(r.kind == "use-before-def" for r in report.risks)


def test_candidate_audit_member_assignment_does_not_define_same_named_local() -> None:
    report = candidate_audit.audit_candidate_source(
        """
typedef unsigned char u8;
typedef struct Diagram {
    u8 is_name_mode;
} Diagram;
void f(Diagram* data)
{
    u8 is_name_mode;
    data->is_name_mode = 1;
    use(is_name_mode);
}
"""
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert report.should_reject is True
    assert any(
        r.kind == "use-before-def" and r.name == "is_name_mode"
        for r in report.risks
    )


def test_candidate_audit_member_read_does_not_read_same_named_local() -> None:
    report = candidate_audit.audit_candidate_source(
        """
typedef unsigned char u8;
typedef struct Diagram {
    u8 is_name_mode;
} Diagram;
void f(Diagram* data)
{
    u8 is_name_mode;
    u8 result = data->is_name_mode;
    use(result);
}
"""
    )

    assert report.status == "ok"
    assert report.semantic_risk_bucket == "plausible-C-shape"
    assert not any(r.kind == "use-before-def" for r in report.risks)


def test_candidate_audit_does_not_reject_base_existing_use_before_def() -> None:
    base = """
void f(void)
{
    int tmp;
    use(tmp);
}
"""
    candidate = """
void f(void)
{
    int tmp;
    use(tmp);
}
"""

    report = candidate_audit.audit_candidate_source(candidate, base_text=base)

    assert report.status == "ok"
    assert report.semantic_risk_bucket == "plausible-C-shape"
    assert not any(r.kind == "use-before-def" for r in report.risks)


def test_candidate_audit_rejects_scalar_clobber_store_before_read() -> None:
    base = """
void f(int max_percentage, int max_distance)
{
    int val;
    val = max_percentage;
    if (val > max_percentage) {
        use(val);
    }
}
"""
    candidate = """
void f(int max_percentage, int max_distance)
{
    int val;
    val = max_percentage;
    val = max_distance;
    if (val > max_percentage) {
        use(val);
    }
}
"""

    report = candidate_audit.audit_candidate_source(
        candidate,
        base_text=base,
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert any(
        r.kind == "scalar-clobber-store" and r.name == "val"
        for r in report.risks
    )


def test_candidate_audit_rejects_unproven_alias_substitution() -> None:
    base = """
void f(char* icon_text, char* value_text)
{
    HSD_SisLib_803A6368(icon_text, 17);
}
"""
    candidate = """
void f(char* icon_text, char* value_text)
{
    value_text = icon_text;
    HSD_SisLib_803A6368(value_text, 17);
}
"""

    report = candidate_audit.audit_candidate_source(
        candidate,
        base_text=base,
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert any(
        r.kind == "alias-substitution" and r.name == "value_text"
        for r in report.risks
    )


def test_candidate_audit_rejects_call_hoist_into_conditional() -> None:
    base = """
void f(int val, int max_time)
{
    if (val > max_time) {
        val = max_time;
    }
    mnDiagram_FormatTime(sp58, val);
}
"""
    candidate = """
void f(int val, int max_time)
{
    if (val > max_time) {
        val = max_time;
        mnDiagram_FormatTime(sp58, val);
    }
}
"""

    report = candidate_audit.audit_candidate_source(
        candidate,
        base_text=base,
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert any(
        r.kind == "call-hoist-into-conditional"
        and r.name == "mnDiagram_FormatTime"
        for r in report.risks
    )


def test_candidate_audit_rejects_undeclared_raw_register_identifier() -> None:
    report = candidate_audit.audit_candidate_source(
        """
void f(char* value_text)
{
    HSD_SisLib_803A6368(value_text, r17);
}
"""
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "semantic-risk-high"
    assert any(
        r.kind == "raw-register-identifier" and r.name == "r17"
        for r in report.risks
    )


def test_candidate_audit_allows_declared_register_like_identifier() -> None:
    report = candidate_audit.audit_candidate_source(
        """
void f(void)
{
    int r17 = 1;
    use(r17);
}
"""
    )

    assert report.status == "ok"
    assert report.semantic_risk_bucket == "plausible-C-shape"
    assert not any(
        r.kind == "raw-register-identifier"
        for r in report.risks
    )


def test_candidate_audit_buckets_plausible_c_shape() -> None:
    report = candidate_audit.audit_candidate_source(
        "void f(int x)\n{\n    int tmp = x + 1;\n    use(tmp);\n}\n"
    )

    assert report.status == "ok"
    assert report.semantic_risk_bucket == "plausible-C-shape"
    assert report.risks == ()


def test_candidate_audit_rejects_external_prototype_mutations() -> None:
    base = (
        "typedef struct Vec3 Vec3;\n"
        "void Stage_UnkSetVec3TCam_Offset(Vec3 *);\n"
        "void fn_8003F654(Vec3 *v) { Stage_UnkSetVec3TCam_Offset(v); }\n"
    )
    candidate = (
        "typedef struct Vec3 Vec3;\n"
        "volatile unsigned int Stage_UnkSetVec3TCam_Offset(Vec3 *);\n"
        "void fn_8003F654(Vec3 *v) { Stage_UnkSetVec3TCam_Offset(v); }\n"
    )

    report = candidate_audit.audit_candidate_source(
        candidate,
        base_text=base,
    )

    assert report.status == "unsafe-candidate"
    assert report.semantic_risk_bucket == "repo-invalid"
    assert report.should_reject is True
    assert any(r.kind == "external-prototype-mutation" for r in report.risks)


def test_candidate_audit_writes_status_sidecar(tmp_path: Path) -> None:
    candidate = tmp_path / "output-1-1" / "source.c"
    candidate.parent.mkdir()
    candidate.write_text("void f(void) { abs = abs; }\n")
    report = candidate_audit.audit_candidate_source(candidate.read_text())

    sidecar = candidate_audit.write_candidate_status(
        candidate,
        status=report.status,
        function="f",
        first_diag=candidate_audit.format_candidate_audit_diagnostic(
            report,
            command="test",
            candidate=candidate,
        ),
        risks=report.risks,
    )

    payload = json.loads(sidecar.read_text())
    assert payload["status"] == "unsafe-candidate"
    assert payload["semantic_risk_bucket"] == "semantic-risk-high"
    assert payload["function"] == "f"
    assert payload["source_risks"][0]["kind"] == "scalar-self-assignment"


def test_candidate_audit_tree_marks_fetched_outputs(tmp_path: Path) -> None:
    good = tmp_path / "output-1-1" / "source.c"
    bad = tmp_path / "output-2-1" / "source.c"
    good.parent.mkdir()
    bad.parent.mkdir()
    good.write_text("void f(void) { abs = abs; }\n")
    bad.write_text("void f(void) { helper_fn(); }\n")

    summary = candidate_audit.audit_candidate_tree(tmp_path, function="f")

    assert summary["total"] == 2
    assert summary["by_status"]["unsafe-candidate"] == 1
    assert summary["by_status"]["corrupt-candidate"] == 1
    assert summary["by_semantic_risk_bucket"]["semantic-risk-high"] == 1
    assert summary["by_semantic_risk_bucket"]["repo-invalid"] == 1
    assert (tmp_path / "candidate_audit.json").exists()
    assert (good.parent / "melee-agent-candidate-status.json").exists()
    assert (bad.parent / "melee-agent-candidate-status.json").exists()


def test_candidate_audit_cli_prints_tree_summary(tmp_path: Path) -> None:
    good = tmp_path / "output-1-1" / "source.c"
    bad = tmp_path / "output-2-1" / "source.c"
    good.parent.mkdir()
    bad.parent.mkdir()
    good.write_text("void f(void) { abs = abs; }\n")
    bad.write_text("void f(void) { helper_fn(); }\n")

    result = runner.invoke(
        app,
        [
            "debug",
            "permute",
            "candidate-audit",
            str(tmp_path),
            "--function",
            "f",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Candidates: 2" in result.stdout
    assert "unsafe-candidate: 1" in result.stdout
    assert "corrupt-candidate: 1" in result.stdout
    assert "candidate_audit.json" in result.stdout


def test_candidate_audit_tree_uses_base_for_prototype_mutations(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.c"
    candidate = tmp_path / "output-1-1" / "source.c"
    candidate.parent.mkdir()
    base.write_text(
        "typedef struct Vec3 Vec3;\n"
        "void Stage_UnkSetVec3TCam_Offset(Vec3 *);\n"
        "void fn_8003F654(Vec3 *v) { Stage_UnkSetVec3TCam_Offset(v); }\n"
    )
    candidate.write_text(
        "typedef struct Vec3 Vec3;\n"
        "volatile unsigned int Stage_UnkSetVec3TCam_Offset(Vec3 *);\n"
        "void fn_8003F654(Vec3 *v) { Stage_UnkSetVec3TCam_Offset(v); }\n"
    )

    summary = candidate_audit.audit_candidate_tree(
        tmp_path,
        function="fn_8003F654",
    )

    assert summary["by_status"]["unsafe-candidate"] == 1
    assert summary["by_semantic_risk_bucket"]["repo-invalid"] == 1
    payload = json.loads(
        (candidate.parent / "melee-agent-candidate-status.json").read_text()
    )
    assert payload["semantic_risk_bucket"] == "repo-invalid"
    assert payload["source_risks"][0]["kind"] == "external-prototype-mutation"


def test_candidate_audit_tree_finds_ancestor_base_for_remote_runs(
    tmp_path: Path,
) -> None:
    perm_root = tmp_path / "nonmatchings" / "fn_8003F654"
    run_root = perm_root / "remote-runs" / "job-1"
    candidate = run_root / "output-1-1" / "source.c"
    candidate.parent.mkdir(parents=True)
    (perm_root / "base.c").write_text(
        "typedef struct Vec3 Vec3;\n"
        "void Stage_UnkSetVec3TCam_Offset(Vec3 *);\n"
        "void fn_8003F654(Vec3 *v) { Stage_UnkSetVec3TCam_Offset(v); }\n"
    )
    candidate.write_text(
        "typedef struct Vec3 Vec3;\n"
        "volatile unsigned int Stage_UnkSetVec3TCam_Offset(Vec3 *);\n"
        "void fn_8003F654(Vec3 *v) { Stage_UnkSetVec3TCam_Offset(v); }\n"
    )

    summary = candidate_audit.audit_candidate_tree(
        run_root,
        function="fn_8003F654",
    )

    assert summary["by_status"]["unsafe-candidate"] == 1
    assert summary["by_semantic_risk_bucket"]["repo-invalid"] == 1
    payload = json.loads(
        (candidate.parent / "melee-agent-candidate-status.json").read_text()
    )
    assert payload["semantic_risk_bucket"] == "repo-invalid"
    assert payload["source_risks"][0]["kind"] == "external-prototype-mutation"


def test_candidate_audit_tree_does_not_downgrade_verified_failure(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "output-1-1" / "source.c"
    candidate.parent.mkdir()
    candidate.write_text("void f(void) { ok(); }\n")
    candidate_audit.write_candidate_status(
        candidate,
        status="build-failed",
        function="f",
        first_diag="compiler error",
        source="verify",
    )

    summary = candidate_audit.audit_candidate_tree(tmp_path, function="f")

    assert summary["by_status"]["ok"] == 1
    payload = json.loads(
        (candidate.parent / "melee-agent-candidate-status.json").read_text()
    )
    assert payload["status"] == "build-failed"
    assert payload["semantic_risk_bucket"] == "repo-invalid"
    assert payload["first_diag"] == "compiler error"
    assert payload["fetch_audit"]["status"] == "ok"
    assert payload["fetch_audit"]["semantic_risk_bucket"] == "plausible-C-shape"
