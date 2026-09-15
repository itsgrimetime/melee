from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

import pytest

from src.mwcc_debug.causal_diff.bundles import (
    CORE_BACKEND_CAPABILITIES,
    BundleInputError,
    load_bundle,
    validate_bundle_pair,
    validate_capability_union,
)
from src.mwcc_debug.causal_diff.canonical import canonical_bytes
from src.mwcc_debug.causal_diff.models import FrontierBundleManifestV2


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compile_id(
    *,
    function: str,
    compiler: str,
    target_build: str,
    flags_digest: str,
    environment_digest: str,
    source_digest: str,
) -> str:
    return _sha256(
        canonical_bytes(
            {
                "function": function,
                "compiler": compiler,
                "target_build": target_build,
                "flags_digest": flags_digest,
                "environment_digest": environment_digest,
                "source_digest": source_digest,
            }
        )
    )


def write_valid_bundle(
    directory: Path,
    *,
    label: str,
    source: str,
    function: str = "fn_test",
    compiler: str = "mwcc_233_163n",
    target_build: str = "GALE01",
    flags_digest: str | None = None,
    environment_digest: str | None = None,
) -> Path:
    directory.mkdir(parents=True)
    artifact_data = {
        "source": source.encode(),
        "checkdiff": b'{"expected": [], "actual": []}\n',
        "backend": b"PCode for fn_test\n",
        "inspector": b"Statements for fn_test\n",
        "frame_report": b'{"frame_size": 0}\n',
    }
    artifact_names = {
        "source": "candidate.c",
        "checkdiff": "checkdiff.json",
        "backend": "backend.pcdump.txt",
        "inspector": "inspector.txt",
        "frame_report": "frame.json",
    }
    digests: dict[str, str] = {}
    for name, data in artifact_data.items():
        (directory / artifact_names[name]).write_bytes(data)
        digests[name] = _sha256(data)

    flags_digest = flags_digest or _sha256(b"-O4,p -proc gekko")
    environment_digest = environment_digest or _sha256(b"mwcc-debug-env-v1")
    compile_id = _compile_id(
        function=function,
        compiler=compiler,
        target_build=target_build,
        flags_digest=flags_digest,
        environment_digest=environment_digest,
        source_digest=digests["source"],
    )
    payload = {
        "schema_version": "causal-frontier-bundle.v1",
        "label": label,
        "function": function,
        "compile": {
            "id": compile_id,
            "compiler": compiler,
            "target_build": target_build,
            "flags_digest": flags_digest,
            "environment_digest": environment_digest,
            "source_digest": digests["source"],
            "expected_assembly_digest": _sha256(b"retail fn_test assembly"),
        },
        "artifacts": {
            "source": {
                "path": artifact_names["source"],
                "sha256": digests["source"],
            },
            "checkdiff": {
                "path": artifact_names["checkdiff"],
                "sha256": digests["checkdiff"],
            },
            "backend": [
                {
                    "path": artifact_names["backend"],
                    "sha256": digests["backend"],
                    "format": "mwcc-debug-pcdump",
                    "capabilities": sorted(CORE_BACKEND_CAPABILITIES),
                }
            ],
            "inspector": {
                "path": artifact_names["inspector"],
                "sha256": digests["inspector"],
            },
            "frame_report": {
                "path": artifact_names["frame_report"],
                "sha256": digests["frame_report"],
            },
        },
        "producer_versions": {
            "checkdiff": "checkdiff-json.v1",
            "mwcc_debug": "mwcc-debug-pcdump.v1",
            "mwcc_inspect": "mwcc-inspect-text.v1",
        },
    }
    manifest_path = directory / "bundle.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path


