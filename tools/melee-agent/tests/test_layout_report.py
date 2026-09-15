import json
from src.layout.compare import Finding
from src.layout.audit import AuditResult, EnrichedFinding
from src.layout.report import render_text, render_json


def _result():
    f = Finding("size-mismatch", ".data", ("mnEvent_803EF788", 0x48, 0xA),
                [("mnEvent_803EF788", 0x48, 0xC)], "size 0xC vs target 0xA")
    ef = EnrichedFinding(f, source_line=89, suggestion="Resize the array/type.")
    return AuditResult("melee/mn/mnevent", degraded=False, warnings=["w1"],
                       findings=[f], enriched=[ef])


def test_render_text_groups_and_shows_suggestion():
    out = render_text(_result())
    assert "melee/mn/mnevent" in out
    assert "size-mismatch" in out
    assert "mnEvent_803EF788" in out
    assert "Resize the array/type." in out
    assert ":89" in out


def test_render_json_roundtrips():
    out = json.loads(render_json(_result()))
    assert out["obj_path"] == "melee/mn/mnevent"
    assert out["findings"][0]["kind"] == "size-mismatch"
    assert out["findings"][0]["source_line"] == 89


def test_render_text_no_findings():
    res = AuditResult("melee/mn/foo", degraded=False, warnings=[], findings=[], enriched=[])
    assert "no data-layout discrepancies found" in render_text(res)


def test_render_text_degraded_shows_marker_and_warnings():
    res = AuditResult("melee/mn/foo", degraded=True,
                      warnings=["reference object missing: x"], findings=[], enriched=[])
    out = render_text(res)
    assert "[DEGRADED]" in out
    assert "reference object missing" in out
