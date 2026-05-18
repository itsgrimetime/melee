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
from ..mwcc_debug import cache as pcdump_cache
from ..mwcc_debug.cast_audit import (
    audit_function_casts,
    crossref_with_asm,
    find_call_sites,
)
from ..mwcc_debug.patterns import (
    PATTERNS,
    list_patterns,
)
from ..mwcc_debug.source_patch import (
    get_decl_names,
    reorder_decls_in_function,
    transfer_candidate,
)

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
            help="Output path for the dump. Default: cache it under "
                 "build/mwcc_debug_cache/<unit>.txt so follow-up commands "
                 "can auto-resolve it. Use '-' to force stdout instead.",
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

    On success, the raw pcdump.txt is written to the cache at
    build/mwcc_debug_cache/<unit>.txt by default. Use --output PATH for
    a custom location, or --output - for stdout. Follow-up commands like
    `debug analyze -f FN` auto-resolve the cached pcdump by TU.
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

    # Decide where stdout goes. Default behavior changed in H2: if no
    # --output is given, save to the project pcdump cache instead of
    # stdout. This lets follow-up `debug analyze/guide/score` find the
    # dump automatically without the agent threading file paths.
    # Explicit `--output -` forces stdout (old default).
    use_cache = output is None
    if str(output) == "-":
        stdout_dest = sys.stdout.buffer
        out_path_for_msg = "stdout"
        cache_path_used: Optional[Path] = None
    elif use_cache:
        # Strip the `src/` prefix and `.c` suffix to get the unit key.
        unit = src_rel
        if unit.startswith("src/"):
            unit = unit[len("src/"):]
        if unit.endswith(".c"):
            unit = unit[:-2]
        pcdump_cache.ensure_cache_dir(DEFAULT_MELEE_ROOT)
        cache_path_used = pcdump_cache.cache_path(DEFAULT_MELEE_ROOT, unit)
        cache_path_used.parent.mkdir(parents=True, exist_ok=True)
        stdout_dest = open(cache_path_used, "wb")
        out_path_for_msg = str(cache_path_used)
    else:
        cache_path_used = None
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
        if str(output) != "-":
            stdout_dest.close()

    if exit_code == 0:
        print(
            f"[mwcc_debug] wrote {total} bytes to {out_path_for_msg}",
            file=sys.stderr,
        )
        if cache_path_used is not None:
            print(
                f"[mwcc_debug] cached — follow-up commands "
                f"(`analyze`, `guide`, `score`, etc.) will auto-resolve "
                f"this dump by function name.",
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
        Optional[Path],
        typer.Argument(
            help="Path to a pcdump.txt produced by 'debug pcdump'. "
                 "If omitted, auto-resolves via --function from the "
                 "cache at build/mwcc_debug_cache/.",
        ),
    ] = None,
    function: Annotated[
        Optional[str],
        typer.Option(
            "--function", "-f",
            help="Show only this function (default: list all). Also "
                 "used to auto-resolve the pcdump path when not given.",
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
    dump = _resolve_pcdump_path(dump, function)

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
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to simulate (required)",
        ),
    ],
    dump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to a pcdump.txt produced by 'debug pcdump'. "
                 "If omitted, auto-resolves via --function from cache."
        ),
    ] = None,
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
    dump = _resolve_pcdump_path(dump, function)
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
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to score (required)"),
    ],
    target: Annotated[
        Path,
        typer.Option(
            "--target", "-t",
            help="Target spec file (YAML or JSON, required). See "
                 "src/mwcc_debug/scoring.py for format.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
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
    pcdump = _resolve_pcdump_path(pcdump, function)
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
    function: Annotated[
        str,
        typer.Option("--function", "-f",
                     help="Function name to analyze (required)"),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
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
    pcdump = _resolve_pcdump_path(pcdump, function)
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
    function: Annotated[
        str,
        typer.Option("--function", "-f",
                     help="Function name to extract (required)"),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
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
    pcdump = _resolve_pcdump_path(pcdump, function)
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


def _resolve_pcdump_path(
    pcdump: Optional[Path],
    function: Optional[str],
    melee_root: Path = DEFAULT_MELEE_ROOT,
    *,
    require_fresh: bool = False,
) -> Path:
    """Resolve a pcdump path for a consumer command.

    Resolution order:
      1. If `pcdump` is given AND exists → use it.
      2. Else if `function` is given → look up its TU, check the cache.
         - If cache is fresh (or `require_fresh=False` and stale): use it.
         - If cache is missing or stale: raise typer.Exit with a clear hint.
      3. Else: raise typer.Exit asking for either path or function.

    The cache stale-vs-fresh logic: `require_fresh=False` lets the agent
    work with a slightly stale dump (useful when they just edited source
    but want to inspect what the OLD compile produced). `require_fresh=
    True` is for commands that NEED matching dump+source (e.g. ones that
    correlate per-line source positions).
    """
    if pcdump is not None and pcdump.exists():
        return pcdump
    if pcdump is not None:
        # User specified a path but it doesn't exist
        typer.echo(f"pcdump not found: {pcdump}", err=True)
        raise typer.Exit(2)
    # Auto-resolve via function → TU → cache
    if function is None:
        typer.echo(
            "no pcdump path provided and no --function given.\n"
            "Either pass the pcdump path positionally, or pass --function "
            "and we'll auto-resolve via the cache.",
            err=True,
        )
        raise typer.Exit(2)
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function '{function}' not found in report.json.\n"
            f"Try `ninja build/GALE01/report.json` to regenerate, then retry.",
            err=True,
        )
        raise typer.Exit(2)
    entry = pcdump_cache.lookup(melee_root, unit)
    if entry is None:
        cache_p = pcdump_cache.cache_path(melee_root, unit)
        src_p = pcdump_cache.source_path(melee_root, unit)
        typer.echo(
            f"no cached pcdump for {unit} (function lives in {src_p}).\n"
            f"Generate one with:\n"
            f"  melee-agent debug pcdump {src_p.relative_to(melee_root)}\n"
            f"(it will be cached to {cache_p.relative_to(melee_root)})",
            err=True,
        )
        raise typer.Exit(3)
    if not entry.fresh and require_fresh:
        typer.echo(
            f"cached pcdump is stale (source modified since cache).\n"
            f"  Source: {entry.source_path}\n"
            f"  Cache:  {entry.path}\n"
            f"Regenerate with:\n"
            f"  melee-agent debug pcdump {entry.source_path.relative_to(melee_root)}",
            err=True,
        )
        raise typer.Exit(4)
    if not entry.fresh:
        # Non-fatal — warn but use the stale cache.
        typer.echo(
            f"[mwcc_debug] using stale cached pcdump "
            f"({entry.source_path.name} modified since cache).",
            err=True,
        )
    return entry.path


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


def _build_and_match(
    unit: str,
    function: str,
    melee_root: Path,
    *,
    fast_report: bool = True,
) -> Optional[float]:
    """Rebuild a unit's .o and return the function's fuzzy_match_percent.

    Two paths to regenerate the per-function score after building:

      fast_report=True (default): call `objdiff-cli report generate`
        directly. Skips ninja's dependency-graph traversal and avoids
        re-checking unrelated files. Same metric (fuzzy_match_percent)
        as the slow path. Typical speedup: ~0.7sec vs ~2-3sec.

      fast_report=False: run `ninja build/GALE01/report.json` (slow
        path). Use this when ninja's full dependency reasoning is
        needed — e.g. after a configure change.

    Returns None on build failure.
    """
    obj_path = f"build/GALE01/src/{unit}.o"
    r = subprocess.run(
        ["ninja", obj_path],
        cwd=melee_root, capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None

    objdiff_bin = melee_root / "build" / "tools" / "objdiff-cli"
    if fast_report and objdiff_bin.exists():
        report_path = melee_root / "build" / "GALE01" / "report.json"
        r = subprocess.run(
            [str(objdiff_bin), "report", "generate",
             "-o", str(report_path), "-f", "json"],
            cwd=melee_root, capture_output=True, text=True,
        )
        if r.returncode != 0:
            return None
        return _get_match_pct(function, melee_root)

    # Slow path: full ninja regen.
    r = subprocess.run(
        ["ninja", "build/GALE01/report.json"],
        cwd=melee_root, capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    return _get_match_pct(function, melee_root)


@debug_app.command(name="enumerate-decl-orders")
def enumerate_decl_orders(
    function: Annotated[
        str,
        typer.Argument(help="Function name to enumerate orderings for"),
    ],
    strategy: Annotated[
        str,
        typer.Option(
            "--strategy",
            help="Which orderings to try: 'promote' (move each var to "
                 "first; N candidates), 'demote' (move each to last; N), "
                 "'swap' (adjacent pair swaps; N-1), 'all' (promote+demote+"
                 "swap), or 'full' (every permutation; N! — refuses for N>7).",
        ),
    ] = "promote",
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum improvement (percentage points) to consider a win.",
        ),
    ] = 0.1,
    keep_best: Annotated[
        bool,
        typer.Option(
            "--keep-best",
            help="If the best ordering improves match% by ≥threshold, "
                 "leave it applied. Default reverts to original.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit results as JSON."),
    ] = False,
) -> None:
    """Tier 7b: enumerate local-decl orderings, find ones that improve match%.

    Most "stuck near 99%" cases have a 1-line declaration-reorder fix that
    permuter eventually finds at ~2000 iterations. This command brute-forces
    the small decl-order search space directly.

    Strategies (in order of cost):

      promote (default): for each of N locals, try promoting to position 0
        → N candidates, ~N×6sec
      demote: each → position N-1 → N candidates
      swap: each adjacent pair swap → N-1 candidates
      all: promote + demote + swap → ~3N candidates
      full: all N! permutations (refuses for N>7 — would take hours)

    Default reverts after enumeration. Pass --keep-best to apply the best
    winning ordering.
    """
    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    orig = target_path.read_text()
    names = get_decl_names(orig, function)
    if not names:
        typer.echo(
            f"could not find a declaration block in {function} — function "
            f"may have no locals or an unsupported decl style.",
            err=True,
        )
        raise typer.Exit(3)
    n = len(names)

    # Build the list of (label, permutation) candidates to try.
    candidates: list[tuple[str, list[int]]] = []
    if strategy in ("promote", "all"):
        for k in range(n):
            if k == 0:
                continue  # already first — identity
            perm = [k] + [i for i in range(n) if i != k]
            candidates.append((f"promote {names[k]}", perm))
    if strategy in ("demote", "all"):
        for k in range(n):
            if k == n - 1:
                continue
            perm = [i for i in range(n) if i != k] + [k]
            candidates.append((f"demote {names[k]}", perm))
    if strategy in ("swap", "all"):
        for k in range(n - 1):
            perm = list(range(n))
            perm[k], perm[k + 1] = perm[k + 1], perm[k]
            candidates.append((f"swap {names[k]} <-> {names[k+1]}", perm))
    if strategy == "full":
        if n > 7:
            typer.echo(
                f"--strategy full refused: {n} locals = {n}! permutations. "
                f"Use --strategy all for a tractable subset.",
                err=True,
            )
            raise typer.Exit(4)
        from itertools import permutations
        for p in permutations(range(n)):
            if list(p) == list(range(n)):
                continue
            candidates.append((f"order {list(p)}", list(p)))
    if not candidates and strategy not in ("promote", "demote", "swap", "all", "full"):
        typer.echo(f"unknown --strategy: {strategy}", err=True)
        raise typer.Exit(2)
    if not candidates:
        typer.echo("no candidate orderings to try (function may have only 1 local).")
        return

    # Baseline match%.
    baseline = _get_match_pct(function, melee_root) or 0.0
    if not json_out:
        print(f"Function:    {function} ({n} locals: {', '.join(names)})")
        print(f"Source:      {target_path}")
        print(f"Strategy:    {strategy} ({len(candidates)} candidates)")
        print(f"Baseline:    {baseline:.2f}%")
        print()

    results: list[dict] = []
    best_pct = baseline
    best_label: Optional[str] = None
    best_perm: Optional[list[int]] = None

    try:
        for label, perm in candidates:
            patched = reorder_decls_in_function(orig, function, perm)
            if patched is None:
                # Permutation rejected — shouldn't happen with our generators
                continue
            target_path.write_text(patched)
            pct = _build_and_match(unit, function, melee_root)
            target_path.write_text(orig)  # revert before next iter
            if pct is None:
                # Build failed — record as such and continue
                if not json_out:
                    print(f"  {label}: BUILD FAILED")
                results.append({"label": label, "match_pct": None, "delta": None})
                continue
            delta = pct - baseline
            results.append({"label": label, "match_pct": pct, "delta": delta})
            tag = ""
            if delta >= threshold:
                tag = "  WIN"
                if pct > best_pct:
                    best_pct = pct
                    best_label = label
                    best_perm = perm
            elif delta > 0:
                tag = "  (improved)"
            elif delta < 0:
                tag = "  (worse)"
            if not json_out:
                print(f"  {label}: {pct:.2f}%  delta={delta:+.2f}%{tag}")
    finally:
        # Restore original at the very end (in case of unexpected error)
        target_path.write_text(orig)
        # Re-build to restore prior state in report.json
        subprocess.run(
            ["ninja", f"build/GALE01/src/{unit}.o",
             "build/GALE01/report.json"],
            cwd=melee_root, capture_output=True,
        )

    if json_out:
        print(json.dumps({
            "function": function,
            "baseline_pct": baseline,
            "best_label": best_label,
            "best_pct": best_pct,
            "results": results,
        }, indent=2))
        return

    print()
    if best_label is None:
        print(f"No ordering improved match by ≥{threshold:.2f}%.")
        return
    print(f"Best: {best_label} → {best_pct:.2f}% (delta {best_pct - baseline:+.2f}%)")

    if keep_best and best_perm is not None:
        patched = reorder_decls_in_function(orig, function, best_perm)
        if patched is not None:
            target_path.write_text(patched)
            subprocess.run(
                ["ninja", f"build/GALE01/src/{unit}.o",
                 "build/GALE01/report.json"],
                cwd=melee_root, capture_output=True,
            )
            print(f"Applied to {target_path}. Verify with `git diff`.")
    else:
        print("Source reverted. Re-run with --keep-best to apply the win.")


@debug_app.command(name="pattern-catalog")
def pattern_catalog(
    name: Annotated[
        Optional[str],
        typer.Argument(help="Optional pattern name. If omitted, lists all "
                            "patterns."),
    ] = None,
    search: Annotated[
        Optional[str],
        typer.Option("--search", help="Filter the list by substring match "
                                      "against pattern name/title."),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit catalog as JSON."),
    ] = False,
) -> None:
    """Tier 7c: dump the catalog of recurring MWCC mutation patterns.

    The catalog captures the small family of source mutations that
    permuter keeps rediscovering across stuck functions — alias-split,
    decl-order, u8↔u32 widening, drop-variadic-cast, subexpr-extract,
    chained-init. Use as a starting point when staring at a stuck
    function; `debug guide` will also cite pattern names directly.

    Without arguments: lists all patterns with title and one-liner summary.
    With `<name>`: shows the full pattern entry (when-to-try, example
    before/after, mechanism).
    """
    if name is not None:
        p = PATTERNS.get(name)
        if p is None:
            available = ", ".join(sorted(PATTERNS.keys()))
            typer.echo(
                f"unknown pattern: {name}\nAvailable: {available}",
                err=True,
            )
            raise typer.Exit(2)
        if json_out:
            print(json.dumps({
                "name": p.name,
                "title": p.title,
                "summary": p.summary,
                "when_to_try": p.when_to_try,
                "example_before": p.example_before,
                "example_after": p.example_after,
                "mechanism": p.mechanism,
                "addresses": list(p.addresses),
            }, indent=2))
            return
        print(f"Pattern: {p.name}")
        print(f"Title:   {p.title}")
        print(f"Addresses: {', '.join(p.addresses)}")
        print()
        print("Summary:")
        print(f"  {p.summary}")
        print()
        print("When to try:")
        print(f"  {p.when_to_try}")
        print()
        print("Example before:")
        for line in p.example_before.splitlines():
            print(f"  {line}")
        print()
        print("Example after:")
        for line in p.example_after.splitlines():
            print(f"  {line}")
        print()
        print("Mechanism:")
        print(f"  {p.mechanism}")
        return

    patterns = list_patterns()
    if search:
        s = search.lower()
        patterns = [p for p in patterns
                    if s in p.name.lower() or s in p.title.lower()]
        if not patterns:
            print(f"No patterns matched: {search}")
            return

    if json_out:
        print(json.dumps([{
            "name": p.name,
            "title": p.title,
            "summary": p.summary,
            "addresses": list(p.addresses),
        } for p in patterns], indent=2))
        return

    print(f"MWCC mutation pattern catalog ({len(patterns)} entries):\n")
    for p in patterns:
        print(f"  {p.name}")
        print(f"    {p.title}")
        print(f"    Addresses: {', '.join(p.addresses)}")
        print(f"    {p.summary}")
        print()
    print(
        "Run `melee-agent debug pattern-catalog <name>` for full details "
        "(example before/after, mechanism)."
    )


@debug_app.command(name="suggest-casts")
def suggest_casts(
    function: Annotated[
        str,
        typer.Argument(help="Function name to audit"),
    ],
    asm: Annotated[
        bool,
        typer.Option(
            "--asm",
            help="Cross-reference each call-site with the expected ASM "
                 "in build/GALE01/asm/. Detects integer-loaded args that "
                 "the source code wraps in (f32) (and vice versa).",
        ),
    ] = False,
    severity: Annotated[
        str,
        typer.Option(
            "--severity",
            help="Filter by severity: high/medium/low/all (default: medium+).",
        ),
    ] = "medium",
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit warnings as JSON."),
    ] = False,
) -> None:
    """Tier 7d: static lint for cast-mismatch patterns in call args.

    Surfaces explicit casts on function arguments that are likely wrong —
    especially the `(f32)` cast on integer values that the matching agent
    identified as the `drop-variadic-cast` pattern in their session
    findings.

    Three-tier classification:
      HIGH — cast on a value the function declares as integer
      MEDIUM — cast on a value that LOOKS integer but can't be proven
      LOW — every other explicit cast (for general audit)

    With `--asm`, also cross-references the call site against
    build/GALE01/asm/<unit>.s to identify args loaded as integers when
    the source casts to float (and vice versa).
    """
    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    text = target_path.read_text()
    warnings = audit_function_casts(text, function)

    # Severity filter
    sev_order = {"high": 0, "medium": 1, "low": 2}
    min_level = sev_order.get(severity, 1) if severity != "all" else 99
    if severity != "all":
        warnings = [w for w in warnings if sev_order.get(w.severity, 99) <= min_level]

    asm_contexts: dict = {}
    if asm:
        asm_path = melee_root / "build" / "GALE01" / "asm" / f"{unit}.s"
        if not asm_path.exists():
            typer.echo(
                f"asm file not found: {asm_path}\n"
                f"(try `ninja {asm_path.relative_to(melee_root)}`)",
                err=True,
            )
        else:
            from ..mwcc_debug.source_patch import find_function as _find_fn
            span = _find_fn(text, function)
            if span:
                fn_text = text[span.sig_start : span.full_end]
                sites = find_call_sites(fn_text)
                contexts = crossref_with_asm(sites, asm_path, function)
                # Index by (call_target, source_line) for warning correlation
                for ctx in contexts:
                    key = (ctx.source_site.call_target, ctx.source_site.line)
                    asm_contexts[key] = ctx

    if json_out:
        data = []
        for w in warnings:
            entry = {
                "line": w.line,
                "call_target": w.call_target,
                "arg_index": w.arg_index,
                "cast_type": w.cast_type,
                "inner_expr": w.inner_expr,
                "severity": w.severity,
                "reason": w.reason,
            }
            data.append(entry)
        print(json.dumps({"function": function, "warnings": data}, indent=2))
        return

    print(f"Function: {function}")
    print(f"Source:   {target_path}")
    if not warnings:
        print(
            f"No casts at severity≥{severity}. "
            f"(Re-run with --severity all to see all explicit casts.)"
        )
        return
    print(f"Cast warnings ({len(warnings)} at severity≥{severity}):")
    print()
    for w in warnings:
        marker = {"high": "!!", "medium": "!", "low": "·"}.get(w.severity, " ")
        print(f"  {marker} {target_path}:{w.line}  ({w.severity})")
        print(f"     ({w.cast_type}) {w.inner_expr}  →  "
              f"{w.call_target}(... arg{w.arg_index} ...)")
        print(f"     {w.reason}")
        if asm:
            key = (w.call_target, w.line - (text[:0].count('\n')))
            # Find any matching context by call target + line proximity
            for (target, src_line), ctx in asm_contexts.items():
                if target == w.call_target and ctx.asm_line_idx is not None:
                    kinds = ctx.arg_register_kinds
                    if kinds:
                        kind_str = ", ".join(f"{r}={k}"
                                             for r, k in sorted(kinds.items()))
                        print(f"     ASM arg loads: {kind_str}")
                    break
        print()


@debug_app.command(name="triage-perm")
def triage_perm(
    perm_dir: Annotated[
        Path,
        typer.Argument(
            help="Directory containing permuter output subdirs "
                 "(output-NNNN-N/) each with a source.c.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name to verify"),
    ],
    max_candidates: Annotated[
        int,
        typer.Option(
            "--max-candidates",
            help="Stop after evaluating this many candidates "
                 "(0 = no limit).",
        ),
    ] = 0,
    top_k: Annotated[
        int,
        typer.Option(
            "--top",
            help="Show the top K results in the summary.",
        ),
    ] = 5,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum improvement (percentage points) to consider a win.",
        ),
    ] = 0.1,
    apply_best: Annotated[
        bool,
        typer.Option(
            "--apply-best",
            help="If the best transferring candidate clears --threshold, "
                 "leave it applied. Default reverts at the end.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit results as JSON."),
    ] = False,
) -> None:
    """Tier 7e: batch-triage decomp-permuter output candidates.

    The matching agent's session noted that many permuter "winners"
    (score=N where N < baseline) don't transfer to the real source tree
    because permuter preprocesses base.c (header merging, macro
    expansion). This command iterates each `output-*/source.c` in a
    permuter run, applies the candidate to the real tree via the same
    transfer logic as `verify-perm`, runs `ninja` + reads
    fuzzy_match_percent, and produces a ranked list of which candidates
    actually improve real-tree match%.

    Per-candidate cost: ~5-10 seconds (one ninja + report.json). With
    permuter generating ~100 winning candidates per session, total
    triage time is typically a few minutes.

    Designed as the v1 of permuter integration. v2 would be a permuter
    `--external-scorer` patch that calls our scoring per-iteration
    instead of per-winner.
    """
    melee_root = DEFAULT_MELEE_ROOT
    if not perm_dir.is_dir():
        typer.echo(f"not a directory: {perm_dir}", err=True)
        raise typer.Exit(2)

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"function not found in report.json: {function}", err=True)
        raise typer.Exit(2)
    target_path = melee_root / "src" / f"{unit}.c"
    if not target_path.exists():
        typer.echo(f"target source not found: {target_path}", err=True)
        raise typer.Exit(2)

    # Locate candidate sources. Try the common permuter layouts:
    #   <perm-dir>/output-NNNN-N/source.c     (default)
    #   <perm-dir>/<anything>/source.c
    candidate_paths: list[Path] = []
    for entry in sorted(perm_dir.iterdir()):
        if not entry.is_dir():
            continue
        src = entry / "source.c"
        if src.exists():
            candidate_paths.append(src)
    if not candidate_paths:
        # Fallback: maybe the perm-dir itself is one output (no subdirs)
        direct_src = perm_dir / "source.c"
        if direct_src.exists():
            candidate_paths = [direct_src]
    if not candidate_paths:
        typer.echo(
            f"no candidate sources found under {perm_dir}\n"
            f"(expected output-NNNN-N/source.c or source.c)",
            err=True,
        )
        raise typer.Exit(3)
    if max_candidates > 0 and len(candidate_paths) > max_candidates:
        candidate_paths = candidate_paths[:max_candidates]

    baseline = _get_match_pct(function, melee_root) or 0.0
    if not json_out:
        print(f"Function: {function}")
        print(f"Target:   {target_path}")
        print(f"Baseline: {baseline:.2f}%")
        print(f"Candidates: {len(candidate_paths)}")
        print()

    orig = target_path.read_text()

    @dataclasses.dataclass
    class Result:
        path: Path
        match_pct: Optional[float]
        delta: Optional[float]
        status: str  # "ok" / "no-function" / "build-failed"

    results: list[Result] = []
    best: Optional[Result] = None
    try:
        for i, cand in enumerate(candidate_paths, 1):
            cand_text = cand.read_text()
            orig_again = transfer_candidate(cand_text, target_path, function)
            if orig_again is None:
                results.append(Result(path=cand, match_pct=None,
                                      delta=None, status="no-function"))
                if not json_out:
                    print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                          f"function not in candidate")
                continue
            pct = _build_and_match(unit, function, melee_root)
            # Always revert to original before next iter
            target_path.write_text(orig)
            if pct is None:
                results.append(Result(path=cand, match_pct=None,
                                      delta=None, status="build-failed"))
                if not json_out:
                    print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                          f"BUILD FAILED")
                continue
            delta = pct - baseline
            res = Result(path=cand, match_pct=pct, delta=delta, status="ok")
            results.append(res)
            tag = ""
            if delta >= threshold:
                tag = "  WIN"
                if best is None or pct > best.match_pct:
                    best = res
            elif delta < 0:
                tag = "  (worse)"
            if not json_out:
                print(f"  [{i}/{len(candidate_paths)}] {cand.parent.name}: "
                      f"{pct:.2f}%  delta={delta:+.2f}%{tag}")
    finally:
        target_path.write_text(orig)
        subprocess.run(
            ["ninja", f"build/GALE01/src/{unit}.o",
             "build/GALE01/report.json"],
            cwd=melee_root, capture_output=True,
        )

    # Sort results: highest match% first, then by directory name as tiebreak
    ok_results = [r for r in results if r.status == "ok"]
    ok_results.sort(key=lambda r: (-(r.match_pct or 0), str(r.path)))

    if json_out:
        print(json.dumps({
            "function": function,
            "baseline_pct": baseline,
            "best_pct": best.match_pct if best else None,
            "best_path": str(best.path) if best else None,
            "results": [{
                "path": str(r.path),
                "match_pct": r.match_pct,
                "delta": r.delta,
                "status": r.status,
            } for r in results],
        }, indent=2))
        return

    print()
    print("=" * 70)
    print(f"Top {min(top_k, len(ok_results))} candidates by real-tree match%:")
    print("=" * 70)
    for r in ok_results[:top_k]:
        marker = "WIN" if r.delta >= threshold else "    "
        print(f"  {marker}  {r.match_pct:.2f}%  ({r.delta:+.2f}%)  "
              f"{r.path.parent.name}/source.c")

    n_wins = sum(1 for r in ok_results if r.delta >= threshold)
    n_build_failed = sum(1 for r in results if r.status == "build-failed")
    n_no_fn = sum(1 for r in results if r.status == "no-function")
    print()
    print(f"Summary: {n_wins} winners (≥{threshold:.2f}% over baseline), "
          f"{n_build_failed} build failures, {n_no_fn} missing function")

    if apply_best and best is not None and best.delta >= threshold:
        cand_text = best.path.read_text()
        transfer_candidate(cand_text, target_path, function)
        subprocess.run(
            ["ninja", f"build/GALE01/src/{unit}.o",
             "build/GALE01/report.json"],
            cwd=melee_root, capture_output=True,
        )
        print()
        print(f"Applied best candidate ({best.path.parent.name}) to "
              f"{target_path}. Verify with `git diff`.")


