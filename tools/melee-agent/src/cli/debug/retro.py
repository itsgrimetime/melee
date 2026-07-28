"""`melee-agent debug retro` — retail-binary MWCC introspection (issue #541)."""
from __future__ import annotations

import json
import shlex
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import typer

retro_app = typer.Typer(
    help="Retail-binary MWCC introspection via retrowin32 + gdb "
    "(GC/1.2.5n front-end IRO and backend/regalloc traces, plus GC/1.1 backend dumps)."
)

# Package checkout discovery (this file is tools/melee-agent/src/cli/debug/retro.py).
_PACKAGE_REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(_PACKAGE_REPO))
from tools.mwcc_retro import (  # noqa: E402
    TABLES_DIR,
    backend_events,
    backend_trace_assembler,
)
from tools.mwcc_retro import (
    setup as retro_setup,
)

from src.mwcc_debug.diff_capture import _run_with_process_group_timeout  # noqa: E402

RETRO_DUMP_TIMEOUT_SECONDS = 600
_STATIC_BACKEND_PRODUCER_QUERY_BUDGET = 32


def setup_mwcc_ghidra(**kwargs):
    """Load the MWCC Ghidra runner lazily to avoid the src.cli import cycle."""
    from src.mwcc_debug.ghidra_mwcc_setup import setup_mwcc_ghidra as setup

    return setup(**kwargs)


@dataclass
class DumpOutcome:
    exit_code: int
    produced: list[str]
    missing: list[str] = field(default_factory=list)


@dataclass
class BackendOutcome:
    exit_code: int
    trace: dict | None = None
    fidelity: dict | None = None
    missing: list[str] = field(default_factory=list)


@dataclass
class BackendIgSnapshotOutcome:
    exit_code: int
    summary_path: Path | None = None
    events_path: Path | None = None


@dataclass
class BackendPcodeSnapshotOutcome:
    exit_code: int
    summary_path: Path | None = None
    events_path: Path | None = None


@dataclass
class BackendCandidateOutcome:
    exit_code: int
    trace: dict | None = None
    map_dir: Path | None = None
    pcode_dir: Path | None = None
    ig_dir: Path | None = None


def _looks_like_melee_root(path: Path) -> bool:
    return (
        (path / "src" / "melee").is_dir()
        and (path / "tools" / "mwcc_retro").is_dir()
        and ((path / "build.ninja").exists() or (path / "configure.py").exists())
    )


