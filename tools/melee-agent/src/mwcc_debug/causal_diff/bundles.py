"""Validation for immutable causal frontier artifact bundles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from pydantic import ValidationError

from .canonical import canonical_bytes
from .models import (
    CORE_BACKEND_CAPABILITIES,
    ArtifactRef,
    BackendArtifactRef,
    BackendArtifactRefV2,
    BundleManifest,
    CaptureIdentity,
    CompileManifest,
    FrontierBundleManifest,
    FrontierBundleManifestV2,
)


class BundleInputError(ValueError):
    """A frontier bundle is malformed, incomplete, or incompatible."""


@dataclass(frozen=True, slots=True)
class ValidatedBundle:
    manifest_path: Path
    manifest: BundleManifest
    label: str
    compile_id: str
    artifact_paths: Mapping[str, Path]

    def read_text(self, artifact_name: str) -> str:
        return self.artifact_paths[artifact_name].read_text(encoding="utf-8")

    @property
    def candidate_object_path(self) -> Path | None:
        return self.artifact_paths.get("candidate_object")

    def backend_paths(self, format_name: str) -> tuple[Path, ...]:
        return tuple(
            self.artifact_paths[f"backend[{index}]"]
            for index, reference in enumerate(self.manifest.artifacts.backend)
            if reference.format == format_name
        )


def _artifact_refs(
    manifest: BundleManifest,
) -> tuple[tuple[str, ArtifactRef], ...]:
    refs: list[tuple[str, ArtifactRef]] = [
        ("source", manifest.artifacts.source),
        ("checkdiff", manifest.artifacts.checkdiff),
        ("inspector", manifest.artifacts.inspector),
    ]
    if manifest.artifacts.frame_report is not None:
        refs.append(("frame_report", manifest.artifacts.frame_report))
    if isinstance(manifest, FrontierBundleManifestV2):
        refs.append(("candidate_object", manifest.artifacts.candidate_object))
    refs.extend((f"backend[{index}]", backend) for index, backend in enumerate(manifest.artifacts.backend))
    return tuple(refs)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compile_id(manifest: BundleManifest) -> str:
    compile_manifest = manifest.compile
    identity = {
        "function": manifest.function,
        "compiler": compile_manifest.compiler,
        "target_build": compile_manifest.target_build,
        "flags_digest": compile_manifest.flags_digest,
        "environment_digest": compile_manifest.environment_digest,
        "source_digest": compile_manifest.source_digest,
    }
    return hashlib.sha256(canonical_bytes(identity)).hexdigest()


def _parse_manifest(manifest_path: Path) -> BundleManifest:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("manifest must be an object")
        schema_version = payload.get("schema_version")
        if schema_version == "causal-frontier-bundle.v1":
            return FrontierBundleManifest.model_validate(payload)
        if schema_version == "causal-frontier-bundle.v2":
            return FrontierBundleManifestV2.model_validate(payload)
        raise ValueError(f"unsupported bundle schema_version {schema_version!r}")
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as error:
        raise BundleInputError(f"invalid bundle manifest {manifest_path}: {error}") from error


def _capture_identity_from_trace(path: Path, *, function: str, backend_index: int) -> CaptureIdentity:
    label = f"backend[{backend_index}]"
    try:
        trace = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BundleInputError(f"invalid {label} trace: {error}") from error
    if not isinstance(trace, dict):
        raise BundleInputError(f"invalid {label} trace: payload must be an object")
    if trace.get("schema_version") != "mwcc-retro-backend-trace.v2":
        raise BundleInputError(f"invalid {label} trace schema_version: expected mwcc-retro-backend-trace.v2")
    functions = trace.get("functions")
    if not isinstance(functions, list):
        raise BundleInputError(f"invalid {label} trace: functions must be a list")
    matches: list[dict[str, object]] = []
    for function_index, row in enumerate(functions):
        if not isinstance(row, dict):
            raise BundleInputError(f"invalid {label} trace: function[{function_index}] must be an object")
        if not isinstance(row.get("name"), str):
            raise BundleInputError(f"invalid {label} trace: function[{function_index}] name must be a string")
        if row["name"] == function:
            matches.append(row)
    if len(matches) != 1:
        raise BundleInputError(f"invalid {label} trace: expected one function {function!r}, found {len(matches)}")
    object_bindings = matches[0].get("object_bindings")
    if not isinstance(object_bindings, dict):
        raise BundleInputError(f"invalid {label} trace: function {function!r} object_bindings must be an object")
    try:
        identity = CaptureIdentity.model_validate(object_bindings.get("capture_identity"))
    except ValidationError as error:
        raise BundleInputError(f"invalid {label} capture identity: {error}") from error

    identity_payload = identity.model_dump()
    capture_run_id = identity_payload.pop("capture_run_id")
    expected_capture_run_id = hashlib.sha256(canonical_bytes(identity_payload)).hexdigest()
    if capture_run_id != expected_capture_run_id:
        raise BundleInputError(
            f"capture run ID mismatch for {label}: expected {expected_capture_run_id}, got {capture_run_id}"
        )
    if object_bindings.get("capture_run_id") != capture_run_id:
        raise BundleInputError(f"object bindings capture run ID mismatch for {label}")
    return identity


def _validate_v2_backend_identity(
    *,
    manifest: FrontierBundleManifestV2,
    reference: BackendArtifactRefV2,
    path: Path,
    backend_index: int,
    candidate_object_sha256: str,
) -> None:
    label = f"backend[{backend_index}]"
    identity = _capture_identity_from_trace(path, function=manifest.function, backend_index=backend_index)
    if identity.source_sha256 != manifest.compile.source_digest:
        raise BundleInputError(f"capture source digest mismatch for {label}")
    if identity.environment_digest != manifest.compile.environment_digest:
        raise BundleInputError(f"capture environment digest mismatch for {label}")
    if identity.function != manifest.function:
        raise BundleInputError(f"capture function mismatch for {label}")
    if identity.candidate_object_sha256 != candidate_object_sha256:
        raise BundleInputError(f"candidate object digest mismatch for {label}")

    expected_pins = {
        "capture_identity_sha256": hashlib.sha256(canonical_bytes(identity.model_dump())).hexdigest(),
        "compiler_executable_sha256": identity.compiler_executable_sha256,
        "mwcc_command_sha256": identity.mwcc_command_sha256,
        "environment_digest": identity.environment_digest,
        "candidate_object_sha256": identity.candidate_object_sha256,
    }
    for field, expected in expected_pins.items():
        actual = getattr(reference, field)
        if actual != expected:
            raise BundleInputError(f"{field.replace('_', ' ')} mismatch for {label}: expected {expected}, got {actual}")


def load_bundle(manifest_path: Path, *, cli_label: str, function: str) -> ValidatedBundle:
    """Load and fully validate one causal frontier bundle manifest."""

    manifest_path = Path(manifest_path).resolve()
    manifest = _parse_manifest(manifest_path)

    if cli_label != manifest.label:
        raise BundleInputError(f"CLI label {cli_label!r} does not match manifest label {manifest.label!r}")
    if function != manifest.function:
        raise BundleInputError(
            f"requested function {function!r} does not match manifest function {manifest.function!r}"
        )

    artifact_paths: dict[str, Path] = {}
    artifact_digests: dict[str, str] = {}
    for name, reference in _artifact_refs(manifest):
        artifact_path = (manifest_path.parent / reference.path).resolve()
        if not artifact_path.is_file():
            raise BundleInputError(f"missing artifact {name}: {artifact_path}")
        actual_digest = _file_sha256(artifact_path)
        if actual_digest != reference.sha256:
            if name == "candidate_object":
                raise BundleInputError(
                    f"candidate object digest mismatch: expected {reference.sha256}, got {actual_digest}"
                )
            raise BundleInputError(
                f"artifact digest mismatch for {name}: expected {reference.sha256}, got {actual_digest}"
            )
        artifact_paths[name] = artifact_path
        artifact_digests[name] = actual_digest

    source_digest = manifest.artifacts.source.sha256
    if source_digest != manifest.compile.source_digest:
        raise BundleInputError("source digest mismatch between compile manifest and source artifact")

    expected_compile_id = _compile_id(manifest)
    if expected_compile_id != manifest.compile.id:
        raise BundleInputError(f"compile ID mismatch: expected {expected_compile_id}, got {manifest.compile.id}")

    if isinstance(manifest, FrontierBundleManifestV2):
        candidate_object_sha256 = artifact_digests["candidate_object"]
        for backend_index, reference in enumerate(manifest.artifacts.backend):
            if isinstance(reference, BackendArtifactRefV2):
                _validate_v2_backend_identity(
                    manifest=manifest,
                    reference=reference,
                    path=artifact_paths[f"backend[{backend_index}]"],
                    backend_index=backend_index,
                    candidate_object_sha256=candidate_object_sha256,
                )

    return ValidatedBundle(
        manifest_path=manifest_path,
        manifest=manifest,
        label=manifest.label,
        compile_id=manifest.compile.id,
        artifact_paths=MappingProxyType(artifact_paths),
    )


def validate_bundle_pair(first: ValidatedBundle, second: ValidatedBundle) -> tuple[ValidatedBundle, ValidatedBundle]:
    """Return two compatible frontier bundles in deterministic label order."""

    bundles = tuple(sorted((first, second), key=lambda bundle: bundle.label))
    left, right = bundles
    if left.label == right.label or left.compile_id.casefold() == right.compile_id.casefold():
        raise BundleInputError("frontiers require distinct labels and compile IDs")

    compatibility_fields = (
        ("expected_assembly_digest", "expected assembly"),
        ("compiler", "compiler"),
        ("target_build", "target build"),
        ("flags_digest", "flags"),
        ("environment_digest", "environment"),
    )
    for field, description in compatibility_fields:
        left_value = getattr(left.manifest.compile, field)
        right_value = getattr(right.manifest.compile, field)
        if left_value != right_value:
            raise BundleInputError(
                f"incompatible {description}: {left.label}={left_value!r}, {right.label}={right_value!r}"
            )
    return bundles


def validate_capability_union(bundle: ValidatedBundle, verified: frozenset[str]) -> None:
    """Require declared backend claims and the core contract to be verified."""

    declared = frozenset(
        capability for backend in bundle.manifest.artifacts.backend for capability in backend.capabilities
    )
    missing = (declared - verified) | (CORE_BACKEND_CAPABILITIES - verified)
    if missing:
        raise BundleInputError("missing backend capabilities: " + ", ".join(sorted(missing)))


__all__ = [
    "CORE_BACKEND_CAPABILITIES",
    "ArtifactRef",
    "BackendArtifactRef",
    "BackendArtifactRefV2",
    "BundleInputError",
    "CompileManifest",
    "FrontierBundleManifest",
    "FrontierBundleManifestV2",
    "ValidatedBundle",
    "load_bundle",
    "validate_bundle_pair",
    "validate_capability_union",
]