def _rewrite_manifest(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _recompute_payload_compile_id(payload: dict[str, Any]) -> None:
    compile_payload = payload["compile"]
    compile_payload["id"] = _compile_id(
        function=payload["function"],
        compiler=compile_payload["compiler"],
        target_build=compile_payload["target_build"],
        flags_digest=compile_payload["flags_digest"],
        environment_digest=compile_payload["environment_digest"],
        source_digest=compile_payload["source_digest"],
    )


@dataclass(frozen=True)
class BundleV2Fixture:
    manifest: Path
    backend: Path
    candidate_object: Path


def _capture_identity(
    *,
    source_sha256: str,
    environment_digest: str,
    candidate_object_sha256: str,
    function: str = "fn",
) -> dict[str, str]:
    payload = {
        "nonce": "1" * 32,
        "compiler_executable_sha256": "2" * 64,
        "source_sha256": source_sha256,
        "mwcc_command_sha256": "4" * 64,
        "environment_digest": environment_digest,
        "candidate_object_sha256": candidate_object_sha256,
        "function": function,
    }
    return {**payload, "capture_run_id": _sha256(canonical_bytes(payload))}


def _write_v2_bundle(directory: Path) -> BundleV2Fixture:
    directory.mkdir(parents=True)
    source = directory / "candidate.c"
    checkdiff = directory / "checkdiff.json"
    backend = directory / "backend.json"
    inspector = directory / "inspector.txt"
    candidate_object = directory / "candidate.o"
    source.write_bytes(b"source")
    checkdiff.write_bytes(b"{}\n")
    inspector.write_bytes(b"inspector\n")
    candidate_object.write_bytes(b"candidate-bytes")

    source_sha256 = _sha256(source.read_bytes())
    environment_digest = _sha256(b"environment")
    candidate_object_sha256 = _sha256(candidate_object.read_bytes())
    identity = _capture_identity(
        source_sha256=source_sha256,
        environment_digest=environment_digest,
        candidate_object_sha256=candidate_object_sha256,
    )
    trace = {
        "schema_version": "mwcc-retro-backend-trace.v2",
        "functions": [
            {
                "name": "fn",
                "object_bindings": {
                    "capture_identity": identity,
                    "capture_run_id": identity["capture_run_id"],
                },
            }
        ],
    }
    backend.write_text(json.dumps(trace), encoding="utf-8")

    artifact_data = {
        "source": source,
        "checkdiff": checkdiff,
        "backend": backend,
        "inspector": inspector,
        "candidate_object": candidate_object,
    }
    artifact_digests = {name: _sha256(path.read_bytes()) for name, path in artifact_data.items()}
    flags_digest = _sha256(b"flags")
    manifest = {
        "schema_version": "causal-frontier-bundle.v2",
        "label": "paired",
        "function": "fn",
        "compile": {
            "id": _compile_id(
                function="fn",
                compiler="mwcc_233_163n",
                target_build="GALE01",
                flags_digest=flags_digest,
                environment_digest=environment_digest,
                source_digest=source_sha256,
            ),
            "compiler": "mwcc_233_163n",
            "target_build": "GALE01",
            "flags_digest": flags_digest,
            "environment_digest": environment_digest,
            "source_digest": source_sha256,
            "expected_assembly_digest": _sha256(b"expected"),
        },
        "artifacts": {
            "source": {"path": source.name, "sha256": artifact_digests["source"]},
            "checkdiff": {
                "path": checkdiff.name,
                "sha256": artifact_digests["checkdiff"],
            },
            "backend": [
                {
                    "path": backend.name,
                    "sha256": artifact_digests["backend"],
                    "format": "backend-trace.v2",
                    "capabilities": [
                        *sorted(CORE_BACKEND_CAPABILITIES),
                        "compiler-object-bindings",
                    ],
                    "capture_identity_sha256": _sha256(canonical_bytes(identity)),
                    "compiler_executable_sha256": identity["compiler_executable_sha256"],
                    "mwcc_command_sha256": identity["mwcc_command_sha256"],
                    "environment_digest": identity["environment_digest"],
                    "candidate_object_sha256": identity["candidate_object_sha256"],
                }
            ],
            "inspector": {
                "path": inspector.name,
                "sha256": artifact_digests["inspector"],
            },
            "candidate_object": {
                "path": candidate_object.name,
                "sha256": artifact_digests["candidate_object"],
            },
        },
        "producer_versions": {"mwcc_retro": "mwcc-retro-backend-trace.v2"},
    }
    manifest_path = directory / "bundle.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return BundleV2Fixture(manifest_path, backend, candidate_object)


@pytest.fixture
def bundle_v2(tmp_path: Path) -> BundleV2Fixture:
    return _write_v2_bundle(tmp_path / "paired")


def _rewrite_v2_backend(fixture: BundleV2Fixture, mutate: Callable[[dict[str, Any]], None]) -> None:
    trace = json.loads(fixture.backend.read_text(encoding="utf-8"))
    mutate(trace)
    fixture.backend.write_text(json.dumps(trace), encoding="utf-8")
    _rewrite_manifest(
        fixture.manifest,
        lambda payload: payload["artifacts"]["backend"][0].__setitem__("sha256", _sha256(fixture.backend.read_bytes())),
    )


def _rewrite_v2_identity(fixture: BundleV2Fixture, mutate: Callable[[dict[str, str]], None]) -> None:
    trace = json.loads(fixture.backend.read_text(encoding="utf-8"))
    bindings = trace["functions"][0]["object_bindings"]
    identity = bindings["capture_identity"]
    mutate(identity)
    payload = {key: value for key, value in identity.items() if key != "capture_run_id"}
    identity["capture_run_id"] = _sha256(canonical_bytes(payload))
    bindings["capture_run_id"] = identity["capture_run_id"]
    fixture.backend.write_text(json.dumps(trace), encoding="utf-8")

    def update_manifest(manifest: dict[str, Any]) -> None:
        reference = manifest["artifacts"]["backend"][0]
        reference["sha256"] = _sha256(fixture.backend.read_bytes())
        reference["capture_identity_sha256"] = _sha256(canonical_bytes(identity))
        for key in (
            "compiler_executable_sha256",
            "mwcc_command_sha256",
            "environment_digest",
            "candidate_object_sha256",
        ):
            reference[key] = identity[key]

    _rewrite_manifest(fixture.manifest, update_manifest)


def _add_second_v2_backend(fixture: BundleV2Fixture) -> Path:
    second_backend = fixture.backend.with_name("backend-second.json")
    second_backend.write_bytes(fixture.backend.read_bytes())

    def add_reference(manifest: dict[str, Any]) -> None:
        reference = dict(manifest["artifacts"]["backend"][0])
        reference["path"] = second_backend.name
        reference["sha256"] = _sha256(second_backend.read_bytes())
        manifest["artifacts"]["backend"].append(reference)

    _rewrite_manifest(fixture.manifest, add_reference)
    return second_backend


def test_bundle_v2_validates_identity_and_exposes_paths(
    bundle_v2: BundleV2Fixture,
) -> None:
    bundle = load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")

    assert isinstance(bundle.manifest, FrontierBundleManifestV2)
    assert bundle.candidate_object_path == bundle_v2.candidate_object.resolve()
    assert bundle.backend_paths("backend-trace.v2") == (bundle_v2.backend.resolve(),)
    assert bundle.backend_paths("backend-trace.v1") == ()


def test_bundle_v2_rejects_candidate_object_digest_mismatch(
    bundle_v2: BundleV2Fixture,
) -> None:
    bundle_v2.candidate_object.write_bytes(b"changed")

    with pytest.raises(BundleInputError, match="candidate object digest mismatch"):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("source_sha256", "6" * 64, "capture source digest mismatch"),
        ("environment_digest", "7" * 64, "capture environment digest mismatch"),
        ("function", "other", "capture function mismatch"),
    ],
)
def test_bundle_v2_rejects_capture_identity_compile_mismatch(
    bundle_v2: BundleV2Fixture, field: str, value: str, match: str
) -> None:
    _rewrite_v2_identity(bundle_v2, lambda identity: identity.__setitem__(field, value))

    with pytest.raises(BundleInputError, match=match):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")


