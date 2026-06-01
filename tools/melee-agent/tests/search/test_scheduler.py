from pathlib import Path
from src.search.scheduler import DefaultScheduler
from src.search.scoring import ByteScorePipeline
from src.search.store import ArtifactStore
from src.search.backends import PlainLocalBackend
from src.search.producers import PermuterJobProducer
from src.search.types import SourceSpec, TargetSpec, Budget, SchedulePolicy, SourceVariant
from src.search.artifact import CompileSpec
from tests.search.test_producers import FakeRemote
from tests.search.test_backends import FakeCompiler

def _spec(tmp, mode): return CompileSpec("f@u","c","b","t",mode,tmp/"m.json")

class MatchScorer:
    def byte_distance(self, obj_path, target): return 0

class NonMatchScorer:
    def byte_distance(self, obj_path, target): return 7

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


class _RecordingSource:
    """Source that yields one variant per call and records observe() batches."""
    def __init__(self):
        self._done = False
        self.observed = []
    def name(self): return "recording"
    def seed(self, base): pass
    def next_batch(self, n):
        if self._done:
            return []
        self._done = True
        return [SourceVariant("int f(){return 1;}", None)]
    def observe(self, scored):
        self.observed.append(scored)


def test_scheduler_calls_observe_per_drained_batch(tmp_path):
    store = ArtifactStore(tmp_path/"store")
    backend = PlainLocalBackend(compiler=FakeCompiler(tmp_path), store=store,
                                compile_spec_factory=lambda v: _spec(tmp_path,"plain-local"))
    pipe = ByteScorePipeline(scorer=NonMatchScorer())
    src = _RecordingSource()
    sched = DefaultScheduler(store=store, verifier=None)
    sched.run(sources=[src], backends=[backend], producers=[], pipeline=pipe,
              target=TargetSpec("f","u",tmp_path/"e.o"), budget=Budget(max_iters=1),
              policy=SchedulePolicy())
    # observe was called once with the scored batch (one ok candidate)
    assert len(src.observed) == 1
    assert len(src.observed[0]) == 1
    assert src.observed[0][0].status == "ok"


class _FlakyCompiler:
    """Fails the first `fail_n` compile calls, then succeeds."""
    def __init__(self, tmp, fail_n):
        self.tmp = tmp; self.fail_n = fail_n; self.calls = 0
    def compile(self, source_text, target):
        self.calls += 1
        if self.calls <= self.fail_n:
            return None, "transient error"
        obj = self.tmp / "out.o"; obj.write_bytes(b"OBJ:" + source_text.encode())
        return obj, ""


def test_scheduler_retries_transient_compile_failure(tmp_path):
    store = ArtifactStore(tmp_path/"store")
    comp = _FlakyCompiler(tmp_path, fail_n=2)   # fail twice, succeed on 3rd
    backend = PlainLocalBackend(compiler=comp, store=store,
                                compile_spec_factory=lambda v: _spec(tmp_path,"plain-local"))
    src = _RecordingSource()
    pipe = ByteScorePipeline(scorer=MatchScorer())
    sched = DefaultScheduler(store=store, verifier=None)
    res = sched.run(sources=[src], backends=[backend], producers=[], pipeline=pipe,
                    target=TargetSpec("f","u",tmp_path/"e.o"), budget=Budget(max_iters=1),
                    policy=SchedulePolicy(max_retries=2))
    # 1 initial + 2 retries == 3 compile calls; final attempt matched.
    assert comp.calls == 3
    assert res.accounting["retried"] == 2
    assert res.matched is not None


def test_scheduler_retry_is_bounded(tmp_path):
    store = ArtifactStore(tmp_path/"store")
    comp = _FlakyCompiler(tmp_path, fail_n=99)  # always fails within bound
    backend = PlainLocalBackend(compiler=comp, store=store,
                                compile_spec_factory=lambda v: _spec(tmp_path,"plain-local"))
    src = _RecordingSource()
    pipe = ByteScorePipeline(scorer=MatchScorer())
    sched = DefaultScheduler(store=store, verifier=None)
    res = sched.run(sources=[src], backends=[backend], producers=[], pipeline=pipe,
                    target=TargetSpec("f","u",tmp_path/"e.o"), budget=Budget(max_iters=1),
                    policy=SchedulePolicy(max_retries=2))
    # bounded: 1 initial + exactly 2 retries, then give up -> compile_failed.
    assert comp.calls == 3
    assert res.accounting["compile_failed"] == 1
    assert res.matched is None
