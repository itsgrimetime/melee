from pathlib import Path
from src.search.producers import PermuterJobProducer
from src.search.store import ArtifactStore
from src.search.types import SourceSpec, TargetSpec, Budget
from src.search.artifact import CompileSpec

class FakeRemote:
    def __init__(self, tmp):
        self.tmp = tmp
        self.stopped = []
        self.submitted = []

    def submit(self, base_dir, function, remote):
        self.submitted.append((Path(base_dir), function, remote))
        return f"{function}-{remote}-job"
    def fetch(self, job_id):
        sc = self.tmp / f"{job_id}.c"; sc.write_text("int f(){return 9;}")
        return [(sc, 1560.0)]
    def status(self, job_id): return "running"
    def stop(self, job_id): self.stopped.append(job_id)

def _spec(tmp): return CompileSpec("f@u","c","b","t","permuter-job",tmp/"m.json")

def test_poll_yields_harvested_sourceonly_candidates(tmp_path):
    store = ArtifactStore(tmp_path/"store"); rem = FakeRemote(tmp_path)
    prod = PermuterJobProducer(client=rem, store=store, remotes=["coder1","coder3"],
                               compile_spec_factory=lambda txt: _spec(tmp_path))
    h = prod.start(SourceSpec("base", TargetSpec("f","u",tmp_path/"e.o")),
                   TargetSpec("f","u",tmp_path/"e.o"), Budget(max_iters=1000))
    assert len(h.job_ids) == 2
    cands = prod.poll(h)
    assert cands
    c = cands[0]
    assert c.status == "harvested" and c.object_path is None and c.byte_score is None
    assert c.producer_score == 1560.0
    assert store.root in c.source_blob.parents

def test_stop_only_targets_our_jobs(tmp_path):
    store = ArtifactStore(tmp_path/"store"); rem = FakeRemote(tmp_path)
    prod = PermuterJobProducer(client=rem, store=store, remotes=["coder1"],
                               compile_spec_factory=lambda txt: _spec(tmp_path))
    h = prod.start(SourceSpec("base", TargetSpec("f","u",tmp_path/"e.o")),
                   TargetSpec("f","u",tmp_path/"e.o"), Budget())
    prod.stop(h)
    assert rem.stopped == h.job_ids


def test_start_copies_remote_ready_permuter_support_files(tmp_path):
    perm_dir = tmp_path / "nonmatchings" / "f"
    perm_dir.mkdir(parents=True)
    compile_sh = perm_dir / "compile.sh"
    compile_sh.write_text("#!/bin/sh\nexit 0\n")
    compile_sh.chmod(0o755)
    (perm_dir / "settings.toml").write_text("base = \"base.c\"\n")
    (perm_dir / "target.o").write_bytes(b"target")

    store = ArtifactStore(tmp_path / "store")
    rem = FakeRemote(tmp_path)
    prod = PermuterJobProducer(
        client=rem,
        store=store,
        remotes=["coder1"],
        compile_spec_factory=lambda txt: _spec(tmp_path),
        permuter_base_dir=perm_dir,
        base_source_text="int f(void){return 1;}\n",
    )

    prod.start(
        SourceSpec("ignored scheduler base", TargetSpec("f", "u", tmp_path / "e.o")),
        TargetSpec("f", "u", tmp_path / "e.o"),
        Budget(max_iters=1),
    )

    submitted_dir, function, remote = rem.submitted[0]
    assert function == "f"
    assert remote == "coder1"
    assert (submitted_dir / "base.c").read_text() == "int f(void){return 1;}\n"
    assert (submitted_dir / "compile.sh").read_text() == "#!/bin/sh\nexit 0\n"
    assert (submitted_dir / "settings.toml").read_text() == "base = \"base.c\"\n"
    assert (submitted_dir / "target.o").read_bytes() == b"target"
    assert (submitted_dir / "compile.sh").stat().st_mode & 0o111


def test_start_uses_existing_permuter_base_when_no_seed_text(tmp_path):
    perm_dir = tmp_path / "nonmatchings" / "f"
    perm_dir.mkdir(parents=True)
    (perm_dir / "base.c").write_text("int f(void){return 7;}\n")
    (perm_dir / "compile.sh").write_text("#!/bin/sh\nexit 0\n")
    (perm_dir / "settings.toml").write_text("base = \"base.c\"\n")
    (perm_dir / "target.o").write_bytes(b"target")

    store = ArtifactStore(tmp_path / "store")
    rem = FakeRemote(tmp_path)
    prod = PermuterJobProducer(
        client=rem,
        store=store,
        remotes=["coder1"],
        compile_spec_factory=lambda txt: _spec(tmp_path),
        permuter_base_dir=perm_dir,
    )

    prod.start(
        SourceSpec("", TargetSpec("f", "u", tmp_path / "e.o")),
        TargetSpec("f", "u", tmp_path / "e.o"),
        Budget(max_iters=1),
    )

    submitted_dir, _, _ = rem.submitted[0]
    assert (submitted_dir / "base.c").read_text() == "int f(void){return 7;}\n"
