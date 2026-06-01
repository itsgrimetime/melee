"""The ONE place that will touch existing melee-agent internals (concrete impls land in a later task).
This task defines only the seam Protocols."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from src.search.types import TargetSpec


class ByteScorer(Protocol):
    def byte_distance(self, obj_path: Path, target: TargetSpec) -> int:
        ...


class LocalCompiler(Protocol):
    def compile(self, source_text: str, target: TargetSpec) -> tuple[Path | None, str]:
        ...


class RemotePermuterClient(Protocol):
    def submit(self, base_dir: Path, function: str, remote: str) -> str:
        ...

    def fetch(self, job_id: str) -> list[tuple[Path, float]]:
        ...

    def status(self, job_id: str) -> str:
        ...

    def stop(self, job_id: str) -> None:
        ...


class CheckdiffVerifier(Protocol):
    def is_match(self, function: str, obj_path: Path) -> bool:
        ...
