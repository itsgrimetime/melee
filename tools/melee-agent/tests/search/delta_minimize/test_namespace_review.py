from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
import yaml

from src.search import delta_minimize
from src.search.delta_minimize.contracts import DeltaMinimizeError
from src.search.delta_minimize.namespace_review import (
    NamespaceArtifact,
    NamespaceReviewRequest,
    ReviewedNamespaceBinding,
    ReviewedNamespaces,
    load_review_request,
    load_reviewed_namespaces,
    resolve_reviewed_map,
    seal_namespace_review,
)

SHA = {
    key: char * 64
    for key, char in zip(
        (
            "target",
            "delta",
            "left",
            "right",
            "canonical_source",
            "canonical_pcdump",
            "cflags",
            "compiler",
            "object",
            "parser",
            "right_dump",
            "candidate_source",
            "candidate_dump",
        ),
        "123456789abcd",
        strict=True,
    )
}
DOMAIN = tuple(range(110))
IDENTITY = {role: role for role in DOMAIN}


def _artifact(
    artifact_id: str,
    *,
    source_sha256: str,
    pcdump_sha256: str,
    automatically_resolved: bool,
) -> NamespaceArtifact:
    if artifact_id.startswith("parent:"):
        return NamespaceArtifact(
            artifact_id=artifact_id,
            kind="parent",
            side=artifact_id.removeprefix("parent:"),
            candidate=None,
            mask=None,
            source_sha256=source_sha256,
            pcdump_sha256=pcdump_sha256,
            domain=DOMAIN,
            automatically_resolved=automatically_resolved,
            diagnostic=None if automatically_resolved else "ambiguous-pairwise-namespace",
        )
    candidate = artifact_id.removeprefix("candidate:")
    return NamespaceArtifact(
        artifact_id=artifact_id,
        kind="candidate",
        side=None,
        candidate=candidate,
        mask=int(candidate.removeprefix("mask-"), 2),
        source_sha256=source_sha256,
        pcdump_sha256=pcdump_sha256,
        domain=DOMAIN,
        automatically_resolved=automatically_resolved,
        diagnostic=None if automatically_resolved else "ambiguous-pairwise-namespace",
    )


def _request() -> NamespaceReviewRequest:
    return NamespaceReviewRequest(
        function="mnDiagram_DrawFighterHeaders",
        class_id=0,
        register_class="GPR",
        namespace_schema="delta-minimize-role-namespace.v5",
        parser_schema_hash=("opcode.v1+color.v5+objobjects.v2+stack-homes.v1+delta-extractor.v2+candidate-evidence.v3"),
        target_sha256=SHA["target"],
        delta_manifest_sha256=SHA["delta"],
        left_source_sha256=SHA["canonical_source"],
        right_source_sha256=SHA["right"],
        cflags_hash=SHA["cflags"],
        compiler_fingerprint=f"mwcc_233_163n:{SHA['compiler']}",
        expected_object_hash=SHA["object"],
        inspector_version="mwcc-inspector 1.4.0",
        canonical_artifact_id="parent:left",
        canonical_source_sha256=SHA["canonical_source"],
        canonical_pcdump_sha256=SHA["canonical_pcdump"],
        reviewed_anchors={64: 64, 78: 78},
        artifacts=(
            _artifact(
                "parent:left",
                source_sha256=SHA["canonical_source"],
                pcdump_sha256=SHA["canonical_pcdump"],
                automatically_resolved=True,
            ),
            _artifact(
                "parent:right",
                source_sha256=SHA["right"],
                pcdump_sha256=SHA["right_dump"],
                automatically_resolved=False,
            ),
            _artifact(
                "candidate:mask-100",
                source_sha256=SHA["candidate_source"],
                pcdump_sha256=SHA["candidate_dump"],
                automatically_resolved=False,
            ),
        ),
    )


