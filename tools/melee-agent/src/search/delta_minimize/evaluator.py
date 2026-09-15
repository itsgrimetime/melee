"""Strict capture and four-axis profiling for delta-search candidates."""

from __future__ import annotations

import hashlib
import inspect
import subprocess
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ...mwcc_debug import parse_pcdump, role_descriptor, role_reanchor
from ...mwcc_debug.colorgraph_profile import build_colorgraph_profile, colorgraph_distance
from ...mwcc_debug.diff_capture import DiffInput, read_inspect_input_if_available
from ...mwcc_debug.frame_reservations import analyze_frame_reservations
from ...mwcc_debug.objobject_profile import objobject_order_distance, parse_objobject_profile
from ...mwcc_debug.opcode_graph import opcode_graph_distance, parse_opcode_graph
from ...mwcc_debug.source_candidate_scoring import ScoreSourceConfig, score_retained_source_rows
from ...mwcc_debug.stack_home_profile import build_stack_home_profile
from ...mwcc_debug.stack_slot_bridge import explain_stack_slot_localizer
from .contracts import AxisDistances, CandidateProfile, DeltaMinimizeError
from .objectives import (
    COLOR_TARGET_SCHEMA_V2,
    ROLE_NAMESPACE_SCHEMA,
    NamespaceMapResolution,
    ObjectiveManifest,
)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise DeltaMinimizeError("invalid-raw-candidate-evidence")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class RawCandidateEvidence:
    candidate_id: str
    mask: int
    source_path: str
    source_hash: str
    compile_status: str
    viable: bool
    pcdump_path: str | None
    checkdiff_evidence: Mapping[str, Any] | None
    inspect_text: str | None
    compiler_stderr: str
    blockers: tuple[str, ...] = ()
    inspection_mode: str = "objobjects"
    pcdump_hash: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.candidate_id, str)
            or not self.candidate_id
            or not _is_int(self.mask)
            or self.mask < 0
            or not isinstance(self.source_path, str)
            or not self.source_path
            or not isinstance(self.source_hash, str)
            or not self.source_hash
            or self.compile_status not in {"compiled", "rejected"}
            or not isinstance(self.viable, bool)
            or (self.compile_status == "rejected") != (not self.viable)
            or (self.pcdump_path is not None and (not isinstance(self.pcdump_path, str) or not self.pcdump_path))
            or (self.checkdiff_evidence is not None and not isinstance(self.checkdiff_evidence, Mapping))
            or (self.inspect_text is not None and not isinstance(self.inspect_text, str))
            or not isinstance(self.compiler_stderr, str)
            or not isinstance(self.blockers, tuple)
            or any(not isinstance(item, str) or not item for item in self.blockers)
            or self.inspection_mode not in {"objobjects", "no-objobjects"}
            or (
                self.pcdump_hash is not None
                and (
                    not isinstance(self.pcdump_hash, str)
                    or len(self.pcdump_hash) != 64
                    or any(character not in "0123456789abcdef" for character in self.pcdump_hash)
                )
            )
        ):
            raise DeltaMinimizeError("invalid-raw-candidate-evidence")
        if self.checkdiff_evidence is not None:
            object.__setattr__(self, "checkdiff_evidence", _freeze(self.checkdiff_evidence))
        object.__setattr__(self, "blockers", tuple(dict.fromkeys(self.blockers)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "mask": self.mask,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "compile_status": self.compile_status,
            "viable": self.viable,
            "pcdump_path": self.pcdump_path,
            "checkdiff_evidence": None if self.checkdiff_evidence is None else _thaw(self.checkdiff_evidence),
            "inspect_text": self.inspect_text,
            "compiler_stderr": self.compiler_stderr,
            "blockers": list(self.blockers),
            "inspection_mode": self.inspection_mode,
            "pcdump_hash": self.pcdump_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RawCandidateEvidence:
        fields = {
            "candidate_id",
            "mask",
            "source_path",
            "source_hash",
            "compile_status",
            "viable",
            "pcdump_path",
            "checkdiff_evidence",
            "inspect_text",
            "compiler_stderr",
            "blockers",
            "inspection_mode",
            "pcdump_hash",
        }
        if not isinstance(data, Mapping) or set(data) != fields:
            raise DeltaMinimizeError("invalid-raw-candidate-evidence")
        raw_blockers = data.get("blockers")
        if not isinstance(raw_blockers, (list, tuple)) or isinstance(raw_blockers, (str, bytes)):
            raise DeltaMinimizeError("invalid-raw-candidate-evidence")
        try:
            return cls(**{**dict(data), "blockers": tuple(raw_blockers)})
        except (TypeError, ValueError) as error:
            raise DeltaMinimizeError("invalid-raw-candidate-evidence") from error


@dataclass(frozen=True)
class ParentEvidenceBundle:
    left: RawCandidateEvidence
    right: RawCandidateEvidence
    cflags_hash: str
    compiler_fingerprint: str
    expected_object_hash: str
    inspector_version: str
    parser_schema_hash: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.left, RawCandidateEvidence)
            or not isinstance(self.right, RawCandidateEvidence)
            or any(
                not isinstance(value, str) or not value
                for value in (
                    self.cflags_hash,
                    self.compiler_fingerprint,
                    self.expected_object_hash,
                    self.parser_schema_hash,
                    self.inspector_version,
                )
            )
        ):
            raise DeltaMinimizeError("invalid-parent-evidence-bundle")

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "cflags_hash": self.cflags_hash,
            "compiler_fingerprint": self.compiler_fingerprint,
            "expected_object_hash": self.expected_object_hash,
            "parser_schema_hash": self.parser_schema_hash,
            "inspector_version": self.inspector_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ParentEvidenceBundle:
        fields = {
            "left",
            "right",
            "cflags_hash",
            "compiler_fingerprint",
            "expected_object_hash",
            "parser_schema_hash",
            "inspector_version",
        }
        if not isinstance(data, Mapping) or set(data) != fields:
            raise DeltaMinimizeError("invalid-parent-evidence-bundle")
        try:
            return cls(
                left=RawCandidateEvidence.from_dict(data["left"]),
                right=RawCandidateEvidence.from_dict(data["right"]),
                cflags_hash=data["cflags_hash"],
                compiler_fingerprint=data["compiler_fingerprint"],
                expected_object_hash=data["expected_object_hash"],
                parser_schema_hash=data["parser_schema_hash"],
                inspector_version=data["inspector_version"],
            )
        except (KeyError, TypeError) as error:
            raise DeltaMinimizeError("invalid-parent-evidence-bundle") from error


