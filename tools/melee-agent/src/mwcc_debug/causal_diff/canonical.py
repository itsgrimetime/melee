"""Canonical serialization and stable identifiers for causal evidence."""

from __future__ import annotations

import hashlib

import rfc8785


def canonical_bytes(value: object) -> bytes:
    """Serialize *value* with the RFC 8785 JSON Canonicalization Scheme."""

    return rfc8785.dumps(value)


def stable_id(scope_id: str, kind: str, local_key: object) -> str:
    """Return the stable content identity for a scoped evidence record."""

    identity = {
        "schema_version": "causal-evidence.v1",
        "scope_id": scope_id,
        "kind": kind,
        "local_key": local_key,
    }
    return hashlib.sha256(canonical_bytes(identity)).hexdigest()
