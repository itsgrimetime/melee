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


def test_value_types_construct():
    sv = SourceVariant(source_text="int f(){}", provenance=None)
    assert sv.source_text.startswith("int")
    assert Budget(max_iters=10, max_seconds=5.0).max_iters == 10
    assert BackendCaps(location="local", parallelism=4, supports_pcdump=False).parallelism == 4
    assert TargetSpec(function="MatToQuat", unit="quatlib", expected_obj=Path("/x")).function == "MatToQuat"