@dataclass(frozen=True)
class CandidateEvaluationConfig:
    melee_root: Path
    function: str
    cflags_from: Path
    target_path: Path
    output_dir: Path
    include_objobjects: bool
    score_timeout: float = 120.0
    inspect_timeout: int = 180

    def __post_init__(self) -> None:
        if (
            any(
                not isinstance(value, Path)
                for value in (self.melee_root, self.cflags_from, self.target_path, self.output_dir)
            )
            or not isinstance(self.function, str)
            or not self.function
            or not isinstance(self.include_objobjects, bool)
            or isinstance(self.score_timeout, bool)
            or not isinstance(self.score_timeout, (int, float))
            or self.score_timeout <= 0
            or not _is_int(self.inspect_timeout)
            or self.inspect_timeout <= 0
        ):
            raise DeltaMinimizeError("invalid-candidate-evaluation-config")


@dataclass(frozen=True)
class EvaluationBackends:
    score_rows: Callable[..., list[dict[str, Any]]]
    inspect_source: Callable[..., str]

    def __post_init__(self) -> None:
        if not callable(self.score_rows) or not callable(self.inspect_source):
            raise TypeError("evaluation backends must be callable")


def _score_source_config(config: CandidateEvaluationConfig) -> ScoreSourceConfig:
    return ScoreSourceConfig(
        repo_root=config.melee_root,
        function=config.function,
        target=config.target_path,
        cflags_from=config.cflags_from,
        expression_source=config.cflags_from,
        expression_baseline=None,
        expression_reg_class="gpr",
        output_dir=config.output_dir,
        timeout=config.score_timeout,
        checkdiff_guard=True,
        full_unit_source=True,
    )


def _default_inspect_source(
    source: Path,
    function: str,
    output: Path,
    *,
    timeout: int,
    melee_root: Path | None = None,
) -> str:
    active_root = melee_root or Path(__file__).resolve().parents[5]
    text = read_inspect_input_if_available(
        DiffInput("delta-candidate", str(source), "source", source),
        function=function,
        melee_root=active_root,
        timeout=timeout,
        output_path=output,
    )
    if text is None:
        raise DeltaMinimizeError("inspector-failed", {"source": str(source)})
    return text


def default_evaluation_backends() -> EvaluationBackends:
    return EvaluationBackends(score_retained_source_rows, _default_inspect_source)


def _candidate_blockers(row: Mapping[str, Any]) -> tuple[str, ...]:
    out: list[str] = []
    raw = row.get("blockers")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        for item in raw:
            reason = item.get("reason") if isinstance(item, Mapping) else item
            if isinstance(reason, str) and reason:
                out.append(reason)
    return tuple(dict.fromkeys(out))


def _compile_diagnostics(row: Mapping[str, Any]) -> str:
    return "\n".join(
        str(row.get(key) or "") for key in ("stdout_tail", "stderr_tail", "score_stdout", "score_stderr")
    ).strip()


def _concrete_mwcc_compile_diagnostics(diagnostics: str) -> bool:
    lowered = diagnostics.lower()
    return "mwcceppc_debug.exe compiler" in lowered and "error:" in lowered


def _compile_rejected(row: Mapping[str, Any]) -> bool:
    if row.get("score_error_kind") != "candidate":
        return False
    if row.get("pcdump_path"):
        return False
    return _concrete_mwcc_compile_diagnostics(_compile_diagnostics(row))


def _target_function_missing(row: Mapping[str, Any], function: str) -> bool:
    expected = f"function {function!r} not in compiled pcdump"
    return (
        row.get("score_error_kind") == "candidate"
        and row.get("terminal_safe") is True
        and isinstance(row.get("pcdump_path"), str)
        and bool(row["pcdump_path"])
        and str(row.get("error") or "").strip() == expected
    )


def _pcdump_proves_function_absent(path: Path, function: str) -> bool:
    parsed = parse_pcdump(path.read_text(encoding="utf-8"))
    return bool(parsed) and all(item.name != function for item in parsed)


def _file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing artifact")
    current = Path(path.anchor)
    for part in path.absolute().parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError("unsafe artifact")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_cached_artifacts(
    evidence: RawCandidateEvidence,
    candidate_source: Path,
    source_hash: str,
    *,
    function: str,
    include_objobjects: bool,
    require_checkdiff: bool = True,
) -> bool:
    try:
        if _file_hash(candidate_source) != source_hash:
            return False
        if evidence.viable:
            if evidence.pcdump_path is None or evidence.pcdump_hash is None:
                return False
            if require_checkdiff and not isinstance(evidence.checkdiff_evidence, Mapping):
                return False
            if _file_hash(Path(evidence.pcdump_path)) != evidence.pcdump_hash:
                return False
            if include_objobjects and not evidence.inspect_text:
                return False
        elif "candidate-target-function-missing" in evidence.blockers:
            if (
                evidence.pcdump_path is None
                or evidence.pcdump_hash is None
                or evidence.checkdiff_evidence is not None
                or evidence.inspect_text is not None
                or _file_hash(Path(evidence.pcdump_path)) != evidence.pcdump_hash
                or not _pcdump_proves_function_absent(Path(evidence.pcdump_path), function)
            ):
                return False
        elif (
            evidence.pcdump_path is not None
            or evidence.pcdump_hash is not None
            or not _concrete_mwcc_compile_diagnostics(evidence.compiler_stderr)
        ):
            return False
    except (OSError, UnicodeError, ValueError):
        return False
    return True


def _complete_objobject_text(text: str, function: str) -> bool:
    try:
        return parse_objobject_profile(text, function).complete
    except (TypeError, ValueError):
        return False


