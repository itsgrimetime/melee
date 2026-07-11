from __future__ import annotations

import hashlib
import json
from dataclasses import replace
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