def _review(request: NamespaceReviewRequest | None = None) -> ReviewedNamespaces:
    request = request or _request()
    return ReviewedNamespaces(
        request=request,
        request_sha256=request.sha256,
        bindings=(
            ReviewedNamespaceBinding(
                artifact_id="parent:right",
                source_sha256=SHA["right"],
                pcdump_sha256=SHA["right_dump"],
                canonical_to_artifact=IDENTITY,
            ),
            ReviewedNamespaceBinding(
                artifact_id="candidate:mask-100",
                source_sha256=SHA["candidate_source"],
                pcdump_sha256=SHA["candidate_dump"],
                canonical_to_artifact=IDENTITY,
            ),
        ),
    )


def _write_yaml(path: Path, payload: object) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_request_round_trip_is_deterministic_and_immutable(tmp_path: Path) -> None:
    request = _request()
    path = tmp_path / "request.yaml"
    request.write(path)

    loaded = load_review_request(path)

    assert loaded == request
    assert loaded.to_dict() == request.to_dict()
    assert loaded.to_yaml() == request.to_yaml()
    assert loaded.sha256 == request.sha256
    assert path.read_text(encoding="utf-8") == request.to_yaml()
    with pytest.raises(FrozenInstanceError):
        loaded.function = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        loaded.reviewed_anchors[64] = 99  # type: ignore[index]


def test_namespace_review_interfaces_are_exported() -> None:
    assert delta_minimize.NamespaceArtifact is NamespaceArtifact
    assert delta_minimize.NamespaceReviewRequest is NamespaceReviewRequest
    assert delta_minimize.ReviewedNamespaceBinding is ReviewedNamespaceBinding
    assert delta_minimize.ReviewedNamespaces is ReviewedNamespaces
    assert delta_minimize.load_review_request is load_review_request
    assert delta_minimize.load_reviewed_namespaces is load_reviewed_namespaces
    assert delta_minimize.seal_namespace_review is seal_namespace_review
    assert delta_minimize.resolve_reviewed_map is resolve_reviewed_map


def test_review_round_trip_verifies_embedded_request(tmp_path: Path) -> None:
    review = _review()
    path = tmp_path / "reviewed.yaml"
    review.write(path)

    loaded = load_reviewed_namespaces(path, request=review.request)

    assert loaded == review
    assert loaded.request_sha256 == loaded.request.sha256
    assert path.read_text(encoding="utf-8") == review.to_yaml()


@pytest.mark.parametrize("kind", ["duplicate-key", "missing-field", "unknown-field"])
def test_request_rejects_ambiguous_or_nonexact_fields(tmp_path: Path, kind: str) -> None:
    request = _request()
    path = tmp_path / "request.yaml"
    if kind == "duplicate-key":
        path.write_text(
            request.to_yaml() + "function: duplicate\n",
            encoding="utf-8",
        )
    else:
        payload = request.to_dict()
        if kind == "missing-field":
            del payload["function"]
        else:
            payload["unknown"] = "value"
        _write_yaml(path, payload)

    with pytest.raises(DeltaMinimizeError):
        load_review_request(path)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("target_sha256",), "A" * 64),
        (("cflags_hash",), "0" * 63),
        (("artifacts", 1, "source_sha256"), "not-a-sha"),
        (("schema_version",), "delta-minimize-namespace-review-request.v0"),
        (("namespace_schema",), "delta-minimize-role-namespace.v4"),
    ],
)
def test_request_rejects_bad_hashes_and_epochs(
    tmp_path: Path,
    path: tuple[str | int, ...],
    value: object,
) -> None:
    payload: object = _request().to_dict()
    cursor = payload
    for key in path[:-1]:
        cursor = cursor[key]  # type: ignore[index]
    cursor[path[-1]] = value  # type: ignore[index]
    request_path = tmp_path / "request.yaml"
    _write_yaml(request_path, payload)

    with pytest.raises(DeltaMinimizeError):
        load_review_request(request_path)


