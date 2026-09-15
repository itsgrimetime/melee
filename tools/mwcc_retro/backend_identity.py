"""Function identity and output path helpers for backend tracing."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FunctionIdentity:
    requested: str
    canonical_name: str
    symbol_name: str | None
    source_name: str | None
    aliases: tuple[str, ...]
    source_file: str

    def matches(self, seen_name: str) -> bool:
        if not seen_name or seen_name.lower().startswith("0x"):
            return False
        names = {
            name
            for name in (
                self.requested,
                self.canonical_name,
                self.symbol_name,
                self.source_name,
                *self.aliases,
            )
            if name
        }
        return seen_name in names

    def to_dict(self) -> dict:
        return {
            "requested": self.requested,
            "canonical_name": self.canonical_name,
            "symbol_name": self.symbol_name,
            "source_name": self.source_name,
            "aliases": list(self.aliases),
            "source_file": self.source_file,
        }


def path_slug(text: str, *, max_len: int = 72) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")
    slug = re.sub(r"_+", "_", slug)
    slug = slug.lstrip(".")
    if slug in {"", ".", ".."}:
        slug = "unnamed"
    return (slug or "unnamed")[:max_len]


def short_hash(text: str, *, n: int = 10) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def output_dir_for(*, root: Path, src: str, function: str, command: str) -> Path:
    unit_key = f"{src}\n{command}"
    unit = f"{path_slug(Path(src).with_suffix('').as_posix())}-{short_hash(unit_key)}"
    fn = f"{path_slug(function)}-{short_hash(function)}"
    return Path(root) / "build" / "mwcc_retro" / unit / fn