def _inspection_cache(store: Any) -> dict[str, str]:
    cache = getattr(store, "_delta_inspection_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(store, "_delta_inspection_cache", cache)
    return cache


def _remember_inspection(store: Any, source_hash: str, function: str, text: str | None) -> None:
    if text is not None and _complete_objobject_text(text, function):
        _inspection_cache(store).setdefault(source_hash, text)


def _invoke_inspector(
    backend: Callable[..., str],
    source: Path,
    function: str,
    output: Path,
    timeout: int,
    melee_root: Path | None = None,
) -> str:
    try:
        parameters = inspect.signature(backend).parameters
    except (TypeError, ValueError):
        parameters = {}
    has_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
    kwargs: dict[str, Any] = {}
    if "timeout" in parameters or has_kwargs:
        kwargs["timeout"] = timeout
    if melee_root is not None and ("melee_root" in parameters or has_kwargs):
        kwargs["melee_root"] = melee_root
    result = backend(source, function, output, **kwargs)
    if not isinstance(result, str) or not result:
        raise DeltaMinimizeError("inspector-failed", {"source": str(source)})
    return result


def _recover_complete_inspector_output(output: Path, function: str) -> str | None:
    try:
        text = output.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if "Compilation finished." not in text or "Error:" in text:
        return None
    try:
        profile = parse_objobject_profile(text, function)
    except (TypeError, ValueError):
        return None
    return text if profile.complete else None


def capture_candidate(
    candidate: Any,
    config: CandidateEvaluationConfig,
    *,
    backends: EvaluationBackends | None = None,
    store: Any,
) -> RawCandidateEvidence:
    """Capture one candidate, reusing only provenance-identical complete evidence."""

    if not isinstance(config, CandidateEvaluationConfig):
        raise DeltaMinimizeError("invalid-candidate-evaluation-config")
    try:
        candidate_id = candidate.candidate_id
        mask = candidate.mask
        source_path = candidate.source_path
        source_hash = candidate.source_hash
    except AttributeError as error:
        raise DeltaMinimizeError("invalid-candidate-evidence-input") from error
    if not isinstance(source_path, Path) or not source_path.is_file():
        raise DeltaMinimizeError("invalid-candidate-source")
    try:
        if _file_hash(source_path) != source_hash:
            raise DeltaMinimizeError("invalid-candidate-source-hash")
    except (OSError, ValueError) as error:
        raise DeltaMinimizeError("invalid-candidate-source") from error

    key = store.evidence_key(candidate, config)
    cached = store.load_evidence(key)
    if cached is not None:
        evidence = RawCandidateEvidence.from_dict(cached)
        if (
            evidence.candidate_id != candidate_id
            or evidence.mask != mask
            or evidence.source_path != str(source_path)
            or evidence.source_hash != source_hash
            or evidence.inspection_mode != ("objobjects" if config.include_objobjects else "no-objobjects")
        ):
            raise DeltaMinimizeError("corrupt-cached-evidence")
        if _validate_cached_artifacts(
            evidence,
            source_path,
            source_hash,
            function=config.function,
            include_objobjects=config.include_objobjects,
        ):
            _remember_inspection(store, source_hash, config.function, evidence.inspect_text)
            return evidence
        store.invalidate_evidence(key)
    if store.evidence_path(key).exists():
        raise DeltaMinimizeError("corrupt-cached-evidence")

    active = backends or default_evaluation_backends()
    rows = active.score_rows(
        [
            {
                "candidate_id": candidate_id,
                "source_file": str(source_path),
                "source_retained": str(source_path),
                "full_unit_source": True,
            }
        ],
        _score_source_config(config),
    )
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise DeltaMinimizeError("malformed-score-source-result")
    row = rows[0]
    if row.get("candidate_id") not in {None, candidate_id}:
        raise DeltaMinimizeError("malformed-score-source-result")
    kind = row.get("score_error_kind")
    if kind not in {None, "candidate", "infrastructure"}:
        raise DeltaMinimizeError(
            "candidate-score-infrastructure",
            {"candidate_id": candidate_id, "error": row.get("error")},
        )
    if kind == "infrastructure":
        raise DeltaMinimizeError(
            "candidate-score-infrastructure",
            {"candidate_id": candidate_id, "error": row.get("error")},
        )

    pcdump = row.get("pcdump_path")
    if pcdump is not None and (not isinstance(pcdump, str) or not pcdump):
        raise DeltaMinimizeError("malformed-score-source-result")
    checkdiff = row.get("checkdiff_evidence")
    if checkdiff is not None and not isinstance(checkdiff, Mapping):
        raise DeltaMinimizeError("malformed-score-source-result")

    compile_rejected = _compile_rejected(row)
    target_missing = _target_function_missing(row, config.function)
    error_text = row.get("error")
    has_error = isinstance(error_text, str) and bool(error_text.strip())
    malformed_error = error_text is not None and not isinstance(error_text, str)
    if (
        malformed_error
        or (kind == "candidate" and not (compile_rejected or target_missing))
        or (has_error and not (compile_rejected or target_missing))
    ):
        raise DeltaMinimizeError(
            "candidate-score-infrastructure",
            {"candidate_id": candidate_id, "error": row.get("error")},
        )
    pcdump_hash: str | None = None
    if not compile_rejected:
        try:
            pcdump_hash = _file_hash(Path(pcdump or ""))
        except (OSError, ValueError) as error:
            raise DeltaMinimizeError(
                "candidate-score-infrastructure",
                {"candidate_id": candidate_id, "error": "missing-or-unsafe-pcdump"},
            ) from error
    blockers = _candidate_blockers(row)
    if target_missing:
        blockers = tuple(dict.fromkeys((*blockers, "candidate-target-function-missing")))
    nonviable = compile_rejected or target_missing
    evidence = RawCandidateEvidence(
        candidate_id=candidate_id,
        mask=mask,
        source_path=str(source_path),
        source_hash=source_hash,
        compile_status="rejected" if nonviable else "compiled",
        viable=not nonviable,
        pcdump_path=None if compile_rejected else pcdump,
        checkdiff_evidence=None if target_missing else checkdiff,
        inspect_text=None,
        compiler_stderr=_compile_diagnostics(row),
        blockers=blockers,
        inspection_mode="objobjects" if config.include_objobjects else "no-objobjects",
        pcdump_hash=pcdump_hash,
    )
    if target_missing and not _validate_cached_artifacts(
        evidence,
        source_path,
        source_hash,
        function=config.function,
        include_objobjects=config.include_objobjects,
    ):
        raise DeltaMinimizeError(
            "candidate-score-infrastructure",
            {"candidate_id": candidate_id, "error": row.get("error")},
        )
    if evidence.viable and config.include_objobjects:
        cached_inspection = _inspection_cache(store).get(source_hash)
        if cached_inspection is not None and _complete_objobject_text(cached_inspection, config.function):
            evidence = RawCandidateEvidence(
                **{
                    **evidence.to_dict(),
                    "blockers": evidence.blockers,
                    "inspect_text": cached_inspection,
                }
            )
            store.write_evidence(key, evidence.to_dict())
            return evidence
        inspect_output = store.inspect_output_path(candidate_id)
        try:
            inspect_output.unlink(missing_ok=True)
        except OSError as error:
            raise DeltaMinimizeError(
                "inspector-output-reset-failed",
                {"candidate_id": candidate_id, "path": str(inspect_output)},
            ) from error
        try:
            inspect_text = _invoke_inspector(
                active.inspect_source,
                source_path,
                config.function,
                inspect_output,
                config.inspect_timeout,
                config.melee_root,
            )
        except (subprocess.TimeoutExpired, TimeoutError) as error:
            raise DeltaMinimizeError("inspector-timeout", {"candidate_id": candidate_id}) from error
        except DeltaMinimizeError as error:
            inspect_text = (
                _recover_complete_inspector_output(inspect_output, config.function)
                if error.reason == "inspector-failed"
                else None
            )
            if inspect_text is None:
                raise
        except Exception as error:
            raise DeltaMinimizeError("inspector-failed", {"candidate_id": candidate_id}) from error
        evidence = RawCandidateEvidence(
            **{**evidence.to_dict(), "blockers": evidence.blockers, "inspect_text": inspect_text}
        )
        _remember_inspection(store, source_hash, config.function, inspect_text)

    store.write_evidence(key, evidence.to_dict())
    return evidence


def _add(blockers: list[str], reason: str) -> None:
    if reason not in blockers:
        blockers.append(reason)


def _asm_lines(payload: Mapping[str, Any], key: str) -> list[str] | None:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)) or not value or any(not isinstance(item, str) for item in value):
        return None
    lines = [item for item in value if item.strip()]
    return lines or None


