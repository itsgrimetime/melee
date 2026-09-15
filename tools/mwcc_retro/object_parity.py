"""Raw object-byte parity helpers for mwcc-retro backend tracing."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ObjectHash:
    path: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class ObjectParityResult:
    matched: bool
    reference: ObjectHash
    retro: ObjectHash

    def to_dict(self) -> dict:
        return {
            "matched": self.matched,
            "reference": {
                "path": str(self.reference.path),
                "size": self.reference.size,
                "sha256": self.reference.sha256,
            },
            "retro": {
                "path": str(self.retro.path),
                "size": self.retro.size,
                "sha256": self.retro.sha256,
            },
        }


def hash_file(path: str | Path) -> ObjectHash:
    p = Path(path)
    data = p.read_bytes()
    return ObjectHash(path=p, size=len(data), sha256=hashlib.sha256(data).hexdigest())


def compare_objects(reference: str | Path, retro: str | Path) -> ObjectParityResult:
    ref = hash_file(reference)
    ret = hash_file(retro)
    return ObjectParityResult(matched=ref.sha256 == ret.sha256, reference=ref, retro=ret)
