from pathlib import Path
from src.search import protocols as P
from src.search.types import SourceVariant, TargetSpec, Budget, BackendCaps


class FakeSource:
    def name(self):
        return "fake"

    def seed(self, base):
        pass

    def next_batch(self, n):
        return []

    def observe(self, scored):
        pass


def test_fake_source_satisfies_protocol():
    assert isinstance(FakeSource(), P.VariantSource)


def test_concrete_impls_satisfy_protocols(tmp_path):
    """Guard: the live concrete classes conform to their @runtime_checkable
    Protocols, so a signature regression trips here instead of at runtime."""
    from src.search.backends import PlainLocalBackend
    from src.search.producers import PermuterJobProducer
    from src.search.scheduler import DefaultScheduler
    from src.search.scoring import ByteScorePipeline
    from src.search.store import ArtifactStore

    store = ArtifactStore(tmp_path / "store")

    class _Compiler:
        def compile(self, source_text, target):
            return None, ""

    class _Client:
        def submit(self, base_dir, function, remote):
            return "job"

        def fetch(self, job_id):
            return []

        def status(self, job_id):
            return "drained"

        def stop(self, job_id):
            pass

    class _Scorer:
        def byte_distance(self, obj_path, target):
            return 0

    backend = PlainLocalBackend(
        compiler=_Compiler(), store=store, compile_spec_factory=lambda v: None
    )
    producer = PermuterJobProducer(
        client=_Client(), store=store, remotes=["coder1"],
        compile_spec_factory=lambda t: None,
    )
    pipeline = ByteScorePipeline(scorer=_Scorer())
    scheduler = DefaultScheduler(store=store, verifier=None)

    assert isinstance(backend, P.CompileBackend)
    assert isinstance(producer, P.ArtifactProducer)
    assert isinstance(pipeline, P.ScorePipeline)
    assert isinstance(scheduler, P.Scheduler)


def test_value_types_construct():
    sv = SourceVariant(source_text="int f(){}", provenance=None)
    assert sv.source_text.startswith("int")
    assert Budget(max_iters=10, max_seconds=5.0).max_iters == 10
    assert BackendCaps(location="local", parallelism=4, supports_pcdump=False).parallelism == 4
    assert TargetSpec(function="MatToQuat", unit="quatlib", expected_obj=Path("/x")).function == "MatToQuat"