@pytest.mark.parametrize(
    "pin",
    [
        "capture_identity_sha256",
        "compiler_executable_sha256",
        "mwcc_command_sha256",
        "environment_digest",
        "candidate_object_sha256",
    ],
)
def test_bundle_v2_rejects_backend_identity_pin_mismatch(bundle_v2: BundleV2Fixture, pin: str) -> None:
    _rewrite_manifest(
        bundle_v2.manifest,
        lambda payload: payload["artifacts"]["backend"][0].__setitem__(pin, "9" * 64),
    )

    with pytest.raises(BundleInputError, match=pin.replace("_", " ")):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")


@pytest.mark.parametrize("corruption", ["identity", "pin"])
def test_bundle_v2_validates_each_backend_and_rejects_second_corruption(
    bundle_v2: BundleV2Fixture, corruption: str
) -> None:
    second_backend = _add_second_v2_backend(bundle_v2)

    if corruption == "identity":
        trace = json.loads(second_backend.read_text(encoding="utf-8"))
        trace["functions"][0]["object_bindings"]["capture_identity"]["capture_run_id"] = "8" * 64
        second_backend.write_text(json.dumps(trace), encoding="utf-8")

        def corrupt_second(manifest: dict[str, Any]) -> None:
            manifest["artifacts"]["backend"][1]["sha256"] = _sha256(second_backend.read_bytes())

    else:

        def corrupt_second(manifest: dict[str, Any]) -> None:
            manifest["artifacts"]["backend"][1]["capture_identity_sha256"] = "9" * 64

    _rewrite_manifest(bundle_v2.manifest, corrupt_second)

    with pytest.raises(BundleInputError, match=r"backend\[1\]"):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")