@pytest.mark.parametrize(
    ("artifact_id", "candidate", "mask"),
    [
        ("candidate:mask-100", "mask-101", 4),
        ("candidate:mask-100", "mask-100", 5),
        ("candidate:mask-8", "mask-8", 8),
        ("parent:right", "mask-100", 4),
    ],
)
def test_request_rejects_bad_candidate_identity(
    tmp_path: Path,
    artifact_id: str,
    candidate: str,
    mask: int,
) -> None:
    payload = _request().to_dict()
    artifact = payload["artifacts"][2]
    artifact["artifact_id"] = artifact_id
    artifact["candidate"] = candidate
    artifact["mask"] = mask
    path = tmp_path / "request.yaml"
    _write_yaml(path, payload)

    with pytest.raises(DeltaMinimizeError):
        load_review_request(path)


def test_request_rejects_duplicate_artifact_ids(tmp_path: Path) -> None:
    payload = _request().to_dict()
    payload["artifacts"][2]["artifact_id"] = "parent:right"
    payload["artifacts"][2]["kind"] = "parent"
    payload["artifacts"][2]["side"] = "right"
    payload["artifacts"][2]["candidate"] = None
    payload["artifacts"][2]["mask"] = None
    path = tmp_path / "request.yaml"
    _write_yaml(path, payload)

    with pytest.raises(DeltaMinimizeError):
        load_review_request(path)


def test_loaders_reject_symlink_paths(tmp_path: Path) -> None:
    request = _request()
    real = tmp_path / "real.yaml"
    real.write_text(request.to_yaml(), encoding="utf-8")
    linked = tmp_path / "linked.yaml"
    linked.symlink_to(real)

    with pytest.raises(DeltaMinimizeError):
        load_review_request(linked)


@pytest.mark.parametrize("kind", ["wrong-digest", "context-drift"])
def test_review_rejects_request_digest_or_context_drift(tmp_path: Path, kind: str) -> None:
    request = _request()
    payload = _review(request).to_dict()
    if kind == "wrong-digest":
        payload["request_sha256"] = "0" * 64
    else:
        payload["request"]["inspector_version"] = "different inspector"
    path = tmp_path / "reviewed.yaml"
    _write_yaml(path, payload)

    with pytest.raises(DeltaMinimizeError):
        load_reviewed_namespaces(path, request=request)


def test_review_rejects_duplicate_exact_content_bindings(tmp_path: Path) -> None:
    payload = _review().to_dict()
    duplicate = dict(payload["bindings"][0])
    duplicate["artifact_id"] = "candidate:mask-100"
    payload["bindings"].append(duplicate)
    path = tmp_path / "reviewed.yaml"
    _write_yaml(path, payload)

    with pytest.raises(DeltaMinimizeError):
        load_reviewed_namespaces(path)


def test_models_reject_unsupported_schema_and_epoch_directly() -> None:
    request = _request()

    with pytest.raises(DeltaMinimizeError):
        replace(request, schema_version="delta-minimize-namespace-review-request.v0")
    with pytest.raises(DeltaMinimizeError):
        replace(request, namespace_schema="delta-minimize-role-namespace.v4")


@pytest.mark.parametrize(
    "parser_epoch",
    [
        "opcode.v1+color.v4+objobjects.v2+stack-homes.v1+delta-extractor.v2+candidate-evidence.v3",
        "opcode.v1+color.v5+objobjects.v2+stack-homes.v1+delta-extractor.v2",
    ],
)
def test_request_rejects_stale_or_truncated_parser_epoch(parser_epoch: str) -> None:
    with pytest.raises(DeltaMinimizeError):
        replace(_request(), parser_schema_hash=parser_epoch)


@pytest.mark.parametrize(
    "change",
    [
        {"left_source_sha256": "0" * 64},
        {"right_source_sha256": "0" * 64},
        {"class_id": 2},
        {"register_class": "VR"},
        {"class_id": 1, "register_class": "GPR"},
        {"class_id": 0, "register_class": "FPR"},
        {"reviewed_anchors": {}},
        {"reviewed_anchors": {64: 64, 78: 64}},
    ],
)
def test_request_rejects_incoherent_parent_context_and_anchors(
    change: dict[str, object],
) -> None:
    with pytest.raises(DeltaMinimizeError):
        replace(_request(), **change)