@debug_app.command(name="stuck")
def stuck(
    function: Annotated[
        str,
        typer.Argument(help="Function name to diagnose"),
    ],
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Optional target spec (YAML/JSON) for guide comparisons. "
                 "If omitted, surfaces red-flag patterns without a specific "
                 "target.",
        ),
    ] = None,
    no_pcdump: Annotated[
        bool,
        typer.Option(
            "--no-pcdump",
            help="Skip the pcdump auto-generation step if the cache is "
                 "missing. Use when you already know there's no pcdump and "
                 "want a static-only digest.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit structured digest as JSON."),
    ] = False,
) -> None:
    """One-shot diagnostic for a stuck function.

    Composes analyze + guide + suggest-casts and recommends the next
    workflow step. Replaces what used to be 4-5 separate commands.

    Output sections (in order):
      1. Function status — match%, TU, virtual count
      2. Pcdump cache — fresh/stale/missing
      3. Coloring summary — virtuals, SPILLED markers, pass info
      4. Guidance issues — red-flag patterns from `debug guide`
      5. Suspicious casts — HIGH+MEDIUM cast warnings
      6. Next steps — ranked by cost/likelihood
    """
    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function '{function}' not found in report.json.\n"
            f"Try `ninja build/GALE01/report.json` to regenerate, then retry.",
            err=True,
        )
        raise typer.Exit(2)
    src = melee_root / "src" / f"{unit}.c"
    match_pct = _get_match_pct(function, melee_root)

    # Pcdump status. If missing, try to generate (unless --no-pcdump).
    entry = pcdump_cache.lookup(melee_root, unit)
    pcdump_status: str
    pcdump_path: Optional[Path] = None
    if entry is None and not no_pcdump:
        pcdump_status = "missing — would auto-generate (run `debug pcdump src/" + unit + ".c`)"
    elif entry is None:
        pcdump_status = "missing (--no-pcdump set, skipping)"
    elif entry.fresh:
        pcdump_status = f"fresh ({entry.path.name})"
        pcdump_path = entry.path
    else:
        pcdump_status = f"stale (source modified after cache; regenerate for accuracy)"
        pcdump_path = entry.path

    # Collect digest data
    digest: dict = {
        "function": function,
        "tu": str(src.relative_to(melee_root)),
        "match_pct": match_pct,
        "pcdump_status": pcdump_status,
    }

    coloring_summary: Optional[dict] = None
    guidance_issues: list = []
    cast_warnings_high_med: list = []

    if pcdump_path is not None:
        text = pcdump_path.read_text()
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is not None:
            infos = analyze_function(fn)
            mapped = sum(1 for v in infos if v.physical is not None)
            unmapped = sum(1 for v in infos if v.physical is None)
            events_list = parse_hook_events(text)
            events = find_function(events_list, function)
            n_spilled = 0
            if events is not None:
                for sec in events.simplify_sections:
                    n_spilled += sum(1 for e in sec.entries if e.spilled)
            coloring_summary = {
                "n_virtuals": len(infos),
                "mapped": mapped,
                "unmapped": unmapped,
                "spilled": n_spilled,
                "pre_pass": (fn.last_precolor_pass().name
                             if fn.last_precolor_pass() else None),
            }

            # Guidance — empty target spec surfaces red-flag patterns
            if target is not None:
                spec = _load_target_spec(target)
            else:
                spec = {"virtuals": {}}
            result = score_function(fn, spec, events=events)
            suggestions = suggest(fn, result, events=events)
            guidance_issues = [{
                "virtual": s.virtual,
                "category": s.category,
                "severity": s.severity,
                "description": s.description,
                "patterns": s.patterns,
            } for s in suggestions]

    # Cast warnings — always run regardless of pcdump
    if src.exists():
        src_text = src.read_text()
        warnings = audit_function_casts(src_text, function)
        cast_warnings_high_med = [{
            "line": w.line,
            "call_target": w.call_target,
            "arg_index": w.arg_index,
            "cast_type": w.cast_type,
            "inner_expr": w.inner_expr,
            "severity": w.severity,
            "reason": w.reason,
        } for w in warnings if w.severity in ("high", "medium")]

    # Next steps — ranked by cost
    next_steps: list[str] = []
    if any(w["severity"] == "high" for w in cast_warnings_high_med):
        next_steps.append(
            "[free, static] Drop suspicious casts surfaced by suggest-casts. "
            "Run `melee-agent debug suggest-casts " + function + "` for "
            "full details."
        )
    if coloring_summary and coloring_summary.get("spilled", 0) > 0:
        next_steps.append(
            "[medium] Try patterns from `debug pattern-catalog` that "
            "address SPILLED markers: widen-u8-to-u32, alias-split."
        )
    next_steps.append(
        "[~70sec] Run `melee-agent debug enumerate-decl-orders " + function +
        "` — brute-forces the decl-order search space, finds 1-line wins."
    )
    next_steps.append(
        "[minutes] Run `melee-agent debug ceiling " + function +
        "` for a structural-ceiling verdict (combines force-phys + "
        "enumerate-decl-orders)."
    )
    next_steps.append(
        "[hours] As a last resort, run decomp-permuter and feed its "
        "outputs through `debug triage-perm`."
    )

    digest["coloring_summary"] = coloring_summary
    digest["guidance_issues"] = guidance_issues
    digest["cast_warnings"] = cast_warnings_high_med
    digest["next_steps"] = next_steps

    if json_out:
        print(json.dumps(digest, indent=2))
        return

    # Human-readable output
    print(f"== Function status ==")
    print(f"  {function}")
    print(f"  TU:       {digest['tu']}")
    if match_pct is not None:
        print(f"  Match:    {match_pct:.2f}%")
    else:
        print(f"  Match:    (no entry in report.json)")
    print()

    print(f"== Pcdump cache ==")
    print(f"  {pcdump_status}")
    print()

    if coloring_summary:
        s = coloring_summary
        print(f"== Coloring summary ==")
        print(f"  Virtuals:    {s['n_virtuals']} ({s['mapped']} mapped, "
              f"{s['unmapped']} unmapped)")
        print(f"  Spilled:     {s['spilled']}")
        print(f"  Pre-pass:    {s['pre_pass']}")
        print()

    if guidance_issues:
        print(f"== Guidance issues ({len(guidance_issues)}) ==")
        for issue in guidance_issues:
            marker = {"high": "!!", "medium": "!", "low": "·"}.get(
                issue["severity"], " ")
            print(f"  {marker} [r{issue['virtual']} / {issue['category']}]")
            print(f"     {issue['description']}")
            if issue["patterns"]:
                names = ", ".join(f"`{p}`" for p in issue["patterns"])
                print(f"     Patterns: {names}")
        print()
    elif coloring_summary:
        print(f"== Guidance issues ==")
        print(f"  (none — pcdump available but no flagged issues. Provide "
              f"--target to compare against a specific mapping.)")
        print()

    if cast_warnings_high_med:
        print(f"== Suspicious casts ({len(cast_warnings_high_med)}) ==")
        for w in cast_warnings_high_med:
            marker = {"high": "!!", "medium": "!"}.get(w["severity"], " ")
            print(f"  {marker} line {w['line']}: ({w['cast_type']}) "
                  f"{w['inner_expr']} → {w['call_target']}")
        print()

    print(f"== Next steps (ranked by cost) ==")
    for i, step in enumerate(next_steps, 1):
        print(f"  {i}. {step}")


