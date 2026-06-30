from pathlib import Path
import pytest
from src.layout.audit import audit_tu, AuditResult, suggest
from src.layout.compare import Finding

REPO = Path(__file__).resolve().parents[3]  # tools/melee-agent/tests -> repo root


@pytest.mark.skipif(
    not (REPO / "build/GALE01/obj/melee/pl/plbonus.o").exists()
    or not (REPO / "build/GALE01/src/melee/pl/plbonus.o").exists(),
    reason="plbonus objects not built",
)
def test_lbl_symbols_are_compared_not_dropped():
    res = audit_tu(REPO, REPO / "src/melee/pl/plbonus.c")
    # lbl_ target symbols must appear in findings (they are real production symbols),
    # not silently filtered out as anonymous.
    assert any(f.target and f.target[0].startswith("lbl_") for f in res.findings), \
        "lbl_ target symbols were dropped — they must be compared, not treated as anonymous"


def test_suggest_covers_every_kind():
    for kind in ["split", "merge", "size-mismatch", "reorder",
                 "section-mismatch", "binding-mismatch", "missing", "anonymous"]:
        assert suggest(Finding(kind, ".data", ("s", 0, 8), [("s", 0, 8)], "m"))


def test_audit_degraded_when_objects_missing(tmp_path):
    c = tmp_path / "src" / "melee" / "xx" / "foo.c"
    c.parent.mkdir(parents=True)
    c.write_text("static int foo_8000 = 0;\n")
    res = audit_tu(tmp_path, c)
    assert res.degraded is True
    assert res.findings == []
    assert res.warnings  # warns about the missing object
    assert res.obj_path == "melee/xx/foo"


def test_audit_degraded_when_our_obj_missing(tmp_path):
    c = tmp_path / "src" / "melee" / "xx" / "foo.c"
    c.parent.mkdir(parents=True)
    c.write_text("static int foo_8000 = 0;\n")
    ref = tmp_path / "build/GALE01/obj/melee/xx/foo.o"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"")
    res = audit_tu(tmp_path, c)
    assert res.degraded is True
    assert "build it first" in res.warnings[0]


def test_audit_warns_when_no_symbols_read(tmp_path, monkeypatch):
    c = tmp_path / "src" / "melee" / "xx" / "foo.c"
    c.parent.mkdir(parents=True)
    c.write_text("static int foo = 0;\n")
    for rel in ["build/GALE01/obj/melee/xx/foo.o", "build/GALE01/src/melee/xx/foo.o"]:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"\x7fELF")
    import src.layout.audit as mod
    monkeypatch.setattr(mod, "section_intervals", lambda _p: {})
    res = mod.audit_tu(tmp_path, c)
    assert any("unreadable" in w or "no data symbols" in w for w in res.warnings)


@pytest.mark.skipif(
    not (REPO / "build/GALE01/obj/melee/mn/mnevent.o").exists()
    or not (REPO / "build/GALE01/src/melee/mn/mnevent.o").exists(),
    reason="mnevent objects not built",
)
def test_mnevent_acceptance_flags_known_issues():
    res = audit_tu(REPO, REPO / "src/melee/mn/mnevent.c")
    assert isinstance(res, AuditResult)
    by_name = {(f.target[0] if f.target else None): f.kind for f in res.findings}
    assert by_name.get("mnEvent_803EF758") == "split"
    assert by_name.get("mnEvent_803EF788") == "size-mismatch"
    assert by_name.get("mnEvent_804A0908") == "section-mismatch"
    assert all(f.kind != "binding-mismatch" for f in res.findings)
