"""Debug commands - introspect MWCC compiler internals via remote Windows host.

The MWCC compiler's verbose-debug code path crashes under macOS+wibo+Rosetta but
works natively on Windows. This subcommand bridges that gap: it SSHs into the
configured Windows host and runs the mwcc_debug DLL hook there, streaming the
resulting pcdump.txt back over SSH.

See docs/mwcc-debug.md for one-time setup of the Windows side.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from ._common import DEFAULT_MELEE_ROOT, console
from ..mwcc_debug import (
    analyze_function,
    derive_target_from_function,
    find_function,
    format_suggestions,
    parse_hook_events,
    parse_pcdump,
    score_function,
    simulate_function,
    suggest,
)
from ..mwcc_debug.source_patch import transfer_candidate

debug_app = typer.Typer(
    help="Compiler introspection via remote Windows mwcc_debug DLL"
)


def _resolve_src_relative(c_file: str) -> str:
    """Resolve a .c file path to one relative to the melee repo root.

    Accepts:
      - Absolute path: /Users/mike/code/melee/src/melee/lb/lbarq.c
      - Repo-relative: src/melee/lb/lbarq.c
      - CWD-relative when run from inside repo

    Returns the path with forward slashes (POSIX style — easier for remote PS).
    """
    p = Path(c_file).resolve()
    repo = DEFAULT_MELEE_ROOT.resolve()
    try:
        rel = p.relative_to(repo)
    except ValueError:
        raise typer.BadParameter(
            f"{c_file} is not inside the melee repo ({repo})"
        )
    if not p.exists():
        raise typer.BadParameter(f"file not found: {p}")
    if p.suffix != ".c":
        raise typer.BadParameter(f"expected .c file, got: {p.name}")
    return str(rel).replace("\\", "/")


@debug_app.command("pcdump")
def pcdump(
    c_file: Annotated[
        str,
        typer.Argument(help="Path to a .c file in the melee repo"),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Save dump to file instead of stdout. Use '-' to force stdout.",
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout", "-t",
            help="Per-compile timeout in seconds (passed to remote)",
        ),
    ] = 60,
    host: Annotated[
        str,
        typer.Option(
            help="SSH host alias for the Windows debug machine",
            envvar="MWCC_DEBUG_HOST",
        ),
    ] = "nzxt-local",
    remote_script: Annotated[
        str,
        typer.Option(
            help="Path to run_pcdump.ps1 on the remote host",
            envvar="MWCC_DEBUG_REMOTE_SCRIPT",
        ),
    ] = r"C:\Users\mikes\code\mwcc_debug\run_pcdump.ps1",
    no_pull: Annotated[
        bool,
        typer.Option(
            "--no-pull",
            help="Skip 'git pull' on the remote side (test stale code)",
        ),
    ] = False,
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help="Tier 5: bias the allocator. Format 'virtIdx:physReg[,...]'. "
                 "E.g. '36:31' forces virtual 36 to physical r31. "
                 "EXPERIMENTAL — may produce broken code if interferences "
                 "are violated.",
        ),
    ] = None,
):
    """Dump MWCC's internal IR + codegen for a TU and emit pcdump.txt to stdout.

    Compiles the given .c file on a remote Windows host under the mwcc_debug
    patched lmgr326b.dll, which unlocks MWCC's normally-disabled `debuglisting`
    output. The dump shows per-function basic-block structure, every pass of
    the IR optimizer with virtual registers, and the AFTER REGISTER COLORING
    pass with physical-register assignments — useful when diagnosing
    register-allocation mismatches that mismatch-db / opseq / ghidra haven't
    explained.

    On success, the raw pcdump.txt is written to stdout (or --output file).
    All diagnostics go to stderr. Exit code matches the remote compile's
    exit code (0 = success).

    Setup: see docs/mwcc-debug.md. Requires SSH access to a Windows machine
    that has run_pcdump.ps1 and the patched lmgr326b.dll installed.
    """
    src_rel = _resolve_src_relative(c_file)

    # Build the SSH command. We invoke via cmd so we can set env vars cleanly
    # without PowerShell-quote-escaping headaches. The cmd line is:
    #   set MWCC_DEBUG_TIMEOUT_SECS=N && [set MWCC_DEBUG_NO_PULL=1 &&]
    #   powershell -NoProfile -ExecutionPolicy Bypass -File <script> <src>
    cmd_parts = [f"set MWCC_DEBUG_TIMEOUT_SECS={timeout}"]
    if no_pull:
        cmd_parts.append("set MWCC_DEBUG_NO_PULL=1")
    if force_phys:
        # Sanity-check format and pass through. The DLL parses it.
        # Reject embedded quotes/spaces to keep the cmd-line safe.
        if any(c in force_phys for c in '"\'; \t'):
            raise typer.BadParameter(
                "--force-phys must not contain quotes, semicolons, or whitespace"
            )
        cmd_parts.append(f"set MWCC_DEBUG_FORCE_PHYS={force_phys}")
    cmd_parts.append(
        f"powershell -NoProfile -ExecutionPolicy Bypass "
        f"-File {remote_script} {src_rel}"
    )
    remote_cmd = " && ".join(cmd_parts)

    # SSH on Windows defaults to cmd as the user's login shell typically.
    # We pass a single command string to be invoked there.
    ssh_cmd = ["ssh", host, remote_cmd]

    print(f"[mwcc_debug] ssh {host} run_pcdump.ps1 {src_rel}", file=sys.stderr)

    # Decide where stdout goes
    if output is None or str(output) == "-":
        stdout_dest = sys.stdout.buffer
        out_path_for_msg = "stdout"
    else:
        stdout_dest = open(output, "wb")
        out_path_for_msg = str(output)

    try:
        # Use Popen so we can stream large dumps without buffering everything
        proc = subprocess.Popen(
            ssh_cmd,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,  # forward remote diagnostics to local stderr
        )
        assert proc.stdout is not None
        total = 0
        while True:
            chunk = proc.stdout.read(8192)
            if not chunk:
                break
            stdout_dest.write(chunk)
            total += len(chunk)
        exit_code = proc.wait()
    finally:
        if output is not None and str(output) != "-":
            stdout_dest.close()

    if exit_code == 0:
        print(
            f"[mwcc_debug] wrote {total} bytes to {out_path_for_msg}",
            file=sys.stderr,
        )
    else:
        print(
            f"[mwcc_debug] remote exited {exit_code}; {total} bytes captured",
            file=sys.stderr,
        )

    raise typer.Exit(code=exit_code)


# PowerPC EABI register conventions for GPR. The first 8 args go in r3..r10;
# return value is in r3. Floats use f1..f13 / f1 return. We only annotate
# the GPR convention here — most matching investigations are GPR-bound.
PPC_ABI_GPR = {
    1: "SP",
    2: "TOC",
    3: "arg0 / ret",
    4: "arg1",
    5: "arg2",
    6: "arg3",
    7: "arg4",
    8: "arg5",
    9: "arg6",
    10: "arg7",
}


def _abi_hint(physical: Optional[int]) -> str:
    """Return a short ABI hint for a physical register, or empty string."""
    if physical is None:
        return ""
    if physical == 0:
        return "scratch"  # r0 has special semantics in some PPC instructions
    if physical in PPC_ABI_GPR:
        return PPC_ABI_GPR[physical]
    if 11 <= physical <= 12:
        return "caller-save"
    if 13 <= physical <= 31:
        return "callee-save"
    return ""


def _virtreg_to_dict(info) -> dict:
    """Serialize a VirtualRegInfo for JSON output."""
    return {
        "virtual": info.virtual,
        "physical": info.physical,
        "physical_class": info.physical_class,
        "abi_hint": _abi_hint(info.physical),
        "first_use": info.first_use,
        "last_use": info.last_use,
        "use_count": info.use_count,
        "interferes_with": sorted(info.interferes_with),
        "candidates": sorted(info.candidates),
    }


@debug_app.command("analyze")
def analyze(
    dump: Annotated[
        Path,
        typer.Argument(
            help="Path to a pcdump.txt produced by 'debug pcdump'"
        ),
    ],
    function: Annotated[
        Optional[str],
        typer.Option(
            "--function", "-f",
            help="Show only this function (default: list all)",
        ),
    ] = None,
    show_candidates: Annotated[
        bool,
        typer.Option(
            "--candidates",
            help="Show the set of physicals each virtual could have been "
                 "assigned (based on interferer constraints).",
        ),
    ] = True,
    json_out: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit structured JSON instead of human-readable text.",
        ),
    ] = False,
):
    """Summarize a pcdump.txt: per-virtual register live ranges, use counts,
    interferences, and 'could have been' candidate sets.

    Without --function, lists all functions with brief summary. With --function,
    prints a detailed coloring-decision table for that function — the kind of
    output that tells you whether a register-cascade question is constrained
    by interferences or is a free allocator choice.

    The 'Candidates' column shows physicals not used by interfering virtuals.
    If a virtual got a physical that's NOT the lowest-numbered candidate, that
    asymmetry is the kind of allocator-preference question worth digging into.
    """
    if not dump.is_file():
        raise typer.BadParameter(f"dump file not found: {dump}")

    text = dump.read_text()
    funcs = parse_pcdump(text)

    if not funcs:
        print(f"No functions found in {dump}", file=sys.stderr)
        raise typer.Exit(code=1)

    if function is None:
        # List all functions, brief summary
        if json_out:
            payload = [
                {
                    "name": fn.name,
                    "n_passes": len(fn.passes),
                    "has_coloring": fn.get_pass("AFTER REGISTER COLORING") is not None,
                }
                for fn in funcs
            ]
            print(json.dumps({"dump": str(dump), "functions": payload}, indent=2))
            return
        print(f"Functions in {dump.name}:")
        for fn in funcs:
            n_passes = len(fn.passes)
            has_color = fn.get_pass("AFTER REGISTER COLORING") is not None
            color_note = "" if has_color else " (no coloring pass — truncated dump?)"
            print(f"  {fn.name}: {n_passes} passes{color_note}")
        return

    # Find the requested function
    target = next((fn for fn in funcs if fn.name == function), None)
    if target is None:
        avail = ", ".join(fn.name for fn in funcs)
        raise typer.BadParameter(
            f"function '{function}' not in dump. Available: {avail}"
        )

    if target.get_pass("AFTER REGISTER COLORING") is None:
        print(
            f"WARNING: {function} has no AFTER REGISTER COLORING pass — "
            "dump may be truncated. Analysis skipped.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    pre = target.last_precolor_pass()
    post = target.get_pass("AFTER REGISTER COLORING")
    if not json_out:
        print(f"Function: {target.name}")
        print(f"Pre-coloring pass: {pre.name if pre else '<none>'}")
        print(f"Post-coloring pass: {post.name}")
        print()

    infos = analyze_function(target)
    if not infos:
        if json_out:
            print(json.dumps({"function": target.name, "virtuals": [], "warning": "no virtual registers found"}, indent=2))
            return
        print("No virtual registers found (or pass alignment failed).")
        return

    if json_out:
        payload = {
            "function": target.name,
            "pre_coloring_pass": pre.name if pre else None,
            "post_coloring_pass": post.name,
            "virtuals": [_virtreg_to_dict(info) for info in infos],
        }
        print(json.dumps(payload, indent=2))
        return

    # PowerPC EABI reminder
    print("ABI: r3=arg0/ret, r4=arg1, r5=arg2, ..., r10=arg7; "
          "r13-r31=callee-save; r0=scratch.")
    print()

    # Column widths
    print(f"{'Virtual':>8}  {'Phys':>5}  {'Class':<8}  {'ABI':<14}  {'Live[first..last]':<18}  {'Uses':>5}  Interferes")
    print(f"{'-' * 8:>8}  {'-' * 5:>5}  {'-' * 8:<8}  {'-' * 14:<14}  {'-' * 18:<18}  {'-' * 5:>5}  ----------")
    for info in infos:
        phys = f"r{info.physical}" if info.physical is not None else "?"
        live = f"{info.first_use}..{info.last_use}"
        abi = _abi_hint(info.physical)
        # Format interferes_with as a compact list
        if info.interferes_with:
            interferers = ",".join(f"r{v}" for v in sorted(info.interferes_with))
        else:
            interferers = "-"
        print(
            f"     r{info.virtual:<3}  {phys:>5}  {info.physical_class:<8}  "
            f"{abi:<14}  {live:<18}  {info.use_count:>5}  {interferers}"
        )

    if show_candidates:
        print()
        print("Coloring decisions. Verified algorithm (Tier 2 binary-hook data):")
        print("  1. Compute workingMask = volatile-regs (r3..r12, r0 excluded)")
        print("     minus regs used by interferers.")
        print("  2. If workingMask non-empty: pick LOWEST set bit.")
        print("  3. Else call obtain_nonvolatile_register(), which dispenses")
        print("     TOP-DOWN: r31, r30, r29, r28, r27, then r26, r25, ...")
        print("     (Once dispensed, reg is added to volatile-regs pool and")
        print("     can be reused for non-interfering virtuals.)")
        print("Run 'debug simulate' to see what the allocator would pick + why.")
        print("For exact iteration order + per-decision data, see the")
        print("'COLORGRAPH DECISIONS' sections in the raw pcdump.")
        for info in infos:
            if info.physical is None or not info.candidates:
                continue
            cands = sorted(info.candidates)
            cand_str = "{" + ",".join(f"r{c}" for c in cands) + "}"
            abi = _abi_hint(info.physical)
            abi_note = f"  [{abi}]" if abi else ""
            print(f"  r{info.virtual} → r{info.physical}{abi_note}.  Candidates: {cand_str}")


@debug_app.command("simulate")
def simulate(
    dump: Annotated[
        Path,
        typer.Argument(
            help="Path to a pcdump.txt produced by 'debug pcdump'"
        ),
    ],
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to simulate",
        ),
    ],
    show_all: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Show every decision, even when prediction matches actual.",
        ),
    ] = False,
):
    """Simulate MWCC's coloring algorithm on a function and diff against actuals.

    Re-implements the register-coloring loop from MWCC's source (extracted from
    the 7.0 decompilation at git.wuffs.org/MWCC). For each virtual register,
    the simulator predicts what physical the allocator would have picked and
    why. Compares against the actual choice from the pcdump.

    Matches confirm our understanding of the algorithm. Mismatches highlight
    cases where our model is wrong — usually due to factors we don't see in
    pcdump (caller-save kill at call sites, argument-passing ABI pinning, or
    nonvolatile-allocation-order edge cases).

    See docs/mwcc-debug-future-ideas.md for the long-term plan to replace
    this simulator with a real hook into mwcceppc.exe's allocator.
    """
    if not dump.is_file():
        raise typer.BadParameter(f"dump file not found: {dump}")

    text = dump.read_text()
    funcs = parse_pcdump(text)
    target = next((fn for fn in funcs if fn.name == function), None)
    if target is None:
        avail = ", ".join(fn.name for fn in funcs)
        raise typer.BadParameter(
            f"function '{function}' not in dump. Available: {avail}"
        )

    decisions = simulate_function(target)
    if not decisions:
        print("No virtual registers found (or pass alignment failed).")
        raise typer.Exit(code=1)

    print(f"Function: {target.name}")
    print(f"Algorithm: MWCC-style greedy coloring (per 7.0 source). Iteration")
    print(f"order: ascending interferer count.")
    print()
    print(f"{'Virtual':>8}  {'Actual':>7}  {'Predicted':>9}  {'Match':>5}  Reasoning")
    print(f"{'-' * 8:>8}  {'-' * 7:>7}  {'-' * 9:>9}  {'-' * 5:>5}  ---------")

    matches = 0
    mismatches = 0
    for d in decisions:
        actual = f"r{d.actual_physical}" if d.actual_physical is not None else "?"
        predicted = f"r{d.predicted_physical}" if d.predicted_physical is not None else "SPILL"
        is_match = d.actual_physical == d.predicted_physical
        if is_match:
            matches += 1
            match_marker = "✓"
        else:
            mismatches += 1
            match_marker = "✗"
        if show_all or not is_match:
            print(
                f"     r{d.virtual:<3}  {actual:>7}  {predicted:>9}  "
                f"{match_marker:>5}  {d.reasoning}"
            )

    print()
    print(f"Summary: {matches} match, {mismatches} mismatch "
          f"(out of {len(decisions)} virtuals)")

    if mismatches and not show_all:
        print("Use --all to see matching decisions too.")


@debug_app.command("diff")
def diff(
    dump_a: Annotated[
        Path,
        typer.Argument(help="Path to first pcdump.txt (baseline)"),
    ],
    dump_b: Annotated[
        Path,
        typer.Argument(help="Path to second pcdump.txt (candidate)"),
    ],
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to diff",
        ),
    ],
    show_unchanged: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Show all decisions, not just changed ones.",
        ),
    ] = False,
):
    """Diff the coloring decisions for one function between two pcdumps.

    Compares COLORGRAPH DECISIONS sections per (function, register class)
    and surfaces only what changed: assigned physical regs, interferer
    lists, degrees, flags. Speeds up the matching agent's iteration loop —
    "I tried source change X, what did it do to the allocator?".

    Matches nodes by ig_idx when both dumps have a non-(-1) value; falls
    back to iter_idx alignment otherwise.
    """
    if not dump_a.is_file():
        raise typer.BadParameter(f"dump A not found: {dump_a}")
    if not dump_b.is_file():
        raise typer.BadParameter(f"dump B not found: {dump_b}")

    events_a = parse_hook_events(dump_a.read_text())
    events_b = parse_hook_events(dump_b.read_text())

    fn_a = find_function(events_a, function)
    fn_b = find_function(events_b, function)
    if fn_a is None or fn_b is None:
        missing = []
        if fn_a is None: missing.append(f"A ({dump_a.name})")
        if fn_b is None: missing.append(f"B ({dump_b.name})")
        raise typer.BadParameter(
            f"function '{function}' not found in: {', '.join(missing)}"
        )

    print(f"Function: {function}")
    print(f"  A: {dump_a.name}")
    print(f"  B: {dump_b.name}")
    print()

    # Diff IG/CP events first (high-level summary)
    if len(fn_a.ig_events) != len(fn_b.ig_events):
        print(f"IG event count differs: A={len(fn_a.ig_events)} B={len(fn_b.ig_events)}")
    for i, (a, b) in enumerate(zip(fn_a.ig_events, fn_b.ig_events)):
        if a.n_nodes != b.n_nodes:
            print(f"IG[{i}] class={a.class_id}: n_nodes A={a.n_nodes} → B={b.n_nodes}")

    if len(fn_a.cp_events) != len(fn_b.cp_events):
        print(f"CP event count differs: A={len(fn_a.cp_events)} B={len(fn_b.cp_events)}")

    # Diff each colorgraph section by class
    n_classes = max(len(fn_a.colorgraph_sections), len(fn_b.colorgraph_sections))
    any_change = False
    for class_pos in range(n_classes):
        sec_a = fn_a.colorgraph_sections[class_pos] if class_pos < len(fn_a.colorgraph_sections) else None
        sec_b = fn_b.colorgraph_sections[class_pos] if class_pos < len(fn_b.colorgraph_sections) else None
        if sec_a is None:
            print(f"\nColorgraph class slot {class_pos}: A has no section, B has class={sec_b.class_id}")
            any_change = True
            continue
        if sec_b is None:
            print(f"\nColorgraph class slot {class_pos}: B has no section, A has class={sec_a.class_id}")
            any_change = True
            continue

        if sec_a.n_nodes != sec_b.n_nodes:
            print(f"\nClass {sec_a.class_id}: n_nodes A={sec_a.n_nodes} → B={sec_b.n_nodes}")
            any_change = True

        # Index decisions by ig_idx for matching. -1 (unfound in linear scan) goes to a separate bucket keyed by iter.
        def index_decisions(sec):
            by_ig = {}
            by_iter_unfound = {}
            for d in sec.decisions:
                if d.ig_idx >= 0:
                    by_ig[d.ig_idx] = d
                else:
                    by_iter_unfound[d.iter_idx] = d
            return by_ig, by_iter_unfound

        a_by_ig, a_by_iter = index_decisions(sec_a)
        b_by_ig, b_by_iter = index_decisions(sec_b)

        # Walk shared keys
        all_ig_keys = sorted(set(a_by_ig.keys()) | set(b_by_ig.keys()))
        per_class_changes = []
        for k in all_ig_keys:
            a = a_by_ig.get(k)
            b = b_by_ig.get(k)
            if a is None:
                per_class_changes.append((k, "added", b))
                continue
            if b is None:
                per_class_changes.append((k, "removed", a))
                continue
            changes = []
            if a.assigned_reg != b.assigned_reg:
                changes.append(f"r{a.assigned_reg}→r{b.assigned_reg}")
            if a.degree != b.degree:
                changes.append(f"degree {a.degree}→{b.degree}")
            if a.n_interferers != b.n_interferers:
                changes.append(f"nIntfr {a.n_interferers}→{b.n_interferers}")
            if a.flags != b.flags:
                changes.append(f"flags 0x{a.flags:02x}→0x{b.flags:02x}")
            # Interferer set diff
            a_set = {idx for idx, _ in a.interferers}
            b_set = {idx for idx, _ in b.interferers}
            added_intfr = sorted(b_set - a_set)
            removed_intfr = sorted(a_set - b_set)
            if added_intfr:
                changes.append(f"+intfr {','.join(map(str, added_intfr))}")
            if removed_intfr:
                changes.append(f"-intfr {','.join(map(str, removed_intfr))}")
            if changes:
                per_class_changes.append((k, "changed", (a, b, changes)))
            elif show_unchanged:
                per_class_changes.append((k, "same", a))

        if per_class_changes or sec_a.n_nodes != sec_b.n_nodes:
            print(f"\nClass {sec_a.class_id} per-node diff:")
            print(f"  {'node':>6}  {'state':<8}  detail")
            print(f"  {'-' * 6:>6}  {'-' * 8:<8}  ------")
            for ig_idx, state, payload in per_class_changes:
                if state == "changed":
                    a, b, changes = payload
                    detail = "; ".join(changes)
                    print(f"  r{ig_idx:<5}  changed   {detail}")
                    any_change = True
                elif state == "added":
                    b = payload
                    print(f"  r{ig_idx:<5}  added(B)  r{b.assigned_reg}, degree={b.degree}, nIntfr={b.n_interferers}")
                    any_change = True
                elif state == "removed":
                    a = payload
                    print(f"  r{ig_idx:<5}  removed(A) r{a.assigned_reg}, degree={a.degree}, nIntfr={a.n_interferers}")
                    any_change = True
                else:  # same, only shown with --all
                    a = payload
                    print(f"  r{ig_idx:<5}  same      r{a.assigned_reg}")

        # Note unmatched -1-iters separately
        unmatched_a = set(a_by_iter.keys()) - set(b_by_iter.keys())
        unmatched_b = set(b_by_iter.keys()) - set(a_by_iter.keys())
        if unmatched_a or unmatched_b:
            print(f"\nClass {sec_a.class_id} -1-iter nodes that don't match by iter idx:")
            if unmatched_a:
                print(f"  A-only iters: {sorted(unmatched_a)}")
            if unmatched_b:
                print(f"  B-only iters: {sorted(unmatched_b)}")
            any_change = True

    if not any_change:
        print("\nNo coloring changes detected.")


def _load_target_spec(path: Path) -> dict:
    """Load a target spec from YAML or JSON.

    Both are accepted; JSON is a strict subset so we can fall back to it
    when PyYAML isn't installed. The spec shape is documented in
    src/mwcc_debug/scoring.py.
    """
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise typer.BadParameter(
                f"PyYAML not installed; convert {path} to JSON or "
                f"`pip install PyYAML`"
            )
        return yaml.safe_load(text)
    return json.loads(text)


@debug_app.command()
def score(
    pcdump: Annotated[
        Path,
        typer.Argument(help="Path to pcdump.txt"),
    ],
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to score"),
    ],
    target: Annotated[
        Path,
        typer.Option(
            "--target", "-t",
            help="Target spec file (YAML or JSON). See "
                 "src/mwcc_debug/scoring.py for format.",
        ),
    ],
    breakdown: Annotated[
        bool,
        typer.Option(
            "--breakdown",
            help="Print the score components in addition to the total.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit score as JSON."),
    ] = False,
) -> None:
    """Tier 4: score a pcdump's coloring decisions against a target spec.

    Lower scores are better (perfect match = 0). Designed to be called by
    decomp-permuter as a custom scorer.
    """
    text = pcdump.read_text()
    spec = _load_target_spec(target)
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        typer.echo(f"Function not found: {function}", err=True)
        raise typer.Exit(1)

    events_list = parse_hook_events(text)
    events = find_function(events_list, function)

    result = score_function(fn, spec, events=events)

    if json_out:
        print(json.dumps({
            "function": function,
            "score": result.total,
            "matched": result.matched,
            "targeted": result.targeted,
            "virtual_distance": result.virtual_distance,
            "spill_unexpected": result.spill_unexpected,
            "spill_missing": result.spill_missing,
            "interferer_distance": result.interferer_distance,
        }))
        return

    if breakdown:
        print(f"Function:           {function}")
        print(f"Score:              {result.total:.2f}")
        print(f"Matched:            {result.matched} / {result.targeted}")
        print(f"Virtual penalty:    {result.virtual_penalty:.2f} "
              f"({result.virtual_distance} wrong)")
        print(f"Spill penalty:      {result.spill_penalty:.2f} "
              f"(unexpected={len(result.spill_unexpected)} "
              f"missing={len(result.spill_missing)})")
        print(f"Interferer penalty: {result.interferer_penalty:.2f} "
              f"(sum |Δdeg| = {result.interferer_distance})")
    else:
        print(f"{result.total:.2f}")


@debug_app.command()
def guide(
    pcdump: Annotated[
        Path,
        typer.Argument(help="Path to pcdump.txt"),
    ],
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to analyze"),
    ],
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec file (YAML or JSON). If omitted, all virtuals "
                 "currently mapped to non-target physicals are shown.",
        ),
    ] = None,
) -> None:
    """Tier 4: human-readable diagnostic for stuck-function debugging.

    Reports which virtuals are at the wrong physical, why (interference,
    spill, iteration order), and suggests directions for C-source nudges.
    Hints, not guarantees — interpret in source context.
    """
    text = pcdump.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        typer.echo(f"Function not found: {function}", err=True)
        raise typer.Exit(1)

    events_list = parse_hook_events(text)
    events = find_function(events_list, function)

    if target is None:
        # No target — score against an empty target spec, just to surface
        # SPILLED markers and other red flags.
        spec: dict = {"virtuals": {}}
    else:
        spec = _load_target_spec(target)

    result = score_function(fn, spec, events=events)
    suggestions = suggest(fn, result, events=events)

    print(f"Function: {function}")
    print(f"Targeted virtuals: {result.targeted}")
    print(f"  Matched: {result.matched}")
    print(f"  Wrong:   {result.virtual_distance}")
    if result.spill_unexpected:
        print(f"  Unexpected SPILLED: r{', r'.join(str(v) for v in result.spill_unexpected)}")
    if result.spill_missing:
        print(f"  Expected-but-missing SPILLED: r{', r'.join(str(v) for v in result.spill_missing)}")
    print()
    print("Suggestions (highest severity first):")
    print(format_suggestions(suggestions))


@debug_app.command(name="derive-target")
def derive_target(
    pcdump: Annotated[
        Path,
        typer.Argument(help="Path to pcdump.txt"),
    ],
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to extract"),
    ],
    output_format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format: yaml (default) or json.",
            click_type=typer.Choice(["yaml", "json"], case_sensitive=False)
            if False  # typer.Choice not available pre-0.12; fall back to str
            else None,
        ),
    ] = "yaml",
) -> None:
    """Tier 4: extract the current virtual→physical mapping as a target spec.

    Useful for capturing a known-good (or known-experimental) target to
    use later as input to `score` or `guide`. Especially useful with
    Tier 5 force-phys: force the desired mapping, run pcdump, capture
    the result with this command, then save the spec and use it to
    score subsequent natural-source attempts.
    """
    text = pcdump.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        typer.echo(f"Function not found: {function}", err=True)
        raise typer.Exit(1)

    events_list = parse_hook_events(text)
    events = find_function(events_list, function)

    spec = derive_target_from_function(fn, events=events)

    fmt = (output_format or "yaml").lower()
    if fmt == "json":
        print(json.dumps(spec, indent=2))
    else:
        # Render as YAML manually (avoid PyYAML dependency for output)
        print(f"function: {spec['function']}")
        print(f"virtuals:")
        for v in sorted(spec["virtuals"]):
            print(f"  {v}: {spec['virtuals'][v]}")
        if spec.get("spilled"):
            print(f"spilled:")
            for v in spec["spilled"]:
                print(f"  - {v}")


def _find_unit_for_function(func_name: str, melee_root: Path) -> Optional[str]:
    """Locate the unit (source path without .c) containing func_name via
    report.json. Mirrors tools/checkdiff.py's find_unit_for_function."""
    report_path = melee_root / "build" / "GALE01" / "report.json"
    if not report_path.exists():
        return None
    with report_path.open("r") as f:
        for unit in json.load(f).get("units", []):
            for function in unit.get("functions", []):
                if function.get("name") == func_name:
                    return unit.get("name", "").removeprefix("main/")
    return None