def test_bundle_v2_rejects_recomputed_capture_run_id_mismatch(
    bundle_v2: BundleV2Fixture,
) -> None:
    def mutate(trace: dict[str, Any]) -> None:
        trace["functions"][0]["object_bindings"]["capture_identity"]["capture_run_id"] = "8" * 64

    _rewrite_v2_backend(bundle_v2, mutate)

    with pytest.raises(BundleInputError, match="capture run ID mismatch"):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")


def test_bundle_v2_rejects_object_bindings_capture_run_id_mismatch(
    bundle_v2: BundleV2Fixture,
) -> None:
    _rewrite_v2_backend(
        bundle_v2,
        lambda trace: trace["functions"][0]["object_bindings"].__setitem__("capture_run_id", "8" * 64),
    )

    with pytest.raises(BundleInputError, match="object bindings capture run ID mismatch"):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")


def test_bundle_v2_capture_identity_is_closed(bundle_v2: BundleV2Fixture) -> None:
    _rewrite_v2_backend(
        bundle_v2,
        lambda trace: trace["functions"][0]["object_bindings"]["capture_identity"].__setitem__("unexpected", True),
    )

    with pytest.raises(BundleInputError, match="unexpected"):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")


def test_bundle_v2_rejects_non_utf8_backend_as_bundle_input_error(
    bundle_v2: BundleV2Fixture,
) -> None:
    bundle_v2.backend.write_bytes(b"\xff")
    _rewrite_manifest(
        bundle_v2.manifest,
        lambda payload: payload["artifacts"]["backend"][0].__setitem__(
            "sha256", _sha256(bundle_v2.backend.read_bytes())
        ),
    )

    with pytest.raises(BundleInputError, match=r"invalid backend\[0\] trace"):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")


def test_bundle_rejects_deep_manifest_as_bundle_input_error(tmp_path: Path) -> None:
    manifest = tmp_path / "deep-manifest.json"
    depth = 2000
    manifest.write_text(
        '{"deep":' * depth + "null" + "}" * depth,
        encoding="utf-8",
    )

    with pytest.raises(BundleInputError, match="invalid bundle manifest"):
        load_bundle(manifest, cli_label="paired", function="fn")


