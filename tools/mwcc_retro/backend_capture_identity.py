"""Finalize a retail backend capture identity after object generation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import rfc8785


def finalize_capture_identity(
    *,
    nonce: str,
    compiler_executable_sha256: str,
    source_sha256: str,
    mwcc_command_sha256: str,
    environment_digest: str,
    function: str,
    candidate_object: Path,
) -> dict[str, str]:
    """Bind one capture run to the generated candidate object's raw bytes."""

    return finalize_capture_identity_from_bytes(
        nonce=nonce,
        compiler_executable_sha256=compiler_executable_sha256,
        source_sha256=source_sha256,
        mwcc_command_sha256=mwcc_command_sha256,
        environment_digest=environment_digest,
        function=function,
        candidate_object_bytes=Path(candidate_object).read_bytes(),
    )


def finalize_capture_identity_from_bytes(
    *,
    nonce: str,
    compiler_executable_sha256: str,
    source_sha256: str,
    mwcc_command_sha256: str,
    environment_digest: str,
    function: str,
    candidate_object_bytes: bytes,
) -> dict[str, str]:
    """Bind one capture run to an already detached candidate byte string."""

    payload = {
        "nonce": nonce,
        "compiler_executable_sha256": compiler_executable_sha256,
        "source_sha256": source_sha256,
        "mwcc_command_sha256": mwcc_command_sha256,
        "environment_digest": environment_digest,
        "candidate_object_sha256": hashlib.sha256(candidate_object_bytes).hexdigest(),
        "function": function,
    }
    capture_run_id = hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    return {**payload, "capture_run_id": capture_run_id}


__all__ = ["finalize_capture_identity", "finalize_capture_identity_from_bytes"]
