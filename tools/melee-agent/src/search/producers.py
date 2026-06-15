from __future__ import annotations
import hashlib
import re
import shutil
from pathlib import Path
from typing import Callable
from src.search.adapters import RemotePermuterClient
from src.search.artifact import CandidateArtifact, CompileSpec, Provenance, compute_candidate_id
from src.search.store import ArtifactStore
from src.search.types import SourceSpec, TargetSpec, Budget, ProducerHandle, ProducerStatus

class PermuterJobProducer:
    def __init__(self, *, client: RemotePermuterClient, store: ArtifactStore,
                 remotes: list[str], compile_spec_factory: Callable[[str], CompileSpec],
                 permuter_base_dir: Path | None = None,
                 base_source_text: str | None = None):
        self._client = client; self._store = store
        self._remotes = remotes; self._spec_factory = compile_spec_factory
        self._permuter_base_dir = Path(permuter_base_dir) if permuter_base_dir else None
        self._base_source_text = base_source_text
        self._seen: set[str] = set()

    def name(self) -> str: return "permuter-job"

    def start(self, base: SourceSpec, target: TargetSpec, budget: Budget) -> ProducerHandle:
        base_dir = self._store.root / "permuter-bases" / target.function
        base_dir.mkdir(parents=True, exist_ok=True)
        base_source = (
            self._base_source_text if self._base_source_text is not None else base.base_source
        )
        (base_dir / "base.c").write_text(
            self._prepare_base_source(base_source, target.function)
        )
        if self._permuter_base_dir is not None:
            for name in ("compile.sh", "settings.toml", "target.o"):
                src = self._permuter_base_dir / name
                if not src.exists():
                    raise FileNotFoundError(
                        f"remote permuter base missing required {name}: {src}"
                    )
                shutil.copy2(src, base_dir / name)
        job_ids: list[str] = []
        start_failures: list[dict[str, str]] = []
        for remote in self._remotes:
            try:
                job_ids.append(self._client.submit(base_dir, target.function, remote))
            except Exception as exc:
                start_failures.append({
                    "remote": remote,
                    "detail": str(exc),
                })
        return ProducerHandle(self.name(), job_ids, start_failures=start_failures)

    def _prepare_base_source(self, base_source: str, function: str) -> str:
        if self._permuter_base_dir is None:
            return base_source
        permuter_base = self._permuter_base_dir / "base.c"
        if not permuter_base.exists():
            return base_source
        permuter_text = permuter_base.read_text()
        if not base_source:
            return permuter_text

        from src.mwcc_debug.source_patch import extract_function, replace_function

        candidate_function = extract_function(base_source, function)
        if candidate_function is None:
            return _ensure_permuter_literal_defines(permuter_text)
        candidate_function = _trim_leading_preprocessor_lines(candidate_function)
        patched = replace_function(permuter_text, function, candidate_function)
        if patched is None:
            raise ValueError(
                f"permuter base.c does not define {function}; cannot patch seed"
            )
        return _ensure_permuter_literal_defines(patched)

    def poll(self, handle: ProducerHandle) -> list[CandidateArtifact]:
        out: list[CandidateArtifact] = []
        for jid in handle.job_ids:
            for src_path, producer_score in self._client.fetch(jid):
                text = Path(src_path).read_text()
                shash = hashlib.sha256(text.encode()).hexdigest()[:32]
                spec = self._spec_factory(text)
                cid = compute_candidate_id(spec, shash)
                if cid in self._seen:
                    continue
                self._seen.add(cid)
                blob = self._store.put_source(text)
                prov = Provenance("permuter-job", None, None, "base",
                                  {"job_id": jid, "permuter_score": producer_score})
                out.append(CandidateArtifact(cid, shash, blob, spec, None, producer_score,
                                             None, None, None, "", prov, "harvested"))
        return out

    def status(self, handle: ProducerHandle) -> ProducerStatus:
        if not handle.job_ids:
            detail = "; ".join(
                failure.get("detail", "") for failure in handle.start_failures
                if failure.get("detail")
            )
            return ProducerStatus("failed", detail=detail or "no remote jobs started")
        states: set[str] = set()
        details: list[str] = []
        for jid in handle.job_ids:
            state = self._client.status(jid)
            if state.startswith("failed:"):
                states.add("failed")
                details.append(state.split(":", 1)[1].strip())
            else:
                states.add(state)
        if "running" in states: return ProducerStatus("running")
        if states == {"drained"}: return ProducerStatus("drained")
        detail = "; ".join(detail for detail in details if detail)
        return ProducerStatus("failed", detail=detail or ",".join(sorted(states)))

    def stop(self, handle: ProducerHandle) -> None:
        for jid in handle.job_ids:
            self._client.stop(jid)


def _trim_leading_preprocessor_lines(source: str) -> str:
    lines = source.splitlines(keepends=True)
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("#")):
        lines.pop(0)
    return "".join(lines)


def _ensure_permuter_literal_defines(source: str) -> str:
    missing: list[str] = []
    for name, value in (("false", "0"), ("true", "1"), ("NULL", "0")):
        if re.search(rf"\b{re.escape(name)}\b", source) and not re.search(
            rf"(?m)^[ \t]*#\s*define\s+{re.escape(name)}\b", source
        ):
            missing.append(
                f"#ifndef {name}\n"
                f"#define {name} {value}\n"
                f"#endif\n"
            )
    if not missing:
        return source
    block = "".join(missing)
    bool_decl = re.search(r"(?m)^typedef\s+int\s+bool\s*;\s*$", source)
    if bool_decl is None:
        return block + source
    insert_at = source.find("\n", bool_decl.end())
    if insert_at < 0:
        insert_at = bool_decl.end()
        newline = "\n"
    else:
        insert_at += 1
        newline = ""
    return source[:insert_at] + newline + block + source[insert_at:]