def _structural_status(payload: Mapping[str, Any]) -> str:
    if payload.get("match") is True:
        return "structural-match"
    classification = payload.get("classification")
    truth_gate = classification.get("structural_truth_gate") if isinstance(classification, Mapping) else None
    if isinstance(truth_gate, Mapping) and truth_gate.get("status") == "structural-match":
        return "structural-match"
    primary = classification.get("primary") if isinstance(classification, Mapping) else None
    if primary in {"instruction-identical", "relocation-label-only", "normalized-structural-match"}:
        return "structural-match"
    return str(primary or "unknown")


def _load_text(path_value: str | None) -> str:
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("missing path")
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing path")
    return path.read_text(encoding="utf-8")


def _target_spec(data: Mapping[str, Any]) -> role_descriptor.TargetSpec:
    if not isinstance(data, Mapping):
        raise ValueError("invalid target spec")
    roles_raw = data.get("roles")
    if not isinstance(roles_raw, (list, tuple)):
        raise ValueError("invalid target spec")
    roles: list[role_descriptor.TargetRoleSpec] = []
    for raw in roles_raw:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid target spec")
        descriptor_raw = raw.get("descriptor")
        descriptor = None
        if isinstance(descriptor_raw, Mapping):
            descriptor = role_descriptor.RoleDescriptor(
                **{
                    **dict(descriptor_raw),
                    "use_site_multiset": tuple(tuple(item) for item in descriptor_raw.get("use_site_multiset", ())),
                    "live_range": tuple(descriptor_raw.get("live_range", ())),
                }
            )
        roles.append(
            role_descriptor.TargetRoleSpec(
                original_ig=raw["original_ig"],
                desired_phys=raw["desired_phys"],
                class_id=raw["class_id"],
                descriptor=descriptor,
                role_order_rank=raw.get("role_order_rank"),
            )
        )
    return role_descriptor.TargetSpec(
        function=data["function"],
        target_kind=data["target_kind"],
        target_coverage=data["target_coverage"],
        causal_closure=data["causal_closure"],
        provenance=_thaw(data["provenance"]),
        roles=roles,
    )


def _compile(raw: RawCandidateEvidence, function: str) -> role_descriptor.Compile:
    return role_descriptor.Compile.from_text(
        _load_text(raw.pcdump_path),
        function,
        Path(raw.source_path).read_text(encoding="utf-8") if Path(raw.source_path).is_file() else "",
    )


def _donor_raw(parents: ParentEvidenceBundle | None, side: str | None) -> RawCandidateEvidence | None:
    if parents is None:
        return None
    if side == "right":
        return parents.right
    if side == "left":
        return parents.left
    return None


def _evidence_content_hashes(evidence: RawCandidateEvidence) -> tuple[str, str]:
    if evidence.pcdump_path is None:
        raise ValueError("missing pcdump evidence")
    source_hash = hashlib.sha256(Path(evidence.source_path).read_bytes()).hexdigest()
    pcdump_hash = hashlib.sha256(Path(evidence.pcdump_path).read_bytes()).hexdigest()
    if evidence.source_hash != source_hash or evidence.pcdump_hash is None or evidence.pcdump_hash != pcdump_hash:
        raise ValueError("inconsistent candidate content hashes")
    return source_hash, pcdump_hash


def _v2_parent_role_maps(
    objective: ObjectiveManifest,
    parents: ParentEvidenceBundle,
) -> dict[str, dict[int, int]] | None:
    """Validate persisted reviewed bindings and invert them to raw role maps."""
    provenance = objective.target_spec.get("provenance")
    if not isinstance(provenance, Mapping):
        return None
    if provenance.get("schema_version") != COLOR_TARGET_SCHEMA_V2:
        if {
            "baseline_side",
            "baseline_dump_sha256",
            "parent_role_bindings",
            "namespace_schema",
        } & set(provenance):
            raise ValueError("invalid v2 role binding provenance")
        return None
    if set(provenance) != {
        "schema_version",
        "baseline_side",
        "baseline_dump",
        "baseline_dump_sha256",
        "parent_role_bindings",
        "namespace_schema",
    }:
        raise ValueError("invalid v2 role binding provenance")
    baseline_side = provenance["baseline_side"]
    bindings = provenance["parent_role_bindings"]
    if (
        baseline_side not in {"left", "right"}
        or not isinstance(provenance["baseline_dump"], str)
        or not provenance["baseline_dump"]
        or provenance["namespace_schema"] != ROLE_NAMESPACE_SCHEMA
        or not isinstance(bindings, Mapping)
        or tuple(bindings) != ("left", "right")
    ):
        raise ValueError("invalid v2 role binding provenance")
    desired = set(objective.desired_phys)
    raw_maps: dict[str, dict[int, int]] = {}
    parent_rows = {"left": parents.left, "right": parents.right}
    for side in ("left", "right"):
        binding = bindings[side]
        if (
            not isinstance(binding, Mapping)
            or set(binding)
            != {
                "source_sha256",
                "pcdump_sha256",
                "canonical_to_parent",
            }
            or not isinstance(binding["source_sha256"], str)
            or not isinstance(binding["pcdump_sha256"], str)
            or not isinstance(binding["canonical_to_parent"], Mapping)
        ):
            raise ValueError("invalid v2 role binding provenance")
        canonical_to_parent: dict[int, int] = {}
        for raw_canonical, parent_ig in binding["canonical_to_parent"].items():
            if (
                not isinstance(raw_canonical, str)
                or not raw_canonical.isdecimal()
                or str(int(raw_canonical)) != raw_canonical
                or int(raw_canonical) in canonical_to_parent
                or not _is_int(parent_ig)
                or parent_ig < 0
            ):
                raise ValueError("invalid v2 role binding provenance")
            canonical_to_parent[int(raw_canonical)] = parent_ig
        if (
            set(canonical_to_parent) != desired
            or len(set(canonical_to_parent.values())) != len(canonical_to_parent)
            or side == baseline_side
            and any(canonical != parent for canonical, parent in canonical_to_parent.items())
        ):
            raise ValueError("invalid v2 role binding provenance")
        source_hash, pcdump_hash = _evidence_content_hashes(parent_rows[side])
        if source_hash != binding["source_sha256"] or pcdump_hash != binding["pcdump_sha256"]:
            raise ValueError("unbound v2 parent role evidence")
        raw_maps[side] = {parent_ig: canonical for canonical, parent_ig in canonical_to_parent.items()}
    if provenance["baseline_dump_sha256"] != bindings[baseline_side]["pcdump_sha256"]:
        raise ValueError("invalid v2 baseline binding")
    return raw_maps