@pytest.mark.parametrize(
    "anchors",
    ({40: 40}, {40: 40, 41: 41}, {64: 64, 79: 79}),
)
def test_request_accepts_generic_force_role_anchors(
    anchors: dict[int, int],
) -> None:
    request = replace(_request(), reviewed_anchors=anchors)

    assert dict(request.reviewed_anchors) == anchors


def test_request_accepts_fpr_namespace_context() -> None:
    request = replace(_request(), class_id=1, register_class="FPR")

    assert request.class_id == 1
    assert request.register_class == "FPR"


def _nonidentity_map() -> dict[int, int]:
    mapping = dict(IDENTITY)
    mapping[40], mapping[41] = mapping[41], mapping[40]
    return mapping


def _anchor_moving_map() -> dict[int, int]:
    mapping = dict(IDENTITY)
    mapping[64], mapping[65] = mapping[65], mapping[64]
    mapping[78], mapping[79] = mapping[79], mapping[78]
    return mapping


def _request_with_parent_content_alias() -> NamespaceReviewRequest:
    request = _request()
    alias = _artifact(
        "candidate:mask-111",
        source_sha256=SHA["right"],
        pcdump_sha256=SHA["right_dump"],
        automatically_resolved=False,
    )
    return replace(request, artifacts=(*request.artifacts, alias))


def _write_map(path: Path, mapping: object) -> Path:
    _write_yaml(path, mapping)
    return path


def test_seal_expands_identity_and_accepts_full_nonidentity_map(tmp_path: Path) -> None:
    request = _request()
    mapped = _nonidentity_map()

    reviewed = seal_namespace_review(
        request,
        identity_ids=("parent:right",),
        map_paths={"candidate:mask-100": _write_map(tmp_path / "candidate.yaml", mapped)},
    )

    by_id = {binding.artifact_id: binding for binding in reviewed.bindings}
    assert dict(by_id["parent:right"].canonical_to_artifact) == IDENTITY
    assert dict(by_id["candidate:mask-100"].canonical_to_artifact) == mapped
    assert "identity" not in reviewed.to_dict()["bindings"][0]
    assert len(by_id["parent:right"].canonical_to_artifact) == 110


def test_seal_allows_candidate_bijection_to_move_parent_anchor_roles(
    tmp_path: Path,
) -> None:
    moved = _anchor_moving_map()

    reviewed = seal_namespace_review(
        _request(),
        identity_ids=("parent:right",),
        map_paths={"candidate:mask-100": _write_map(tmp_path / "candidate.yaml", moved)},
    )

    binding = next(item for item in reviewed.bindings if item.artifact_id == "candidate:mask-100")
    assert dict(binding.canonical_to_artifact) == moved


def test_seal_rejects_parent_binding_that_conflicts_with_reviewed_anchors(
    tmp_path: Path,
) -> None:
    with pytest.raises(DeltaMinimizeError):
        seal_namespace_review(
            _request(),
            identity_ids=("candidate:mask-100",),
            map_paths={"parent:right": _write_map(tmp_path / "parent.yaml", _anchor_moving_map())},
        )


def test_seal_rejects_anchor_moving_candidate_alias_of_parent_content(
    tmp_path: Path,
) -> None:
    with pytest.raises(DeltaMinimizeError):
        seal_namespace_review(
            _request_with_parent_content_alias(),
            identity_ids=("candidate:mask-100",),
            map_paths={"candidate:mask-111": _write_map(tmp_path / "alias.yaml", _anchor_moving_map())},
        )


