from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from src.search.artifact import CompileManifest


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        (self.root / "manifests").mkdir(parents=True, exist_ok=True)
        (self.root / "objects").mkdir(parents=True, exist_ok=True)
        gi = self.root / ".gitignore"
        if not gi.exists():
            gi.write_text("*\n")

    def _addr(self, text: bytes) -> str:
        return hashlib.sha256(text).hexdigest()[:32]

    def put_source(self, source_text: str) -> Path:
        b = source_text.encode()
        p = self.root / "sources" / f"{self._addr(b)}.c"
        if not p.exists():
            p.write_bytes(b)
        return p

    def put_manifest(self, man: CompileManifest) -> Path:
        payload = asdict(man)
        for k, v in payload.items():
            if isinstance(v, Path):
                payload[k] = str(v)
        blob = json.dumps(payload, sort_keys=True).encode()
        p = self.root / "manifests" / f"{self._addr(blob)}.json"
        if not p.exists():
            p.write_bytes(blob)
        return p

    def read_manifest(self, path: Path) -> CompileManifest:
        d = json.loads(Path(path).read_text())
        for k in ("base_context_blob", "permuter_compile_sh", "permuter_settings_toml"):
            if d.get(k) is not None:
                d[k] = Path(d[k])
        return CompileManifest(**d)

    @contextlib.contextmanager
    def stage_for_verify(self, build_obj: Path, candidate_obj: Path):
        backup = build_obj.with_suffix(build_obj.suffix + ".search-bak")
        had_prior = build_obj.exists()
        if had_prior:
            shutil.copy2(build_obj, backup)
        try:
            shutil.copy2(candidate_obj, build_obj)
            yield build_obj
        finally:
            if had_prior:
                shutil.move(str(backup), str(build_obj))
            elif build_obj.exists():
                build_obj.unlink()