def _agreeing_proven_map(
    maps: Sequence[Mapping[int, int]],
) -> dict[int, int] | None:
    if not maps:
        return None
    first = dict(maps[0])
    if any(dict(candidate) != first for candidate in maps[1:]):
        raise ValueError("conflicting proven parent role bindings")
    return first


def _candidate_proven_role_map(
    evidence: RawCandidateEvidence,
    candidate_compile: role_descriptor.Compile,
    objective: ObjectiveManifest,
    parent_maps: Mapping[str, Mapping[int, int]],
    parent_compiles: Mapping[str, role_descriptor.Compile],
) -> dict[int, int] | None:
    source_hash, pcdump_hash = _evidence_content_hashes(evidence)
    provenance = objective.target_spec["provenance"]
    bindings = provenance["parent_role_bindings"]
    direct = [
        parent_maps[side]
        for side in ("left", "right")
        if source_hash == bindings[side]["source_sha256"] and pcdump_hash == bindings[side]["pcdump_sha256"]
    ]
    proven = _agreeing_proven_map(direct)
    if proven is not None:
        return proven

    inherited: list[dict[int, int]] = []
    for side in ("left", "right"):
        sections = [
            section for section in parent_compiles[side].fev.coalesce_sections if section.class_id == objective.class_id
        ]
        if not sections:
            continue
        candidate_to_parent = role_descriptor.prove_virtual_namespace_map(
            parent_compiles[side],
            candidate_compile,
            objective.class_id,
            sections[-1].n_virtuals,
        )
        if candidate_to_parent is None:
            continue
        inherited.append(
            {
                candidate_ig: parent_maps[side][parent_ig]
                for candidate_ig, parent_ig in candidate_to_parent.items()
                if parent_ig in parent_maps[side]
            }
        )
    return _agreeing_proven_map(inherited)


def _overlay_graph_roles(
    ordinary: Mapping[int, int],
    proven: Mapping[int, int],
) -> dict[int, int]:
    merged = dict(ordinary)
    for candidate_ig, donor_ig in proven.items():
        existing = merged.get(candidate_ig)
        if (
            existing is not None
            and existing != donor_ig
            or any(
                other_candidate != candidate_ig and other_donor == donor_ig
                for other_candidate, other_donor in merged.items()
            )
        ):
            raise ValueError("conflicting proven graph role binding")
        merged[candidate_ig] = donor_ig
    return merged


