from pathlib import Path
from src.search.producers import PermuterJobProducer
from src.search.store import ArtifactStore
from src.search.types import SourceSpec, TargetSpec, Budget
from src.search.artifact import CompileSpec

class FakeRemote:
    def __init__(self, tmp): self.tmp = tmp; self.stopped = []
    def submit(self, base_dir, function, remote): return f"{function}-{remote}-job"
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