def _get_match_pct(func_name: str, melee_root: Path) -> Optional[float]:
    """Read the function's fuzzy_match_percent from report.json."""
    report_path = melee_root / "build" / "GALE01" / "report.json"
    if not report_path.exists():
        return None
    with report_path.open("r") as f:
        for unit in json.load(f).get("units", []):
            for function in unit.get("functions", []):
                if function.get("name") == func_name:
                    return function.get("fuzzy_match_percent")
    return None


@debug_app.command(name="verify-perm")
def verify_perm(
    candidate: Annotated[
        Path,
        typer.Argument(
            help="Path to permuter candidate source (.c file with the "
                 "mutated function). Typically output-NNNN-N/source.c "
                 "from decomp-permuter.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to transfer"),
    ],
    keep: Annotated[
        bool,
        typer.Option(
            "--keep",
            help="If the transfer improves match%, leave the patched source "
                 "in place. By default we always revert (dry-run semantics).",
        ),
    ] = False,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum improvement (in percentage points) to consider "
                 "the candidate a win. Default 0.1.",
        ),
    ] = 0.1,
) -> None:
    """Tier 7a: apply a permuter candidate to the real source and verify.

    The permuter preprocesses its base.c (macro expansion, header merging),
    so a winning candidate doesn't always transfer cleanly. This command:

      1. Extracts the target function from the candidate source
      2. Patches it into the real source tree
      3. Runs `ninja <obj>` to rebuild
      4. Reads the fresh fuzzy_match_percent from report.json
      5. Reports the delta vs. pre-patch baseline

    By default the patched source is REVERTED at the end regardless of
    outcome — pass --keep to leave a winning transfer applied.
    """
    melee_root = DEFAULT_MELEE_ROOT
    if not candidate.exists():
        typer.echo(f"candidate not found: {candidate}", err=True)
        raise typer.Exit(2)

    # Locate the real source file via report.json.
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function not found in report.json: {function}\n"
            f"(report.json may be stale; try `ninja build/GALE01/report.json`)",
            err=True,
        )
        raise typer.Exit(2)
    # checkdiff convention: unit paths are relative to src/
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    # Baseline match%.
    baseline_pct = _get_match_pct(function, melee_root)
    print(f"Function:       {function}")
    print(f"Real source:    {target_path}")
    print(f"Candidate:      {candidate}")
    print(f"Baseline match: {baseline_pct:.2f}%" if baseline_pct is not None
          else "Baseline match: (unknown)")

    candidate_text = candidate.read_text()
    orig = transfer_candidate(candidate_text, target_path, function)
    if orig is None:
        typer.echo(
            f"failed to locate function '{function}' in candidate OR "
            f"target — cannot transfer.",
            err=True,
        )
        raise typer.Exit(3)

    try:
        # Build the affected .o. checkdiff convention: report.json's unit
        # name doesn't include the "src/" prefix; ninja target does.
        obj_path = f"build/GALE01/src/{unit}.o"
        print(f"\nRebuilding {obj_path}...")
        ninja_result = subprocess.run(
            ["ninja", obj_path],
            cwd=melee_root, capture_output=True, text=True,
        )
        if ninja_result.returncode != 0:
            print("ninja failed:")
            print(ninja_result.stdout)
            print(ninja_result.stderr, file=sys.stderr)
            target_path.write_text(orig)
            print("\nReverted source. Build error implies candidate doesn't "
                  "compile cleanly in the real tree (often due to missing "
                  "includes or preprocessor differences from permuter's base.c).")
            raise typer.Exit(4)

        # Regenerate report.json for fresh fuzzy_match_percent.
        report_result = subprocess.run(
            ["ninja", "build/GALE01/report.json"],
            cwd=melee_root, capture_output=True, text=True,
        )
        if report_result.returncode != 0:
            # Non-fatal — report stale data anyway
            print("warning: ninja build/GALE01/report.json failed", file=sys.stderr)

        new_pct = _get_match_pct(function, melee_root)
        if new_pct is None:
            print("Could not read fresh match% after build.", file=sys.stderr)
            target_path.write_text(orig)
            raise typer.Exit(5)

        delta = new_pct - (baseline_pct or 0.0)
        print(f"\nNew match:      {new_pct:.2f}%")
        print(f"Delta:          {delta:+.2f}%")

        improved = delta >= threshold

        if improved and keep:
            print(f"\nCandidate improved match by ≥{threshold:.2f}% — leaving "
                  f"patched source in place ({target_path}).")
            return  # don't revert

        if improved:
            print(f"\nCandidate improved match by ≥{threshold:.2f}% but "
                  f"--keep was not set — reverting. Re-run with --keep to "
                  f"commit the change.")
        else:
            print(f"\nCandidate did not improve by ≥{threshold:.2f}% — "
                  f"reverting.")
        target_path.write_text(orig)
        # Rebuild to restore prior state in report.json
        subprocess.run(["ninja", obj_path, "build/GALE01/report.json"],
                       cwd=melee_root, capture_output=True)
    except Exception:
        # Always revert on unexpected error
        try:
            target_path.write_text(orig)
        except Exception:
            pass
        raise