def _color_axis(
    evidence: RawCandidateEvidence,
    objective: ObjectiveManifest,
    parents: ParentEvidenceBundle,
    *,
    namespace_resolutions: Mapping[str, NamespaceMapResolution] | None = None,
) -> tuple[int, int, int, int, int, int]:
    # A ``none`` color donor is valid only when objective inference proved the
    # parent secondary profiles identical.  Either side is then an equivalent
    # concrete artifact for the comparison.
    donor_side = "left" if objective.color_donor is None else objective.color_donor
    donor_raw = _donor_raw(parents, donor_side)
    if donor_raw is None:
        raise ValueError("missing donor")
    candidate_payload = evidence.checkdiff_evidence or {}
    donor_payload = donor_raw.checkdiff_evidence or {}
    candidate_explicit = _explicit_color_role_map(candidate_payload)
    donor_explicit = _explicit_color_role_map(donor_payload)
    desired = dict(objective.desired_phys)
    if namespace_resolutions is not None:
        candidate_id = f"candidate:{evidence.candidate_id}"
        candidate_resolution = namespace_resolutions.get(candidate_id)
        donor_resolution = namespace_resolutions.get(f"parent:{donor_side}")
        if (
            not isinstance(candidate_resolution, NamespaceMapResolution)
            or not isinstance(donor_resolution, NamespaceMapResolution)
            or candidate_resolution.raw_to_canonical is None
            or donor_resolution.raw_to_canonical is None
            or _evidence_content_hashes(evidence)
            != (candidate_resolution.source_sha256, candidate_resolution.pcdump_sha256)
            or _evidence_content_hashes(donor_raw) != (donor_resolution.source_sha256, donor_resolution.pcdump_sha256)
        ):
            raise ValueError("incomplete namespace resolution")
        candidate_profile = build_colorgraph_profile(
            _load_text(evidence.pcdump_path),
            objective.function,
            objective.class_id,
            candidate_resolution.raw_to_canonical,
            required_roles=frozenset(desired),
        )
        donor_profile = build_colorgraph_profile(
            _load_text(donor_raw.pcdump_path),
            objective.function,
            objective.class_id,
            donor_resolution.raw_to_canonical,
            required_roles=frozenset(desired),
        )
        return tuple(colorgraph_distance(candidate_profile, donor_profile, desired).as_tuple())  # type: ignore[return-value]
    if candidate_explicit is not None or donor_explicit is not None:
        if candidate_explicit is None or donor_explicit is None:
            raise ValueError("partial explicit color role evidence")
        candidate_profile = build_colorgraph_profile(
            _load_text(evidence.pcdump_path),
            objective.function,
            objective.class_id,
            candidate_explicit,
            required_roles=frozenset(desired),
        )
        donor_profile = build_colorgraph_profile(
            _load_text(donor_raw.pcdump_path),
            objective.function,
            objective.class_id,
            donor_explicit,
            required_roles=frozenset(desired),
        )
        return tuple(colorgraph_distance(candidate_profile, donor_profile, desired).as_tuple())  # type: ignore[return-value]

    candidate_compile = _compile(evidence, objective.function)
    parent_compiles = {
        "left": _compile(parents.left, objective.function),
        "right": _compile(parents.right, objective.function),
    }
    donor_compile = parent_compiles[donor_side]
    target = _target_spec(objective.target_spec)
    donor_sections = [
        section for section in donor_compile.fev.coalesce_sections if section.class_id == objective.class_id
    ]
    exact_graph_roles = (
        role_descriptor.prove_virtual_namespace_map(
            donor_compile,
            candidate_compile,
            objective.class_id,
            donor_sections[-1].n_virtuals,
        )
        if donor_sections
        else None
    )
    if target.provenance.get("inference") == "parent-register-diff" and exact_graph_roles is not None:
        donor_role_map = {ig_idx: ig_idx for ig_idx in range(donor_sections[-1].n_virtuals)}
        candidate_profile = build_colorgraph_profile(
            _load_text(evidence.pcdump_path),
            objective.function,
            objective.class_id,
            exact_graph_roles,
            required_roles=frozenset(desired),
        )
        donor_profile = build_colorgraph_profile(
            _load_text(donor_raw.pcdump_path),
            objective.function,
            objective.class_id,
            donor_role_map,
            required_roles=frozenset(desired),
        )
        return tuple(colorgraph_distance(candidate_profile, donor_profile, desired).as_tuple())  # type: ignore[return-value]

    parent_maps = _v2_parent_role_maps(objective, parents)
    candidate_proven: dict[int, int] | None = None
    donor_proven: dict[int, int] | None = None
    if parent_maps is not None:
        candidate_proven = _candidate_proven_role_map(
            evidence,
            candidate_compile,
            objective,
            parent_maps,
            parent_compiles,
        )
        donor_proven = dict(parent_maps[donor_side])

    if candidate_proven is None:
        candidate_target = role_reanchor.reanchor(
            target,
            candidate_compile,
            class_id=objective.class_id,
        )
        candidate_target_roles = dict(candidate_target.matched)
    else:
        candidate_target_roles = dict(candidate_proven)
    if donor_proven is None:
        donor_target = role_reanchor.reanchor(
            target,
            donor_compile,
            class_id=objective.class_id,
        )
        donor_target_roles_raw = dict(donor_target.matched)
    else:
        donor_target_roles_raw = dict(donor_proven)
    if set(candidate_target_roles.values()) != set(desired) or set(donor_target_roles_raw.values()) != set(desired):
        raise ValueError("incomplete target reanchor")

    donor_descriptors = role_descriptor.build_descriptors(donor_compile, objective.class_id)
    if not donor_descriptors:
        raise ValueError("missing donor roles")
    graph_target = role_descriptor.build_target_spec(
        donor_compile,
        {ig_idx: 0 for ig_idx in donor_descriptors},
        objective.class_id,
        "force_proof_proxy",
        {"inference": "delta-candidate-color-profile"},
    )
    proven_graph_roles: dict[int, int] = {}
    if candidate_proven is not None and donor_proven is not None:
        donor_by_canonical = {canonical: donor_ig for donor_ig, canonical in donor_proven.items()}
        proven_graph_roles = {
            candidate_ig: donor_by_canonical[canonical]
            for candidate_ig, canonical in candidate_proven.items()
            if canonical in donor_by_canonical
        }
    donor_graph_igs = tuple(sorted(donor_descriptors))
    reviewed_graph_roles = (
        role_descriptor.prove_virtual_namespace_map(
            donor_compile,
            candidate_compile,
            objective.class_id,
            donor_sections[-1].n_virtuals,
            proven_graph_roles,
        )
        if donor_sections and proven_graph_roles
        else None
    )
    if reviewed_graph_roles is not None:
        donor_graph_igs = tuple(range(donor_sections[-1].n_virtuals))
        candidate_graph_roles = reviewed_graph_roles
    elif set(proven_graph_roles.values()) == set(donor_descriptors) and len(proven_graph_roles) == len(
        donor_descriptors
    ):
        candidate_graph_roles = proven_graph_roles
    elif _load_text(evidence.pcdump_path) == _load_text(donor_raw.pcdump_path):
        # Byte-identical backend evidence has an exact IG identity relation;
        # using it is stronger than asking the descriptor matcher to break
        # ties between otherwise indistinguishable roles.
        candidate_graph_roles = {ig_idx: ig_idx for ig_idx in donor_descriptors}
    else:
        candidate_graph = role_reanchor.reanchor(
            graph_target,
            candidate_compile,
            class_id=objective.class_id,
        )
        candidate_graph_roles = _overlay_graph_roles(
            candidate_graph.matched,
            proven_graph_roles,
        )
        unresolved = set(candidate_graph.diagnostics) - set(proven_graph_roles.values())
        if unresolved or set(candidate_graph_roles.values()) != set(donor_descriptors):
            raise ValueError("incomplete graph reanchor")

    donor_role_map = {ig_idx: donor_target_roles_raw.get(ig_idx, 1_000_000 + ig_idx) for ig_idx in donor_graph_igs}
    candidate_role_map = {
        candidate_ig: donor_role_map[donor_ig] for candidate_ig, donor_ig in candidate_graph_roles.items()
    }
    for candidate_ig, canonical in candidate_target_roles.items():
        existing = candidate_role_map.get(candidate_ig)
        if existing is not None and existing != canonical:
            raise ValueError("conflicting candidate target role binding")
        candidate_role_map[candidate_ig] = canonical
    candidate_profile = build_colorgraph_profile(
        _load_text(evidence.pcdump_path),
        objective.function,
        objective.class_id,
        candidate_role_map,
        required_roles=frozenset(desired),
    )
    donor_profile = build_colorgraph_profile(
        _load_text(donor_raw.pcdump_path),
        objective.function,
        objective.class_id,
        donor_role_map,
        required_roles=frozenset(desired),
    )
    return tuple(colorgraph_distance(candidate_profile, donor_profile, desired).as_tuple())  # type: ignore[return-value]


def _explicit_color_role_map(payload: Mapping[str, Any]) -> dict[int, int] | None:
    raw = payload.get("color_role_map")
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError("invalid explicit color role map")
    result: dict[int, int] = {}
    for raw_ig, raw_role in raw.items():
        if isinstance(raw_ig, str) and raw_ig.isdecimal():
            ig_idx = int(raw_ig)
        elif _is_int(raw_ig):
            ig_idx = raw_ig
        else:
            raise ValueError("invalid explicit color role map")
        if ig_idx < 0 or not _is_int(raw_role) or raw_role < 0 or ig_idx in result:
            raise ValueError("invalid explicit color role map")
        result[ig_idx] = raw_role
    if len(set(result.values())) != len(result):
        raise ValueError("invalid explicit color role map")
    return result


