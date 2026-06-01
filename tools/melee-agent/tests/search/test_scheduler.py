from pathlib import Path
from src.search.scheduler import DefaultScheduler
from src.search.scoring import ByteScorePipeline
from src.search.store import ArtifactStore
from src.search.backends import PlainLocalBackend
from src.search.producers import PermuterJobProducer
from src.search.types import SourceSpec, TargetSpec, Budget, SchedulePolicy
from src.search.artifact import CompileSpec
from tests.search.test_producers import FakeRemote
from tests.search.test_backends import FakeCompiler

def _spec(tmp, mode): return CompileSpec("f@u","c","b","t",mode,tmp/"m.json")

class MatchScorer:
    def byte_distance(self, obj_path, target): return 0

def test_scheduler_promotes_harvested_then_scores_and_matches(tmp_path):
    store = ArtifactStore(tmp_path/"store")
    backend = PlainLocalBackend(compiler=FakeCompiler(tmp_path), store=store,
                                compile_spec_factory=lambda v: _spec(tmp_path,"plain-local"))
    producer = PermuterJobProducer(client=FakeRemote(tmp_path), store=store, remotes=["coder1"],
                                   compile_spec_factory=lambda t: _spec(tmp_path,"permuter-job"))
    pipe = ByteScorePipeline(scorer=MatchScorer())
    sched = DefaultScheduler(store=store, verifier=None)
    res = sched.run(sources=[], backends=[backend], producers=[producer], pipeline=pipe,
                    target=TargetSpec("f","u",tmp_path/"e.o"), budget=Budget(max_iters=1),
                    policy=SchedulePolicy(promote_top_k=4))
    assert res.matched is not None and res.matched.byte_score == 0
    assert res.accounting["harvested"] >= 1 and res.accounting["promoted"] >= 1

def test_scheduler_dedups_on_candidate_id(tmp_path):
    store = ArtifactStore(tmp_path/"store")
    comp = FakeCompiler(tmp_path)
    backend = PlainLocalBackend(compiler=comp, store=store,
                                compile_spec_factory=lambda v: _spec(tmp_path,"plain-local"))
    producer = PermuterJobProducer(client=FakeRemote(tmp_path), store=store, remotes=["coder1"],
                                   compile_spec_factory=lambda t: _spec(tmp_path,"permuter-job"))
    pipe = ByteScorePipeline(scorer=MatchScorer())
    sched = DefaultScheduler(store=store, verifier=None)
    sched.run(sources=[], backends=[backend], producers=[producer], pipeline=pipe,
              target=TargetSpec("f","u",tmp_path/"e.o"), budget=Budget(max_iters=2),
              policy=SchedulePolicy(promote_top_k=4))
    assert comp.calls == 1