def _find_melee_root(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if _looks_like_melee_root(candidate):
            return candidate
    return None


def _resolve_melee_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        root = explicit.expanduser().resolve()
        if not _looks_like_melee_root(root):
            raise typer.BadParameter(
                f"--melee-root is not a Melee checkout: {root}",
                param_hint="--melee-root",
            )
        return root
    return (_find_melee_root(Path.cwd()) or _PACKAGE_REPO).resolve()


def _retro_tables_dir(_melee_root: Path) -> Path:
    return TABLES_DIR


def _retro_script(name: str) -> Path:
    return _PACKAGE_REPO / "tools" / "mwcc_retro" / name


def _retro_subprocess_env(**overrides: str) -> dict[str, str]:
    import os

    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    paths = [str(_PACKAGE_REPO)]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.update(overrides)
    return env


def _resolve_output_dir(out: Path | None, *, melee_root: Path, src: str, fn: str) -> Path:
    if out is not None:
        return out.expanduser().resolve() if out.is_absolute() else melee_root / out
    unit = Path(src).with_suffix("").as_posix().replace("/", "_")
    return melee_root / "build" / "mwcc_retro" / unit / fn


def _ensure_setup(melee_root: Path | None = None):
    root = _resolve_melee_root(melee_root)
    if hasattr(retro_setup, "ensure_for_root"):
        return retro_setup.ensure_for_root(root, force=False)
    return retro_setup.ensure(force=False)


def _write_backend_outputs(
    out_dir: Path,
    trace: dict,
    fidelity: dict | None = None,
) -> None:
    from tools.mwcc_retro import backend_fidelity, backend_schema, backend_summary

    out_dir.mkdir(parents=True, exist_ok=True)
    errors = backend_schema.validate_backend_trace(trace)
    if errors:
        raise RuntimeError("backend trace schema errors: " + "; ".join(errors))
    backend_schema.write_backend_trace(out_dir / "backend-trace.v1.json", trace)
    (out_dir / "regalloc-summary.txt").write_text(
        backend_summary.render_regalloc_summary(trace)
    )
    (out_dir / "backend-summary.txt").write_text(
        backend_summary.render_backend_summary(trace)
    )
    if fidelity is not None:
        (out_dir / "backend-fidelity.json").write_text(
            json.dumps(fidelity, indent=2, sort_keys=True) + "\n"
        )
        (out_dir / "backend-fidelity.txt").write_text(
            backend_fidelity.render_fidelity_text(fidelity)
        )


_BACKEND_REQUIRED_OUTPUTS = (
    "backend-trace.v1.json",
    "regalloc-summary.txt",
    "backend-summary.txt",
)


def _validate_backend_outputs(out_dir: Path) -> None:
    missing = [
        name
        for name in _BACKEND_REQUIRED_OUTPUTS
        if not (out_dir / name).is_file()
    ]
    if missing:
        raise RuntimeError(
            "backend trace command reported success but did not produce "
            "required output(s): " + ", ".join(missing)
        )


def _write_backend_candidate_outputs(out_dir: Path, trace: dict) -> None:
    from tools.mwcc_retro import backend_schema, backend_summary

    out_dir.mkdir(parents=True, exist_ok=True)
    errors = backend_schema.validate_backend_trace(trace)
    if errors:
        raise RuntimeError("backend candidate trace schema errors: " + "; ".join(errors))
    (out_dir / "backend-trace.candidate.v1.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n"
    )
    (out_dir / "regalloc-summary.candidate.txt").write_text(
        backend_summary.render_regalloc_summary(trace)
    )
    (out_dir / "backend-summary.candidate.txt").write_text(
        backend_summary.render_backend_summary(trace)
    )


def _tail_text(value, *, limit: int = 2000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode(errors="replace")
    else:
        text = str(value)
    return text[-limit:]


def _tail(text: str, *, lines: int = 20) -> str:
    return "\n".join(str(text).splitlines()[-lines:])


def _process_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _dedupe_strings(values) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return tuple(result)


def _parse_symbol_function_addresses(melee_root: Path) -> dict[str, int]:
    import re

    symbols_path = melee_root / "config" / "GALE01" / "symbols.txt"
    try:
        lines = symbols_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}

    parsed: dict[str, int] = {}
    pattern = re.compile(
        r"^\s*(?P<name>\S+)\s*=\s*\.text:0x(?P<addr>[0-9A-Fa-f]+);.*\btype:function\b"
    )
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        try:
            parsed[match.group("name")] = int(match.group("addr"), 16)
        except ValueError:
            continue
    return parsed


def _address_from_fn_alias(function: str) -> int | None:
    import re

    match = re.fullmatch(r"fn_([0-9A-Fa-f]{8})", function)
    if not match:
        return None
    return int(match.group(1), 16)


def _address_style_name(function: str, address: int) -> str | None:
    if "_" not in function or function.startswith("fn_"):
        return None
    prefix = function.split("_", 1)[0]
    if not prefix:
        return None
    return f"{prefix}_{address:08X}"


def _symbol_function_aliases(function: str, melee_root: Path) -> tuple[str, ...]:
    symbols = _parse_symbol_function_addresses(melee_root)
    address = symbols.get(function)
    if address is None:
        address = _address_from_fn_alias(function)
    if address is None:
        return ()

    same_address = [
        name for name, value in symbols.items() if value == address and name != function
    ]
    return _dedupe_strings(
        (
            *same_address,
            f"fn_{address:08X}",
            _address_style_name(function, address),
        )
    )


def _backend_function_aliases(fn: str, *, melee_root: Path) -> tuple[str, ...]:
    try:
        from src.mwcc_debug.diff_capture import function_pcdump_aliases

        pcdump_aliases = function_pcdump_aliases(fn, melee_root)
    except Exception:  # noqa: BLE001 - aliases are best-effort diagnostics
        pcdump_aliases = ()
    return _dedupe_strings(
        (
            *pcdump_aliases,
            *_symbol_function_aliases(fn, melee_root),
        )
    )


def _backend_function_aliases_json(fn: str, *, melee_root: Path) -> str:
    return json.dumps(list(_backend_function_aliases(fn, melee_root=melee_root)))


def _format_parity_mismatch(parity: dict) -> str:
    def object_line(label: str, data: dict | None) -> str:
        data = data or {}
        return (
            f"{label}: path={data.get('path', '<unknown>')} "
            f"size={data.get('size', '<unknown>')} "
            f"sha256={data.get('sha256', '<unknown>')}"
        )

    return "\n".join(
        [
            "backend object parity mismatch",
            object_line("reference", parity.get("reference")),
            object_line("retro", parity.get("retro")),
        ]
    )


def _format_parity_compile_error(*, phase: str, cmd: list[str], exc) -> str:
    import shlex
    import subprocess

    lines = [
        f"backend object parity {phase} compile failed",
        "command: " + shlex.join([str(part) for part in cmd]),
    ]
    if isinstance(exc, subprocess.CalledProcessError):
        lines.append(f"exit code: {exc.returncode}")
        stdout = _tail_text(getattr(exc, "stdout", None) or getattr(exc, "output", None))
        stderr = _tail_text(getattr(exc, "stderr", None))
    elif isinstance(exc, subprocess.TimeoutExpired):
        lines.append(f"timeout: {exc.timeout}s")
        stdout = _tail_text(getattr(exc, "stdout", None) or getattr(exc, "output", None))
        stderr = _tail_text(getattr(exc, "stderr", None))
    else:
        lines.append(f"error: {exc}")
        stdout = ""
        stderr = ""
    if stdout:
        lines.append("stdout tail:\n" + stdout)
    if stderr:
        lines.append("stderr tail:\n" + stderr)
    return "\n".join(lines)


def _run_parity_compile_command(*, phase: str, cmd: list[str], melee_root: Path) -> None:
    import subprocess

    try:
        subprocess.run(
            cmd,
            cwd=melee_root,
            check=True,
            capture_output=True,
            timeout=300,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(
            _format_parity_compile_error(phase=phase, cmd=cmd, exc=exc)
        ) from exc


def _run_object_parity_for_backend(
    *,
    src: str,
    melee_root: Path,
    retain_object: Path | None = None,
) -> dict:
    """Run the raw .o byte-parity gate for backend tracing."""
    import shlex
    import tempfile

    from tools.mwcc_retro import object_parity
    from tools.mwcc_retro import setup as _setup

    setup_result = _setup.ensure_for_root(melee_root, force=False)
    cmd = _ninja_cmd_for_unit(src, melee_root=melee_root)
    parts = shlex.split(cmd)
    compiler = str(melee_root / parts[0])
    args = [p for p in parts[1:] if p != "-MMD"]
    with tempfile.TemporaryDirectory() as td:
        ref = Path(td) / "reference.o"
        retro_obj = Path(td) / "retro.o"

        def with_output(path: Path) -> list[str]:
            local = list(args)
            if "-o" in local:
                local[local.index("-o") + 1] = str(path)
            else:
                local += ["-o", str(path)]
            return local

        wibo = melee_root / "build/tools/wibo"
        sjis = melee_root / "build/tools/sjiswrap.exe"
        if sjis.exists():
            normal_cmd = [str(wibo), str(sjis), compiler] + with_output(ref)
        else:
            normal_cmd = [str(wibo), compiler] + with_output(ref)
        _run_parity_compile_command(
            phase="reference",
            cmd=normal_cmd,
            melee_root=melee_root,
        )
        _run_parity_compile_command(
            phase="retro",
            cmd=[str(setup_result.retrowin32_bin), compiler] + with_output(retro_obj),
            melee_root=melee_root,
        )
        result = object_parity.compare_objects(ref, retro_obj).to_dict()
        if retain_object is not None and result.get("matched") is True:
            retain_object.parent.mkdir(parents=True, exist_ok=True)
            retain_object.write_bytes(ref.read_bytes())
        return result


def _launch_backend_events(*, src: str, fn: str, out_dir: Path, melee_root: Path) -> Path:
    """Launch retrowin32+gdb backend event tracing and return JSONL path."""
    import shlex
    import subprocess

    from tools.mwcc_retro import setup as _setup
    from tools.mwcc_retro import struct_map

    setup_result = _setup.ensure_for_root(melee_root, force=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "backend-events.v1.jsonl"
    table = _retro_tables_dir(melee_root) / "gc_125n.json"
    launcher = _retro_script("mwcc_retro_debugger.py")

    table_data = json.loads(table.read_text())
    map_errors = struct_map.validate_required_backend_map(table_data)
    if map_errors:
        raise RuntimeError(
            "backend event launcher requires validated 1.2.5n struct map: "
            + "; ".join(map_errors)
        )
    reader_errors = struct_map.validate_backend_reader_capability(table_data)
    if reader_errors:
        raise RuntimeError(
            "backend event launcher requires complete backend reader: "
            + "; ".join(reader_errors)
        )

    ninja_cmd = _ninja_cmd_for_unit(src, melee_root=melee_root)
    parts = shlex.split(ninja_cmd)
    if not parts:
        raise RuntimeError("backend event launcher failed: empty compiler command")
    mwcc_exe = melee_root / "build" / "compilers" / "GC" / "1.2.5n" / "mwcceppc.exe"
    mwcc_args = shlex.join([str(mwcc_exe), *parts[1:]])
    cmd = [
        "python3",
        str(launcher),
        "-e",
        str(setup_result.retrowin32_bin),
        "-a",
        mwcc_args,
        "--table",
        str(table),
        "--out",
        str(out_dir),
        "--phases",
        "backend",
        "--compiler",
        "1.2.5n",
        fn,
    ]
    hook = _retro_script("backend_onepass_trace_hook.py")
    cmd[-1:-1] = ["--gdb-py", str(hook)]
    env = _retro_subprocess_env(
        RETRO_SOURCE=src,
        RETRO_FUNCTION=fn,
        RETRO_FUNCTION_ALIASES=_backend_function_aliases_json(fn, melee_root=melee_root),
    )
    command_text = shlex.join([str(part) for part in cmd])
    launch_log = out_dir / "launch.log"

    def write_launch_log(*, exit_text: str, stdout="", stderr="") -> None:
        launch_log.write_text(
            "\n".join(
                [
                    f"COMMAND: {command_text}",
                    f"RETRO_SOURCE: {src}",
                    f"RETRO_FUNCTION: {fn}",
                    f"EXIT: {exit_text}",
                    "STDOUT:",
                    _process_text(stdout),
                    "STDERR:",
                    _process_text(stderr),
                ]
            )
            + "\n"
        )

    def remove_partial_events() -> None:
        events_path.unlink(missing_ok=True)

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(melee_root),
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = getattr(exc, "stdout", None) or getattr(exc, "output", None)
        stderr = getattr(exc, "stderr", None)
        write_launch_log(
            exit_text=f"timeout after {exc.timeout:g}s",
            stdout=stdout,
            stderr=stderr,
        )
        remove_partial_events()
        raise RuntimeError(
            "backend event launcher timed out"
            + ("\n" + _tail(_process_text(stdout) + "\n" + _process_text(stderr))
               if stdout or stderr else "")
        ) from exc
    except OSError as exc:
        write_launch_log(exit_text=f"{exc.__class__.__name__}: {exc}")
        remove_partial_events()
        raise RuntimeError(
            f"backend event launcher failed: {exc.__class__.__name__}: {exc}"
        ) from exc

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    write_launch_log(exit_text=str(proc.returncode), stdout=proc.stdout, stderr=proc.stderr)

    if "[retro] ABORT:" in combined:
        remove_partial_events()
        raise RuntimeError(
            "backend event launcher aborted"
            + ("\n" + _tail(combined) if combined.strip() else "")
        )
    if proc.returncode != 0:
        remove_partial_events()
        raise RuntimeError(
            f"backend event launcher failed (exit {proc.returncode})"
            + ("\n" + _tail(combined) if combined.strip() else "")
        )
    if not events_path.exists() or events_path.stat().st_size == 0:
        remove_partial_events()
        raise RuntimeError(
            "backend event launcher produced no backend-events.v1.jsonl"
            + ("\n" + _tail(combined) if combined.strip() else "")
        )
    try:
        _validate_onepass_candidate_summary(out_dir, fn=fn)
        _validate_onepass_event_function_start(backend_events.load_events(events_path), fn=fn)
        _promote_onepass_summary_for_full_backend(out_dir)
    except (RuntimeError, ValueError) as exc:
        remove_partial_events()
        raise RuntimeError(f"backend event launcher produced invalid trace: {exc}") from exc
    return events_path


def _remove_backend_probe_stale_artifacts(out_dir: Path) -> None:
    """Remove backend trace artifacts that would make probe output ambiguous."""
    names = {
        "raw-pe-cfg.v1.jsonl",
        "raw-ghidra-crosscheck.v1.json",
        "backend-map-candidates.json",
        "backend-map-probe.json",
        "backend-map-evidence.json",
        "backend-ig-snapshot.json",
        "backend-ig-snapshot-events.v1.jsonl",
        "backend-pcode-snapshot.json",
        "backend-pcode-snapshot-events.v1.jsonl",
        "backend-pcode-lineage.v1.json",
        "candidate.o",
        "backend-colorgraph-decisions.v1.jsonl",
        "backend-colorgraph-trace.json",
        "backend-events.v1.jsonl",
        "backend-trace.v1.json",
        "backend-summary.txt",
        "regalloc-summary.txt",
        "backend-fidelity.json",
        "backend-fidelity.txt",
        "backend-source-attribution.json",
        "backend-trace.candidate.v1.json",
        "backend-summary.candidate.txt",
        "regalloc-summary.candidate.txt",
        "launch.log",
        "provenance.json",
        "variables.txt",
        "instrumentation.json",
    }
    for name in names:
        (out_dir / name).unlink(missing_ok=True)
    for pattern in ("backend-*.txt", "regalloc-*.txt"):
        for path in out_dir.glob(pattern):
            if path.is_file():
                path.unlink()


def _remove_backend_dump_text_artifacts(out_dir: Path) -> None:
    for pattern in ("backend-*.txt", "regalloc-*.txt"):
        for path in out_dir.glob(pattern):
            if path.is_file():
                path.unlink()


def _validate_backend_map_probe_payload(path: Path, *, fn: str) -> dict:
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"backend map probe wrote invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("backend map probe payload must be a JSON object")

    problems: list[str] = []
    if payload.get("schema_version") != "mwcc-retro-backend-map-probe.v1":
        problems.append(
            "backend map probe wrote unexpected schema "
            f"{payload.get('schema_version')!r}"
        )
    if payload.get("requested_function") != fn:
        problems.append(
            "backend map probe requested_function mismatch: "
            f"{payload.get('requested_function')!r} != {fn!r}"
        )
    if payload.get("requested_function_matched") is not True:
        problems.append(f"backend map probe did not observe requested function {fn}")
    errors = payload.get("errors") or []
    if errors:
        problems.append(f"backend map probe recorded {len(errors)} error(s): {errors!r}")
    if problems:
        raise RuntimeError("; ".join(problems))
    return payload


def _validate_backend_ig_snapshot_payload(path: Path, *, fn: str) -> dict:
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"backend IG snapshot wrote invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("backend IG snapshot payload must be a JSON object")

    problems: list[str] = []
    if payload.get("schema_version") != "mwcc-retro-backend-ig-snapshot.v1":
        problems.append(
            "backend IG snapshot wrote unexpected schema "
            f"{payload.get('schema_version')!r}"
        )
    if payload.get("requested_function") != fn:
        problems.append(
            "backend IG snapshot requested_function mismatch: "
            f"{payload.get('requested_function')!r} != {fn!r}"
        )
    if payload.get("requested_function_matched") is not True:
        problems.append(f"backend IG snapshot did not observe requested function {fn}")
    errors = payload.get("errors") or []
    if errors:
        problems.append(
            f"backend IG snapshot recorded {len(errors)} error(s): {errors!r}"
        )
    classes = payload.get("classes_seen")
    if not isinstance(classes, list) or not classes:
        problems.append("backend IG snapshot did not record any register classes")
    if problems:
        raise RuntimeError("; ".join(problems))
    return payload


def _validate_backend_ig_snapshot_events(path: Path, *, fn: str) -> None:
    from tools.mwcc_retro import struct_map

    allowed_events = set(struct_map.REQUIRED_BACKEND_IG_SNAPSHOT_FAMILIES)
    required_events = allowed_events - {"edge", "coalesce_mapping_empty", "color_decision"}
    problems: list[str] = []
    event_count = 0
    function_start_seen = False
    seen_events: set[str] = set()
    regclass_ids: set[int] = set()
    regclass_names: set[str] = set()
    regclass_names_by_id: dict[int, str] = {}
    node_classes: dict[int, set[int]] = {}
    order_events_by_class: dict[int, set[str]] = {}
    coalesce_events_by_class: dict[int, set[str]] = {}
    coalesce_aliases_by_class: dict[int, set[int]] = {}
    color_decision_ids_by_class: dict[int, set[str]] = {}

    def resolve_allocator_class(event: dict, *, kind: str, lineno: int) -> int | None:
        class_id = event.get("class_id")
        if not isinstance(class_id, int) or class_id not in regclass_ids:
            problems.append(
                f"line {lineno} {kind} references class_id {class_id!r} "
                "before regclass"
            )
            return None

        class_name = event.get("class_name")
        expected_name = regclass_names_by_id.get(class_id)
        if not isinstance(class_name, str) or not class_name:
            problems.append(f"line {lineno} {kind} missing class_name")
        elif expected_name is not None and class_name != expected_name:
            problems.append(
                f"line {lineno} class_id {class_id} registered as "
                f"{expected_name!r} but {kind} reports class_name {class_name!r}"
            )
        return class_id

    with path.open(encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            event_count += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "backend IG snapshot events wrote invalid JSON on "
                    f"line {lineno}: {exc}"
                ) from exc
            if not isinstance(event, dict):
                problems.append(f"line {lineno} event must be a JSON object")
                continue

            kind = event.get("event")
            if kind not in allowed_events:
                problems.append(f"line {lineno} unexpected event {kind!r}")
                continue
            seen_events.add(kind)
            if kind == "coalesce_mapping_empty":
                seen_events.add("coalesce_mapping")

            if kind == "function_start":
                if function_start_seen:
                    problems.append("backend IG snapshot events duplicate function_start")
                function_start_seen = True
                name = event.get("name")
                if name != fn:
                    problems.append(
                        "backend IG snapshot events function_start mismatch: "
                        f"{name!r} != {fn!r}"
                    )
            elif kind == "regclass":
                class_id = event.get("class_id")
                class_name = event.get("class_name")
                if not isinstance(class_id, int):
                    problems.append(f"line {lineno} regclass missing integer class_id")
                elif class_id in regclass_ids:
                    problems.append(
                        f"backend IG snapshot events duplicate regclass class_id {class_id}"
                    )
                else:
                    regclass_ids.add(class_id)
                    node_classes.setdefault(class_id, set())
                    order_events_by_class.setdefault(class_id, set())
                    coalesce_events_by_class.setdefault(class_id, set())
                    coalesce_aliases_by_class.setdefault(class_id, set())
                    color_decision_ids_by_class.setdefault(class_id, set())

                if not isinstance(class_name, str) or not class_name:
                    problems.append(f"line {lineno} regclass missing class_name")
                elif class_name in regclass_names:
                    problems.append(
                        "backend IG snapshot events duplicate regclass class_name "
                        f"{class_name!r}"
                    )
                else:
                    regclass_names.add(class_name)
                    if isinstance(class_id, int):
                        regclass_names_by_id[class_id] = class_name

                registers = event.get("registers")
                if not isinstance(registers, dict) or not registers:
                    problems.append(f"line {lineno} regclass missing register metadata")
            elif kind == "node":
                class_id = resolve_allocator_class(event, kind=kind, lineno=lineno)
                if class_id is None:
                    continue
                ig_id = event.get("ig_id")
                if not isinstance(ig_id, int):
                    problems.append(f"line {lineno} node missing integer ig_id")
                else:
                    node_classes.setdefault(class_id, set()).add(ig_id)
            elif kind == "edge":
                class_id = resolve_allocator_class(event, kind=kind, lineno=lineno)
                if class_id is None:
                    continue
                for key in ("a", "b"):
                    endpoint = event.get(key)
                    if not isinstance(endpoint, int):
                        problems.append(f"line {lineno} edge missing integer {key}")
                    elif endpoint not in node_classes.get(class_id, set()):
                        problems.append(
                            f"line {lineno} edge references missing node {endpoint} "
                            f"in class_id {class_id}"
                        )
            elif kind in {"coalesce_mapping", "coalesce_mapping_empty"}:
                class_id = resolve_allocator_class(event, kind=kind, lineno=lineno)
                if class_id is None:
                    continue

                coalesce_events_by_class.setdefault(class_id, set()).add(kind)

                for key in ("source_stage", "provenance"):
                    if not isinstance(event.get(key), str) or not event.get(key):
                        problems.append(f"line {lineno} {kind} missing {key}")

                if kind == "coalesce_mapping_empty":
                    continue

                emitted_nodes = node_classes.get(class_id, set())
                alias = event.get("alias")
                root = event.get("root")
                if not isinstance(alias, int):
                    problems.append(f"line {lineno} coalesce_mapping missing integer alias")
                elif alias not in emitted_nodes:
                    problems.append(
                        f"line {lineno} coalesce_mapping references missing alias node "
                        f"{alias} in class_id {class_id}"
                    )
                else:
                    seen_aliases = coalesce_aliases_by_class.setdefault(class_id, set())
                    if alias in seen_aliases:
                        problems.append(
                            "backend IG snapshot events duplicate coalesce_mapping "
                            f"alias {alias} for class_id {class_id}"
                        )
                    else:
                        seen_aliases.add(alias)

                if not isinstance(root, int):
                    problems.append(f"line {lineno} coalesce_mapping missing integer root")
                elif isinstance(alias, int) and alias == root:
                    problems.append(
                        f"line {lineno} coalesce_mapping self-map alias {alias} "
                        f"root {root} in class_id {class_id}"
                    )
                elif root not in emitted_nodes:
                    problems.append(
                        f"line {lineno} coalesce_mapping references missing root node "
                        f"{root} in class_id {class_id}"
                    )
            elif kind in {"simplify_order", "select_order"}:
                class_id = resolve_allocator_class(event, kind=kind, lineno=lineno)
                if class_id is None:
                    continue

                seen_orders = order_events_by_class.setdefault(class_id, set())
                if kind in seen_orders:
                    problems.append(
                        f"backend IG snapshot events duplicate {kind} "
                        f"for class_id {class_id}"
                    )
                else:
                    seen_orders.add(kind)

                order = event.get("order")
                if not isinstance(order, list):
                    problems.append(f"line {lineno} {kind} missing order list")
                else:
                    emitted_nodes = node_classes.get(class_id, set())
                    seen_order_ids: set[int] = set()
                    for ig_id in order:
                        if not isinstance(ig_id, int):
                            problems.append(f"line {lineno} {kind} contains non-integer ig id")
                        elif ig_id not in emitted_nodes:
                            problems.append(
                                f"line {lineno} {kind} references missing node {ig_id} "
                                f"in class_id {class_id}"
                            )
                        elif ig_id in seen_order_ids:
                            problems.append(
                                f"line {lineno} {kind} duplicates ig id {ig_id} "
                                f"in class_id {class_id}"
                            )
                        else:
                            seen_order_ids.add(ig_id)

                for key in ("source_stage", "provenance"):
                    if not isinstance(event.get(key), str) or not event.get(key):
                        problems.append(f"line {lineno} {kind} missing {key}")
            elif kind == "color_decision":
                class_id = resolve_allocator_class(event, kind=kind, lineno=lineno)
                if class_id is None:
                    continue

                if event.get("source_stage") != "colorgraph_return":
                    problems.append(f"line {lineno} color_decision missing source_stage")
                if event.get("provenance") != "retail-colorgraph-return":
                    problems.append(
                        "line "
                        f"{lineno} color_decision provenance must be retail-colorgraph-return"
                    )
                if event.get("confidence") != "observed-partial":
                    problems.append(
                        f"line {lineno} color_decision confidence must be observed-partial"
                    )
                if event.get("chosen_source") != "observed-retail-assignment":
                    problems.append(
                        "line "
                        f"{lineno} color_decision chosen_source must be "
                        "observed-retail-assignment"
                    )
                if event.get("available_phys_ordered") != []:
                    problems.append(
                        "line "
                        f"{lineno} color_decision available_phys_ordered must be "
                        "empty for partial observed facts"
                    )
                if event.get("tie_rule") != "unavailable-retail-post-colorgraph":
                    problems.append(
                        "line "
                        f"{lineno} color_decision tie_rule must be "
                        "unavailable-retail-post-colorgraph"
                    )
                if event.get("decision_rule") != "retail-post-colorgraph-observed-assignment":
                    problems.append(
                        "line "
                        f"{lineno} color_decision decision_rule must be "
                        "retail-post-colorgraph-observed-assignment"
                    )
                if event.get("node_state_before_select") != {
                    "status": "unavailable",
                    "reason": "retail-post-colorgraph-only",
                }:
                    problems.append(
                        "line "
                        f"{lineno} color_decision node_state_before_select must mark "
                        "retail-post-colorgraph-only"
                    )

                decision_id = event.get("id")
                if not isinstance(decision_id, str) or not decision_id:
                    problems.append(f"line {lineno} color_decision missing id")
                else:
                    seen_decisions = color_decision_ids_by_class.setdefault(class_id, set())
                    if decision_id in seen_decisions:
                        problems.append(
                            "backend IG snapshot events duplicate color_decision "
                            f"id {decision_id} for class_id {class_id}"
                        )
                    else:
                        seen_decisions.add(decision_id)

                emitted_nodes = node_classes.get(class_id, set())
                ig_id = event.get("ig_id")
                if not isinstance(ig_id, int):
                    problems.append(f"line {lineno} color_decision missing integer ig_id")
                elif ig_id not in emitted_nodes:
                    problems.append(
                        f"line {lineno} color_decision references missing node {ig_id} "
                        f"in class_id {class_id}"
                    )

                blocked_candidates = event.get("blocked_candidates", [])
                if not isinstance(blocked_candidates, list):
                    problems.append(
                        f"line {lineno} color_decision blocked_candidates must be list"
                    )
                else:
                    for blocked in blocked_candidates:
                        if not isinstance(blocked, dict):
                            problems.append(
                                f"line {lineno} color_decision blocked candidate must be object"
                            )
                            continue
                        holder = blocked.get("holder_ig_id")
                        if not isinstance(holder, int):
                            problems.append(
                                "line "
                                f"{lineno} color_decision blocked candidate missing "
                                "integer holder_ig_id"
                            )
                        elif holder not in emitted_nodes:
                            problems.append(
                                "line "
                                f"{lineno} color_decision blocked candidate references "
                                f"missing holder node {holder} in class_id {class_id}"
                            )

    if event_count == 0:
        problems.append("backend IG snapshot events file is empty")
    if not function_start_seen:
        problems.append("backend IG snapshot events missing function_start")
    if not regclass_ids:
        problems.append("backend IG snapshot events missing regclass")
    missing_events = sorted(required_events - seen_events)
    if missing_events:
        problems.append(
            "backend IG snapshot events missing required event families: "
            + ", ".join(missing_events)
        )
    for class_id, kinds in sorted(order_events_by_class.items()):
        missing_order = sorted({"select_order", "simplify_order"} - kinds)
        if missing_order:
            problems.append(
                f"backend IG snapshot events class_id {class_id} missing order "
                "event families: " + ", ".join(missing_order)
            )
    for class_id, kinds in sorted(coalesce_events_by_class.items()):
        if not kinds:
            problems.append(
                f"backend IG snapshot events class_id {class_id} missing "
                "coalesce_mapping event family"
            )
        elif {"coalesce_mapping", "coalesce_mapping_empty"} <= kinds:
            problems.append(
                f"backend IG snapshot events class_id {class_id} emitted both "
                "coalesce_mapping and coalesce_mapping_empty"
            )

    if problems:
        raise RuntimeError("; ".join(problems))


def _validate_backend_colorgraph_decision_events(path: Path, *, fn: str) -> None:
    problems: list[str] = []
    function_start_seen = False
    event_count = 0
    decision_ids: set[str] = set()

    with path.open(encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            event_count += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "backend colorgraph decision events wrote invalid JSON on "
                    f"line {lineno}: {exc}"
                ) from exc
            if not isinstance(event, dict):
                problems.append(f"line {lineno} event must be a JSON object")
                continue

            kind = event.get("event")
            if kind == "function_start":
                if function_start_seen:
                    problems.append("backend colorgraph events duplicate function_start")
                function_start_seen = True
                name = event.get("name")
                if name != fn:
                    problems.append(
                        "backend colorgraph events function_start mismatch: "
                        f"{name!r} != {fn!r}"
                    )
                continue
            if kind != "color_decision":
                problems.append(f"line {lineno} unexpected colorgraph event {kind!r}")
                continue

            decision_id = event.get("id")
            if not isinstance(decision_id, str) or not decision_id:
                problems.append(f"line {lineno} colorgraph decision missing id")
                decision_id = f"<line-{lineno}>"
            elif decision_id in decision_ids:
                problems.append(
                    f"backend colorgraph events duplicate decision id {decision_id}"
                )
            else:
                decision_ids.add(decision_id)

            for key in ("class_name", "chosen_source", "tie_rule", "decision_rule"):
                if not isinstance(event.get(key), str) or not event.get(key):
                    problems.append(
                        f"line {lineno} colorgraph decision {decision_id} missing {key}"
                    )
            for key in ("class_id", "ig_id", "iter"):
                if not isinstance(event.get(key), int):
                    problems.append(
                        f"line {lineno} colorgraph decision {decision_id} "
                        f"missing integer {key}"
                    )

            if event.get("source_stage") != "colorgraph":
                problems.append(f"line {lineno} colorgraph decision missing source_stage")
            if event.get("provenance") != "retail-colorgraph-internal":
                problems.append(
                    "line "
                    f"{lineno} colorgraph decision provenance must be "
                    "retail-colorgraph-internal"
                )
            if event.get("confidence") != "observed-internal":
                problems.append(
                    f"line {lineno} colorgraph decision confidence must be observed-internal"
                )

            for key in (
                "available_phys_ordered",
                "candidate_phys_ordered",
                "blocked_candidates",
                "blocked_by",
                "reserved_or_precolored_filtered",
                "volatile_pool_before",
                "volatile_pool_after",
            ):
                if not isinstance(event.get(key), list):
                    problems.append(
                        f"line {lineno} colorgraph decision {decision_id} {key} must be list"
                    )
            for key in ("nonvolatile_dispense_before", "nonvolatile_dispense_after"):
                if not isinstance(event.get(key), dict):
                    problems.append(
                        f"line {lineno} colorgraph decision {decision_id} {key} must be object"
                    )

            assigned_phys = event.get("assigned_phys")
            candidates = event.get("candidate_phys_ordered")
            if assigned_phys is not None:
                if not isinstance(assigned_phys, int):
                    problems.append(
                        f"line {lineno} colorgraph decision {decision_id} "
                        "assigned_phys must be integer or null"
                    )
                elif isinstance(candidates, list) and assigned_phys not in candidates:
                    problems.append(
                        f"line {lineno} colorgraph decision candidate_phys_ordered "
                        f"must include assigned_phys {assigned_phys}"
                    )

            state = event.get("node_state_before_select")
            if not isinstance(state, dict):
                problems.append(
                    f"line {lineno} colorgraph decision {decision_id} "
                    "node_state_before_select must be object"
                )
            else:
                for key in (
                    "precolored",
                    "coalesced",
                    "spill_marked",
                    "rematerialized",
                ):
                    if key not in state:
                        problems.append(
                            f"line {lineno} colorgraph decision "
                            f"node_state_before_select missing {key}"
                        )
                    elif not isinstance(state.get(key), bool):
                        problems.append(
                            f"line {lineno} colorgraph decision "
                            f"node_state_before_select {key} must be bool"
                        )

    if event_count == 0:
        problems.append("backend colorgraph decision events file is empty")
    if not function_start_seen:
        problems.append("backend colorgraph decision events missing function_start")
    if problems:
        raise RuntimeError("; ".join(problems))


def _validate_backend_colorgraph_trace_payload(path: Path, *, fn: str) -> dict:
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"backend colorgraph trace wrote invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("backend colorgraph trace payload must be a JSON object")

    problems: list[str] = []
    if payload.get("schema_version") != "mwcc-retro-backend-colorgraph-trace.v1":
        problems.append(
            "backend colorgraph trace wrote unexpected schema "
            f"{payload.get('schema_version')!r}"
        )
    if payload.get("requested_function") != fn:
        problems.append(
            "backend colorgraph trace requested_function mismatch: "
            f"{payload.get('requested_function')!r} != {fn!r}"
        )
    if payload.get("requested_function_matched") is not True:
        problems.append(f"backend colorgraph trace did not observe requested function {fn}")
    errors = payload.get("errors") or []
    if errors:
        problems.append(
            f"backend colorgraph trace recorded {len(errors)} error(s): {errors!r}"
        )
    breakpoints = payload.get("internal_breakpoints")
    if not isinstance(breakpoints, dict) or not breakpoints:
        problems.append("backend colorgraph trace missing internal_breakpoints")
    if not isinstance(payload.get("decisions_seen"), list):
        problems.append("backend colorgraph trace decisions_seen must be a list")
    if problems:
        raise RuntimeError("; ".join(problems))
    return payload


def _validate_backend_pcode_snapshot_payload(path: Path, *, fn: str) -> dict:
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"backend PCode snapshot wrote invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("backend PCode snapshot payload must be a JSON object")

    problems: list[str] = []
    if payload.get("schema_version") != "mwcc-retro-backend-pcode-snapshot.v1":
        problems.append(
            "backend PCode snapshot wrote unexpected schema "
            f"{payload.get('schema_version')!r}"
        )
    if payload.get("requested_function") != fn:
        problems.append(
            "backend PCode snapshot requested_function mismatch: "
            f"{payload.get('requested_function')!r} != {fn!r}"
        )
    if payload.get("requested_function_matched") is not True:
        problems.append(f"backend PCode snapshot did not observe requested function {fn}")
    errors = payload.get("errors") or []
    if errors:
        problems.append(
            f"backend PCode snapshot recorded {len(errors)} error(s): {errors!r}"
        )
    passes = payload.get("passes_seen")
    if not isinstance(passes, list) or not passes:
        problems.append("backend PCode snapshot did not record any PCode passes")
    if problems:
        raise RuntimeError("; ".join(problems))
    return payload


def _validate_backend_pcode_snapshot_events(path: Path, *, fn: str) -> None:
    from tools.mwcc_retro import struct_map

    allowed_events = set(struct_map.REQUIRED_BACKEND_PCODE_SNAPSHOT_FAMILIES)
    problems: list[str] = []
    event_count = 0
    function_start_seen = False
    seen_events: set[str] = set()
    block_ids: set[str] = set()
    instruction_ids: set[str] = set()

    with path.open(encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            event_count += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "backend PCode snapshot events wrote invalid JSON on "
                    f"line {lineno}: {exc}"
                ) from exc
            if not isinstance(event, dict):
                problems.append(f"line {lineno} event must be a JSON object")
                continue

            kind = event.get("event")
            if kind not in allowed_events:
                problems.append(f"line {lineno} unexpected event {kind!r}")
                continue
            seen_events.add(kind)

            if kind == "function_start":
                if function_start_seen:
                    problems.append("backend PCode snapshot events duplicate function_start")
                function_start_seen = True
                name = event.get("name")
                if name != fn:
                    problems.append(
                        "backend PCode snapshot events function_start mismatch: "
                        f"{name!r} != {fn!r}"
                    )
            elif kind == "block":
                block_id = event.get("id")
                if not isinstance(block_id, str) or not block_id:
                    problems.append(f"line {lineno} block missing id")
                elif block_id in block_ids:
                    problems.append(
                        f"backend PCode snapshot events duplicate block {block_id!r}"
                    )
                else:
                    block_ids.add(block_id)
                if not isinstance(event.get("order"), int):
                    problems.append(f"line {lineno} block missing integer order")
            elif kind == "pcode_instruction":
                instr_id = event.get("id")
                if not isinstance(instr_id, str) or not instr_id:
                    problems.append(f"line {lineno} pcode_instruction missing id")
                elif instr_id in instruction_ids:
                    problems.append(
                        "backend PCode snapshot events duplicate pcode_instruction "
                        f"{instr_id!r}"
                    )
                else:
                    instruction_ids.add(instr_id)
                block_id = event.get("block_id")
                if block_id not in block_ids:
                    problems.append(
                        f"line {lineno} pcode_instruction references missing block "
                        f"{block_id!r}"
                    )
                for key in ("order",):
                    if not isinstance(event.get(key), int):
                        problems.append(
                            f"line {lineno} pcode_instruction missing integer {key}"
                        )
                for key in ("pass_id", "pass_name", "opcode"):
                    if not isinstance(event.get(key), str) or not event.get(key):
                        problems.append(f"line {lineno} pcode_instruction missing {key}")

    if event_count == 0:
        problems.append("backend PCode snapshot events file is empty")
    if not function_start_seen:
        problems.append("backend PCode snapshot events missing function_start")
    missing_events = sorted(allowed_events - seen_events)
    if missing_events:
        problems.append(
            "backend PCode snapshot events missing required event families: "
            + ", ".join(missing_events)
        )
    if problems:
        raise RuntimeError("; ".join(problems))


def _run_backend_map_probe(
    *,
    src: str,
    fn: str,
    out_dir: Path,
    static_only: bool,
    melee_root: Path,
    instrumentation_table: Path | None = None,
) -> DumpOutcome:
    """Write static candidate evidence and optionally run a live map probe."""
    from tools.mwcc_retro import backend_discovery

    out_dir.mkdir(parents=True, exist_ok=True)
    _remove_backend_probe_stale_artifacts(out_dir)
    exe = melee_root / "build" / "compilers" / "GC" / "1.2.5n" / "mwcceppc.exe"
    report = backend_discovery.build_gc125n_backend_candidate_report(exe)
    candidate_payload = (
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _run_static_backend_map_audit(
        melee_root=melee_root,
        out_dir=out_dir,
        candidate_payload=candidate_payload,
    )

    if static_only:
        return DumpOutcome(exit_code=0, produced=["static"], missing=[])

    parity = _run_object_parity_for_backend(src=src, melee_root=melee_root)
    if not parity.get("matched"):
        raise RuntimeError(_format_parity_mismatch(parity))

    table = _retro_tables_dir(melee_root) / "gc_125n.json"
    if instrumentation_table is not None:
        table = instrumentation_table
    from tools.mwcc_retro.backend_runtime_instrumentation import (
        load_runtime_bundle,
    )

    bundle = load_runtime_bundle(table, exe)
    instrumentation = {
        "status": bundle.status,
        "compiler_sha256": bundle.compiler_sha256,
        "expected_site_ids": sorted(bundle.expected_site_ids),
    }
    hook = _retro_script("backend_map_probe_hook.py")
    outcome = _launch_dump(
        src=src,
        fn=fn,
        phases="backend",
        compiler="1.2.5n",
        out_dir=out_dir,
        table=table,
        melee_root=melee_root,
        gdb_py=str(hook),
        instrumentation=instrumentation,
    )
    if outcome.exit_code != 0:
        missing = f"\nmissing: {', '.join(outcome.missing)}" if outcome.missing else ""
        raise RuntimeError(
            f"backend map probe launcher failed (exit {outcome.exit_code})" + missing
        )
    probe_path = out_dir / "backend-map-probe.json"
    if not probe_path.exists():
        raise RuntimeError("backend map probe did not produce backend-map-probe.json")
    payload = _validate_backend_map_probe_payload(probe_path, fn=fn)
    from tools.mwcc_retro import backend_map_evidence

    evidence = backend_map_evidence.classify_probe_evidence(payload)
    (out_dir / "backend-map-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    )
    return outcome


def _load_transient_ghidra_inventory(*, melee_root: Path):
    """Validate the canonical project and consume one fresh temp export."""
    import subprocess
    import tempfile

    from tools.mwcc_retro.backend_lifetime_audit import (
        load_ghidra_inventory,
    )

    from src.mwcc_debug.ghidra_mwcc_setup import (
        EXPECTED_COMPILER_SHA256,
        PROGRAM_PATH,
        PROJECT_NAME,
    )

    project_dir = melee_root / "tools" / "mwcc_debug" / "ghidra_project"
    setup = setup_mwcc_ghidra(
        melee_root=melee_root,
        project_dir=project_dir,
        analysis_timeout=300,
        wall_timeout=420,
        repair=False,
    )
    if (
        setup.compiler_sha256 != EXPECTED_COMPILER_SHA256
        or setup.project_name != PROJECT_NAME
        or setup.program_path != PROGRAM_PATH
        or setup.project_dir.resolve() != project_dir.resolve()
    ):
        raise RuntimeError("validated Ghidra project identity differs")
    exporter = melee_root / "tools/mwcc_debug/scripts/ExportMwccRawCrosscheck.java"
    if not exporter.is_file():
        raise RuntimeError(f"missing Ghidra raw cross-check exporter: {exporter}")

    with tempfile.TemporaryDirectory(prefix="mwcc-ghidra-crosscheck-") as temporary:
        inventory_path = Path(temporary) / "inventory.jsonl"
        if inventory_path.exists():
            raise RuntimeError("fresh Ghidra inventory path unexpectedly exists")
        command = [
            str(setup.headless_path),
            str(setup.project_dir),
            setup.project_name,
            "-process",
            setup.program_path.removeprefix("/"),
            "-noanalysis",
            "-scriptPath",
            str(exporter.parent),
            "-postScript",
            exporter.name,
            EXPECTED_COMPILER_SHA256,
            str(inventory_path),
        ]
        try:
            process = _run_with_process_group_timeout(
                command,
                cwd=melee_root,
                timeout=420,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Ghidra raw cross-check export timed out") from exc
        combined = f"{process.stdout or ''}\n{process.stderr or ''}"
        lowered = combined.lower()
        if process.returncode != 0 or any(
            marker in lowered
            for marker in (
                "analysis timed out",
                "analysis cancelled",
                "analysis canceled",
                "processing cancelled",
                "processing canceled",
                "abort due to headless analyzer error",
            )
        ):
            raise RuntimeError(
                "Ghidra raw cross-check export failed: " + _tail(combined)
            )
        return load_ghidra_inventory(
            inventory_path,
            expected_sha256=EXPECTED_COMPILER_SHA256,
        )


def _run_static_backend_map_audit(
    *, melee_root: Path, out_dir: Path, candidate_payload: bytes
) -> object:
    """Recover and reconcile Task 4, then construct the closed Task 7 bundle."""
    from tools.mwcc_retro import (
        backend_abstract_values,
        backend_lifetime_audit,
        backend_lifetime_proof,
        backend_opcode_layout,
        pe,
        x86_cfg,
    )

    from src.mwcc_debug.ghidra_mwcc_setup import EXPECTED_COMPILER_SHA256

    compiler = (
        melee_root / "build/compilers/GC/1.2.5n/mwcceppc.exe"
    )
    image = pe.load(
        compiler,
        expected_sha256=EXPECTED_COMPILER_SHA256,
        require_pe32_i386=True,
    )
    format_anchor = x86_cfg.AuditAnchor(
        name="formatoperands",
        address=0x004C4BF0,
        instruction_bytes=b"\x53",
        evidence="retail-encoder-dispatch-bound",
    )
    seeds = x86_cfg.build_seed_inventory(image, (format_anchor,))
    static_started_at = time.monotonic()

    def report_static_progress(message: str) -> None:
        typer.echo(
            f"{message};elapsed_seconds="
            f"{time.monotonic() - static_started_at:.1f}",
            err=True,
        )

    cfg = x86_cfg.recover_cfg(
        image,
        seeds,
        x86_cfg.AnalysisLimits.for_image(image),
        producer_checkpoint_dir=(
            out_dir / ".producer-domain-checkpoints.v1"
        ),
        producer_query_budget=_STATIC_BACKEND_PRODUCER_QUERY_BUDGET,
        producer_progress_callback=report_static_progress,
    )
    format_dispatch = backend_lifetime_audit.validate_gc125n_formatoperands(
        image, cfg
    )
    inventory = _load_transient_ghidra_inventory(melee_root=melee_root)
    report = backend_lifetime_audit.compare_ghidra_inventory(cfg, inventory)
    report.require_no_raw_decode_conflicts()
    report.require_retained_regressions()
    report = replace(report, formatoperands_dispatch=format_dispatch)
    cfg = backend_lifetime_audit.accept_reconciled_residue(cfg, report)
    values = backend_abstract_values.analyze_values(
        image,
        cfg,
        cfg.control_targets,
    )
    lifetime_sites = backend_lifetime_audit.build_lifetime_site_inventory(
        image, cfg, values
    )
    opcode_layouts = backend_opcode_layout.analyze_opcode_layouts(
        image, cfg, values
    )
    if opcode_layouts.proof_ready and not opcode_layouts.unresolved:
        opcode_tables = backend_opcode_layout.build_opcode_proof_tables(
            opcode_layouts
        ).to_dict()
    else:
        opcode_tables = {"opcode_table": [], "operand_rules": []}
    proof_plan = backend_lifetime_proof.derive_exact_lifetime_proof_plan(
        cfg, lifetime_sites
    )
    candidate_table_path = (
        melee_root / "tools/mwcc_retro/tables/gc_125n.json"
    )
    if not candidate_table_path.is_file():
        raise RuntimeError(
            f"missing production-shape candidate table: {candidate_table_path}"
        )
    try:
        candidate_table = json.loads(candidate_table_path.read_bytes())
        backend_map_candidates = json.loads(candidate_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("static Task 7 input JSON is malformed") from exc
    exact_inputs = backend_lifetime_proof.ExactLifetimeBundleInputs(
        compiler_sha256=image.sha256,
        raw_cfg_jsonl=x86_cfg.canonical_jsonl_bytes(cfg),
        ghidra_crosscheck_json=(
            backend_lifetime_audit.crosscheck_json_bytes(report)
        ),
        value_analysis=values,
        lifetime_site_inventory=lifetime_sites,
        opcode_layout_inventory=opcode_layouts,
        opcode_tables=opcode_tables,
        proof_plan=proof_plan,
        candidate_table=candidate_table,
        backend_map_candidates=backend_map_candidates,
    )
    generated = backend_lifetime_proof.generate_exact_lifetime_bundle(
        exact_inputs, out_dir
    )
    if (
        generated.audit_summary.get("proof_ready") is not True
        or generated.publication is None
    ):
        unresolved = generated.audit_summary.get("unresolved_inputs", [])
        raise RuntimeError(
            "static Task 7 proof is not ready: "
            + ("; ".join(map(str, unresolved)) or "unresolved exact evidence")
        )
    return generated


def _launch_backend_ig_snapshot(
    *,
    src: str,
    fn: str,
    out_dir: Path,
    melee_root: Path,
) -> tuple[Path, Path]:
    from tools.mwcc_retro import setup as _setup
    from tools.mwcc_retro import struct_map

    _setup.ensure_for_root(melee_root, force=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "backend-ig-snapshot.json"
    events_path = out_dir / "backend-ig-snapshot-events.v1.jsonl"
    summary_path.unlink(missing_ok=True)
    events_path.unlink(missing_ok=True)

    table = _retro_tables_dir(melee_root) / "gc_125n.json"
    table_data = json.loads(table.read_text())
    map_errors = struct_map.validate_required_backend_map(table_data)
    if map_errors:
        raise RuntimeError(
            "backend IG snapshot requires validated 1.2.5n struct map: "
            + "; ".join(map_errors)
        )
    partial_errors = struct_map.validate_backend_ig_snapshot_capability(table_data)
    if partial_errors:
        raise RuntimeError(
            "backend IG snapshot requires internal colorgraph PCs and partial reader: "
            + "; ".join(partial_errors)
        )

    hook = _retro_script("backend_ig_snapshot_hook.py")
    outcome = _launch_dump(
        src=src,
        fn=fn,
        phases="backend",
        compiler="1.2.5n",
        out_dir=out_dir,
        table=table,
        melee_root=melee_root,
        gdb_py=str(hook),
    )
    if outcome.exit_code != 0:
        missing = f"\nmissing: {', '.join(outcome.missing)}" if outcome.missing else ""
        raise RuntimeError(
            f"backend IG snapshot launcher failed (exit {outcome.exit_code})" + missing
        )
    if not summary_path.exists():
        raise RuntimeError("backend IG snapshot did not produce backend-ig-snapshot.json")
    _validate_backend_ig_snapshot_payload(summary_path, fn=fn)
    if not events_path.exists() or events_path.stat().st_size == 0:
        raise RuntimeError(
            "backend IG snapshot did not produce backend-ig-snapshot-events.v1.jsonl"
        )
    _validate_backend_ig_snapshot_events(events_path, fn=fn)
    colorgraph_summary_path = out_dir / "backend-colorgraph-trace.json"
    if colorgraph_summary_path.exists():
        _validate_backend_colorgraph_trace_payload(colorgraph_summary_path, fn=fn)
    colorgraph_events_path = out_dir / "backend-colorgraph-decisions.v1.jsonl"
    if colorgraph_events_path.exists():
        _validate_backend_colorgraph_decision_events(colorgraph_events_path, fn=fn)
    (out_dir / "launch.log").unlink(missing_ok=True)
    return summary_path, events_path


def _run_backend_ig_snapshot(
    *,
    src: str,
    fn: str,
    out_dir: Path,
    melee_root: Path,
) -> BackendIgSnapshotOutcome:
    out_dir.mkdir(parents=True, exist_ok=True)
    _remove_backend_probe_stale_artifacts(out_dir)
    parity = _run_object_parity_for_backend(src=src, melee_root=melee_root)
    if not parity.get("matched"):
        raise RuntimeError(_format_parity_mismatch(parity))
    summary_path, events_path = _launch_backend_ig_snapshot(
        src=src,
        fn=fn,
        out_dir=out_dir,
        melee_root=melee_root,
    )
    return BackendIgSnapshotOutcome(
        exit_code=0,
        summary_path=summary_path,
        events_path=events_path,
    )


def _launch_backend_pcode_snapshot(
    *,
    src: str,
    fn: str,
    out_dir: Path,
    melee_root: Path,
    instrumentation_table: Path | None = None,
) -> tuple[Path, Path]:
    from tools.mwcc_retro import setup as _setup
    from tools.mwcc_retro import struct_map

    _setup.ensure_for_root(melee_root, force=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "backend-pcode-snapshot.json"
    events_path = out_dir / "backend-pcode-snapshot-events.v1.jsonl"
    summary_path.unlink(missing_ok=True)
    events_path.unlink(missing_ok=True)

    table = (
        instrumentation_table
        if instrumentation_table is not None
        else _retro_tables_dir(melee_root) / "gc_125n.json"
    )
    table_data = json.loads(table.read_text())
    map_errors = struct_map.validate_required_backend_map(table_data)
    if map_errors:
        raise RuntimeError(
            "backend PCode snapshot requires validated 1.2.5n struct map: "
            + "; ".join(map_errors)
        )
    partial_errors = struct_map.validate_backend_pcode_snapshot_capability(table_data)
    if partial_errors:
        raise RuntimeError(
            "backend PCode snapshot requires partial reader: "
            + "; ".join(partial_errors)
        )

    instrumentation = None
    if instrumentation_table is not None:
        from tools.mwcc_retro.backend_runtime_instrumentation import (
            load_runtime_bundle,
        )

        compiler_exe = (
            melee_root
            / "build"
            / "compilers"
            / "GC"
            / "1.2.5n"
            / "mwcceppc.exe"
        )
        bundle = load_runtime_bundle(table, compiler_exe)
        instrumentation = {
            "status": bundle.status,
            "compiler_sha256": bundle.compiler_sha256,
            "expected_site_ids": sorted(bundle.expected_site_ids),
        }
    hook = _retro_script("backend_pcode_snapshot_hook.py")
    outcome = _launch_dump(
        src=src,
        fn=fn,
        phases="backend",
        compiler="1.2.5n",
        out_dir=out_dir,
        table=table,
        melee_root=melee_root,
        gdb_py=str(hook),
        instrumentation=instrumentation,
    )
    if outcome.exit_code != 0:
        missing = f"\nmissing: {', '.join(outcome.missing)}" if outcome.missing else ""
        raise RuntimeError(
            f"backend PCode snapshot launcher failed (exit {outcome.exit_code})"
            + missing
        )
    if not summary_path.exists():
        raise RuntimeError(
            "backend PCode snapshot did not produce backend-pcode-snapshot.json"
        )
    _validate_backend_pcode_snapshot_payload(summary_path, fn=fn)
    if not events_path.exists() or events_path.stat().st_size == 0:
        raise RuntimeError(
            "backend PCode snapshot did not produce "
            "backend-pcode-snapshot-events.v1.jsonl"
        )
    _validate_backend_pcode_snapshot_events(events_path, fn=fn)
    (out_dir / "launch.log").unlink(missing_ok=True)
    return summary_path, events_path


def _run_backend_pcode_snapshot(
    *,
    src: str,
    fn: str,
    out_dir: Path,
    melee_root: Path,
    instrumentation_table: Path | None = None,
) -> BackendPcodeSnapshotOutcome:
    out_dir.mkdir(parents=True, exist_ok=True)
    _remove_backend_probe_stale_artifacts(out_dir)
    candidate_object = out_dir / "candidate.o"
    parity = _run_object_parity_for_backend(
        src=src,
        melee_root=melee_root,
        retain_object=(candidate_object if instrumentation_table else None),
    )
    if not parity.get("matched"):
        raise RuntimeError(_format_parity_mismatch(parity))
    summary_path, events_path = _launch_backend_pcode_snapshot(
        src=src,
        fn=fn,
        out_dir=out_dir,
        melee_root=melee_root,
        instrumentation_table=instrumentation_table,
    )
    if instrumentation_table is not None:
        from tools.mwcc_retro.backend_instrumentation_proof import (
            InstrumentationProof,
            proof_sha256,
        )
        from tools.mwcc_retro.backend_pcode_lineage import (
            validate_pcode_lineage,
        )
        from tools.mwcc_retro.backend_runtime_instrumentation import (
            load_runtime_bundle,
        )

        compiler = (
            melee_root
            / "build"
            / "compilers"
            / "GC"
            / "1.2.5n"
            / "mwcceppc.exe"
        )
        bundle = load_runtime_bundle(instrumentation_table, compiler)
        if not bundle.validated or bundle.proof is None:
            raise RuntimeError(
                "proof-bound PCode probe requires a validated runtime bundle"
            )
        runtime_status = json.loads(summary_path.read_text()).get(
            "runtime_instrumentation"
        )
        if not isinstance(runtime_status, dict):
            raise RuntimeError("PCode probe has no runtime instrumentation status")
        lineage_payload = backend_trace_assembler.assemble_pcode_lineage_payload(
            snapshot_events=backend_events.load_events(events_path),
            runtime_status=runtime_status,
            proof=bundle.proof,
            function=fn,
            candidate_object=candidate_object,
        )
        proof = InstrumentationProof(
            str(bundle.proof["proof_id"]),
            bundle.compiler_sha256,
            bundle.proof,
            proof_sha256(bundle.proof),
        )
        validation = validate_pcode_lineage(
            lineage_payload,
            proof,
            candidate_object,
            fn,
            promotion_registry=bundle.table,
        )
        if validation.errors:
            raise RuntimeError(
                "proof-bound PCode lineage validation failed: "
                + "; ".join(validation.errors)
            )
        (out_dir / "backend-pcode-lineage.v1.json").write_text(
            json.dumps(
                lineage_payload,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
    return BackendPcodeSnapshotOutcome(
        exit_code=0,
        summary_path=summary_path,
        events_path=events_path,
    )


def _run_backend_candidate_trace(
    *,
    src: str,
    fn: str,
    out_dir: Path,
    melee_root: Path,
    one_pass: bool = False,
) -> BackendCandidateOutcome:
    if one_pass:
        return _run_backend_onepass_candidate_trace(
            src=src,
            fn=fn,
            out_dir=out_dir,
            melee_root=melee_root,
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    _remove_backend_probe_stale_artifacts(out_dir)
    map_dir = out_dir / "map"
    pcode_dir = out_dir / "pcode"
    ig_dir = out_dir / "ig"

    _run_backend_map_probe(
        src=src,
        fn=fn,
        out_dir=map_dir,
        static_only=False,
        melee_root=melee_root,
    )
    pcode = _run_backend_pcode_snapshot(
        src=src,
        fn=fn,
        out_dir=pcode_dir,
        melee_root=melee_root,
    )
    ig = _run_backend_ig_snapshot(
        src=src,
        fn=fn,
        out_dir=ig_dir,
        melee_root=melee_root,
    )

    map_probe_path = map_dir / "backend-map-probe.json"
    if not map_probe_path.exists():
        raise RuntimeError("backend candidate missing map/backend-map-probe.json")
    if pcode.events_path is None or not pcode.events_path.exists():
        raise RuntimeError("backend candidate missing PCode events")
    if ig.events_path is None or not ig.events_path.exists():
        raise RuntimeError("backend candidate missing IG events")
    colorgraph_events_path = ig_dir / "backend-colorgraph-decisions.v1.jsonl"
    if not colorgraph_events_path.exists():
        raise RuntimeError("backend candidate missing colorgraph decision events")

    frame_events = backend_trace_assembler.frame_events_from_map_probe_payload(
        json.loads(map_probe_path.read_text())
    )
    pcode_events = backend_events.load_events(pcode.events_path)
    ig_events = backend_events.load_events(ig.events_path)
    colorgraph_events = backend_events.load_events(colorgraph_events_path)
    trace = backend_trace_assembler.assemble_candidate_trace(
        pcode_events=pcode_events,
        ig_events=ig_events,
        frame_events=frame_events,
        colorgraph_events=colorgraph_events,
        compiler={"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
        source=_backend_source_metadata(src=src, fn=fn, melee_root=melee_root),
        tool_version="mwcc-retro-candidate",
    )
    _write_backend_candidate_outputs(out_dir, trace)
    return BackendCandidateOutcome(
        exit_code=0,
        trace=trace,
        map_dir=map_dir,
        pcode_dir=pcode_dir,
        ig_dir=ig_dir,
    )


def _run_backend_onepass_candidate_trace(
    *,
    src: str,
    fn: str,
    out_dir: Path,
    melee_root: Path,
) -> BackendCandidateOutcome:
    from tools.mwcc_retro import struct_map

    out_dir.mkdir(parents=True, exist_ok=True)
    _remove_backend_probe_stale_artifacts(out_dir)

    parity = _run_object_parity_for_backend(src=src, melee_root=melee_root)
    if not parity.get("matched"):
        raise RuntimeError(_format_parity_mismatch(parity))

    table = _retro_tables_dir(melee_root) / "gc_125n.json"
    table_data = json.loads(table.read_text())
    map_errors = struct_map.validate_required_backend_map(table_data)
    if map_errors:
        raise RuntimeError(
            "backend one-pass candidate requires validated 1.2.5n struct map: "
            + "; ".join(map_errors)
        )
    pcode_errors = struct_map.validate_backend_pcode_snapshot_capability(table_data)
    ig_errors = struct_map.validate_backend_ig_snapshot_capability(table_data)
    if pcode_errors or ig_errors:
        raise RuntimeError(
            "backend one-pass candidate requires partial PCode and IG readers: "
            + "; ".join([*pcode_errors, *ig_errors])
        )

    hook = _retro_script("backend_onepass_trace_hook.py")
    outcome = _launch_dump(
        src=src,
        fn=fn,
        phases="backend",
        compiler="1.2.5n",
        out_dir=out_dir,
        table=table,
        melee_root=melee_root,
        gdb_py=str(hook),
    )
    if outcome.exit_code != 0:
        missing = f"\nmissing: {', '.join(outcome.missing)}" if outcome.missing else ""
        raise RuntimeError(
            f"backend one-pass candidate launcher failed (exit {outcome.exit_code})"
            + missing
        )

    events_path = out_dir / "backend-events.v1.jsonl"
    if not events_path.exists() or events_path.stat().st_size == 0:
        raise RuntimeError(
            "backend one-pass candidate did not produce backend-events.v1.jsonl"
        )
    _validate_onepass_candidate_summary(out_dir, fn=fn)
    try:
        events = backend_events.load_events(events_path)
        _validate_onepass_event_function_start(events, fn=fn)
        trace = backend_events.normalize_events(
            events,
            compiler={"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
            source=_backend_source_metadata(src=src, fn=fn, melee_root=melee_root),
            tool_version="mwcc-retro-candidate-one-pass",
        )
    except ValueError as exc:
        raise RuntimeError(
            f"backend one-pass candidate normalization failed: {exc}"
        ) from exc
    _write_backend_candidate_outputs(out_dir, trace)
    return BackendCandidateOutcome(exit_code=0, trace=trace)


def _compare_backend_trace_with_debug_pcdump(
    *,
    trace: dict,
    src: str,
    fn: str,
    melee_root: Path,
) -> dict:
    import importlib

    from tools.mwcc_retro import backend_fidelity

    debug_cli = importlib.import_module("src.cli.debug")
    pcdump_path = debug_cli._resolve_pcdump_path(
        None,
        fn,
        melee_root,
        require_fresh=False,
    )
    debug_trace = backend_fidelity.trace_from_mwcc_debug_pcdump(
        pcdump_path.read_text(encoding="utf-8"),
        function=fn,
        source=src,
    )
    return backend_fidelity.compare_backend_traces(trace, debug_trace)


def _validate_onepass_candidate_summary(out_dir: Path, *, fn: str) -> None:
    summary_path = out_dir / "backend-onepass-candidate.json"
    if not summary_path.exists():
        raise RuntimeError("backend one-pass candidate missing backend-onepass-candidate.json")
    try:
        payload = json.loads(summary_path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"backend one-pass candidate summary invalid JSON: {exc}"
        ) from exc

    requested_function = payload.get("requested_function")
    if requested_function != fn:
        raise RuntimeError(
            "backend one-pass candidate requested_function mismatch: "
            f"{requested_function!r} != {fn!r}"
        )

    if payload.get("requested_function_matched") is not True:
        raise RuntimeError("backend one-pass candidate did not match requested function")

    errors = payload.get("errors") or []
    if errors:
        detail = "; ".join(
            error.get("error", str(error)) if isinstance(error, dict) else str(error)
            for error in errors
        )
        raise RuntimeError(f"backend one-pass candidate hook errors: {detail}")

    classes_seen = payload.get("classes_seen")
    if not isinstance(classes_seen, list) or not classes_seen:
        raise RuntimeError("backend one-pass candidate saw no allocator classes")

    for cls in classes_seen:
        if not isinstance(cls, dict):
            raise RuntimeError("backend one-pass candidate class summary must be object")
        class_name = cls.get("class_name", cls.get("class_id", "<unknown>"))
        order_nodes = cls.get("order_nodes")
        exact_decisions = cls.get("exact_color_decisions")
        if not isinstance(order_nodes, int) or not isinstance(exact_decisions, int):
            raise RuntimeError(
                f"backend one-pass candidate class {class_name} missing decision counts"
            )
        if exact_decisions != order_nodes:
            raise RuntimeError(
                "one-pass candidate missing exact color decisions for "
                f"{class_name}: {exact_decisions}/{order_nodes}"
            )


def _function_start_names(event: dict) -> set[str]:
    names: set[str] = set()
    name = event.get("name")
    if isinstance(name, str):
        names.add(name)
    identity = event.get("identity")
    if isinstance(identity, dict):
        for key in ("requested", "canonical_name", "symbol_name", "source_name"):
            value = identity.get(key)
            if isinstance(value, str):
                names.add(value)
        aliases = identity.get("aliases")
        if isinstance(aliases, list):
            names.update(alias for alias in aliases if isinstance(alias, str))
    return names


def _validate_onepass_event_function_start(events: list[dict], *, fn: str) -> None:
    starts = [event for event in events if event.get("event") == "function_start"]
    if not starts:
        raise RuntimeError("backend one-pass candidate events missing function_start")
    for event in starts:
        names = _function_start_names(event)
        if fn not in names:
            name = event.get("name")
            raise RuntimeError(
                "backend one-pass candidate event function_start mismatch: "
                f"{name!r} does not identify {fn!r}"
            )


def _promote_onepass_summary_for_full_backend(out_dir: Path) -> None:
    raw_path = out_dir / "backend-onepass-candidate.json"
    public_path = out_dir / "backend-onepass-summary.json"
    if not raw_path.exists():
        return
    payload = json.loads(raw_path.read_text())
    payload["schema_version"] = "mwcc-retro-backend-onepass-summary.v1"
    payload["source_sidecar"] = raw_path.name
    payload["notes"] = [
        "Retail GC/1.2.5n backend event stream.",
        "Validated before assembling backend-trace.v1.json.",
    ]
    public_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    raw_path.unlink()


def _run_backend_trace(
    *,
    src: str,
    fn: str,
    out_dir: Path,
    verify_debug: bool,
    melee_root: Path,
) -> BackendOutcome:
    parity = _run_object_parity_for_backend(src=src, melee_root=melee_root)
    if not parity.get("matched"):
        raise RuntimeError(_format_parity_mismatch(parity))
    try:
        events_path = _launch_backend_events(
            src=src,
            fn=fn,
            out_dir=out_dir,
            melee_root=melee_root,
        )
    except RuntimeError:
        raise
    try:
        events = backend_events.load_events(events_path)
        trace = backend_events.normalize_events(
            events,
            compiler={"family": "MWCC", "version": "GC/1.2.5n", "retail": True},
            source=_backend_source_metadata(src=src, fn=fn, melee_root=melee_root),
            tool_version="mwcc-retro-dev",
        )
    except ValueError as exc:
        raise RuntimeError(f"backend event normalization failed: {exc}") from exc
    fidelity = None
    if verify_debug:
        fidelity = _compare_backend_trace_with_debug_pcdump(
            trace=trace,
            src=src,
            fn=fn,
            melee_root=melee_root,
        )
    return BackendOutcome(exit_code=0, trace=trace, fidelity=fidelity)


def _backend_trace_function_names(trace: dict) -> set[str]:
    names: set[str] = set()
    source = trace.get("source")
    if isinstance(source, dict) and isinstance(source.get("function"), str):
        names.add(source["function"])
    functions = trace.get("functions")
    if isinstance(functions, list):
        for function in functions:
            if not isinstance(function, dict):
                continue
            if isinstance(function.get("name"), str):
                names.add(function["name"])
            identity = function.get("identity")
            if isinstance(identity, dict):
                for key in ("requested", "canonical_name", "symbol_name", "source_name"):
                    if isinstance(identity.get(key), str):
                        names.add(identity[key])
                aliases = identity.get("aliases")
                if isinstance(aliases, list):
                    names.update(alias for alias in aliases if isinstance(alias, str))
    return names


def _validate_backend_trace_matches_function(trace: dict, fn: str) -> None:
    names = _backend_trace_function_names(trace)
    if fn not in names:
        available = ", ".join(sorted(names)) or "<none>"
        raise ValueError(
            f"backend trace function mismatch: requested {fn}; trace contains {available}"
        )


def _resolve_backend_trace_for_verify(
    trace_path: Path | None,
    *,
    out_dir: Path,
) -> Path:
    if trace_path is not None:
        return trace_path
    full_trace = out_dir / "backend-trace.v1.json"
    if full_trace.exists():
        return full_trace
    candidate_trace = out_dir / "backend-trace.candidate.v1.json"
    if candidate_trace.exists():
        return candidate_trace
    return full_trace


def _ninja_cmd_for_unit(src_rel: str, *, melee_root: Path) -> str:
    """The mwcceppc command line for a unit, WITHOUT wibo/sjiswrap prefix."""
    from src.cli.debug import _ninja_cflags_for_unit
    cflags, _mw = _ninja_cflags_for_unit(src_rel, melee_root=melee_root)
    unit = src_rel
    obj = f"build/GALE01/{Path(src_rel).with_suffix('.o')}"
    compiler = "build/compilers/GC/1.2.5n/mwcceppc.exe"
    return f"{compiler} {cflags} -c {unit} -o {obj}"


def _stream_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _backend_source_metadata(*, src: str, fn: str, melee_root: Path) -> dict:
    import hashlib

    mwcc_command = _ninja_cmd_for_unit(src, melee_root=melee_root)
    return {
        "tu": src,
        "function": fn,
        "mwcc_command": mwcc_command,
        "mwcc_command_hash": "sha256:"
        + hashlib.sha256(mwcc_command.encode()).hexdigest(),
    }


def _launch_dump(*, src: str, fn: str, phases: str, compiler: str,
                 out_dir: Path, table: Path, melee_root: Path,
                 gdb_py: str = "",
                 instrumentation: dict | None = None,
                 timeout: int = RETRO_DUMP_TIMEOUT_SECONDS) -> DumpOutcome:
    """Invoke the gdb-side launcher, then post-process the IRO trace.

    Runs `mwcc_retro_debugger.py main()` (host launcher), which drives
    retrowin32 + gdb to write `iro-trace.txt`. On success, splits the trace into
    per-phase files and builds `iro-summary.txt` (the node/temp ledger). Returns
    a DumpOutcome whose exit code follows the contract in the spec. When `gdb_py`
    is set, the gdb session is handed to that intervention hook instead.
    """
    import subprocess

    from tools.mwcc_retro import setup as _setup
    from tools.mwcc_retro import trace_summary

    if hasattr(_setup, "ensure_for_root"):
        res = _setup.ensure_for_root(melee_root, force=False)
    else:
        res = _setup.ensure(force=False)
    mwcc_dir = melee_root / "build" / "compilers" / "GC" / compiler
    mwcc_args = _ninja_cmd_for_unit(src, melee_root=melee_root)
    # strip the leading compiler path; the launcher prepends the emulator.
    mwcc_args = mwcc_args.split(" ", 1)[1] if " " in mwcc_args else mwcc_args
    mwcc_exe = str(mwcc_dir / "mwcceppc.exe")
    launcher = _retro_script("mwcc_retro_debugger.py")
    cmd = [
        "python3", str(launcher),
        "-e", str(res.retrowin32_bin),
        "-a", f"{mwcc_exe} {mwcc_args}",
        "--table", str(table),
        "--out", str(out_dir),
        "--phases", phases,
        "--compiler", compiler,
    ]
    if gdb_py:
        cmd += ["--gdb-py", str(Path(gdb_py).resolve())]
    cmd.append(fn)
    # Run from the active repo root so the emulated mwcceppc resolves the relative
    # source path (the ninja command uses repo-relative paths, like wibo does).
    out_dir.mkdir(parents=True, exist_ok=True)
    if phases in ("backend", "all"):
        _remove_backend_dump_text_artifacts(out_dir)
    env = _retro_subprocess_env(
        RETRO_SOURCE=src,
        RETRO_FUNCTION=fn,
        RETRO_FUNCTION_ALIASES=_backend_function_aliases_json(fn, melee_root=melee_root),
    )
    if instrumentation:
        instr_path = out_dir / "instrumentation.json"
        instr_path.write_text(json.dumps(instrumentation))
        env["RETRO_INSTRUMENTATION"] = str(instr_path)
    log = out_dir / "launch.log"
    command_text = shlex.join([str(part) for part in cmd])

    def write_launch_log(
        *,
        status: str,
        exit_text: str | None = None,
        stdout: object = "",
        stderr: object = "",
    ) -> None:
        lines = [
            f"STATUS: {status}",
            f"RETRO_SOURCE: {src}",
            f"RETRO_FUNCTION: {fn}",
            f"RETRO_OUTPUT_DIR: {out_dir}",
            f"TIMEOUT_SECONDS: {timeout}",
            f"COMMAND: {command_text}",
        ]
        if exit_text is not None:
            lines.extend(
                [
                    f"EXIT: {exit_text}",
                    "STDOUT:",
                    _stream_text(stdout),
                    "--- stderr ---",
                    _stream_text(stderr),
                ]
            )
        log.write_text("\n".join(lines) + "\n")

    write_launch_log(status="running")
    try:
        proc = _run_with_process_group_timeout(
            cmd,
            cwd=melee_root,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        write_launch_log(
            status="timed out",
            exit_text=f"timeout after {timeout}s",
            stdout=exc.output,
            stderr=(
                _stream_text(exc.stderr)
                + f"\n[retro] launcher timed out after {timeout}s; "
                "killed process group"
            ),
        )
        return DumpOutcome(exit_code=2, produced=[], missing=["timeout"])
    write_launch_log(
        status="exited",
        exit_text=str(proc.returncode),
        stdout=proc.stdout,
        stderr=proc.stderr,
    )

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    safety_aborted = "[retro] ABORT" in combined
    if safety_aborted:
        if gdb_py:
            missing = ["hook"]
        elif phases == "frontend":
            missing = ["frontend"]
        else:
            missing = ["backend"]
        return DumpOutcome(exit_code=5, produced=[], missing=missing)

    if gdb_py:
        # The hook owns the session; trace/backend post-processing doesn't apply.
        ran = "[retro] running intervention hook" in proc.stdout
        if ran and proc.returncode == 0:
            return DumpOutcome(exit_code=0, produced=["hook"], missing=[])
        return DumpOutcome(exit_code=2, produced=[], missing=["hook"])

    if proc.returncode != 0:
        missing = []
        if phases in ("frontend", "all"):
            missing.append("frontend")
        if phases in ("backend", "all"):
            missing.append("backend")
        return DumpOutcome(exit_code=2, produced=[], missing=missing)

    produced: list[str] = []
    missing: list[str] = []
    target_absent = False  # set by the host-side trace filter below
    trace = out_dir / "iro-trace.txt"
    if phases in ("frontend", "all"):
        if trace.exists() and trace.stat().st_size > 0:
            # Dumps are enabled globally (all functions); isolate the target's
            # section host-side (robust per-function scoping, #546).
            full = trace.read_text(errors="replace")
            text = trace_summary.filter_to_function(full, fn)
            if text and f"Dumping function {fn} after" in text:
                trace.write_text(text)  # iro-trace.txt = target only
                trace_summary.split_phase_files(text, out_dir)
                (out_dir / "iro-summary.txt").write_text(
                    trace_summary.build_summary(text))
                produced.append("frontend")
            else:
                # trace produced but no section for the target fn -> not found
                target_absent = True
                missing.append("frontend")
        else:
            missing.append("frontend")

    if phases in ("backend", "all"):
        # cadmic writes backend/regalloc/variables files straight into out_dir.
        backend_files = (list(out_dir.glob("backend-*.txt"))
                         + list(out_dir.glob("regalloc-*.txt")))
        if backend_files:
            produced.append("backend")
        elif phases == "backend":
            missing.append("backend")

    if target_absent and not produced:
        return DumpOutcome(exit_code=3, produced=produced, missing=missing)
    if missing:
        return DumpOutcome(exit_code=4, produced=produced, missing=missing)
    return DumpOutcome(exit_code=0, produced=produced, missing=missing)


def _write_backend_source_attribution(
    *,
    out_dir: Path,
    src: str,
    fn: str,
    compiler: str,
    missing: list[str],
    melee_root: Path,
) -> Path | None:
    """Write a source-attribution sidecar when 1.2.5n backend streams are absent."""
    if compiler != "1.2.5n" or "backend" not in missing:
        return None

    payload: dict = {
        "status": "backend-trace-unavailable",
        "function": fn,
        "source": src,
        "compiler": compiler,
        "reason": (
            "the requested dump did not produce retail GC/1.2.5n backend/regalloc traces; "
            "this sidecar uses mwcc-debug pcdump source attribution as the "
            "actionable fallback instead of fabricating backend decisions"
        ),
        "source_attribution": [],
        "next_commands": [
            f"melee-agent debug dump local {src} --function {fn}",
            f"melee-agent debug retro backend {src} --function {fn}",
            f"melee-agent debug inspect explain-virtual --function {fn} --virtual <ig>",
        ],
    }

    try:
        import importlib

        debug_cli = importlib.import_module("src.cli.debug")
        from src.mwcc_debug.colorgraph_parser import (
            find_function,
            parse_hook_events,
        )
        from src.mwcc_debug.virtual_attribution import explain_virtuals

        pcdump_path = debug_cli._resolve_pcdump_path(
            None,
            fn,
            melee_root,
            require_fresh=False,
        )
        pcdump_text = pcdump_path.read_text(encoding="utf-8")
        source_path = melee_root / src
        source_text = (
            source_path.read_text(encoding="utf-8")
            if source_path.exists() else ""
        )
        events = find_function(parse_hook_events(pcdump_text), fn)
        if events is None or not events.colorgraph_sections:
            payload["status"] = "pcdump-no-colorgraph"
            payload["pcdump"] = str(pcdump_path)
            payload["reason"] = (
                "cached pcdump resolved, but it has no COLORGRAPH DECISIONS "
                "for backend source attribution"
            )
        else:
            payload["pcdump"] = str(pcdump_path)
            classes = []
            for section in events.colorgraph_sections:
                virtuals = sorted({
                    decision.ig_idx
                    for decision in section.decisions
                    if decision.ig_idx >= 0
                })
                if not virtuals:
                    continue
                report = explain_virtuals(
                    pcdump_text,
                    fn,
                    virtuals=virtuals,
                    source_text=source_text,
                    source_file=str(source_path),
                    reg_class="fp" if section.class_id == 1 else "gpr",
                )
                classes.append({
                    "class_id": section.class_id,
                    "virtual_count": len(virtuals),
                    "virtuals": report.to_dict()["virtuals"],
                })
            payload["source_attribution"] = classes
    except Exception as exc:
        payload["status"] = "pcdump-unavailable"
        payload["reason"] = (
            "backend trace unavailable and mwcc-debug pcdump attribution "
            f"could not be resolved: {exc}"
        )

    out_path = out_dir / "backend-source-attribution.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return out_path


@retro_app.command("setup")
def setup_cmd(force: bool = typer.Option(False, "--force")):
    """Clone + build retrowin32 and cadmic at pinned SHAs (idempotent)."""
    try:
        res = retro_setup.ensure(force=force)
    except retro_setup.SetupError as e:
        typer.secho(f"setup failed: {e}", fg="red", err=True)
        raise typer.Exit(1)
    typer.echo(f"retrowin32: {res.retrowin32_bin}")
    typer.echo(f"cadmic:     {res.cadmic_script}")
    typer.echo(f"rebuilt:    {res.rebuilt}")


@retro_app.command("ghidra-setup")
def ghidra_setup_cmd(
    project_dir: Path = typer.Option(
        Path("tools/mwcc_debug/ghidra_project"),
        "--project-dir",
        help="MWCC Ghidra project directory; relative paths use the Melee root.",
    ),
    analysis_timeout: int = typer.Option(
        300,
        "--analysis-timeout",
        min=1,
        help="Ghidra per-file analysis timeout in seconds.",
    ),
    wall_timeout: int = typer.Option(
        420,
        "--wall-timeout",
        min=1,
        help="Outer process-group wall timeout in seconds.",
    ),
    repair: bool = typer.Option(
        False,
        "--repair",
        help="Retain and quarantine an invalid canonical project before importing.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit stable result JSON."),
    melee_root: Path | None = typer.Option(
        None,
        "--melee-root",
        help="Active Melee checkout/worktree root. Defaults to the current cwd tree.",
    ),
):
    """Create or validate the exact GC/1.2.5n compiler Ghidra audit project."""
    from src.mwcc_debug.ghidra_mwcc_setup import MwccGhidraSetupError

    active_root = _resolve_melee_root(melee_root)
    expanded_project = project_dir.expanduser()
    resolved_project = (
        expanded_project.resolve()
        if expanded_project.is_absolute()
        else (active_root / expanded_project).resolve()
    )
    try:
        result = setup_mwcc_ghidra(
            melee_root=active_root,
            project_dir=resolved_project,
            analysis_timeout=analysis_timeout,
            wall_timeout=wall_timeout,
            repair=repair,
        )
    except MwccGhidraSetupError as error:
        typer.secho(f"ghidra setup failed: {error.reason}", fg="red", err=True)
        if error.details:
            typer.echo(json.dumps(error.details, sort_keys=True, default=str), err=True)
        if error.reason == "invalid-existing-project":
            retry = shlex.join(
                [
                    "melee-agent",
                    "debug",
                    "retro",
                    "ghidra-setup",
                    "--repair",
                    "--melee-root",
                    str(active_root),
                    "--project-dir",
                    str(resolved_project),
                    "--analysis-timeout",
                    str(analysis_timeout),
                    "--wall-timeout",
                    str(wall_timeout),
                ]
            )
            typer.echo(f"Retry: {retry}", err=True)
        raise typer.Exit(4)

    if json_output:
        typer.echo(json.dumps(result.to_dict(), sort_keys=True))
        return

    typer.echo(f"status: {result.status}")
    typer.echo(f"compiler SHA-256: {result.compiler_sha256}")
    typer.echo(f"function count: {result.function_count}")
    typer.echo(f"project: {result.project_dir}")
    typer.echo(f"program: {result.program_path}")
    typer.echo(f"Ghidra: {result.ghidra_install}")
    typer.echo(f"headless: {result.headless_path}")
    typer.echo(f"native decompiler: {result.native_decompiler_path or 'not required'}")
    typer.echo(f"elapsed seconds: {result.elapsed_seconds}")
    if result.quarantined_paths:
        typer.echo("quarantine paths:")
        for path in result.quarantined_paths:
            typer.echo(f"  {path}")
    else:
        typer.echo("quarantine paths: none")


@retro_app.command("dump")
def dump_cmd(
    src: str = typer.Argument(..., help="TU source path, e.g. src/melee/mn/mnvibration.c"),
    fn: str = typer.Option(..., "-f", "--function"),
    phases: str = typer.Option("all", "--phases", help="all|frontend|backend"),
    compiler: str = typer.Option("1.2.5n", "--compiler", help="1.2.5n|1.1"),
    out: Path = typer.Option(None, "-O", "--output"),
    melee_root: Path = typer.Option(
        None,
        "--melee-root",
        help="Active Melee checkout/worktree root. Defaults to the current cwd tree.",
    ),
    gdb_py: Path = typer.Option(
        None, "--gdb-py",
        help="Intervention hook (a .py with intervene(ctx)) handed the connected "
             "gdb session to mutate compiler state and replay forward."),
    timeout: int = typer.Option(
        RETRO_DUMP_TIMEOUT_SECONDS,
        "--timeout",
        min=1,
        help="Seconds to wait for the retrowin32+gdb launcher before killing "
             "the whole subprocess tree.",
    ),
):
    """Dump retail compiler internals for FN in SRC."""
    if phases not in ("all", "frontend", "backend"):
        typer.secho("invalid --phases", fg="red", err=True)
        raise typer.Exit(2)
    if gdb_py is not None and not gdb_py.is_file():
        typer.secho(f"--gdb-py hook not found: {gdb_py}", fg="red", err=True)
        raise typer.Exit(2)
    active_root = _resolve_melee_root(melee_root)
    _ensure_setup(active_root)
    out_dir = _resolve_output_dir(out, melee_root=active_root, src=src, fn=fn)
    out_dir.mkdir(parents=True, exist_ok=True)
    table = _retro_tables_dir(active_root) / (
        "gc_125n.json" if compiler == "1.2.5n" else "gc_11.json"
    )
    if compiler == "1.2.5n" and phases == "backend" and gdb_py is None:
        try:
            backend_outcome = _run_backend_trace(
                src=src,
                fn=fn,
                out_dir=out_dir,
                verify_debug=False,
                melee_root=active_root,
            )
            if backend_outcome.trace is not None:
                _write_backend_outputs(out_dir, backend_outcome.trace, backend_outcome.fidelity)
                if backend_outcome.exit_code == 0:
                    _validate_backend_outputs(out_dir)
        except RuntimeError as exc:
            typer.secho(str(exc), fg="red", err=True)
            raise typer.Exit(2)
        outcome = DumpOutcome(
            exit_code=backend_outcome.exit_code,
            produced=["backend"] if backend_outcome.trace is not None else [],
            missing=backend_outcome.missing,
        )
        _write_provenance(out_dir, src, fn, compiler, table, outcome, active_root)
        raise typer.Exit(outcome.exit_code)

    outcome = _launch_dump(src=src, fn=fn, phases=phases, compiler=compiler,
                           out_dir=out_dir, table=table, melee_root=active_root,
                           gdb_py=str(gdb_py) if gdb_py else "",
                           timeout=timeout)
    attribution_path = _write_backend_source_attribution(
        out_dir=out_dir,
        src=src,
        fn=fn,
        compiler=compiler,
        missing=outcome.missing,
        melee_root=active_root,
    )
    _write_provenance(out_dir, src, fn, compiler, table, outcome, active_root)
    if attribution_path is not None:
        typer.echo(f"backend source attribution: {attribution_path}")
    if outcome.missing:
        typer.secho(f"missing phase streams: {outcome.missing}", fg="yellow", err=True)
    raise typer.Exit(outcome.exit_code)


@retro_app.command("backend")
def backend_cmd(
    src: str = typer.Argument(..., help="TU source path, e.g. src/melee/mn/mndiagram.c"),
    fn: str = typer.Option(..., "-f", "--function"),
    out: Path = typer.Option(None, "-O", "--output"),
    melee_root: Path = typer.Option(
        None,
        "--melee-root",
        help="Active Melee checkout/worktree root. Defaults to the current cwd tree.",
    ),
    verify_debug: bool = typer.Option(
        False,
        "--verify-debug",
        help="Also compare the retail backend trace to the mwcc-debug pcdump.",
    ),
):
    """Gated retail GC/1.2.5n backend/regalloc trace command."""
    active_root = _resolve_melee_root(melee_root)
    out_dir = _resolve_output_dir(out, melee_root=active_root, src=src, fn=fn)
    try:
        outcome = _run_backend_trace(
            src=src,
            fn=fn,
            out_dir=out_dir,
            verify_debug=verify_debug,
            melee_root=active_root,
        )
        if outcome.exit_code == 0 and outcome.trace is None:
            raise RuntimeError("backend trace runner returned success without a trace")
        if outcome.trace is not None:
            _write_backend_outputs(out_dir, outcome.trace, outcome.fidelity)
            if outcome.exit_code == 0:
                _validate_backend_outputs(out_dir)
    except RuntimeError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2)
    raise typer.Exit(outcome.exit_code)


@retro_app.command("backend-candidate")
def backend_candidate_cmd(
    src: str = typer.Argument(..., help="TU source path to compile under retail MWCC"),
    fn: str = typer.Option(..., "-f", "--function"),
    out: Path = typer.Option(None, "-O", "--output"),
    melee_root: Path = typer.Option(
        None,
        "--melee-root",
        help="Active Melee checkout/worktree root. Defaults to the current cwd tree.",
    ),
    one_pass: bool = typer.Option(
        False,
        "--one-pass",
        help=(
            "Use the one-pass candidate hook instead of separate "
            "map/PCode/IG probe compiles."
        ),
    ),
):
    """Assemble a candidate retail GC/1.2.5n backend trace.

    Diagnostic candidate output. Use `debug retro backend` for full traces.
    """
    active_root = _resolve_melee_root(melee_root)
    _ensure_setup(active_root)
    out_dir = _resolve_output_dir(out, melee_root=active_root, src=src, fn=fn)
    try:
        outcome = _run_backend_candidate_trace(
            src=src,
            fn=fn,
            out_dir=out_dir,
            melee_root=active_root,
            one_pass=one_pass,
        )
        if outcome.trace is not None:
            _write_backend_candidate_outputs(out_dir, outcome.trace)
    except RuntimeError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2)
    except Exception as exc:  # noqa: BLE001 - CLI should report probe failures cleanly.
        typer.secho(
            f"backend candidate trace failed: {exc.__class__.__name__}: {exc}",
            fg="red",
            err=True,
        )
        raise typer.Exit(2)

    typer.echo(f"backend candidate trace: {out_dir / 'backend-trace.candidate.v1.json'}")
    typer.echo(f"regalloc candidate summary: {out_dir / 'regalloc-summary.candidate.txt'}")
    typer.echo(f"backend candidate summary: {out_dir / 'backend-summary.candidate.txt'}")
    if outcome.map_dir is not None:
        typer.echo(f"backend map probe dir: {outcome.map_dir}")
    if outcome.pcode_dir is not None:
        typer.echo(f"backend PCode probe dir: {outcome.pcode_dir}")
    if outcome.ig_dir is not None:
        typer.echo(f"backend IG probe dir: {outcome.ig_dir}")
    raise typer.Exit(outcome.exit_code)


@retro_app.command("probe-backend-map")
def probe_backend_map_cmd(
    src: str = typer.Argument(..., help="TU source path to compile under retail MWCC"),
    fn: str = typer.Option(..., "-f", "--function"),
    out: Path = typer.Option(None, "-O", "--output"),
    melee_root: Path = typer.Option(
        None,
        "--melee-root",
        help="Active Melee checkout/worktree root. Defaults to the current cwd tree.",
    ),
    static_only: bool = typer.Option(
        False,
        "--static-only",
        help=(
            "Generate the canonical nine-member static bundle, including "
            "raw-pe-cfg.v1.jsonl, raw-ghidra-crosscheck.v1.json, and "
            "gc_125n_lifetime_proof.candidate.json; skip parity and the live "
            "gdb probe."
        ),
    ),
    instrumentation_table: Path = typer.Option(
        None,
        "--instrumentation-table",
        help=(
            "Path to gc_125n.json or gc_125n.candidate.json table. "
            "Defaults to installed gc_125n.json in the configured tables dir. "
            "Resolves sibling _lifetime_proof.json and _lifetime_hooks.json."
        ),
    ),
):
    """Probe retail GC/1.2.5n backend map candidates without emitting traces.

    Static mode produces gc_125n_lifetime_proof.candidate.json.
    """
    active_root = _resolve_melee_root(melee_root)
    out_dir = _resolve_output_dir(out, melee_root=active_root, src=src, fn=fn)
    try:
        outcome = _run_backend_map_probe(
            src=src,
            fn=fn,
            out_dir=out_dir,
            static_only=static_only,
            melee_root=active_root,
            instrumentation_table=instrumentation_table,
        )
    except RuntimeError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2)
    except Exception as exc:  # noqa: BLE001 - CLI should report probe setup failures cleanly.
        typer.secho(
            f"backend map probe failed: {exc.__class__.__name__}: {exc}",
            fg="red",
            err=True,
        )
        raise typer.Exit(2)
    current = out_dir / "CURRENT"
    if current.exists():
        from tools.mwcc_retro.backend_lifetime_proof import (
            CURRENT_SCHEMA as LIFETIME_CURRENT_SCHEMA,
        )
        from tools.mwcc_retro.backend_lifetime_proof import (
            resolve_lifetime_bundle,
        )

        try:
            pointer = json.loads(current.read_bytes())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("static backend CURRENT pointer is malformed") from exc
        if pointer.get("schema_version") == LIFETIME_CURRENT_SCHEMA:
            bundle = resolve_lifetime_bundle(out_dir)
            typer.echo(f"raw PE CFG: {bundle.path('raw-pe-cfg.v1.jsonl')}")
            typer.echo(
                "raw/Ghidra cross-check: "
                f"{bundle.path('raw-ghidra-crosscheck.v1.json')}"
            )
            typer.echo(
                "lifetime proof candidate: "
                f"{bundle.path('gc_125n_lifetime_proof.candidate.json')}"
            )
            typer.echo(
                "runtime hook manifest candidate: "
                f"{bundle.path('gc_125n_lifetime_hooks.candidate.json')}"
            )
            typer.echo(f"lifetime audit report: {bundle.path('REPORT.md')}")
        else:
            from tools.mwcc_retro.backend_lifetime_audit import (
                resolve_static_backend_bundle,
            )

            bundle = resolve_static_backend_bundle(out_dir)
            typer.echo(
                "backend map candidates: "
                f"{bundle.path('backend-map-candidates.json')}"
            )
            typer.echo(f"raw PE CFG: {bundle.path('raw-pe-cfg.v1.jsonl')}")
            typer.echo(
                "raw/Ghidra cross-check: "
                f"{bundle.path('raw-ghidra-crosscheck.v1.json')}"
            )
    if (out_dir / "backend-map-probe.json").exists():
        typer.echo(f"backend map probe: {out_dir / 'backend-map-probe.json'}")
    if (out_dir / "backend-map-evidence.json").exists():
        typer.echo(f"backend map evidence: {out_dir / 'backend-map-evidence.json'}")
    raise typer.Exit(outcome.exit_code)


@retro_app.command("probe-backend-ig")
def probe_backend_ig_cmd(
    src: str = typer.Argument(..., help="TU source path to compile under retail MWCC"),
    fn: str = typer.Option(..., "-f", "--function"),
    out: Path = typer.Option(None, "-O", "--output"),
    melee_root: Path = typer.Option(
        None,
        "--melee-root",
        help="Active Melee checkout/worktree root. Defaults to the current cwd tree.",
    ),
):
    """Probe retail GC/1.2.5n partial IG/order/coalesce/observed-color snapshots."""
    active_root = _resolve_melee_root(melee_root)
    out_dir = _resolve_output_dir(out, melee_root=active_root, src=src, fn=fn)
    try:
        outcome = _run_backend_ig_snapshot(
            src=src,
            fn=fn,
            out_dir=out_dir,
            melee_root=active_root,
        )
    except RuntimeError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2)
    except Exception as exc:  # noqa: BLE001 - CLI should report probe setup failures cleanly.
        typer.secho(
            f"backend IG snapshot failed: {exc.__class__.__name__}: {exc}",
            fg="red",
            err=True,
        )
        raise typer.Exit(2)
    if outcome.summary_path is not None:
        typer.echo(f"backend IG snapshot: {outcome.summary_path}")
    if outcome.events_path is not None:
        typer.echo(f"backend IG events: {outcome.events_path}")
    colorgraph_summary = out_dir / "backend-colorgraph-trace.json"
    colorgraph_events = out_dir / "backend-colorgraph-decisions.v1.jsonl"
    if colorgraph_summary.exists():
        typer.echo(f"backend colorgraph trace: {colorgraph_summary}")
    if colorgraph_events.exists():
        typer.echo(f"backend colorgraph decisions: {colorgraph_events}")
    raise typer.Exit(outcome.exit_code)


@retro_app.command("probe-backend-pcode")
def probe_backend_pcode_cmd(
    src: str = typer.Argument(..., help="TU source path to compile under retail MWCC"),
    fn: str = typer.Option(..., "-f", "--function"),
    out: Path = typer.Option(None, "-O", "--output"),
    melee_root: Path = typer.Option(
        None,
        "--melee-root",
        help="Active Melee checkout/worktree root. Defaults to the current cwd tree.",
    ),
    instrumentation_table: Path = typer.Option(
        None,
        "--instrumentation-table",
        help=(
            "Path to gc_125n.json or gc_125n.candidate.json table. "
            "Defaults to installed gc_125n.json in the configured tables dir. "
            "Resolves fixed proof and runtime-hook siblings."
        ),
    ),
):
    """Probe retail GC/1.2.5n backend PCode/block snapshots."""
    active_root = _resolve_melee_root(melee_root)
    out_dir = _resolve_output_dir(out, melee_root=active_root, src=src, fn=fn)
    try:
        outcome = _run_backend_pcode_snapshot(
            src=src,
            fn=fn,
            out_dir=out_dir,
            melee_root=active_root,
            instrumentation_table=instrumentation_table,
        )
    except RuntimeError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2)
    except Exception as exc:  # noqa: BLE001 - CLI should report probe setup failures cleanly.
        typer.secho(
            f"backend PCode snapshot failed: {exc.__class__.__name__}: {exc}",
            fg="red",
            err=True,
        )
        raise typer.Exit(2)
    if outcome.summary_path is not None:
        typer.echo(f"backend PCode snapshot: {outcome.summary_path}")
    if outcome.events_path is not None:
        typer.echo(f"backend PCode events: {outcome.events_path}")
    raise typer.Exit(outcome.exit_code)


@retro_app.command("verify-backend")
def verify_backend_cmd(
    src: str = typer.Argument(..., help="TU source path used for trace generation"),
    fn: str = typer.Option(..., "-f", "--function"),
    trace_path: Path = typer.Option(
        None,
        "--trace",
        help="Existing backend-trace.v1.json. Defaults to the generated output path.",
    ),
    debug_pcdump: Path = typer.Option(
        None,
        "--debug-pcdump",
        help="Existing mwcc-debug pcdump.txt to compare against.",
    ),
    out: Path = typer.Option(None, "-O", "--output"),
    melee_root: Path = typer.Option(None, "--melee-root"),
):
    """Compare a retail backend trace to mwcc-debug pcdump facts."""
    from tools.mwcc_retro import backend_fidelity, backend_schema

    active_root = _resolve_melee_root(melee_root)
    out_dir = _resolve_output_dir(out, melee_root=active_root, src=src, fn=fn)
    trace_file = _resolve_backend_trace_for_verify(trace_path, out_dir=out_dir)
    if not trace_file.exists():
        typer.secho(f"backend trace not found: {trace_file}", fg="red", err=True)
        raise typer.Exit(2)
    if debug_pcdump is None:
        typer.secho(
            "--debug-pcdump is required until automatic mwcc-debug lookup lands",
            fg="red",
            err=True,
        )
        raise typer.Exit(2)
    if not debug_pcdump.exists():
        typer.secho(f"mwcc-debug pcdump not found: {debug_pcdump}", fg="red", err=True)
        raise typer.Exit(2)

    retail_trace = backend_schema.load_backend_trace(trace_file)
    errors = backend_schema.validate_backend_trace(retail_trace)
    if errors:
        typer.secho("backend trace failed validation:", fg="red", err=True)
        for error in errors:
            typer.secho(f"  {error}", fg="red", err=True)
        raise typer.Exit(2)
    try:
        _validate_backend_trace_matches_function(retail_trace, fn)
    except ValueError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc

    try:
        debug_trace = backend_fidelity.trace_from_mwcc_debug_pcdump(
            debug_pcdump.read_text(encoding="utf-8"),
            function=fn,
            source=src,
        )
    except ValueError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc
    report = backend_fidelity.compare_backend_traces(retail_trace, debug_trace)
    out_dir.mkdir(parents=True, exist_ok=True)
    fidelity_json = out_dir / "backend-fidelity.json"
    fidelity_txt = out_dir / "backend-fidelity.txt"
    fidelity_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    fidelity_txt.write_text(backend_fidelity.render_fidelity_text(report))

    typer.echo(f"backend trace: {trace_file}")
    typer.echo(f"mwcc-debug pcdump: {debug_pcdump}")
    typer.echo(f"backend fidelity: {fidelity_json}")
    typer.echo(f"backend fidelity text: {fidelity_txt}")
    raise typer.Exit(0)


@retro_app.command("verify")
def verify_cmd(
    unit: str = typer.Option("src/melee/mn/mnvibration.c", "--unit"),
    fn: str = typer.Option(None, "-f", "--function"),
):
    """Cross-check a retro dump against the existing DLL pcdump (control TU)."""
    from tools.mwcc_retro import verify as rv  # lands in P3
    results = rv.run(unit=unit, fn=fn)
    ok = True
    for r in results:
        typer.echo(f"{'PASS' if r.passed else 'FAIL'} [{r.kind}] {r.name}")
        if r.authoritative and not r.passed:
            ok = False
    raise typer.Exit(0 if ok else 1)


def _write_provenance(out_dir: Path, src, fn, compiler, table, outcome, melee_root):
    from tools.mwcc_retro import CADMIC_PIN, RETROWIN32_PIN
    prov = {
        "true_compiler": compiler,
        "note": "dumps use a GC/1.1 name-spoof internally; true compiler above",
        "src": src, "function": fn,
        "melee_root": str(melee_root),
        "table": str(table),
        "retrowin32_pin": RETROWIN32_PIN, "cadmic_pin": CADMIC_PIN,
        "exit_code": outcome.exit_code,
        "produced": outcome.produced, "missing": outcome.missing,
    }
    (out_dir / "provenance.json").write_text(json.dumps(prov, indent=2) + "\n")