def _frame_and_stack(payload: Mapping[str, Any], function: str) -> tuple[Mapping[str, Any], Mapping[str, Any] | None]:
    frame = payload.get("frame_report")
    stack = payload.get("stack_slot_report")
    if isinstance(frame, Mapping):
        return _thaw(frame), _thaw(stack) if isinstance(stack, Mapping) else None
    classification = payload.get("classification")
    classification = classification if isinstance(classification, Mapping) else {}
    sizes = classification.get("stack_frame_sizes")
    localizer = classification.get("stack_slot_localizer")
    if not isinstance(sizes, Mapping):
        raise ValueError("missing frame report")
    current_size = sizes.get("current_frame_size")
    frame = {
        "function": function,
        "current": {
            "frame_size": current_size,
            "stack_home_assignment_status": "unavailable-no-resolved-symbolic-homes",
            "stack_home_assignments": [],
        },
    }
    stack = localizer.get("pcdump_bridge") if isinstance(localizer, Mapping) else None
    return frame, stack if isinstance(stack, Mapping) else None


def _evidence_frame_and_stack(
    evidence: RawCandidateEvidence,
    function: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any] | None]:
    payload = evidence.checkdiff_evidence
    if payload is None:
        raise ValueError("missing checkdiff evidence")
    if isinstance(payload.get("frame_report"), Mapping):
        return _frame_and_stack(payload, function)
    if evidence.pcdump_path is None:
        raise ValueError("missing pcdump")
    pcdump_text = _load_text(evidence.pcdump_path)
    source_text = _load_text(evidence.source_path)

    def asm_text(key: str) -> str:
        raw = payload.get(key)
        if not isinstance(raw, (list, tuple)) or any(not isinstance(line, str) for line in raw):
            raise ValueError("invalid assembly evidence")
        lines = [line for line in raw if line.strip()]
        if not lines:
            raise ValueError("empty assembly evidence")
        return "\n".join(lines)

    frame = analyze_frame_reservations(
        pcdump_text,
        function,
        expected_asm_text=asm_text("target_asm"),
        current_asm_text=asm_text("current_asm"),
        source_text=source_text,
        source_path=evidence.source_path,
    )
    classification = payload.get("classification")
    classification = classification if isinstance(classification, Mapping) else {}
    localizer = classification.get("stack_slot_localizer")
    if isinstance(localizer, Mapping):
        bridge = explain_stack_slot_localizer(
            pcdump_text,
            function,
            dict(localizer),
            source_text=source_text,
            source_file=evidence.source_path,
        )
    elif isinstance(classification.get("offset_discrepancies"), (list, tuple)) and not classification.get(
        "offset_discrepancies"
    ):
        bridge = {
            "status": "no-candidates",
            "function": function,
            "frame_size": frame["current"].get("frame_size"),
            "candidate_count": 0,
            "candidates": [],
        }
    else:
        bridge = None
    return frame, bridge


def _stack_axis(
    evidence: RawCandidateEvidence,
    objective: ObjectiveManifest,
    parents: ParentEvidenceBundle,
) -> tuple[int, int, int, int]:
    if evidence.checkdiff_evidence is None:
        raise ValueError("missing checkdiff")
    candidate_inputs = _evidence_frame_and_stack(evidence, objective.function)
    candidate = build_stack_home_profile(*candidate_inputs)
    if not candidate.complete:
        raise ValueError("incomplete candidate stack profile")

    expected_frame, expected_stack = deepcopy(candidate_inputs)
    raw_expected = expected_frame.get("expected")
    expected_frame_size = raw_expected.get("frame_size") if isinstance(raw_expected, Mapping) else None
    if not _is_int(expected_frame_size) or expected_frame_size < 0:
        classification = evidence.checkdiff_evidence.get("classification")
        sizes = classification.get("stack_frame_sizes") if isinstance(classification, Mapping) else None
        expected_frame_size = sizes.get("expected_frame_size") if isinstance(sizes, Mapping) else None
    if not _is_int(expected_frame_size) or expected_frame_size < 0:
        raise ValueError("missing expected frame size")
    expected_frame["current"]["frame_size"] = expected_frame_size
    assignments = expected_frame["current"].get("stack_home_assignments")
    if isinstance(assignments, list):
        for assignment in assignments:
            if isinstance(assignment, dict) and _is_int(assignment.get("expected_offset")):
                assignment["offset"] = assignment["expected_offset"]
    if isinstance(expected_stack, dict):
        candidates = expected_stack.get("candidates")
        if isinstance(candidates, list):
            for raw in candidates:
                if not isinstance(raw, dict):
                    continue
                mismatch = raw.get("mismatch")
                expected_offset = raw.get("expected_offset")
                if not _is_int(expected_offset) and isinstance(mismatch, Mapping):
                    expected_offset = mismatch.get("expected_offset")
                if _is_int(expected_offset):
                    raw["current_offset"] = expected_offset
                    if isinstance(mismatch, dict):
                        mismatch["current_offset"] = expected_offset
    absolute_reference = build_stack_home_profile(expected_frame, expected_stack)
    if not absolute_reference.complete:
        raise ValueError("incomplete absolute stack reference")

    stack_reference = objective.references.get("stack-homes")
    if stack_reference is None:
        raise ValueError("missing stack objective reference")
    unresolved = set(stack_reference.unresolved)
    donor = _donor_raw(parents, objective.stack_home_donor)
    donor_profile = None
    if unresolved:
        if donor is None or donor.checkdiff_evidence is None:
            raise ValueError("missing stack proxy donor")
        donor_profile = build_stack_home_profile(*_evidence_frame_and_stack(donor, objective.function))
        if not donor_profile.complete:
            raise ValueError("incomplete stack proxy donor")

    candidate_homes = {home.identity: home for home in candidate.homes}
    absolute_homes = {home.identity: home for home in absolute_reference.homes}
    donor_homes = {} if donor_profile is None else {home.identity: home for home in donor_profile.homes}
    absolute_ids = {identity for identity, home in candidate_homes.items() if home.reference_kind == "absolute"}
    proxy_ids = set(candidate_homes) - absolute_ids
    if proxy_ids - unresolved:
        raise ValueError("proxy stack home missing objective provenance")
    if unresolved - set(donor_homes):
        raise ValueError("unresolved stack home missing from donor")
    if absolute_ids - set(absolute_homes):
        raise ValueError("absolute stack home missing expected reference")

    absolute_moved = sum(
        candidate_homes[identity].offset != absolute_homes[identity].offset for identity in absolute_ids
    )
    absolute_delta = sum(
        abs(candidate_homes[identity].offset - absolute_homes[identity].offset) for identity in absolute_ids
    )
    proxy_common = proxy_ids & unresolved
    proxy_moved = sum(candidate_homes[identity].offset != donor_homes[identity].offset for identity in proxy_common)
    proxy_membership = len(proxy_ids ^ unresolved)
    candidate_order = [
        home.identity for home in sorted(candidate.homes, key=lambda item: item.order) if home.identity in proxy_common
    ]
    donor_order = (
        [
            home.identity
            for home in sorted(donor_profile.homes, key=lambda item: item.order)  # type: ignore[union-attr]
            if home.identity in proxy_common
        ]
        if donor_profile is not None
        else []
    )
    donor_positions = {identity: index for index, identity in enumerate(donor_order)}
    positions = [donor_positions[identity] for identity in candidate_order]
    inversions = sum(
        positions[left] > positions[right]
        for left in range(len(positions))
        for right in range(left + 1, len(positions))
    )
    return (
        absolute_moved + proxy_moved + proxy_membership,
        absolute_delta,
        inversions,
        abs(int(candidate.frame_size) - int(expected_frame_size)),
    )