def test_loader_rejects_anchor_moving_candidate_alias_of_parent_content(
    tmp_path: Path,
) -> None:
    request = _request_with_parent_content_alias()
    reviewed = seal_namespace_review(
        request,
        identity_ids=("parent:right", "candidate:mask-100"),
        map_paths={},
    )
    payload = reviewed.to_dict()
    parent_binding = next(binding for binding in payload["bindings"] if binding["artifact_id"] == "parent:right")
    parent_binding["artifact_id"] = "candidate:mask-111"
    parent_binding["canonical_to_artifact"] = _anchor_moving_map()
    path = tmp_path / "reviewed.yaml"
    _write_yaml(path, payload)

    with pytest.raises(DeltaMinimizeError):
        load_reviewed_namespaces(path, request=request)


def test_resolver_revalidates_parent_content_group_through_candidate_alias(
    tmp_path: Path,
) -> None:
    request = _request_with_parent_content_alias()
    reviewed = seal_namespace_review(
        request,
        identity_ids=("parent:right", "candidate:mask-100"),
        map_paths={},
    )
    alias_binding = ReviewedNamespaceBinding(
        artifact_id="candidate:mask-111",
        source_sha256=SHA["right"],
        pcdump_sha256=SHA["right_dump"],
        canonical_to_artifact=_anchor_moving_map(),
    )
    object.__setattr__(
        reviewed,
        "bindings",
        tuple(alias_binding if binding.artifact_id == "parent:right" else binding for binding in reviewed.bindings),
    )

    with pytest.raises(DeltaMinimizeError):
        resolve_reviewed_map(
            reviewed,
            request,
            artifact_id="candidate:mask-111",
            source_sha256=SHA["right"],
            pcdump_sha256=SHA["right_dump"],
        )


@pytest.mark.parametrize(
    "malformation",
    [
        "missing-key",
        "extra-key",
        "bool-key",
        "bool-value",
        "duplicate-value",
        "out-of-range-value",
        "nonidentity-abi",
        "incomplete-virtual-bijection",
    ],
)
def test_seal_rejects_invalid_full_maps(
    tmp_path: Path,
    malformation: str,
) -> None:
    mapping: dict[object, object] = dict(IDENTITY)
    if malformation == "missing-key":
        del mapping[109]
    elif malformation == "extra-key":
        mapping[110] = 110
    elif malformation == "bool-key":
        del mapping[1]
        mapping[True] = 1
    elif malformation == "bool-value":
        mapping[40] = True
    elif malformation == "duplicate-value":
        mapping[40] = 41
    elif malformation == "out-of-range-value":
        mapping[40] = 110
    elif malformation == "nonidentity-abi":
        mapping[0], mapping[1] = mapping[1], mapping[0]
    elif malformation == "incomplete-virtual-bijection":
        mapping[40] = 31
        mapping[31] = 40
    map_path = _write_map(tmp_path / "map.yaml", mapping)

    with pytest.raises(DeltaMinimizeError):
        seal_namespace_review(
            _request(),
            identity_ids=("parent:right",),
            map_paths={"candidate:mask-100": map_path},
        )


@pytest.mark.parametrize(
    ("identities", "mapped_id"),
    [
        (("parent:right",), None),
        (("parent:right", "candidate:mask-100", "unknown"), None),
        (("parent:right", "candidate:mask-100"), "candidate:mask-100"),
        (("parent:left", "parent:right", "candidate:mask-100"), None),
        (("parent:right", "parent:right", "candidate:mask-100"), None),
    ],
)
def test_seal_rejects_missing_extra_redundant_or_automatic_approvals(
    tmp_path: Path,
    identities: tuple[str, ...],
    mapped_id: str | None,
) -> None:
    map_paths = {} if mapped_id is None else {mapped_id: _write_map(tmp_path / "map.yaml", IDENTITY)}

    with pytest.raises(DeltaMinimizeError):
        seal_namespace_review(_request(), identity_ids=identities, map_paths=map_paths)


