"""Post-process retail IRO trace streams into per-phase files + a summary.

The retail compiler emits, when IRO logging is on:
  Starting function <fn>
  ... optional preamble ...
  Dumping function <fn> after <PHASE>
  ----...
  Flowgraph node N  First=.., Last=..
  Succ = ...
  Pred = ...
     <idx>: <linear node>
  (blank line between nodes; phases separated by the next "Dumping function")
The fixpoint optimizer prints "*****************\nDumps for pass=N\n****..." markers
between iterations; phases after a marker belong to that iteration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_PHASE_RE = re.compile(r"^Dumping function .+? after (?P<phase>.+?)\s*$")
_PASS_RE = re.compile(r"^Dumps for pass=(?P<n>\d+)\s*$")
_NODE_RE = re.compile(r"^\s*(?P<idx>\d+):\s")
# An IROLinear `Operand <name>` line names a leaf: a source local, a synthesized
# front-end temp (temp_rN / var_rN), or a data symbol. Integer-constant operands
# (e.g. `Operand 44`) are excluded by requiring a leading letter/underscore.
_OPERAND_RE = re.compile(r"\bOperand (?P<name>[A-Za-z_][A-Za-z0-9_]*)")


_START_RE = re.compile(r"^Starting function (?P<fn>\S+)")


_START_RE = re.compile(r"^Starting function (?P<fn>\S+)")


_START_RE = re.compile(r"^Starting function (?P<fn>\S+)")


def slug(phase: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", phase).strip("-").lower()
    return s[:60]


def filter_to_function(text: str, fn: str) -> str:
    """Return only the target function's section of a (possibly multi-function)
    trace: from its `Starting function <fn>` line to the next `Starting
    function` (or EOF). With global dump-enable the compiler emits every
    function; this isolates the requested one robustly (no reliance on the
    fragile FunctionName-at-entry read). Returns "" if the function is absent."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    capturing = False
    for line in lines:
        m = _START_RE.match(line)
        if m:
            if capturing:
                break  # next function begins
            if m.group("fn") == fn:
                capturing = True
        if capturing:
            out.append(line)
    return "".join(out)


@dataclass
class Phase:
    phase: str
    pass_iter: int | None
    body: str
    node_indices: set[int] = field(default_factory=set)


def parse_phases(text: str) -> list[Phase]:
    lines = text.splitlines()
    phases: list[Phase] = []
    cur_iter: int | None = None
    i = 0
    while i < len(lines):
        m_pass = _PASS_RE.match(lines[i])
        if m_pass:
            cur_iter = int(m_pass.group("n"))
            i += 1
            continue
        m = _PHASE_RE.match(lines[i])
        if m:
            phase = m.group("phase")
            body_lines: list[str] = []
            i += 1
            while i < len(lines) and not _PHASE_RE.match(lines[i]) and not _PASS_RE.match(lines[i]):
                body_lines.append(lines[i])
                i += 1
            body = "\n".join(body_lines)
            idxs = {int(mm.group("idx")) for mm in (_NODE_RE.match(l) for l in body_lines) if mm}
            phases.append(Phase(phase=phase, pass_iter=cur_iter, body=body, node_indices=idxs))
        else:
            i += 1
    return phases


@dataclass
class CreatedName:
    name: str
    kind: str              # "temp" | "var" | "local" | "symbol"
    order: int             # first-appearance order across the whole trace
    first_phase: str       # phase whose dump first names it
    first_pass_iter: int | None


def _classify_name(name: str) -> str:
    if name.startswith("temp_"):
        return "temp"
    if name.startswith("var_"):
        return "var"
    # Heuristic: an address-suffixed identifier (Foo_804D6C28) is a data/global
    # symbol; a bare lowercase/underscore identifier is a source local.
    if re.search(r"_[0-9A-Fa-f]{6,}$", name):
        return "symbol"
    return "local"


def creation_order(text: str) -> list[CreatedName]:
    """Timeline of named IR leaves (front-end temps/vars + source locals/symbols)
    in the order they FIRST appear across the trace, each annotated with the
    phase that introduced it.

    Why named operands and not node indices: flowgraph node indices are
    renumbered in every per-phase dump, so they are not stable across phases;
    the `temp_rN`/`var_rN` names ARE stable and are the front-end's synthesized
    temporaries — the creation-order signal upstream of back-end vreg/ig_idx
    ordering (see docs reverse-compiler-feasibility)."""
    seen: dict[str, CreatedName] = {}
    for p in parse_phases(text):
        for line in p.body.splitlines():
            for m in _OPERAND_RE.finditer(line):
                name = m.group("name")
                if name not in seen:
                    seen[name] = CreatedName(
                        name=name, kind=_classify_name(name), order=len(seen),
                        first_phase=p.phase, first_pass_iter=p.pass_iter)
    return list(seen.values())


def split_phase_files(text: str, out_dir) -> list[str]:
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for n, p in enumerate(parse_phases(text)):
        fname = f"iro-{n:02d}-{slug(p.phase)}.txt"
        (out / fname).write_text(f"after {p.phase} (pass={p.pass_iter})\n{p.body}\n")
        written.append(fname)
    return written


def build_summary(text: str) -> str:
    phases = parse_phases(text)
    out: list[str] = ["IRO pass sequence (node ledger v1):", ""]
    prev: set[int] | None = None
    prev_name = None
    for n, p in enumerate(phases):
        tag = f"pass={p.pass_iter}" if p.pass_iter is not None else "pre-loop"
        out.append(f"[{n:02d}] after {p.phase} ({tag}) — {len(p.node_indices)} nodes")
        if prev is not None:
            added = sorted(p.node_indices - prev)
            removed = sorted(prev - p.node_indices)
            if added:
                out.append(f"     added: {added}")
            if removed:
                out.append(f"     removed: {removed} (vs {prev_name})")
        prev = p.node_indices
        prev_name = p.phase

    created = creation_order(text)
    out += ["", "Named-leaf creation order (temps/vars/locals/symbols):", ""]
    for c in created:
        tag = f"pass={c.first_pass_iter}" if c.first_pass_iter is not None else "pre-loop"
        out.append(f"  #{c.order:02d} {c.name:24} [{c.kind}] first seen after "
                   f"{c.first_phase} ({tag})")
    # Synthesized temps in their creation order = the front-end materialization
    # sequence upstream of back-end vreg/ig_idx ordering.
    synth = [c.name for c in created if c.kind in ("temp", "var")]
    if synth:
        out += ["", f"Synthesized-temp creation sequence: {' -> '.join(synth)}"]
    return "\n".join(out) + "\n"