def _objobject_axis(
    evidence: RawCandidateEvidence,
    objective: ObjectiveManifest,
    parents: ParentEvidenceBundle,
) -> tuple[int, int]:
    donor = _donor_raw(parents, objective.objobject_donor)
    if evidence.inspect_text is None or donor is None or donor.inspect_text is None:
        raise ValueError("missing ObjObject evidence")
    return objobject_order_distance(
        parse_objobject_profile(evidence.inspect_text, objective.function),
        parse_objobject_profile(donor.inspect_text, objective.function),
    )


def profile_candidate(
    evidence: RawCandidateEvidence,
    objective: ObjectiveManifest,
    *,
    parents: ParentEvidenceBundle | None = None,
    namespace_resolutions: Mapping[str, NamespaceMapResolution] | None = None,
) -> CandidateProfile:
    """Normalize one captured row into a complete or explicitly blocked profile."""

    if not isinstance(evidence, RawCandidateEvidence) or not isinstance(objective, ObjectiveManifest):
        raise DeltaMinimizeError("invalid-candidate-profile-input")
    if not evidence.viable:
        return CandidateProfile(
            candidate_id=evidence.candidate_id,
            mask=evidence.mask,
            source_hash=evidence.source_hash,
            source_path=evidence.source_path,
            viable=False,
            compile_status=evidence.compile_status,
            axes=None,
            complete=True,
            blockers=evidence.blockers,
        )

    blockers = list(evidence.blockers)
    if evidence.pcdump_path is None:
        _add(blockers, "missing-pcdump-path")
    if evidence.checkdiff_evidence is None:
        _add(blockers, "missing-checkdiff-evidence")
    if evidence.inspection_mode == "objobjects" and evidence.inspect_text is None:
        _add(blockers, "missing-inspect-text")
    if evidence.inspection_mode == "no-objobjects":
        _add(blockers, "objobjects-disabled-provisional")

    exact = bool(evidence.checkdiff_evidence is not None and evidence.checkdiff_evidence.get("match") is True)
    axes: dict[str, tuple[int, ...]] = {}
    if evidence.checkdiff_evidence is not None:
        target_asm = _asm_lines(evidence.checkdiff_evidence, "target_asm")
        current_asm = _asm_lines(evidence.checkdiff_evidence, "current_asm")
        if target_asm is None or current_asm is None:
            _add(blockers, "incomplete-opcode-evidence")
        else:
            try:
                axes["opcode"] = opcode_graph_distance(
                    parse_opcode_graph(target_asm),
                    parse_opcode_graph(current_asm),
                    structural_status=_structural_status(evidence.checkdiff_evidence),
                )
            except ValueError:
                _add(blockers, "contradictory-opcode-evidence")

    if evidence.pcdump_path is not None:
        try:
            _load_text(evidence.pcdump_path)
        except (OSError, UnicodeError, ValueError):
            _add(blockers, "unreadable-pcdump-path")
        else:
            if parents is None:
                _add(blockers, "missing-parent-color-evidence")
                _add(blockers, "missing-parent-stack-evidence")
            else:
                try:
                    axes["color"] = _color_axis(
                        evidence,
                        objective,
                        parents,
                        namespace_resolutions=namespace_resolutions,
                    )
                except (KeyError, OSError, TypeError, UnicodeError, ValueError):
                    _add(blockers, "incomplete-color-evidence")
                try:
                    axes["stack_homes"] = _stack_axis(evidence, objective, parents)
                except (KeyError, OSError, TypeError, UnicodeError, ValueError):
                    _add(blockers, "incomplete-stack-home-evidence")

    if evidence.inspection_mode == "no-objobjects":
        axes["objobjects"] = (0, 0)
    elif evidence.inspect_text is not None:
        if parents is None:
            _add(blockers, "missing-parent-objobject-evidence")
        else:
            try:
                axes["objobjects"] = _objobject_axis(evidence, objective, parents)
            except (TypeError, ValueError):
                _add(blockers, "incomplete-objobject-evidence")

    required = {"opcode", "color", "objobjects", "stack_homes"}
    complete = required <= axes.keys()
    if not complete:
        return CandidateProfile(
            candidate_id=evidence.candidate_id,
            mask=evidence.mask,
            source_hash=evidence.source_hash,
            source_path=evidence.source_path,
            viable=True,
            compile_status=evidence.compile_status,
            axes=None,
            complete=False,
            exact_object_match=exact,
            blockers=tuple(blockers),
        )
    return CandidateProfile(
        candidate_id=evidence.candidate_id,
        mask=evidence.mask,
        source_hash=evidence.source_hash,
        source_path=evidence.source_path,
        viable=True,
        compile_status=evidence.compile_status,
        axes=AxisDistances(
            opcode=axes["opcode"],  # type: ignore[arg-type]
            color=axes["color"],  # type: ignore[arg-type]
            objobjects=axes["objobjects"],  # type: ignore[arg-type]
            stack_homes=axes["stack_homes"],  # type: ignore[arg-type]
        ),
        complete=True,
        exact_object_match=exact,
        blockers=tuple(blockers),
    )
