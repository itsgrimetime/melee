"""Tests for PcdumpLocalBackend (Task 2)."""

import subprocess
from pathlib import Path

from src.search.directed.pcdump_backend import PcdumpLocalBackend
from src.search.types import TargetSpec, SourceVariant, BackendCaps
from src.search.artifact import CompileSpec


def _spec():
    return CompileSpec(
        "grIceMt_801F9ACC@melee/gr/gricemt",
        "cf",
        "bc",
        "tc",
        "pcdump-local",
        Path("/m"),
    )


class _FakeStore:
    def __init__(self, root):
        self.root = root

    def put_source(self, text):
        p = self.root / "blob.c"
        p.write_text(text)
        return p


def _rc0():
    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    return R()


def test_caps_report_pcdump(tmp_path):
    be = PcdumpLocalBackend(
        melee_root=tmp_path,
        unit="melee/gr/gricemt",
        target=TargetSpec("grIceMt_801F9ACC", "melee/gr/gricemt", tmp_path / "e.o"),
        store=_FakeStore(tmp_path),
        compile_spec_factory=lambda v: _spec(),
        runner=lambda argv, **k: _rc0(),
    )
    assert be.capabilities() == BackendCaps("local", 1, True)


def test_compile_binds_obj_and_pcdump_and_restores(tmp_path):
    (tmp_path / "src/melee/gr").mkdir(parents=True)
    (tmp_path / "src/melee/gr/gricemt.c").write_text("orig")

    def runner(argv, **k):
        Path(argv[argv.index("--keep-obj") + 1]).write_bytes(b"\x00" * 4)
        Path(argv[argv.index("--output") + 1]).write_text("PCDUMP")

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    be = PcdumpLocalBackend(
        melee_root=tmp_path,
        unit="melee/gr/gricemt",
        target=TargetSpec("grIceMt_801F9ACC", "melee/gr/gricemt", tmp_path / "e.o"),
        store=_FakeStore(tmp_path),
        compile_spec_factory=lambda v: _spec(),
        runner=runner,
    )
    art = be.compile(SourceVariant("CAND", None), want_pcdump=True)
    assert art.object_path and art.object_path.exists()
    assert art.pcdump_path and art.pcdump_path.read_text() == "PCDUMP"
    assert (tmp_path / "src/melee/gr/gricemt.c").read_text() == "orig"  # restored
    assert art.status == "ok"


def test_compile_failed_when_obj_missing(tmp_path):
    (tmp_path / "src/melee/gr").mkdir(parents=True)
    (tmp_path / "src/melee/gr/gricemt.c").write_text("orig")

    def runner(argv, **k):
        class R:
            returncode = 1
            stdout = ""
            stderr = "boom"

        return R()

    be = PcdumpLocalBackend(
        melee_root=tmp_path,
        unit="melee/gr/gricemt",
        target=TargetSpec("grIceMt_801F9ACC", "melee/gr/gricemt", tmp_path / "e.o"),
        store=_FakeStore(tmp_path),
        compile_spec_factory=lambda v: _spec(),
        runner=runner,
    )
    art = be.compile(SourceVariant("CAND", None), want_pcdump=True)
    assert art.status == "compile_failed"


def test_compile_timeout_returns_failed_artifact_and_restores(tmp_path):
    (tmp_path / "src/melee/gr").mkdir(parents=True)
    tu = tmp_path / "src/melee/gr/gricemt.c"
    tu.write_text("orig")
    captured = {}

    def runner(argv, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        captured["env"] = kwargs.get("env")
        raise subprocess.TimeoutExpired(
            argv,
            kwargs.get("timeout"),
            output="partial stdout",
            stderr="unreaped uninterruptible wibo process",
        )

    be = PcdumpLocalBackend(
        melee_root=tmp_path,
        unit="melee/gr/gricemt",
        target=TargetSpec("grIceMt_801F9ACC", "melee/gr/gricemt", tmp_path / "e.o"),
        store=_FakeStore(tmp_path),
        compile_spec_factory=lambda v: _spec(),
        runner=runner,
        timeout=17,
    )

    art = be.compile(SourceVariant("CAND", None), want_pcdump=True)

    assert captured["timeout"] == 17
    assert captured["env"] is not None
    assert float(captured["env"]["MWCC_DEBUG_HANG_TIMEOUT"]) < 17
    assert tu.read_text() == "orig"
    assert art.status == "compile_failed"
    assert art.object_path is None
    assert art.pcdump_path is None
    assert "unreaped uninterruptible wibo process" in art.compiler_stderr
