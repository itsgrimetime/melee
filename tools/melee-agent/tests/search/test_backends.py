"""Tests for search backends."""

from pathlib import Path
from src.search.backends import PlainLocalBackend
from src.search.store import ArtifactStore
from src.search.types import SourceVariant, TargetSpec, BackendCaps
from src.search.artifact import CompileSpec


class FakeCompiler:
    def __init__(self, tmp):
        self.tmp = tmp
        self.calls = 0

    def compile(self, source_text, target):
        self.calls += 1
        obj = self.tmp / "out.o"
        obj.write_bytes(b"OBJ:" + source_text.encode())
        return obj, ""


def _spec(tmp):
    return CompileSpec(
        "f@u", "c", "b", "t", "plain-local", tmp / "m.json"
    )


def test_plain_local_backend_compiles_and_persists(tmp_path):
    store = ArtifactStore(tmp_path / "store")
    comp = FakeCompiler(tmp_path)
    be = PlainLocalBackend(
        compiler=comp,
        store=store,
        compile_spec_factory=lambda v: _spec(tmp_path),
    )
    art = be.compile(SourceVariant("int f(){return 1;}", None))
    assert art.status == "ok" and art.object_path is not None
    assert store.root in art.source_blob.parents
    assert be.capabilities() == BackendCaps("local", 1, False)


def test_compile_failure_yields_compile_failed(tmp_path):
    store = ArtifactStore(tmp_path / "store")

    class FailComp:
        def compile(self, s, t):
            return None, "error: boom"

    be = PlainLocalBackend(
        compiler=FailComp(),
        store=store,
        compile_spec_factory=lambda v: _spec(tmp_path),
    )
    art = be.compile(SourceVariant("bad", None))
    assert (
        art.status == "compile_failed"
        and art.object_path is None
        and "boom" in art.compiler_stderr
    )