def test_bundle_v2_rejects_deep_backend_as_bundle_input_error(
    bundle_v2: BundleV2Fixture,
) -> None:
    depth = 2000
    bundle_v2.backend.write_text(
        '{"deep":' * depth + "null" + "}" * depth,
        encoding="utf-8",
    )
    _rewrite_manifest(
        bundle_v2.manifest,
        lambda payload: payload["artifacts"]["backend"][0].__setitem__(
            "sha256", _sha256(bundle_v2.backend.read_bytes())
        ),
    )

    with pytest.raises(BundleInputError, match=r"invalid backend\[0\] trace"):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")


def test_bundle_v2_rejects_noncanonical_unicode_as_bundle_input_error(
    bundle_v2: BundleV2Fixture,
) -> None:
    trace = json.loads(bundle_v2.backend.read_text(encoding="utf-8"))
    trace["functions"][0]["object_bindings"]["capture_identity"]["function"] = "\ud800"
    bundle_v2.backend.write_text(json.dumps(trace), encoding="utf-8")
    _rewrite_manifest(
        bundle_v2.manifest,
        lambda payload: payload["artifacts"]["backend"][0].__setitem__(
            "sha256", _sha256(bundle_v2.backend.read_bytes())
        ),
    )

    with pytest.raises(BundleInputError, match="capture identity is not RFC 8785 canonicalizable"):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")


def test_bundle_v2_manifest_is_closed(bundle_v2: BundleV2Fixture) -> None:
    _rewrite_manifest(bundle_v2.manifest, lambda payload: payload.__setitem__("unexpected", True))

    with pytest.raises(BundleInputError, match="unexpected"):
        load_bundle(bundle_v2.manifest, cli_label="paired", function="fn")


def test_bundle_v1_rejects_backend_trace_v2(tmp_path: Path) -> None:
    manifest = write_valid_bundle(tmp_path / "paired", label="paired", source="paired", function="fn")
    _rewrite_manifest(
        manifest,
        lambda payload: payload["artifacts"]["backend"][0].__setitem__("format", "backend-trace.v2"),
    )

    with pytest.raises(BundleInputError, match="backend-trace.v2"):
        load_bundle(manifest, cli_label="paired", function="fn")


def test_bundle_v1_accessors_remain_compatible(tmp_path: Path) -> None:
    manifest = write_valid_bundle(tmp_path / "paired", label="paired", source="paired", function="fn")
    bundle = load_bundle(manifest, cli_label="paired", function="fn")

    assert bundle.candidate_object_path is None
    assert bundle.backend_paths("mwcc-debug-pcdump") == ((manifest.parent / "backend.pcdump.txt").resolve(),)


def test_load_bundle_validates_artifacts_and_exposes_text(tmp_path: Path) -> None:
    path = write_valid_bundle(tmp_path / "paired", label="paired", source="paired")

    bundle = load_bundle(path, cli_label="paired", function="fn_test")

    assert bundle.manifest_path == path
    assert bundle.label == "paired"
    assert bundle.compile_id == bundle.manifest.compile.id
    assert bundle.read_text("source") == "paired"


def test_pair_accepts_distinct_sources_in_shared_environment(tmp_path: Path) -> None:
    paired = write_valid_bundle(tmp_path / "paired", label="paired", source="paired")
    direct = write_valid_bundle(tmp_path / "direct", label="direct", source="direct")
    first = load_bundle(paired, cli_label="paired", function="fn_test")
    second = load_bundle(direct, cli_label="direct", function="fn_test")
    ordered = validate_bundle_pair(first, second)
    assert first.compile_id != second.compile_id
    assert first.manifest.compile.environment_digest == second.manifest.compile.environment_digest
    assert tuple(bundle.label for bundle in ordered) == ("direct", "paired")


