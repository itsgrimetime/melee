"""RED tests for lifetime proof bundle generation (Task 7)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))


def test_proof_bundle_resolver_rejects_missing_current(tmp_path):
    """Resolver must fail when no CURRENT pointer exists."""
    from tools.mwcc_retro.backend_lifetime_proof import resolve_lifetime_bundle
    with pytest.raises(FileNotFoundError):
        resolve_lifetime_bundle(tmp_path)


def test_proof_bundle_resolver_rejects_tampered_manifest(tmp_path):
    """Resolver must detect a manifest whose hash doesn't match CURRENT."""
    from tools.mwcc_retro.backend_lifetime_proof import (
        publish_lifetime_bundle,
        resolve_lifetime_bundle,
    )
    members = {"test.json": b'{"ok":true}\n'}
    published = publish_lifetime_bundle(
        tmp_path, members, compiler_sha256="a" * 64
    )
    # Tamper with CURRENT to point to wrong manifest hash
    current = json.loads((tmp_path / "CURRENT").read_text())
    current["manifest_sha256"] = "0" * 64
    (tmp_path / "CURRENT").write_text(json.dumps(current))
    with pytest.raises(ValueError, match="manifest SHA-256 mismatch"):
        resolve_lifetime_bundle(tmp_path)


def test_proof_bundle_resolver_rejects_missing_member(tmp_path):
    """Resolver must reject a generation missing a declared member file."""
    from tools.mwcc_retro.backend_lifetime_proof import (
        publish_lifetime_bundle,
        resolve_lifetime_bundle,
    )
    members = {"test.json": b'{"ok":true}\n'}
    published = publish_lifetime_bundle(
        tmp_path, members, compiler_sha256="a" * 64
    )
    # Delete a member file
    gen_dir = tmp_path / published.generation_name
    (gen_dir / "test.json").unlink()
    with pytest.raises(FileNotFoundError):
        resolve_lifetime_bundle(tmp_path)


def test_generation_produces_nine_files(tmp_path):
    """generate_lifetime_bundle must produce exactly nine canonical files."""
    from tools.mwcc_retro.backend_lifetime_proof import generate_lifetime_bundle
    inputs = {
        "raw-pe-cfg.v1.jsonl": b'{"cfg": true}\n',
    }
    bundle = generate_lifetime_bundle(
        inputs, tmp_path,
        proof_ready=True, compiler_sha256="a" * 64,
    )
    files = bundle.canonical_files()
    assert len(files) == 9
    expected = (
        "raw-pe-cfg.v1.jsonl",
        "raw-ghidra-crosscheck.v1.json",
        "backend-lifetime-sites.candidate.v1.json",
        "opcode-layouts.candidate.v1.json",
        "backend-lifetime-audit.v1.json",
        "gc_125n_lifetime_hooks.candidate.json",
        "gc_125n_lifetime_proof.candidate.json",
        "gc_125n.candidate.json",
        "REPORT.md",
    )
    for name in expected:
        assert name in files
