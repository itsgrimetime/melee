from pathlib import Path
from src.search.store import ArtifactStore
from src.search.artifact import CompileManifest

def test_store_is_outside_repo_and_content_addressed(tmp_path):
    store = ArtifactStore(root=tmp_path / "store")
    p1 = store.put_source("int f(){return 0;}")
    p2 = store.put_source("int f(){return 0;}")
    assert p1 == p2
    assert store.root in p1.parents
    assert (store.root / ".gitignore").read_text().strip() == "*"

def test_manifest_round_trips(tmp_path):
    store = ArtifactStore(root=tmp_path / "store")
    man = CompileManifest(compile_command=["mwcc", "-c"], cflags=["-O4,p"],
                          include_paths=["src"], base_context_blob=tmp_path / "base.c")
    mp = store.put_manifest(man)
    got = store.read_manifest(mp)
    assert got.compile_command == ["mwcc", "-c"] and got.cflags == ["-O4,p"]

def test_locked_staging_restores_prior_object(tmp_path):
    store = ArtifactStore(root=tmp_path / "store")
    build_obj = tmp_path / "build" / "x.o"; build_obj.parent.mkdir(parents=True); build_obj.write_bytes(b"ORIG")
    cand_obj = tmp_path / "cand.o"; cand_obj.write_bytes(b"CANDIDATE")
    with store.stage_for_verify(build_obj, cand_obj):
        assert build_obj.read_bytes() == b"CANDIDATE"
    assert build_obj.read_bytes() == b"ORIG"