def test_pair_rejects_expected_assembly_mismatch(tmp_path: Path) -> None:
    paired = load_bundle(
        write_valid_bundle(tmp_path / "paired", label="paired", source="paired"),
        cli_label="paired",
        function="fn_test",
    )
    direct_path = write_valid_bundle(tmp_path / "direct", label="direct", source="direct")
    _rewrite_manifest(
        direct_path,
        lambda payload: payload["compile"].__setitem__("expected_assembly_digest", "9" * 64),
    )
    direct = load_bundle(direct_path, cli_label="direct", function="fn_test")
    with pytest.raises(BundleInputError, match="expected assembly"):
        validate_bundle_pair(paired, direct)


def test_capability_claim_must_be_verified(tmp_path: Path) -> None:
    bundle = load_bundle(
        write_valid_bundle(tmp_path / "paired", label="paired", source="paired"),
        cli_label="paired",
        function="fn_test",
    )
    with pytest.raises(BundleInputError, match="missing backend capabilities"):
        validate_capability_union(bundle, frozenset({"allocator-decisions"}))


def test_complete_verified_capability_union_is_accepted(tmp_path: Path) -> None:
    bundle = load_bundle(
        write_valid_bundle(tmp_path / "paired", label="paired", source="paired"),
        cli_label="paired",
        function="fn_test",
    )

    validate_capability_union(bundle, CORE_BACKEND_CAPABILITIES)


