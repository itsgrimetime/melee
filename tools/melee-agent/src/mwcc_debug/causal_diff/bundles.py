"""Validation for immutable causal frontier artifact bundles."""

from __future__ import annotations

import hashlib
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
    CompileManifest,
    FrontierBundleManifest,
)


class BundleInputError(ValueError):
    """A frontier bundle is malformed, incomplete, or incompatible."""


@dataclass(frozen=True, slots=True)
class ValidatedBundle:
    manifest_path: Path
    manifest: FrontierBundleManifest
    label: str
    compile_id: str
    artifact_paths: Mapping[str, Path]

    def read_text(self, artifact_name: str) -> str:
        return self.artifact_paths[artifact_name].read_text(encoding="utf-8")


def _artifact_refs(
    manifest: FrontierBundleManifest,
) -> tuple[tuple[str, ArtifactRef], ...]:
    refs: list[tuple[str, ArtifactRef]] = [
        ("source", manifest.artifacts.source),
        ("checkdiff", manifest.artifacts.checkdiff),
        ("inspector", manifest.artifacts.inspector),
    ]
    if manifest.artifacts.frame_report is not None:
        refs.append(("frame_report", manifest.artifacts.frame_report))
    refs.extend((f"backend[{index}]", backend) for index, backend in enumerate(manifest.artifacts.backend))
    return tuple(refs)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compile_id(manifest: FrontierBundleManifest) -> str:
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


def load_bundle(manifest_path: Path, *, cli_label: str, function: str) -> ValidatedBundle:
    """Load and fully validate one causal frontier bundle manifest."""

    manifest_path = Path(manifest_path).resolve()
    try:
        manifest = FrontierBundleManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as error:
        raise BundleInputError(f"invalid bundle manifest {manifest_path}: {error}") from error

    if cli_label != manifest.label:
        raise BundleInputError(f"CLI label {cli_label!r} does not match manifest label {manifest.label!r}")
    if function != manifest.function:
        raise BundleInputError(
            f"requested function {function!r} does not match manifest function {manifest.function!r}"
        )

    artifact_paths: dict[str, Path] = {}
    for name, reference in _artifact_refs(manifest):
        artifact_path = (manifest_path.parent / reference.path).resolve()
        if not artifact_path.is_file():
            raise BundleInputError(f"missing artifact {name}: {artifact_path}")
        actual_digest = _file_sha256(artifact_path)
        if actual_digest != reference.sha256:
            raise BundleInputError(
                f"artifact digest mismatch for {name}: expected {reference.sha256}, got {actual_digest}"
            )
        artifact_paths[name] = artifact_path

    source_digest = manifest.artifacts.source.sha256
    if source_digest != manifest.compile.source_digest:
        raise BundleInputError("source digest mismatch between compile manifest and source artifact")

    expected_compile_id = _compile_id(manifest)
    if expected_compile_id != manifest.compile.id:
        raise BundleInputError(f"compile ID mismatch: expected {expected_compile_id}, got {manifest.compile.id}")

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
    "BundleInputError",
    "CompileManifest",
    "FrontierBundleManifest",
    "ValidatedBundle",
    "load_bundle",
    "validate_bundle_pair",
    "validate_capability_union",
]
