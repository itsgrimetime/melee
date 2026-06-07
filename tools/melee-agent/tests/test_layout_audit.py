from pathlib import Path
import pytest
from src.layout.audit import audit_tu, AuditResult, suggest
from src.layout.compare import Finding

REPO = Path(__file__).resolve().parents[3]  # tools/melee-agent/tests -> repo root


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