@pytest.mark.parametrize(
    ("case", "mutate_files", "mutate_manifest", "cli_label", "match"),
    [
        (
            "missing artifact",
            lambda path: (path.parent / "backend.pcdump.txt").unlink(),
            lambda payload: None,
            "paired",
            "missing artifact",
        ),
        (
            "bad digest",
            lambda path: None,
            lambda payload: payload["artifacts"]["source"].__setitem__("sha256", "0" * 64),
            "paired",
            "digest mismatch",
        ),
        (
            "label mismatch",
            lambda path: None,
            lambda payload: None,
            "direct",
            "label",
        ),
        (
            "unknown capability",
            lambda path: None,
            lambda payload: payload["artifacts"]["backend"][0]["capabilities"].append("unknown-capability"),
            "paired",
            "unknown backend capability",
        ),
        (
            "missing target build",
            lambda path: None,
            lambda payload: payload["compile"].pop("target_build"),
            "paired",
            "target_build",
        ),
        (
            "bad compile id",
            lambda path: None,
            lambda payload: payload["compile"].__setitem__("id", "a" * 64),
            "paired",
            "compile ID",
        ),
        (
            "source digest mismatch",
            lambda path: None,
            lambda payload: payload["compile"].__setitem__("source_digest", "b" * 64),
            "paired",
            "source digest mismatch",
        ),
        (
            "non-hex digest",
            lambda path: None,
            lambda payload: payload["compile"].__setitem__("flags_digest", "z" * 64),
            "paired",
            "64 hexadecimal",
        ),
        (
            "short digest",
            lambda path: None,
            lambda payload: payload["compile"].__setitem__("environment_digest", "f" * 63),
            "paired",
            "64 hexadecimal",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_load_bundle_rejects_invalid_inputs(
    tmp_path: Path,
    case: str,
    mutate_files: Callable[[Path], None],
    mutate_manifest: Callable[[dict[str, Any]], None],
    cli_label: str,
    match: str,
) -> None:
    del case
    path = write_valid_bundle(tmp_path / "paired", label="paired", source="paired")
    mutate_files(path)
    _rewrite_manifest(path, mutate_manifest)

    with pytest.raises(BundleInputError, match=match):
        load_bundle(path, cli_label=cli_label, function="fn_test")


def test_load_bundle_rejects_function_mismatch(tmp_path: Path) -> None:
    path = write_valid_bundle(tmp_path / "paired", label="paired", source="paired")

    with pytest.raises(BundleInputError, match="function"):
        load_bundle(path, cli_label="paired", function="fn_other")


@pytest.mark.parametrize(
    "field",
    [
        "artifact_sha256",
        "source_digest",
        "flags_digest",
        "environment_digest",
        "expected_assembly_digest",
        "id",
    ],
)
def test_load_bundle_rejects_uppercase_digest_identity(tmp_path: Path, field: str) -> None:
    path = write_valid_bundle(tmp_path / "paired", label="paired", source="paired")

    def uppercase_digest(payload: dict[str, Any]) -> None:
        if field == "artifact_sha256":
            artifact = payload["artifacts"]["source"]
            artifact["sha256"] = artifact["sha256"].upper()
            return
        compile_payload = payload["compile"]
        compile_payload[field] = compile_payload[field].upper()
        if field in {"source_digest", "flags_digest", "environment_digest"}:
            _recompute_payload_compile_id(payload)

    _rewrite_manifest(path, uppercase_digest)

    with pytest.raises(BundleInputError, match="lowercase"):
        load_bundle(path, cli_label="paired", function="fn_test")


def test_compile_id_case_variant_cannot_bypass_distinct_pair_check(
    tmp_path: Path,
) -> None:
    paired_path = write_valid_bundle(tmp_path / "paired", label="paired", source="same source")
    direct_path = write_valid_bundle(tmp_path / "direct", label="direct", source="same source")
    paired = load_bundle(paired_path, cli_label="paired", function="fn_test")
    _rewrite_manifest(
        direct_path,
        lambda payload: payload["compile"].__setitem__("id", payload["compile"]["id"].upper()),
    )

    with pytest.raises(BundleInputError, match="lowercase"):
        load_bundle(direct_path, cli_label="direct", function="fn_test")
    assert paired.compile_id == paired.compile_id.lower()


def test_pair_defensively_rejects_case_only_compile_id_difference(
    tmp_path: Path,
) -> None:
    paired = load_bundle(
        write_valid_bundle(tmp_path / "paired", label="paired", source="same source"),
        cli_label="paired",
        function="fn_test",
    )
    direct = load_bundle(
        write_valid_bundle(tmp_path / "direct", label="direct", source="same source"),
        cli_label="direct",
        function="fn_test",
    )
    case_variant = replace(direct, compile_id=direct.compile_id.upper())

    with pytest.raises(BundleInputError, match="distinct"):
        validate_bundle_pair(paired, case_variant)


@pytest.mark.parametrize(
    "label",
    ["", "has space", "path/label", "path\\label", "frontiér"],
)
def test_load_bundle_rejects_invalid_label_grammar(tmp_path: Path, label: str) -> None:
    path = write_valid_bundle(tmp_path / "bundle", label=label, source="paired")

    with pytest.raises(BundleInputError, match=r"\[A-Za-z0-9_-\]\+"):
        load_bundle(path, cli_label=label, function="fn_test")


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("flags_digest", "1" * 64, "flags"),
        ("environment_digest", "2" * 64, "environment"),
        ("compiler", "mwcc_other", "compiler"),
    ],
)
def test_pair_rejects_incompatible_compile_environment(tmp_path: Path, field: str, value: str, match: str) -> None:
    first = load_bundle(
        write_valid_bundle(tmp_path / "paired", label="paired", source="paired"),
        cli_label="paired",
        function="fn_test",
    )
    kwargs = {field: value}
    second = load_bundle(
        write_valid_bundle(
            tmp_path / "direct",
            label="direct",
            source="direct",
            **kwargs,
        ),
        cli_label="direct",
        function="fn_test",
    )

    with pytest.raises(BundleInputError, match=match):
        validate_bundle_pair(first, second)


@pytest.mark.parametrize(("field", "value"), [("label", "paired"), ("source", "paired")])
def test_pair_requires_distinct_labels_and_compile_ids(tmp_path: Path, field: str, value: str) -> None:
    first = load_bundle(
        write_valid_bundle(tmp_path / "paired", label="paired", source="paired"),
        cli_label="paired",
        function="fn_test",
    )
    label = value if field == "label" else "direct"
    source = value if field == "source" else "direct"
    second = load_bundle(
        write_valid_bundle(tmp_path / "direct", label=label, source=source),
        cli_label=label,
        function="fn_test",
    )

    with pytest.raises(BundleInputError, match="distinct"):
        validate_bundle_pair(first, second)