@debug_app.command(name="ceiling")
def ceiling(
    function: Annotated[
        str,
        typer.Argument(help="Function name to check"),
    ],
    skip_decl_orders: Annotated[
        bool,
        typer.Option(
            "--skip-decl-orders",
            help="Skip the enumerate-decl-orders step (saves ~1 min "
                 "but produces a less confident verdict).",
        ),
    ] = False,
    decl_strategy: Annotated[
        str,
        typer.Option(
            "--decl-strategy",
            help="Strategy passed to enumerate-decl-orders. 'promote' is "
                 "fast (N candidates); 'all' covers promote+demote+swap "
                 "(~3N candidates).",
        ),
    ] = "promote",
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit verdict as JSON."),
    ] = False,
) -> None:
    """Structural-ceiling verdict: is this function stuck, or is there
    a quick win we haven't tried?

    Combines two checks:
      1. suggest-casts — static cast linter (free, milliseconds)
      2. enumerate-decl-orders — brute-force decl-order space (~70s)

    Verdict categories:
      - WIN AVAILABLE — a quick fix exists (casts to drop, or a decl-
        order that improves match%)
      - PROBABLE CEILING — no fast wins found; recommends force-phys
        hypothesis test and/or permuter as next steps

    This is the command to run when you're staring at a stuck function
    and asking "should I keep iterating, or move on?"
    """
    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function '{function}' not found in report.json", err=True
        )
        raise typer.Exit(2)
    src = melee_root / "src" / f"{unit}.c"
    baseline = _get_match_pct(function, melee_root) or 0.0

    if not json_out:
        print(f"== Structural-ceiling check for {function} ==")
        print(f"  Baseline: {baseline:.2f}%")
        print(f"  TU:       {src.relative_to(melee_root)}")
        print()

    # Step 1: suggest-casts
    if not json_out:
        print(f"[1] Cast audit (free, ~ms)...")
    src_text = src.read_text() if src.exists() else ""
    cast_warnings = audit_function_casts(src_text, function)
    high_casts = [w for w in cast_warnings if w.severity == "high"]
    med_casts = [w for w in cast_warnings if w.severity == "medium"]
    if not json_out:
        if high_casts:
            print(f"    ! {len(high_casts)} HIGH-severity cast(s) found:")
            for w in high_casts[:3]:
                print(f"      - line {w.line}: ({w.cast_type}) "
                      f"{w.inner_expr} → {w.call_target}")
            if len(high_casts) > 3:
                print(f"      ... +{len(high_casts) - 3} more")
        else:
            print(f"    No HIGH-severity casts.")
        print()

    # Step 2: enumerate-decl-orders (optional)
    decl_results: list = []
    decl_best_pct: float = baseline
    decl_best_label: Optional[str] = None
    if not skip_decl_orders:
        if not json_out:
            print(f"[2] Decl-order enumeration ({decl_strategy} strategy, "
                  f"~minute)...")
        names = get_decl_names(src_text, function) if src_text else None
        if not names:
            if not json_out:
                print(f"    Could not find decl block — skipping.")
        else:
            # Build candidate list (mirror of enumerate_decl_orders logic)
            n = len(names)
            candidates: list[tuple[str, list[int]]] = []
            if decl_strategy in ("promote", "all"):
                for k in range(1, n):
                    perm = [k] + [i for i in range(n) if i != k]
                    candidates.append((f"promote {names[k]}", perm))
            if decl_strategy in ("demote", "all"):
                for k in range(n - 1):
                    perm = [i for i in range(n) if i != k] + [k]
                    candidates.append((f"demote {names[k]}", perm))
            if decl_strategy in ("swap", "all"):
                for k in range(n - 1):
                    perm = list(range(n))
                    perm[k], perm[k + 1] = perm[k + 1], perm[k]
                    candidates.append((f"swap {names[k]}<->{names[k+1]}",
                                       perm))

            orig = src.read_text()
            try:
                for label, perm in candidates:
                    patched = reorder_decls_in_function(orig, function, perm)
                    if patched is None:
                        continue
                    src.write_text(patched)
                    pct = _build_and_match(unit, function, melee_root)
                    src.write_text(orig)  # revert immediately
                    if pct is None:
                        decl_results.append({"label": label,
                                             "pct": None,
                                             "delta": None})
                        continue
                    delta = pct - baseline
                    decl_results.append({"label": label, "pct": pct,
                                         "delta": delta})
                    if pct > decl_best_pct:
                        decl_best_pct = pct
                        decl_best_label = label
            finally:
                src.write_text(orig)
                subprocess.run(
                    ["ninja", f"build/GALE01/src/{unit}.o",
                     "build/GALE01/report.json"],
                    cwd=melee_root, capture_output=True,
                )
            if not json_out:
                if decl_best_label is not None:
                    print(f"    WIN: {decl_best_label} → "
                          f"{decl_best_pct:.2f}% (delta "
                          f"{decl_best_pct - baseline:+.2f}%)")
                else:
                    print(f"    No decl-order win found "
                          f"({len(decl_results)} candidates).")
            print() if not json_out else None
    else:
        if not json_out:
            print(f"[2] Decl-order enumeration: SKIPPED")
            print()

    # Verdict
    has_cast_win = bool(high_casts)
    decl_delta = decl_best_pct - baseline if decl_best_label else 0.0
    has_decl_win = decl_delta >= 0.1

    if has_cast_win or has_decl_win:
        verdict = "WIN AVAILABLE"
        recommendations: list[str] = []
        if has_cast_win:
            recommendations.append(
                f"Drop {len(high_casts)} HIGH-severity cast(s) — run "
                f"`melee-agent debug suggest-casts {function}` for details."
            )
        if has_decl_win:
            recommendations.append(
                f"Apply decl-order win: `melee-agent debug "
                f"enumerate-decl-orders {function} --strategy "
                f"{decl_strategy} --keep-best` → expected "
                f"{decl_best_pct:.2f}%."
            )
    else:
        verdict = "PROBABLE CEILING"
        recommendations = [
            "No fast wins from casts or decl-order. Next options:",
            "  (a) Construct a target mapping and run `debug pcdump "
            f"src/{unit}.c --force-phys ...` to confirm the target ASM "
            "is reachable.",
            "  (b) If reachable, run decomp-permuter on the function — "
            "many small mutations are out of scope for this command.",
            "  (c) If force-phys cannot reach the target either, this "
            "is a true structural ceiling. Document and move on.",
        ]

    if json_out:
        print(json.dumps({
            "function": function,
            "baseline_pct": baseline,
            "verdict": verdict,
            "high_cast_warnings": [{
                "line": w.line, "call_target": w.call_target,
                "cast_type": w.cast_type, "inner_expr": w.inner_expr,
            } for w in high_casts],
            "med_cast_warnings": [{
                "line": w.line, "call_target": w.call_target,
                "cast_type": w.cast_type, "inner_expr": w.inner_expr,
            } for w in med_casts],
            "decl_best_label": decl_best_label,
            "decl_best_pct": decl_best_pct,
            "decl_results": decl_results,
            "recommendations": recommendations,
        }, indent=2))
        return

    print(f"== VERDICT: {verdict} ==")
    for rec in recommendations:
        print(f"  {rec}")