def test_seal_rejects_conflicting_maps_for_duplicate_exact_content(
    tmp_path: Path,
) -> None:
    request = _request()
    candidate = request.artifacts[2]
    aliased = replace(
        candidate,
        source_sha256=SHA["right"],
        pcdump_sha256=SHA["right_dump"],
    )
    request = replace(request, artifacts=(*request.artifacts[:2], aliased))

    with pytest.raises(DeltaMinimizeError):
        seal_namespace_review(
            request,
            identity_ids=("parent:right",),
            map_paths={"candidate:mask-100": _write_map(tmp_path / "conflicting.yaml", _nonidentity_map())},
        )


def test_seal_rejects_symlinked_map_input(tmp_path: Path) -> None:
    real = _write_map(tmp_path / "real.yaml", IDENTITY)
    linked = tmp_path / "linked.yaml"
    linked.symlink_to(real)

    with pytest.raises(DeltaMinimizeError):
        seal_namespace_review(
            _request(),
            identity_ids=("parent:right",),
            map_paths={"candidate:mask-100": linked},
        )


def test_writers_reject_symlink_outputs(tmp_path: Path) -> None:
    real = tmp_path / "real.yaml"
    real.write_text("preserve me\n", encoding="utf-8")
    linked = tmp_path / "linked.yaml"
    linked.symlink_to(real)

    with pytest.raises(DeltaMinimizeError):
        _request().write(linked)
    with pytest.raises(DeltaMinimizeError):
        _review().write(linked)
    assert real.read_text(encoding="utf-8") == "preserve me\n"


def test_resolver_returns_validated_artifact_to_canonical_map(tmp_path: Path) -> None:
    request = _request()
    mapped = _nonidentity_map()
    reviewed = seal_namespace_review(
        request,
        identity_ids=("parent:right",),
        map_paths={"candidate:mask-100": _write_map(tmp_path / "candidate.yaml", mapped)},
    )

    resolved = resolve_reviewed_map(
        reviewed,
        request,
        artifact_id="candidate:mask-100",
        source_sha256=SHA["candidate_source"],
        pcdump_sha256=SHA["candidate_dump"],
    )

    assert dict(resolved) == {artifact: canonical for canonical, artifact in mapped.items()}
    with pytest.raises(TypeError):
        resolved[40] = 40  # type: ignore[index]


@pytest.mark.parametrize(
    "drift",
    ["request", "source", "pcdump", "automatic-artifact", "unknown-artifact"],
)
def test_resolver_rejects_current_context_or_content_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    request = _request()
    reviewed = seal_namespace_review(
        request,
        identity_ids=("parent:right",),
        map_paths={"candidate:mask-100": _write_map(tmp_path / "candidate.yaml", IDENTITY)},
    )
    current = request
    artifact_id = "parent:right"
    source = SHA["right"]
    pcdump = SHA["right_dump"]
    if drift == "request":
        current = replace(request, inspector_version="new inspector")
    elif drift == "source":
        source = "0" * 64
    elif drift == "pcdump":
        pcdump = "0" * 64
    elif drift == "automatic-artifact":
        artifact_id = "parent:left"
        source = SHA["canonical_source"]
        pcdump = SHA["canonical_pcdump"]
    elif drift == "unknown-artifact":
        artifact_id = "candidate:mask-111"

    with pytest.raises(DeltaMinimizeError):
        resolve_reviewed_map(
            reviewed,
            current,
            artifact_id=artifact_id,
            source_sha256=source,
            pcdump_sha256=pcdump,
        )


def test_resolver_uses_identical_review_for_exact_content_alias(tmp_path: Path) -> None:
    request = _request()
    candidate = replace(
        request.artifacts[2],
        source_sha256=SHA["right"],
        pcdump_sha256=SHA["right_dump"],
    )
    request = replace(request, artifacts=(*request.artifacts[:2], candidate))
    reviewed = seal_namespace_review(
        request,
        identity_ids=("parent:right",),
        map_paths={},
    )

    resolved = resolve_reviewed_map(
        reviewed,
        request,
        artifact_id="candidate:mask-100",
        source_sha256=SHA["right"],
        pcdump_sha256=SHA["right_dump"],
    )

    assert dict(resolved) == IDENTITY
