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
import re
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
from ..mwcc_debug.asm_parser import (
    extract_function as asm_extract_function,
    find_first_def as asm_find_first_def,
    parse_prologue_end as asm_parse_prologue_end,
)
from ..mwcc_debug.iter_match import match_virtual_for_expected_def

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
    force_phys_iter: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-iter",
            help="Tier 5: bias by colorgraph iter position "
                 "(class:iter:phys[,...]). Use for nodes that lack an "
                 "addressable ig_idx. EXPERIMENTAL.",
        ),
    ] = None,
    force_phys_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-fn",
            help="Scope --force-phys and --force-phys-iter to one function. "
                 "EXPERIMENTAL.",
        ),
    ] = None,
    branch: Annotated[
        Optional[str],
        typer.Option(
            "--branch",
            help="Compile against this branch on the remote. If omitted, "
                 "auto-detects from the local repo's current branch. The "
                 "remote maintains a worktree per branch so concurrent "
                 "pcdumps on different branches don't clobber each other.",
            envvar="MWCC_DEBUG_BRANCH",
        ),
    ] = None,
    force_iter_first: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first",
            help="Tier 6: reorder the simplification list so named virtuals "
                 "are popped first by colorgraph. Format 'virtIdx[,virtIdx]*'. "
                 "E.g. '32' promotes virtual r32 to the head of the "
                 "simplification stack — it gets first crack at the top-down "
                 "callee-save dispense (r31). Addresses the param-iter-ceiling "
                 "pattern. EXPERIMENTAL — produces DLL-patched binary, NOT "
                 "what real MWCC would emit from any C source.",
        ),
    ] = None,
    force_coalesce: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce",
            help="Tier 6: override the conservative coalescer. Format "
                 "'virt=root[,virt=root]*'. E.g. '42=38' forces virtual 42 "
                 "to coalesce into 38; '42=42' un-coalesces 42 back to its "
                 "own root. EXPERIMENTAL.",
        ),
    ] = None,
    force_coalesce_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce-fn",
            help="Scope --force-coalesce to a single function name in "
                 "the TU. Other functions compile naturally. EXPERIMENTAL.",
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

    # Resolve the branch. If not provided, auto-detect from local git
    # (the agent's typical case: they're on `wip/<topic>` locally and
    # want to compile that branch on the remote without thinking about
    # it). master/main use the legacy single-checkout path on the remote.
    if branch is None:
        try:
            r = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=DEFAULT_MELEE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode == 0:
                branch = r.stdout.strip() or None
        except Exception:
            branch = None
    # Reject anything that looks dangerous to pass through cmd.exe.
    if branch is not None and any(c in branch for c in '"\'; \t&|<>'):
        raise typer.BadParameter(
            f"branch name must not contain shell metacharacters: {branch!r}"
        )

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
    if force_phys_iter:
        if any(c in force_phys_iter for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-phys-iter must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(f"set MWCC_DEBUG_FORCE_PHYS_ITER={force_phys_iter}")
    if force_phys_fn:
        if any(c in force_phys_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-phys-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(f"set MWCC_DEBUG_FORCE_PHYS_FUNCTION={force_phys_fn}")
    if branch and branch not in ("master", "main"):
        # Non-default branch — remote will use a worktree.
        cmd_parts.append(f"set MWCC_DEBUG_BRANCH={branch}")
    if force_iter_first:
        if any(c in force_iter_first for c in '"\'; \t'):
            raise typer.BadParameter(
                "--force-iter-first must not contain quotes, semicolons, "
                "or whitespace"
            )
        cmd_parts.append(f"set MWCC_DEBUG_FORCE_ITER_FIRST={force_iter_first}")
    if force_coalesce:
        if any(c in force_coalesce for c in '"\'; \t'):
            raise typer.BadParameter(
                "--force-coalesce must not contain quotes, semicolons, "
                "or whitespace"
            )
        cmd_parts.append(f"set MWCC_DEBUG_FORCE_COALESCE={force_coalesce}")
    if force_coalesce_fn:
        if any(c in force_coalesce_fn for c in '"\'; \t&|<>'):
            raise typer.BadParameter(
                "--force-coalesce-fn must not contain quotes, semicolons, "
                "whitespace, or shell metacharacters"
            )
        cmd_parts.append(
            f"set MWCC_DEBUG_FORCE_COALESCE_FUNCTION={force_coalesce_fn}"
        )
    cmd_parts.append(
        f"powershell -NoProfile -ExecutionPolicy Bypass "
        f"-File {remote_script} {src_rel}"
    )
    remote_cmd = " && ".join(cmd_parts)

    # SSH on Windows defaults to cmd as the user's login shell typically.
    # We pass a single command string to be invoked there.
    ssh_cmd = ["ssh", host, remote_cmd]

    branch_label = (f" branch={branch}"
                    if branch and branch not in ("master", "main") else "")
    print(f"[mwcc_debug] ssh {host} run_pcdump.ps1 {src_rel}{branch_label}",
          file=sys.stderr)

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
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit simulation results as JSON."),
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
        _abort_function_not_in_dump(function, [fn.name for fn in funcs])

    decisions = simulate_function(target)
    if not decisions:
        if json_out:
            print(json.dumps({"function": function, "error":
                              "no virtual registers found (or pass alignment failed)"}))
        else:
            print("No virtual registers found (or pass alignment failed).")
        raise typer.Exit(code=1)

    matches = sum(1 for d in decisions if d.actual_physical == d.predicted_physical)
    mismatches = len(decisions) - matches

    if json_out:
        print(json.dumps({
            "function": target.name,
            "summary": {
                "matches": matches,
                "mismatches": mismatches,
                "total": len(decisions),
            },
            "decisions": [{
                "virtual": d.virtual,
                "actual_physical": d.actual_physical,
                "predicted_physical": d.predicted_physical,
                "match": d.actual_physical == d.predicted_physical,
                "reasoning": d.reasoning,
            } for d in decisions],
        }, indent=2))
        return

    print(f"Function: {target.name}")
    print(f"Algorithm: MWCC-style greedy coloring (per 7.0 source). Iteration")
    print(f"order: ascending interferer count.")
    print()
    print(f"{'Virtual':>8}  {'Actual':>7}  {'Predicted':>9}  {'Match':>5}  Reasoning")
    print(f"{'-' * 8:>8}  {'-' * 7:>7}  {'-' * 9:>9}  {'-' * 5:>5}  ---------")

    for d in decisions:
        actual = f"r{d.actual_physical}" if d.actual_physical is not None else "?"
        predicted = f"r{d.predicted_physical}" if d.predicted_physical is not None else "SPILL"
        is_match = d.actual_physical == d.predicted_physical
        match_marker = "✓" if is_match else "✗"
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

    Validates the basic shape of the loaded spec and emits a helpful
    error if it's malformed.
    """
    if not path.exists():
        typer.echo(f"target spec file not found: {path}", err=True)
        typer.echo(
            "Generate one with `melee-agent debug derive-target -f FN`.",
            err=True,
        )
        raise typer.Exit(2)
    text = path.read_text()
    try:
        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except ImportError:
                typer.echo(
                    f"PyYAML not installed but target file {path.name} "
                    f"has YAML extension.\n"
                    f"Either `pip install PyYAML` or convert the file to "
                    f"JSON (use `derive-target --format json` to regenerate).",
                    err=True,
                )
                raise typer.Exit(2)
            spec = yaml.safe_load(text)
        else:
            spec = json.loads(text)
    except json.JSONDecodeError as e:
        typer.echo(
            f"failed to parse {path} as JSON: {e}\n"
            f"Expected shape:\n"
            f'  {{ "function": "fn_name", "virtuals": {{"32": 26, ...}} }}',
            err=True,
        )
        raise typer.Exit(2)
    except Exception as e:
        typer.echo(f"failed to parse target spec {path}: {e}", err=True)
        raise typer.Exit(2)

    # Basic shape validation
    if not isinstance(spec, dict):
        typer.echo(
            f"target spec {path} must be an object/dict at top level, "
            f"got {type(spec).__name__}.",
            err=True,
        )
        raise typer.Exit(2)
    if "virtuals" not in spec:
        typer.echo(
            f"target spec {path} is missing the 'virtuals' key.\n"
            f"Expected shape:\n"
            f'  {{ "function": "fn_name", "virtuals": {{"32": 26, ...}} }}\n'
            f"Generate a valid one with `melee-agent debug derive-target "
            f"-f FN`.",
            err=True,
        )
        raise typer.Exit(2)
    return spec


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
        _abort_function_not_in_dump(function, [f.name for f in fns])

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


def _get_asm_hunks(
    function: str, melee_root: Path, top_n: int = 5,
) -> Optional[list[list[str]]]:
    """Run checkdiff in JSON mode and group its unified-diff lines into
    hunks of consecutive +/- changes. Each hunk gets a small context
    window around it for readability.

    Returns:
        list of hunks (each a list of lines), or None if checkdiff
        couldn't run / produce JSON / find a meaningful diff.

    The 'top N' selection is by hunk size — longest hunks first, since
    those tend to encode the most informative differences.
    """
    try:
        proc = subprocess.run(
            ["python", "tools/checkdiff.py", function,
             "--format", "json", "--no-build"],
            cwd=melee_root, capture_output=True, text=True, timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    # checkdiff returns 1 when there's a mismatch (expected for stuck fns)
    if proc.returncode not in (0, 1) or not proc.stdout:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    diff_lines = data.get("diff", [])
    if not diff_lines:
        return None

    # Group lines into hunks. A hunk = a span containing +/- lines with
    # up to 1 line of intermediate context. checkdiff produces unified-
    # diff format, so context lines start with ' ' and change lines
    # start with '+'/'-'. The first 3 lines are the file header.
    body = diff_lines[3:] if len(diff_lines) >= 3 else diff_lines
    hunks: list[list[str]] = []
    cur: list[str] = []
    blank_run = 0
    for line in body:
        if line.startswith("@@"):
            # objdiff hunk header — boundary
            if cur:
                hunks.append(cur)
                cur = []
            blank_run = 0
            continue
        if line.startswith("+") or line.startswith("-"):
            cur.append(line)
            blank_run = 0
        elif cur:
            # Context line inside a hunk — keep tightly bound (one line
            # of slack), then close on the next.
            cur.append(line)
            blank_run += 1
            if blank_run >= 2:
                hunks.append(cur[:-1])  # drop the trailing context lines
                cur = []
                blank_run = 0
    if cur:
        hunks.append(cur)

    if not hunks:
        return None
    # Score by number of change lines (longer = more interesting)
    def _score(h: list[str]) -> int:
        return sum(1 for l in h if l.startswith("+") or l.startswith("-"))
    hunks.sort(key=_score, reverse=True)
    return hunks[:top_n]


def _format_asm_hunks(hunks: list[list[str]], max_lines_per_hunk: int = 12) -> str:
    """Render hunks compactly: cap each hunk at max_lines_per_hunk
    (with a '...(N more)' footer if truncated). Returns the formatted
    block, ready to print after a header.
    """
    out: list[str] = []
    for i, hunk in enumerate(hunks):
        if i > 0:
            out.append("  ---")
        n_show = min(len(hunk), max_lines_per_hunk)
        for line in hunk[:n_show]:
            out.append(f"  {line}")
        if len(hunk) > n_show:
            out.append(f"  ...({len(hunk) - n_show} more lines)")
    return "\n".join(out)


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
    asm_hunks: Annotated[
        int,
        typer.Option(
            "--asm-hunks",
            help="Also show the top N asm-diff hunks from checkdiff. "
                 "0 (default) omits. Useful when an allocator suggestion "
                 "is hard to interpret without seeing the actual text-"
                 "level diff (e.g. unexpected clrlwi from a missing "
                 "cast). Caps each hunk at ~12 lines for readability.",
        ),
    ] = 0,
) -> None:
    """Tier 4: human-readable diagnostic for stuck-function debugging.

    Reports which virtuals are at the wrong physical, why (interference,
    spill, iteration order), and suggests directions for C-source nudges.
    Hints, not guarantees — interpret in source context.

    Pass --asm-hunks N to also dump the top N asm-diff hunks from
    checkdiff. Saves switching tools when allocator-only analysis
    doesn't explain the mismatch (e.g. text diffs from a stray cast).
    """
    pcdump = _resolve_pcdump_path(pcdump, function)
    text = pcdump.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])

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

    if asm_hunks > 0:
        print()
        hunks = _get_asm_hunks(function, DEFAULT_MELEE_ROOT, top_n=asm_hunks)
        if hunks is None:
            print(f"== asm hunks ==")
            print("  (checkdiff didn't produce a diff — either the .o "
                  "isn't built yet, the function matches, or checkdiff "
                  "errored. Run `tools/checkdiff.py {fn}` for details.)"
                  .replace("{fn}", function))
        elif not hunks:
            print(f"== asm hunks ==")
            print("  (no diff)")
        else:
            print(f"== top {len(hunks)} asm hunks (by diff size) ==")
            print(_format_asm_hunks(hunks))


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
        _abort_function_not_in_dump(function, [f.name for f in fns])

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


def _count_function_defs(source: str) -> int:
    """Coarse count of function definitions in a C TU. Used as a safety
    heuristic for the --force-coalesce / --force-phys multi-fn guard:
    when N>=2, force-* without -fn is risky enough to refuse.

    Heuristic: count lines that look like `<retval> <name>(...)` at the
    top of the file (column 0), excluding obvious non-definitions
    (statements, declarations ending in `;`). Strings + comments are
    stripped first. Not exact — `static inline` definitions and
    K&R prototypes can over- or under-count — but good enough for a
    "are there multiple functions in this TU" gate.
    """
    # Strip strings + comments crudely (newline-preserving)
    cleaned = re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)
    cleaned = re.sub(r'//[^\n]*', '', cleaned)
    cleaned = re.sub(r'"[^"\n]*"', '""', cleaned)
    # Function-definition heuristic: at column 0, a line that has
    # `name(...)` followed (eventually) by `{` not `;`. Count by
    # searching for `^<type-or-attr-tokens>+<name>(...)` followed by
    # `{` somewhere within a few hundred chars (allows multiline
    # parameter lists).
    pattern = re.compile(
        r'^[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^)]*\)\s*'
        r'(?:[A-Za-z_]\w*\s*)*\{',
        re.MULTILINE,
    )
    return len(pattern.findall(cleaned))


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


def _extract_ninja_error(stdout: str, stderr: str, max_lines: int = 8) -> str:
    """Pull the relevant error lines out of a ninja failure dump.

    ninja's full output is mostly progress lines (`[N/M] ...`) that
    aren't useful. The actual error lives in lines containing 'error:',
    'FAILED:', or compiler diagnostics. Return at most `max_lines`.
    """
    lines = (stdout + "\n" + stderr).splitlines()
    relevant = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if any(marker in s.lower() for marker in (
            "error:", "failed:", "fatal:", "warning:",
            "undefined reference", "implicit declaration",
            "no such file", "cannot find",
        )):
            relevant.append(line)
        elif s.startswith(("/", "src/", "include/", "tools/")) and ":" in s:
            # File:line:col-style references — likely the diagnostic location
            relevant.append(line)
    if not relevant:
        # Fall back to last few non-empty stderr lines
        tail_stderr = [l for l in stderr.splitlines() if l.strip()][-max_lines:]
        relevant = tail_stderr or ["(no error lines captured)"]
    return "\n".join(relevant[:max_lines])


def _suggest_similar_functions(target: str, available: list[str], n: int = 5) -> list[str]:
    """Return up to `n` available function names that look similar to `target`.

    Uses Python's difflib for fuzzy ranking. Common typos (e.g. wrong
    case, missing underscore, trailing digit drift) are surfaced this way.
    """
    import difflib
    return difflib.get_close_matches(target, available, n=n, cutoff=0.5)


def _abort_function_not_in_dump(function: str, available_names: list[str]) -> None:
    """Emit a rich error message + exit. Used by every command that
    fails to find a function in a pcdump.
    """
    typer.echo(f"function '{function}' not found in pcdump.", err=True)
    suggestions = _suggest_similar_functions(function, available_names)
    if suggestions:
        typer.echo("", err=True)
        typer.echo("Did you mean one of these?", err=True)
        for s in suggestions:
            typer.echo(f"  - {s}", err=True)
    else:
        # No close matches — show a sample
        typer.echo("", err=True)
        sample = available_names[:8]
        if sample:
            typer.echo(f"Sample of {len(available_names)} functions in this dump:", err=True)
            for s in sample:
                typer.echo(f"  - {s}", err=True)
            if len(available_names) > 8:
                typer.echo(f"  ... +{len(available_names) - 8} more", err=True)
    typer.echo("", err=True)
    typer.echo(
        "Hint: check spelling, or if the source changed since the cache "
        "was generated, re-run `debug pcdump <c_file>`.",
        err=True,
    )
    raise typer.Exit(3)


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
        # Suggest similar names from report.json
        try:
            report_path = melee_root / "build" / "GALE01" / "report.json"
            if report_path.exists():
                with report_path.open() as f:
                    rdata = json.load(f)
                all_names = [fn.get("name") for u in rdata.get("units", [])
                             for fn in u.get("functions", []) if fn.get("name")]
                suggestions = _suggest_similar_functions(function, all_names)
            else:
                suggestions = []
        except Exception:
            suggestions = []
        msg = f"function '{function}' not found in report.json.\n"
        if suggestions:
            msg += "\nDid you mean one of these?\n"
            for s in suggestions:
                msg += f"  - {s}\n"
        msg += "\nTry `ninja build/GALE01/report.json` to regenerate, then retry."
        typer.echo(msg, err=True)
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


def _merge3_function(
    base_fn: str,
    candidate_fn: str,
    current_fn: str,
) -> tuple[str, list[tuple[int, str]]]:
    """3-way merge wrapper delegating to source_patch.merge3_function.

    Returns (merged_text, conflicts) where conflicts is a list of
    (approx_line_number, description) pairs. Empty conflicts = clean merge.
    """
    from ..mwcc_debug.source_patch import merge3_function
    return merge3_function(base_fn, candidate_fn, current_fn)


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
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="When --keep is set, allow overwriting manual edits that "
                 "diverge from the permuter's base.c. Without --force, "
                 "verify-perm aborts if applying the candidate would silently "
                 "revert commits you made after importing the permuter baseline. "
                 "Has no effect without --keep.",
        ),
    ] = False,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Minimum improvement (in percentage points) to consider "
                 "the candidate a win. Default 0.05 — small enough to catch "
                 "+0.05-0.09% chain wins permuter often produces, but not "
                 "so small that build-noise registers as a hit.",
        ),
    ] = 0.05,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit verification result as JSON."),
    ] = False,
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

    Safe-keep behaviour: when --keep is set and a permuter base.c is found
    (candidate.parent.parent/base.c), verify-perm performs a 3-way merge
    instead of a full replace — it applies the *diff* from base.c to the
    candidate onto the current real source.  If the merge conflicts (e.g.
    you edited the same lines the permuter mutated), the command aborts
    without writing anything.  Pass --force to fall back to a full replace
    when a merge conflict is detected.
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
    if not json_out:
        print(f"Function:       {function}")
        print(f"Real source:    {target_path}")
        print(f"Candidate:      {candidate}")
        print(f"Baseline match: {baseline_pct:.2f}%" if baseline_pct is not None
              else "Baseline match: (unknown)")

    candidate_text = candidate.read_text()
    # Locate which side the function is missing in for a clearer message.
    from ..mwcc_debug.source_patch import find_function as _find_fn
    target_text = target_path.read_text()
    cand_span = _find_fn(candidate_text, function)
    target_span = _find_fn(target_text, function)
    if cand_span is None and target_span is None:
        typer.echo(
            f"function '{function}' not found in EITHER candidate or target.\n"
            f"  Candidate: {candidate}\n"
            f"  Target:    {target_path}\n"
            f"Maybe the function name is misspelled, or both sources were "
            f"renamed.",
            err=True,
        )
        raise typer.Exit(3)
    if cand_span is None:
        typer.echo(
            f"function '{function}' is in target but NOT in candidate.\n"
            f"  Candidate: {candidate}\n"
            f"This usually means the permuter mutated a different function "
            f"in the same TU. Check the candidate source manually:\n"
            f"  grep -n '^[A-Za-z_][A-Za-z_0-9 *]*(' {candidate}",
            err=True,
        )
        raise typer.Exit(3)
    if target_span is None:
        typer.echo(
            f"function '{function}' is in candidate but NOT in target.\n"
            f"  Target: {target_path}\n"
            f"This usually means the function was renamed in the real tree, "
            f"or doesn't exist yet. Verify with:\n"
            f"  grep -n '{function}' {target_path}",
            err=True,
        )
        raise typer.Exit(3)
    # --- 3-way merge / divergence check (when --keep is set) ---
    # When --keep is set, a full replacement of the function body silently
    # discards any manual edits made AFTER the permuter's base.c was created.
    # To prevent this:
    #   1. If base.c exists (candidate.parent.parent/base.c), perform a 3-way
    #      merge: apply the diff (base → candidate) to the current real source.
    #      Conflicts abort (require --force for unsafe full-replace).
    #   2. If base.c doesn't exist but the candidate's function differs from
    #      the current real source's function at lines NOT covered by the
    #      permutation, warn loudly and require --force to proceed.
    _merge_result: Optional[str] = None  # merged target text (if 3-way used)
    _merge_strategy: str = "full-replace"
    if keep:
        base_c_path = candidate.parent.parent / "base.c"
        if base_c_path.exists():
            from ..mwcc_debug.source_patch import (
                extract_function as _extract_fn,
                replace_function as _replace_fn,
            )
            base_text = base_c_path.read_text()
            base_fn = _extract_fn(base_text, function)
            cand_fn = _extract_fn(candidate_text, function)
            real_fn = _extract_fn(target_text, function)
            if base_fn is not None and cand_fn is not None and real_fn is not None:
                merged_fn, conflicts = _merge3_function(base_fn, cand_fn, real_fn)
                if conflicts and not force:
                    # Show which lines conflict so the user knows what to fix
                    conflict_preview = "\n".join(
                        f"  line ~{ln}: {txt!r}" for ln, txt in conflicts[:8]
                    )
                    if len(conflicts) > 8:
                        conflict_preview += f"\n  ... and {len(conflicts) - 8} more"
                    typer.echo(
                        f"\n[verify-perm] ABORTED — 3-way merge conflict detected.\n"
                        f"The candidate mutates {len(conflicts)} line(s) that you "
                        f"also edited manually since the permuter baseline was "
                        f"imported. Applying the full candidate would silently "
                        f"revert those edits.\n\n"
                        f"Conflicting lines (candidate vs your edits):\n"
                        f"{conflict_preview}\n\n"
                        f"Options:\n"
                        f"  1. Re-import the permuter baseline:\n"
                        f"     cd ~/code/decomp-permuter && "
                        f"./import.py <c_file> <target.s> --function {function}\n"
                        f"  2. Apply just the diff manually from:\n"
                        f"     {base_c_path}\n"
                        f"  3. Pass --force to do a full replace (DISCARDS your "
                        f"manual edits in the function body).",
                        err=True,
                    )
                    raise typer.Exit(6)
                _merge_result = _replace_fn(target_text, function, merged_fn)
                _merge_strategy = (
                    "3-way-merge" if not conflicts else "3-way-merge-forced"
                )
                if not json_out:
                    if conflicts:
                        print(
                            f"[verify-perm] WARNING: {len(conflicts)} merge conflict(s) "
                            f"resolved by taking candidate version (--force)."
                        )
                    else:
                        print(
                            f"[verify-perm] 3-way merge: applying permuter diff "
                            f"(base→candidate) onto current source."
                        )
            # else: can't extract from base — fall through to full replace
    # --- end merge logic ---

    orig = transfer_candidate(candidate_text, target_path, function)
    if orig is None:
        # Shouldn't happen if both spans are found, but defensive
        typer.echo(
            f"unexpected error: both sides have the function but transfer "
            f"failed. Please report this with the candidate path.",
            err=True,
        )
        raise typer.Exit(3)

    # If 3-way merge produced a result, overwrite the naive full-replace.
    if _merge_result is not None:
        target_path.write_text(_merge_result)

    try:
        # Build the affected .o. checkdiff convention: report.json's unit
        # name doesn't include the "src/" prefix; ninja target does.
        obj_path = f"build/GALE01/src/{unit}.o"
        if not json_out:
            print(f"\nRebuilding {obj_path}...")
        ninja_result = subprocess.run(
            ["ninja", obj_path],
            cwd=melee_root, capture_output=True, text=True,
        )
        if ninja_result.returncode != 0:
            target_path.write_text(orig)
            err = _extract_ninja_error(ninja_result.stdout, ninja_result.stderr)
            typer.echo(
                f"ninja build failed (exit {ninja_result.returncode}). "
                f"Relevant output:\n{err}\n\n"
                f"Source reverted. The candidate doesn't compile in the real "
                f"tree — typical causes:\n"
                f"  - Permuter's base.c had macros expanded that the real "
                f"tree relies on via #include\n"
                f"  - Missing helper declarations\n"
                f"  - Type mismatches in unrelated decls that the candidate "
                f"introduced\n"
                f"For the full unfiltered ninja output, re-run with the "
                f"`ninja {obj_path}` command directly.",
                err=True,
            )
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
            if json_out:
                print(json.dumps({
                    "function": function,
                    "candidate": str(candidate),
                    "error": "could not read fresh match% after build",
                }))
            else:
                print("Could not read fresh match% after build.", file=sys.stderr)
            target_path.write_text(orig)
            raise typer.Exit(5)

        delta = new_pct - (baseline_pct or 0.0)
        # Use epsilon to tolerate float-precision noise — e.g., 91.64-91.59
        # is 0.04999999... due to IEEE rounding even though both inputs
        # display as 2-decimal numbers. Without the epsilon a real
        # +0.05 win at threshold 0.05 gets silently dropped.
        improved = delta >= threshold - 1e-9
        kept = improved and keep

        if json_out:
            print(json.dumps({
                "function": function,
                "candidate": str(candidate),
                "baseline_pct": baseline_pct,
                "new_pct": new_pct,
                "delta": delta,
                "threshold": threshold,
                "improved": improved,
                "kept": kept,
            }, indent=2))
        else:
            print(f"\nNew match:      {new_pct:.2f}%")
            print(f"Delta:          {delta:+.2f}%")

            if kept:
                print(f"\nCandidate improved match by ≥{threshold:.2f}% — leaving "
                      f"patched source in place ({target_path}).")
            elif improved:
                print(f"\nCandidate improved match by ≥{threshold:.2f}% but "
                      f"--keep was not set — reverting. Re-run with --keep to "
                      f"commit the change.")
            else:
                print(f"\nCandidate did not improve by ≥{threshold:.2f}% — "
                      f"reverting.")

        if not kept:
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
            help="Minimum improvement (percentage points) to consider a win. "
                 "Default 0.05 — catches the +0.05-0.09% chain wins that "
                 "matching agents observed permuter producing.",
        ),
    ] = 0.05,
    keep_best: Annotated[
        bool,
        typer.Option(
            "--keep-best",
            help="If the best ordering improves match% by ≥threshold, "
                 "leave it applied. Default reverts to original.",
        ),
    ] = False,
    iterate: Annotated[
        bool,
        typer.Option(
            "--iterate",
            help="After finding the best ordering, apply it and re-run "
                 "the enumeration from the new baseline. Repeats until no "
                 "improvement found (or --iterate-max reached). Stacks "
                 "small wins below the per-iteration threshold. Implies "
                 "--keep-best.",
        ),
    ] = False,
    iterate_max: Annotated[
        int,
        typer.Option(
            "--iterate-max",
            help="Cap on --iterate rounds. Prevents infinite loops if a "
                 "win-finding cycle emerges. Default 10.",
        ),
    ] = 10,
    iterate_threshold: Annotated[
        float,
        typer.Option(
            "--iterate-threshold",
            help="Per-round threshold when --iterate is set. Smaller than "
                 "--threshold lets the loop stack micro-wins (0.04% type) "
                 "that don't qualify as a single big win.",
        ),
    ] = 0.01,
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
        if iterate:
            print(f"Mode:        --iterate (max {iterate_max} rounds, "
                  f"per-round threshold {iterate_threshold:.3f}%)")
        print()

    # When --iterate is set we want to stack wins. Each round:
    #   1. Re-read `current` as the baseline-of-the-round
    #   2. Sweep all candidates against it
    #   3. If best > iterate_threshold, apply it as the new baseline
    #   4. Else, terminate the iterate loop
    # If --iterate is NOT set, we just do one round and use the larger
    # --threshold to decide whether to apply (controlled by --keep-best).

    def run_one_round(round_idx: int, current_text: str,
                      round_baseline: float, round_threshold: float
                      ) -> tuple[Optional[str], float, Optional[list[int]], list[dict]]:
        """Run one enumeration sweep starting from `current_text`.

        Returns (best_label, best_pct, best_perm, per-candidate results).
        """
        r_results: list[dict] = []
        r_best_pct = round_baseline
        r_best_label: Optional[str] = None
        r_best_perm: Optional[list[int]] = None

        if iterate and not json_out:
            print(f"== Round {round_idx} ==")
            print(f"  Baseline: {round_baseline:.2f}%")

        for label, perm in candidates:
            patched = reorder_decls_in_function(current_text, function, perm)
            if patched is None:
                continue
            target_path.write_text(patched)
            pct = _build_and_match(unit, function, melee_root)
            target_path.write_text(current_text)  # revert before next iter
            if pct is None:
                if not json_out:
                    print(f"  {label}: BUILD FAILED")
                r_results.append({"label": label, "match_pct": None,
                                  "delta": None})
                continue
            delta = pct - round_baseline
            r_results.append({"label": label, "match_pct": pct,
                              "delta": delta})
            tag = ""
            # epsilon: 91.64-91.59 = 0.04999... in IEEE float; without
            # tolerance a real +0.05 win at threshold 0.05 silently drops.
            if delta >= round_threshold - 1e-9:
                tag = "  WIN"
                if pct > r_best_pct:
                    r_best_pct = pct
                    r_best_label = label
                    r_best_perm = perm
            elif delta > 0:
                tag = "  (improved)"
            elif delta < 0:
                tag = "  (worse)"
            if not json_out:
                print(f"  {label}: {pct:.2f}%  delta={delta:+.2f}%{tag}")
        return r_best_label, r_best_pct, r_best_perm, r_results

    all_rounds: list[dict] = []
    current = orig
    current_pct = baseline
    applied_chain: list[str] = []  # labels of rounds that we kept

    try:
        if not iterate:
            # Single sweep — preserve previous behavior.
            best_label, best_pct, best_perm, results = run_one_round(
                round_idx=0,
                current_text=current,
                round_baseline=baseline,
                round_threshold=threshold,
            )
            all_rounds.append({
                "round": 0,
                "baseline_pct": baseline,
                "best_label": best_label,
                "best_pct": best_pct,
                "results": results,
            })
        else:
            # Iterate mode: each round must clear iterate_threshold to
            # continue. We always commit the win for the round (writes
            # back to disk before next sweep).
            for r_idx in range(iterate_max):
                r_best_label, r_best_pct, r_best_perm, r_results = (
                    run_one_round(
                        round_idx=r_idx,
                        current_text=current,
                        round_baseline=current_pct,
                        round_threshold=iterate_threshold,
                    )
                )
                all_rounds.append({
                    "round": r_idx,
                    "baseline_pct": current_pct,
                    "best_label": r_best_label,
                    "best_pct": r_best_pct,
                    "results": r_results,
                })
                if r_best_label is None or r_best_perm is None:
                    if not json_out:
                        print(f"  No more wins; stopping iterate loop.")
                    break
                # Apply the round's winner and use it as the next baseline
                patched = reorder_decls_in_function(
                    current, function, r_best_perm
                )
                if patched is None:
                    if not json_out:
                        print(f"  Could not re-apply best perm "
                              f"({r_best_label}); stopping.")
                    break
                current = patched
                current_pct = r_best_pct
                applied_chain.append(r_best_label)
                if not json_out:
                    print(f"  ** Applied {r_best_label}; new baseline "
                          f"{current_pct:.2f}%")
                    print()
            # After the loop, `current` holds the latest patched text.
            # The top-level best_pct/best_label reflect the cumulative
            # state vs the original baseline.
            best_pct = current_pct
            best_label = (" + ".join(applied_chain)
                          if applied_chain else None)
            best_perm = None  # n/a in iterate mode — we already applied
    finally:
        # Decide whether the disk-state to keep is the accumulated `current`
        # (iterate mode with at least one winning round; or single-sweep
        # with --keep-best after a successful win) or the original.
        had_wins = bool(applied_chain) if iterate else (
            keep_best and best_pct > baseline
        )
        keep_final = had_wins and current != orig
        if keep_final:
            target_path.write_text(current)
            if iterate and not json_out:
                typer.echo(
                    f"[mwcc_debug] iterate kept {len(applied_chain)} "
                    f"winning round(s).",
                    err=True,
                )
        else:
            # No wins (or single-sweep without --keep-best). Always revert
            # to the original, regardless of any intermediate writes the
            # candidate loop might have done. The per-candidate revert in
            # run_one_round should leave disk at the round's baseline
            # already, but write `orig` defensively so we're independent
            # of that contract.
            current_disk = target_path.read_text()
            if current_disk != orig:
                target_path.write_text(orig)
                if not json_out:
                    typer.echo(
                        f"[mwcc_debug] reverted source (no wins above "
                        f"threshold).",
                        err=True,
                    )
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
            "iterate": iterate,
            "applied_chain": applied_chain if iterate else [],
            "rounds": all_rounds,
        }, indent=2))
        return

    print()
    if best_label is None:
        if iterate:
            print(f"No wins clearing iterate-threshold "
                  f"{iterate_threshold:.3f}% in any round.")
        else:
            print(f"No ordering improved match by ≥{threshold:.2f}%.")
        return
    print(f"Best: {best_label} → {best_pct:.2f}% "
          f"(delta {best_pct - baseline:+.2f}%)")

    if iterate:
        print(f"Applied {len(applied_chain)} round(s) to {target_path}. "
              f"Verify with `git diff`.")
    elif keep_best and best_perm is not None:
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
            help="Minimum improvement (percentage points) to consider a "
                 "win. Default 0.05 — catches the +0.05-0.09% chain "
                 "wins that hide at the previous 0.10 default.",
        ),
    ] = 0.05,
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
            # epsilon: float-precision tolerance so +0.05 wins at
            # threshold 0.05 don't silently drop.
            if delta >= threshold - 1e-9:
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
        marker = "WIN" if r.delta >= threshold - 1e-9 else "    "
        print(f"  {marker}  {r.match_pct:.2f}%  ({r.delta:+.2f}%)  "
              f"{r.path.parent.name}/source.c")

    n_wins = sum(1 for r in ok_results if r.delta >= threshold - 1e-9)
    n_build_failed = sum(1 for r in results if r.status == "build-failed")
    n_no_fn = sum(1 for r in results if r.status == "no-function")
    print()
    print(f"Summary: {n_wins} winners (≥{threshold:.2f}% over baseline), "
          f"{n_build_failed} build failures, {n_no_fn} missing function")

    if apply_best and best is not None and best.delta >= threshold - 1e-9:
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
    asm_hunks: Annotated[
        int,
        typer.Option(
            "--asm-hunks",
            help="Also show the top N asm-diff hunks from checkdiff. "
                 "0 (default) omits. Saves switching tools when "
                 "allocator-level analysis doesn't explain the mismatch.",
        ),
    ] = 0,
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
      6. Asm hunks (if --asm-hunks N) — text-level diff samples
      7. Next steps — ranked by cost/likelihood
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

    if asm_hunks > 0:
        hunks = _get_asm_hunks(function, melee_root, top_n=asm_hunks)
        if hunks is None:
            print(f"== Asm hunks ==")
            print(f"  (checkdiff didn't produce a diff — either matching, "
                  f"not built, or errored. Try `tools/checkdiff.py "
                  f"{function}` directly.)")
            print()
        elif hunks:
            print(f"== Top {len(hunks)} asm hunks (by diff size) ==")
            print(_format_asm_hunks(hunks))
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

    # Step 1: suggest-casts (with auto-verify for HIGH-severity findings)
    src_text = src.read_text() if src.exists() else ""
    cast_warnings = audit_function_casts(src_text, function)
    high_casts = [w for w in cast_warnings if w.severity == "high"]
    med_casts = [w for w in cast_warnings if w.severity == "medium"]
    cast_verify_secs = len(high_casts) * 6
    if not json_out:
        if high_casts:
            print(f"[1] Cast audit (~{cast_verify_secs}s including verify)...")
        else:
            print(f"[1] Cast audit (free, ~ms)...")

    # Auto-verify each HIGH cast by drop-test: patch src, compile, revert.
    # Avoids false-positive WIN AVAILABLE when the cast is heuristically
    # suspicious but removal is actually a no-op for codegen.
    cast_verify_results: list[dict] = []  # per-cast verify record
    if high_casts and src.exists():
        orig_src = src.read_text()
        try:
            for w in high_casts:
                # Build the drop pattern: remove "(cast_type) " prefix on the
                # cast's line.  We match the exact text the linter found.
                cast_text = f"({w.cast_type}) {w.inner_expr}"
                if cast_text not in orig_src:
                    # Fallback: maybe there's no space after the cast type.
                    cast_text = f"({w.cast_type}){w.inner_expr}"
                if cast_text not in orig_src:
                    cast_verify_results.append({
                        "line": w.line,
                        "cast_type": w.cast_type,
                        "inner_expr": w.inner_expr,
                        "call_target": w.call_target,
                        "pct_before": baseline,
                        "pct_after": None,
                        "delta": None,
                        "note": "could not locate cast text in source",
                    })
                    continue
                patched = orig_src.replace(cast_text, w.inner_expr, 1)
                src.write_text(patched)
                pct_after = _build_and_match(unit, function, melee_root)
                src.write_text(orig_src)  # revert immediately
                delta = (pct_after - baseline) if pct_after is not None else None
                cast_verify_results.append({
                    "line": w.line,
                    "cast_type": w.cast_type,
                    "inner_expr": w.inner_expr,
                    "call_target": w.call_target,
                    "pct_before": baseline,
                    "pct_after": pct_after,
                    "delta": delta,
                    "note": (
                        "WIN" if (delta is not None and delta > 0.0)
                        else "no change" if (delta is not None and delta == 0.0)
                        else "regression" if (delta is not None and delta < 0.0)
                        else "build failed"
                    ),
                })
        finally:
            # Guarantee revert even if an exception was raised mid-loop.
            src.write_text(orig_src)
            subprocess.run(
                ["ninja", f"build/GALE01/src/{unit}.o",
                 "build/GALE01/report.json"],
                cwd=melee_root, capture_output=True,
            )

    if not json_out:
        if high_casts:
            print(f"    ! {len(high_casts)} HIGH-severity cast(s) found — "
                  f"auto-verified:")
            for w, vr in zip(high_casts[:3], cast_verify_results[:3]):
                delta_str = ""
                if vr["delta"] is not None:
                    if vr["delta"] > 0.0:
                        delta_str = (f"  → drop test: {vr['pct_before']:.2f}% → "
                                     f"{vr['pct_after']:.2f}% "
                                     f"(+{vr['delta']:.2f}%, WIN)")
                    else:
                        delta_str = (f"  → drop test: {vr['pct_before']:.2f}% → "
                                     f"{vr['pct_after']:.2f}% "
                                     f"({vr['delta']:+.2f}%, false positive)")
                elif vr.get("note") == "could not locate cast text in source":
                    delta_str = "  → (could not locate cast in source; skipped)"
                else:
                    delta_str = "  → (build failed during verify)"
                print(f"      - line {w.line}: ({w.cast_type}) "
                      f"{w.inner_expr} → {w.call_target}")
                if delta_str:
                    print(f"      {delta_str}")
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

    # Verdict — use verified cast results (not raw heuristic count) so we
    # don't produce false-positive WIN AVAILABLE on no-op casts.
    #
    # A cast counts as a win only if its verified delta is strictly positive.
    # If cast_verify_results is empty (no high casts, or source not found),
    # has_cast_win is False.
    verified_cast_wins = [
        vr for vr in cast_verify_results
        if vr.get("delta") is not None and vr["delta"] > 0.0
    ]
    has_cast_win = bool(verified_cast_wins)
    decl_delta = decl_best_pct - baseline if decl_best_label else 0.0
    has_decl_win = decl_delta >= 0.05

    if has_cast_win or has_decl_win:
        verdict = "WIN AVAILABLE"
        recommendations: list[str] = []
        if has_cast_win:
            win_lines = ", ".join(
                f"line {vr['line']}" for vr in verified_cast_wins[:3]
            )
            if len(verified_cast_wins) > 3:
                win_lines += f" +{len(verified_cast_wins) - 3} more"
            recommendations.append(
                f"Drop {len(verified_cast_wins)} HIGH-severity cast(s) with "
                f"verified improvement ({win_lines}). "
                f"Run `melee-agent debug suggest-casts {function}` for details."
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
            "cast_verify_results": cast_verify_results,
            "decl_best_label": decl_best_label,
            "decl_best_pct": decl_best_pct,
            "decl_results": decl_results,
            "recommendations": recommendations,
        }, indent=2))
        return

    print(f"== VERDICT: {verdict} ==")
    for rec in recommendations:
        print(f"  {rec}")


@debug_app.command(name="rank-callees")
def rank_callees(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze (required)",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Predict the callee-save cascade for a function before compiling.

    Lists callee-save virtuals (those that got r13-r31) sorted by
    ig_idx descending — the order MWCC's simplifygraph processes them.
    Higher ig_idx = colored first = gets r31, r30, r29, ... via
    top-down nonvolatile dispense.

    Useful for predicting the param-iter-ceiling: if your target wants
    a parameter virtual (low ig_idx) at r31 but several locals have
    higher ig_idx, the cascade will give those locals r31 first and
    the parameter will land lower. No source-level fix.
    """
    pcdump = _resolve_pcdump_path(pcdump, function)
    text = pcdump.read_text()
    events_list = parse_hook_events(text)
    fn_events = find_function(events_list, function)
    if fn_events is None or not fn_events.colorgraph_sections:
        # Fall back to analyze-derived data if no hook events
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is None:
            _abort_function_not_in_dump(function, [f.name for f in fns])
        infos = analyze_function(fn)
        # No ig_idx info from this path; only sort by virtual num
        callee_saves = [v for v in infos
                        if v.physical is not None and 13 <= v.physical <= 31]
        callee_saves.sort(key=lambda v: -v.virtual)
        if json_out:
            print(json.dumps({
                "function": function,
                "source": "analyze (no hook events)",
                "callees": [{
                    "virtual": v.virtual,
                    "ig_idx": None,
                    "physical": v.physical,
                } for v in callee_saves],
            }, indent=2))
            return
        print(f"Function: {function}")
        print(f"Source:   analyze (no COLORGRAPH DECISIONS in dump)")
        print()
        if not callee_saves:
            print("No callee-save virtuals (r13-r31) found.")
            return
        print(f"{'virtual':>8}  {'phys':>4}  {'note':<30}")
        for v in callee_saves:
            note = "param-like (low virtual #)" if v.virtual <= 34 else ""
            print(f"  r{v.virtual:<6}  r{v.physical:<3}  {note}")
        return

    # Build the cascade from COLORGRAPH DECISIONS sections.
    # Decisions are emitted in iter order (which is descending ig_idx order
    # for the virtual-reg nodes).
    rows: list[dict] = []
    for sec in fn_events.colorgraph_sections:
        for d in sec.decisions:
            if d.ig_idx < 0:
                continue  # physical-reg sentinel nodes — skip
            if not (13 <= d.assigned_reg <= 31):
                continue  # not a callee-save
            rows.append({
                "iter": d.iter_idx,
                "ig_idx": d.ig_idx,
                "assigned_reg": d.assigned_reg,
                "degree": d.degree,
                "class_id": sec.class_id,
            })

    # Sort by ig_idx descending (= iter order = coloring order)
    rows.sort(key=lambda r: -r["ig_idx"])

    # Top-down dispense prediction: the i-th popped virtual gets r(31-i)
    # if workingMask is empty. (workingMask non-empty would pick a caller-
    # save first; the cascade prediction is only meaningful for callee-save-
    # bound virtuals — which is what we filtered to above.)
    expected_seq = list(range(31, 12, -1))  # r31, r30, ..., r13

    enriched = []
    for i, r in enumerate(rows):
        expected = expected_seq[i] if i < len(expected_seq) else None
        is_param_like = r["ig_idx"] <= 34
        match = (expected is not None and r["assigned_reg"] == expected)
        enriched.append({
            **r,
            "expected": expected,
            "expected_match": match,
            "is_param_like": is_param_like,
        })

    if json_out:
        print(json.dumps({
            "function": function,
            "source": "COLORGRAPH DECISIONS",
            "callees": enriched,
        }, indent=2))
        return

    print(f"Function: {function}")
    print(f"Source:   COLORGRAPH DECISIONS")
    print()
    print(
        f"  Predicting the callee-save cascade. Higher ig_idx → colored "
        f"first → gets top of dispense pool."
    )
    print()
    print(
        f"  {'ig_idx':>7}  {'phys':>4}  {'predict':>7}  {'deg':>3}  notes"
    )
    print(f"  {'-'*7}  {'-'*4}  {'-'*7}  {'-'*3}  -----")
    for r in enriched:
        notes = []
        if r["is_param_like"]:
            notes.append("param-like (low ig_idx)")
        if r["expected"] is not None and not r["expected_match"]:
            notes.append(f"got r{r['assigned_reg']} not r{r['expected']}")
        notes_str = "; ".join(notes)
        expected_str = (f"r{r['expected']}" if r["expected"] is not None
                        else "-")
        print(
            f"  {r['ig_idx']:>7}  r{r['assigned_reg']:<3}  {expected_str:>7}  "
            f"{r['degree']:>3}  {notes_str}"
        )

    # Footer: surface param-iter-ceiling if any
    params = [r for r in enriched if r["is_param_like"]]
    if any(p["assigned_reg"] != p.get("expected", -1) for p in params):
        print()
        print(
            "Note: at least one param-like virtual (low ig_idx) landed "
            "below its predicted top-down position. This is the typical "
            "param-iter-ceiling signature — see `debug pattern-catalog "
            "param-iter-ceiling` for the full pattern."
        )


@debug_app.command(name="match-iter-first")
def match_iter_first(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze (required)",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    regs: Annotated[
        str,
        typer.Option(
            "--regs",
            help="Comma-separated physical regs to report on "
                 "(default: r31,r30,r29,r28).",
        ),
    ] = "r31,r30,r29,r28",
    asm: Annotated[
        Optional[Path],
        typer.Option(
            "--asm",
            help="Override path to expected .s file. "
                 "Auto-resolves via report.json.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Recommend --force-iter-first arguments by reading the expected .s.

    For each physical register in --regs, finds the first instruction in
    the expected output that defines it (post-prologue), structurally
    aligns that instruction to the current pcdump's pre-coloring pass,
    and reports the virtual register (= ig_idx in MWCC's IG).

    Useful for local-vs-local iter-order cascades where rank-callees
    can't tell which local "should have" gotten r31. Pipe the output's
    ig_idx list into --force-iter-first.
    """
    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    pcdump_text = pcdump_path.read_text()

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"function '{function}' not found in report.json. "
            f"Run `ninja build/GALE01/report.json` and retry.",
            err=True,
        )
        raise typer.Exit(2)

    if asm is None:
        asm_path = melee_root / "build" / "GALE01" / "asm" / f"{unit}.s"
    else:
        asm_path = asm
    if not asm_path.exists():
        typer.echo(
            f"expected .s not found: {asm_path}\n"
            f"Run `python configure.py && ninja` to build it.",
            err=True,
        )
        raise typer.Exit(3)

    asm_text = asm_path.read_text()
    asm_fn = asm_extract_function(asm_text, function)
    if asm_fn is None:
        typer.echo(
            f"function '{function}' not found in {asm_path}",
            err=True,
        )
        raise typer.Exit(3)

    prologue_end = asm_parse_prologue_end(asm_fn.instructions)
    body = asm_fn.instructions[prologue_end:]

    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre_pass = fn.last_precolor_pass()
    if pre_pass is None:
        typer.echo(
            f"no pre-coloring pass found in pcdump for {function}",
            err=True,
        )
        raise typer.Exit(4)

    # Parse --regs
    reg_list: list[int] = []
    for token in regs.split(","):
        token = token.strip()
        if not token:
            continue
        if not token.startswith("r"):
            typer.echo(f"invalid reg token: {token}", err=True)
            raise typer.Exit(2)
        try:
            reg_list.append(int(token[1:]))
        except ValueError:
            typer.echo(f"invalid reg token: {token}", err=True)
            raise typer.Exit(2)

    results: list[dict] = []
    for reg in reg_list:
        expected_def = asm_find_first_def(body, target_reg=reg)
        if expected_def is None:
            results.append({
                "reg": reg,
                "status": "unused",
                "note": f"r{reg} never used as a destination in expected",
            })
            continue
        pos, expected_ist = expected_def
        match = match_virtual_for_expected_def(
            expected_ist=expected_ist,
            expected_position=pos,
            pre_pass=pre_pass,
        )
        if match is None:
            results.append({
                "reg": reg,
                "status": "no_match",
                "note": f"no structural match in pre-coloring for "
                        f"`{expected_ist.opcode} {expected_ist.operands}`",
            })
            continue
        results.append({
            "reg": reg,
            "status": "ok",
            "ig_idx": match.ig_idx,
            "virtual": match.virtual,
            "instr_idx": match.instruction_index,
            "opcode": expected_ist.opcode,
            "operands": expected_ist.operands,
            "confidence": match.confidence,
        })

    if json_out:
        print(json.dumps({
            "function": function,
            "unit": unit,
            "results": results,
        }, indent=2))
        return

    print(f"Function: {function}")
    print(f"Unit:     {unit}")
    print(f"ASM:      {asm_path.relative_to(melee_root)}")
    print()
    print(f"Expected iter-first targets:")
    ig_indices: list[int] = []
    for r in results:
        reg_str = f"r{r['reg']}"
        if r["status"] == "ok":
            print(
                f"  {reg_str} <- ig_idx {r['ig_idx']:<4} "
                f"(virt r{r['virtual']}, instr {r['instr_idx']}: "
                f"{r['opcode']} {r['operands']}) [{r['confidence']}]"
            )
            ig_indices.append(r["ig_idx"])
        else:
            print(f"  {reg_str} - {r['note']}")
    if ig_indices:
        ig_csv = ",".join(str(i) for i in ig_indices)
        print()
        print(f"Try:")
        print(
            f"  melee-agent debug pcdump <source.c> "
            f"--force-iter-first {ig_csv}"
        )


@debug_app.command(name="name-magic")
def name_magic(
    o_file: Annotated[
        Path,
        typer.Argument(help="Path to the .o file to post-process."),
    ],
    mapping: Annotated[
        Optional[str],
        typer.Option(
            "--map", "-m",
            help="Mapping of magic constant value to symbol name. "
                 "Format: '<value>=<name>,<value>=<name>'. <value> is "
                 "'s32' (0x4330000080000000), 'u32' (0x4330000000000000), "
                 "or a hex/decimal literal. May be specified once with "
                 "multiple pairs.",
        ),
    ] = None,
    out: Annotated[
        Optional[Path],
        typer.Option(
            "--out", "-o",
            help="Output path (default: rewrite in place).",
        ),
    ] = None,
    list_only: Annotated[
        bool,
        typer.Option(
            "--list",
            help="Just list anonymous .sdata2 symbols and their values; "
                 "don't rename.",
        ),
    ] = False,
    globalize: Annotated[
        bool,
        typer.Option(
            "--globalize/--no-globalize",
            help="After renaming, promote each new symbol to global "
                 "(STB_GLOBAL) via objcopy --globalize-symbol. Default "
                 "true — the expected .o always has these symbols as "
                 "global, so local symbols produce a symbol-binding diff "
                 "even after renaming.",
        ),
    ] = True,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Rename anonymous @N symbols in a .o's .sdata2 to user-supplied names.

    Use case: MWCC's int-to-float cast emits an anonymous symbol like
    `@491` for the 0x4330000080000000 magic constant. The matching .o
    references this data via a named global like `mnVibration_804DC018`
    (from symbols.txt). The relocation target name diff blocks byte
    matching even when the data is identical.

    With `--map s32=mnVibration_804DC018`, this tool finds the
    anonymous symbol whose .sdata2 value matches the s32 int-to-float
    bias and renames it via objcopy.  The new symbol is also promoted to
    global (``STB_GLOBAL``) by default, matching the binding in the
    expected .o.  Pass ``--no-globalize`` to skip this step.

    Use `--list` to see what's available without renaming.
    """
    from ..mwcc_debug.o_rewriter import (
        find_all_anonymous_sdata2_symbols,
        globalize_symbols,
        parse_mapping,
        rename_magic_symbols,
    )

    if not o_file.exists():
        typer.echo(f".o file not found: {o_file}", err=True)
        raise typer.Exit(2)

    if list_only:
        symbols = find_all_anonymous_sdata2_symbols(o_file)
        if json_out:
            print(json.dumps({
                "o_file": str(o_file),
                "symbols": [{
                    "name": s.name,
                    "offset": s.offset,
                    "value": f"0x{s.value:016x}" if s.size == 8
                             else f"0x{s.value:08x}",
                    "size": s.size,
                } for s in symbols],
            }, indent=2))
            return
        if not symbols:
            print(f"No anonymous .sdata2 symbols found in {o_file}")
            return
        print(f"Anonymous .sdata2 symbols in {o_file}:")
        print(f"  {'name':<10}  {'offset':>6}  {'sz':>2}  {'value':<18}  notes")
        print(f"  {'-'*10}  {'-'*6}  {'-'*2}  {'-'*18}  -----")
        import struct as _struct
        for sym in symbols:
            note = ""
            if sym.size == 8:
                value_str = f"0x{sym.value:016x}"
                if sym.value == 0x4330000080000000:
                    note = "int-to-float bias (signed)"
                elif sym.value == 0x4330000000000000:
                    note = "int-to-float bias (unsigned)"
            elif sym.size == 4:
                value_str = f"0x{sym.value:08x}"
                # Try interpreting as float for the note
                try:
                    f_val = _struct.unpack(">f",
                                           _struct.pack(">I", sym.value))[0]
                    note = f"float ≈ {f_val:g}"
                except Exception:
                    pass
            else:
                value_str = f"0x{sym.value:x}"
            print(
                f"  {sym.name:<10}  {sym.offset:>6}  {sym.size:>2}  "
                f"{value_str:<18}  {note}"
            )
        return

    if mapping is None:
        typer.echo(
            "no --map provided. Use --list to see available symbols.",
            err=True,
        )
        raise typer.Exit(2)

    try:
        value_to_name = parse_mapping(mapping)
    except ValueError as e:
        typer.echo(f"invalid --map: {e}", err=True)
        raise typer.Exit(2)

    try:
        renames = rename_magic_symbols(
            o_file, value_to_name, out_path=out
        )
    except FileNotFoundError as e:
        typer.echo(
            f"objcopy not found: {e}. Install devkitPPC or pass a custom "
            f"path via the o_rewriter module.",
            err=True,
        )
        raise typer.Exit(5)
    except subprocess.CalledProcessError as e:
        typer.echo(f"objcopy failed: {e}", err=True)
        raise typer.Exit(5)

    # Promote renamed symbols to global so the binding matches the expected
    # .o.  The rename step leaves them local (MWCC emits anonymous symbols as
    # STB_LOCAL); the expected .o always has them STB_GLOBAL.
    globalized: list[str] = []
    if globalize and renames:
        target_path = out if out is not None else o_file
        new_names = [new for _, new in renames]
        try:
            globalize_symbols(target_path, new_names)
            globalized = new_names
        except FileNotFoundError as e:
            typer.echo(
                f"objcopy not found during globalize: {e}. "
                f"Rename succeeded but symbols remain local.",
                err=True,
            )
        except subprocess.CalledProcessError as e:
            typer.echo(
                f"objcopy --globalize-symbol failed: {e}. "
                f"Rename succeeded but symbols remain local.",
                err=True,
            )

    if json_out:
        print(json.dumps({
            "o_file": str(o_file),
            "out": str(out) if out else str(o_file),
            "renames": [
                {"old": old, "new": new} for old, new in renames
            ],
            "globalized": globalized,
        }, indent=2))
        return

    target = out if out is not None else o_file
    if not renames:
        print(
            f"No matching anonymous symbols found in {o_file}. "
            f"Use --list to see what's available."
        )
        return
    print(f"Renamed {len(renames)} symbol(s) in {target}:")
    for old, new in renames:
        glob_note = " (globalized)" if new in globalized else ""
        print(f"  {old} -> {new}{glob_note}")


@debug_app.command(name="gen-permuter-config")
def gen_permuter_config(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to generate permuter config for (required).",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Omit to auto-resolve via --function "
                 "from the cache.",
        ),
    ] = None,
    pattern: Annotated[
        Optional[str],
        typer.Option(
            "--pattern", "-p",
            help="Override pattern auto-detection. Use a name from "
                 "`debug pattern-catalog` (e.g. decl-order, alias-split).",
        ),
    ] = None,
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec (YAML or JSON, from `debug derive-target`). "
                 "Auto-detection needs this to identify wrong virtuals. "
                 "Without it, falls back to stock settings unless "
                 "--pattern is provided.",
        ),
    ] = None,
    out: Annotated[
        Optional[Path],
        typer.Option(
            "--out", "-o",
            help="Output path. Default: "
                 "<perm-root>/nonmatchings/<function>/settings.toml",
        ),
    ] = None,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    print_only: Annotated[
        bool,
        typer.Option(
            "--print",
            help="Print rendered TOML to stdout instead of writing.",
        ),
    ] = False,
    merge: Annotated[
        bool,
        typer.Option(
            "--merge",
            help="Preserve existing [weight_overrides] keys not touched "
                 "by the pattern profile. Default: overwrite.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Generate config even for skip-marked patterns "
                 "(e.g. param-iter-ceiling). Use only if you know why.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit a JSON summary of the action."),
    ] = False,
) -> None:
    """Generate a decomp-permuter settings.toml tuned for the detected pattern.

    Pairs with `debug triage-perm` to close the integration loop: this
    command BIASES which mutations permuter prefers based on mwcc-debug's
    pattern detection, then triage-perm filters out base.c-vs-real-tree
    drift on the resulting winners.

    For patterns marked as structural ceilings (param-iter-ceiling),
    this command refuses to generate a config and explains why — permuter
    cannot fix those from C source. Use `--force` to override.

    For `decl-order` specifically, you should ALSO run
    `debug enumerate-decl-orders` first — it's deterministic and
    ~100x faster than letting permuter rediscover decl-order rounds.
    """
    from ..mwcc_debug.patterns import (
        PATTERNS,
        get_pattern,
        patterns_for_category,
    )
    from ..mwcc_debug.permuter_config import (
        PatternSkippedError,
        build_spec,
        parse_existing_overrides,
        render_settings_toml,
        write_settings_toml,
    )

    melee_root = DEFAULT_MELEE_ROOT

    # Determine the pattern
    detected_via: str = ""
    selected: Optional = None  # type: ignore[type-arg]
    if pattern is not None:
        # Explicit pattern — skip pcdump resolution entirely. Useful when
        # the function isn't yet in report.json (e.g. setting up permuter
        # for a newly-imported function).
        selected = get_pattern(pattern)
        if selected is None:
            typer.echo(
                f"unknown pattern: {pattern!r}. "
                f"Run `melee-agent debug pattern-catalog` to list.",
                err=True,
            )
            raise typer.Exit(2)
        detected_via = "--pattern flag"
    else:
        # Auto-detect via guide/suggest infrastructure
        pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
        text = pcdump_path.read_text()
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is None:
            _abort_function_not_in_dump(function, [f.name for f in fns])
        events_list = parse_hook_events(text)
        events = find_function(events_list, function)
        if target is not None:
            target_spec = _load_target_spec(target)
        else:
            target_spec = {"virtuals": {}}
        result = score_function(fn, target_spec, events=events)
        suggestions = suggest(fn, result, events=events)

        # Walk suggestions in severity order. For each, find the best-fit
        # pattern. Prefer permuter_skip patterns (structural ceilings)
        # when they match — those need a different message.
        for s in suggestions:
            candidates = patterns_for_category(s.category)
            # Prefer skip-marked patterns (they're more specific signals)
            skip_candidates = [p for p in candidates if p.permuter_skip]
            if skip_candidates:
                selected = skip_candidates[0]
                detected_via = (
                    f"suggestion category={s.category!r} (severity={s.severity})"
                )
                break
            # Otherwise pick the first pattern with weights
            for p in candidates:
                if p.permuter_weights:
                    selected = p
                    detected_via = (
                        f"suggestion category={s.category!r} "
                        f"(severity={s.severity})"
                    )
                    break
            if selected is not None:
                break

        if selected is None and suggestions:
            # Suggestions exist but no pattern has weights for any category
            detected_via = "no pattern matched any suggestion category"

    # Resolve output path
    if out is None:
        if not perm_root.exists():
            typer.echo(
                f"--perm-root {perm_root} does not exist. "
                f"Clone decomp-permuter there or pass --out explicitly.",
                err=True,
            )
            raise typer.Exit(2)
        fn_dir = perm_root / "nonmatchings" / function
        if not fn_dir.exists() and not print_only:
            typer.echo(
                f"{fn_dir} does not exist. "
                f"Run `./import.py <c_file> <s_file>` in {perm_root} "
                f"first to set up this function.",
                err=True,
            )
            raise typer.Exit(2)
        out = fn_dir / "settings.toml"

    # Read existing overrides if present (for --merge)
    existing_overrides: dict[str, float] = {}
    if out.exists() and merge:
        existing_overrides = parse_existing_overrides(out.read_text())

    # Build the spec
    try:
        spec = build_spec(
            function,
            selected,
            existing_overrides=existing_overrides,
            merge=merge,
            force=force,
        )
    except PatternSkippedError:
        # Structural ceiling — print guidance instead of writing
        assert selected is not None
        if json_out:
            print(json.dumps({
                "function": function,
                "pattern": selected.name,
                "detected_via": detected_via,
                "action": "skipped",
                "reason": "permuter_skip=True (Tier 6 structural ceiling)",
            }, indent=2))
            raise typer.Exit(1)
        typer.echo(
            f"Pattern: {selected.name} "
            f"(detected via {detected_via})",
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "This is a Tier 6 structural ceiling — permuter cannot fix "
            "it from C source. The parameter virtual gets a low ig_idx "
            "by C semantics, and locals always win the top callee-saves.",
            err=True,
        )
        typer.echo("", err=True)
        typer.echo(
            "Recommended: confirm via `debug match-iter-first -f "
            f"{function}` and document the function as Tier 6.",
            err=True,
        )
        typer.echo(
            "Pass --force to gen-permuter-config if you want a config "
            "anyway (no permuter_weights will be applied).",
            err=True,
        )
        raise typer.Exit(1)

    # Render
    rendered = render_settings_toml(spec)

    if print_only:
        if json_out:
            print(json.dumps({
                "function": function,
                "pattern": spec.pattern_name,
                "detected_via": detected_via,
                "action": "printed",
                "overrides": spec.weight_overrides,
                "toml": rendered,
            }, indent=2))
            return
        print(rendered, end="")
        return

    write_settings_toml(spec, out)

    # Side-effect: fix the compile.sh for macOS+wine if it has the
    # known import.py path-handling bug. Quiet if not applicable;
    # one-liner note if a fix was applied.
    from ..mwcc_debug.fix_perm_compile import fix_perm_dir
    compile_fix = fix_perm_dir(out.parent)

    if json_out:
        print(json.dumps({
            "function": function,
            "pattern": spec.pattern_name,
            "detected_via": detected_via,
            "action": "wrote",
            "path": str(out),
            "overrides": spec.weight_overrides,
            "compile_sh_fix": {
                "action": compile_fix.action,
                "reason": compile_fix.reason,
            },
        }, indent=2))
        return

    if spec.pattern_name:
        print(f"Pattern: {spec.pattern_name} (detected via {detected_via})")
        if spec.weight_overrides:
            print(f"Weight overrides:")
            for key in sorted(spec.weight_overrides):
                print(f"  {key} = {spec.weight_overrides[key]}")
    else:
        print(f"No pattern detected ({detected_via or 'no suggestions'}). "
              f"Wrote stock settings.")
    print(f"Wrote: {out}")
    if compile_fix.action == "fixed":
        print(
            f"Also fixed: {compile_fix.path.name} "
            f"(macOS+wine path handling)"
        )
    print()

    # Tail recommendation
    if spec.pattern_name == "decl-order":
        print(
            "Tip: for decl-order specifically, try the deterministic "
            "search first — it's ~100x faster than letting permuter "
            "rediscover decl-order rounds:"
        )
        print(
            f"  melee-agent debug enumerate-decl-orders "
            f"-f {function} --keep-best"
        )
        print(
            "If that doesn't find a win, fall back to permuter with "
            "this config."
        )
    else:
        rel_dir = out.parent.relative_to(perm_root) \
            if perm_root in out.parents else out.parent
        print(f"Run: cd {perm_root} && ./permuter.py {rel_dir}")


@debug_app.command(name="fix-perm-compile")
def fix_perm_compile(
    target: Annotated[
        Path,
        typer.Argument(
            help="Path to either a nonmatchings/<fn>/ directory or a "
                 "compile.sh file directly.",
        ),
    ],
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Fix decomp-permuter's `compile.sh` for macOS+wine compatibility.

    The compile.sh generated by `import.py` passes an absolute mac path
    to mwcc via wine, which fails with an OS_PATHSEP assertion. This
    command rewrites it to stage the candidate as a relative path
    inside `nonmatchings/.permuter_stage_$$.c` (git-ignored,
    parallel-safe), which mwcc accepts.

    Idempotent: re-running on an already-fixed file is a no-op.

    Pass either the function's permuter dir (e.g.
    `~/code/decomp-permuter/nonmatchings/fn_xyz`) or the compile.sh
    directly.
    """
    from ..mwcc_debug.fix_perm_compile import (
        fix_compile_sh,
        fix_perm_dir,
    )

    if not target.exists():
        typer.echo(f"target not found: {target}", err=True)
        raise typer.Exit(2)

    if target.is_dir():
        result = fix_perm_dir(target)
    else:
        result = fix_compile_sh(target)

    if json_out:
        print(json.dumps({
            "path": str(result.path),
            "action": result.action,
            "reason": result.reason,
        }, indent=2))
        if result.action in ("skipped", "not-applicable"):
            raise typer.Exit(1)
        return

    icons = {
        "fixed": "[ok]",
        "already-fixed": "[--]",
        "not-applicable": "[!!]",
        "skipped": "[!!]",
    }
    icon = icons.get(result.action, "[??]")
    print(f"{icon} {result.path}")
    print(f"   {result.action}: {result.reason}")
    if result.action == "fixed":
        print()
        print("Now permuter's compile.sh will:")
        print("  1. Stage the candidate as nonmatchings/.permuter_stage_$$.c")
        print("  2. Pass that relative path to mwcc (avoids OS_PATHSEP)")
        print("  3. Clean up the stage file on exit")
    if result.action in ("skipped", "not-applicable"):
        raise typer.Exit(1)


def _find_wibo() -> Optional[Path]:
    """Locate the patched wibo binary. Resolution order:

    1. $MWCC_DEBUG_WIBO env var
    2. <melee_root>/tools/mwcc_debug/bin/wibo (vendored — built by build_wibo.sh)
    3. <melee_root>/../melee-harness/bin/wibo (adjacent harness checkout)
    4. ~/code/melee-harness/bin/wibo
    """
    import os as _os
    env = _os.environ.get("MWCC_DEBUG_WIBO")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    candidates = [
        DEFAULT_MELEE_ROOT / "tools" / "mwcc_debug" / "bin" / "wibo",
        DEFAULT_MELEE_ROOT.parent / "melee-harness" / "bin" / "wibo",
        Path("~/code/melee-harness/bin/wibo").expanduser(),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _build_local_wibo() -> Optional[Path]:
    """Build the vendored wibo via tools/mwcc_debug/build_wibo.sh.
    Returns the built path or None on failure.
    """
    build_script = (
        DEFAULT_MELEE_ROOT / "tools" / "mwcc_debug" / "build_wibo.sh"
    )
    if not build_script.exists():
        return None
    try:
        subprocess.run(
            [str(build_script)],
            cwd=build_script.parent,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    out = build_script.parent / "bin" / "wibo"
    return out if out.exists() else None


def _find_compiler_dir() -> Path:
    """Path to the GC/1.2.5n compiler directory."""
    return DEFAULT_MELEE_ROOT / "build" / "compilers" / "GC" / "1.2.5n"


def _build_local_dll() -> Optional[Path]:
    """Build the mwcc_debug DLL via tools/mwcc_debug/build_macos.sh.
    Returns the built DLL path or None on failure.
    """
    build_script = (
        DEFAULT_MELEE_ROOT / "tools" / "mwcc_debug" / "build_macos.sh"
    )
    if not build_script.exists():
        return None
    try:
        subprocess.run(
            [str(build_script)],
            cwd=build_script.parent,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    return build_script.parent / "MWDBG326.dll"


@debug_app.command(name="setup-local")
def setup_local(
    rebuild_dll: Annotated[
        bool,
        typer.Option(
            "--rebuild-dll",
            help="Rebuild the mwcc_debug DLL via build_macos.sh even if "
                 "it already exists.",
        ),
    ] = False,
) -> None:
    """One-time setup for local mwcc_debug pcdump (macOS+wibo).

    Steps:
    1. Verify wibo binary is available (built via melee-harness).
    2. Build the mwcc_debug DLL via tools/mwcc_debug/build_macos.sh
       if not already present.
    3. Patch a copy of mwcceppc.exe to import MWDBG326.dll instead
       of LMGR326B.dll (lives next to the stock compiler as
       mwcceppc_debug.exe; stock compiler untouched).
    4. Copy the DLL into the compiler dir so wibo finds it.

    After setup, `melee-agent debug pcdump-local <c_file>` works.

    Wibo dependency: this command expects Luke Champine's patched wibo
    at <melee>/../melee-harness/bin/wibo (or path in $MWCC_DEBUG_WIBO).
    Clone melee-harness adjacent to melee and build via its setup.sh.
    """
    melee_root = DEFAULT_MELEE_ROOT
    compiler_dir = _find_compiler_dir()

    # 1. Locate wibo, or build it
    wibo = _find_wibo()
    if wibo is None:
        print("[..] wibo not found; building via build_wibo.sh...")
        wibo = _build_local_wibo()
        if wibo is None:
            typer.echo(
                "wibo build failed. See tools/mwcc_debug/build_wibo.sh.\n"
                "Alternatives: set $MWCC_DEBUG_WIBO=<path-to-wibo-binary>.",
                err=True,
            )
            raise typer.Exit(2)
    print(f"[ok] wibo: {wibo}")

    # 2. Build the DLL if needed
    dll_src = melee_root / "tools" / "mwcc_debug" / "MWDBG326.dll"
    if rebuild_dll or not dll_src.exists():
        print("[..] building mwcc_debug DLL via build_macos.sh...")
        built = _build_local_dll()
        if built is None or not built.exists():
            typer.echo(
                "DLL build failed. Check tools/mwcc_debug/build_macos.sh.",
                err=True,
            )
            raise typer.Exit(3)
        dll_src = built
    print(f"[ok] DLL:  {dll_src}")

    # 3. Patch the compiler if needed
    stock_compiler = compiler_dir / "mwcceppc.exe"
    debug_compiler = compiler_dir / "mwcceppc_debug.exe"
    patcher = melee_root / "tools" / "mwcc_debug" / "patch_mwcceppc_for_wibo.py"

    if not stock_compiler.exists():
        typer.echo(
            f"stock compiler not found: {stock_compiler}. "
            f"Run `python configure.py` first to download it.",
            err=True,
        )
        raise typer.Exit(4)
    if not patcher.exists():
        typer.echo(
            f"patcher script not found: {patcher}. "
            f"Pull latest tools/mwcc_debug/.",
            err=True,
        )
        raise typer.Exit(5)

    print(f"[..] patching {stock_compiler.name} -> {debug_compiler.name}...")
    try:
        subprocess.run(
            [
                "python3", str(patcher),
                str(stock_compiler), str(debug_compiler),
                "--dll", str(dll_src),
            ],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        typer.echo(f"patcher failed: {e}", err=True)
        raise typer.Exit(6)
    print(f"[ok] compiler patched: {debug_compiler}")
    print(f"[ok] DLL deployed:     {compiler_dir / 'MWDBG326.dll'}")
    print()
    print("Setup complete. Try:")
    print("  melee-agent debug pcdump-local src/melee/mn/mnvibration.c")


def _ninja_cflags_for_unit(src_rel: str) -> tuple[str, str]:
    """Extract (cflags, mw_version) for a source from build.ninja.

    Mirrors melee-harness/tools/mwcc_dump.py's find_build_block.
    Raises typer.Exit if the source has no build block.
    """
    import re as _re
    text = (DEFAULT_MELEE_ROOT / "build.ninja").read_text()
    text = text.replace("$\n", " ")  # unfold ninja line continuations
    obj = f"build/GALE01/{src_rel[:-2]}.o"
    blocks = _re.split(r"^build ", text, flags=_re.M)
    for b in blocks:
        if b.startswith(f"{obj}:") or b.startswith(f"{obj} :"):
            cflags = _re.search(r"\bcflags = (.*)", b).group(1).strip()
            mw = _re.search(r"\bmw_version = (\S+)", b).group(1).strip()
            return cflags, mw
    typer.echo(
        f"no build block for {obj} in build.ninja. "
        f"Run `python configure.py && ninja build/GALE01/report.json` "
        f"first to ensure the source is registered.",
        err=True,
    )
    raise typer.Exit(2)


@debug_app.command(name="pcdump-local")
def pcdump_local(
    c_file: Annotated[
        str,
        typer.Argument(help="Path to a .c file in the melee repo"),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Output path for the dump. Default: cache it under "
                 "build/mwcc_debug_cache/<unit>.txt. Use '-' for stdout.",
        ),
    ] = None,
    force_phys: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys",
            help="Tier 5: allocator bias by ig_idx. Format "
                 "'virtIdx:physReg[,...]'. E.g. '36:31'. By default "
                 "applies globally — scope with --force-phys-fn.",
        ),
    ] = None,
    force_phys_iter: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-iter",
            help="Tier 5: allocator bias by colorgraph iteration "
                 "position (class:iter:phys[,...]). Use when "
                 "--force-phys can't target a node by ig_idx (rare, "
                 "but happens for split/spill nodes created post-IG-"
                 "build). E.g. '1:0:31' = class 1 (GPR), iter 0, "
                 "force to r31.",
        ),
    ] = None,
    force_phys_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-phys-fn",
            help="Scope --force-phys and --force-phys-iter to a "
                 "single function name (mirrors --force-coalesce-fn).",
        ),
    ] = None,
    force_iter_first: Annotated[
        Optional[str],
        typer.Option(
            "--force-iter-first",
            help="Tier 6: reorder simplification list.",
        ),
    ] = None,
    force_coalesce: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce",
            help="Tier 6: override the conservative coalescer's union-find "
                 "decisions. Format 'virt=root[,virt=root]*'. E.g. '42=38' "
                 "forces virtual 42 to coalesce into virtual 38; '42=42' "
                 "un-coalesces 42 back to its own root. By default applies "
                 "to EVERY coalesce invocation in the TU (out-of-bounds "
                 "pairs are silently skipped). For multi-function TUs "
                 "where one function's overrides would corrupt others, "
                 "scope with --force-coalesce-fn. EXPERIMENTAL — forcing "
                 "two interfering virtuals to coalesce produces "
                 "incorrect code.",
        ),
    ] = None,
    force_coalesce_fn: Annotated[
        Optional[str],
        typer.Option(
            "--force-coalesce-fn",
            help="Scope --force-coalesce to a single function name. "
                 "When set, overrides only apply when the currently-"
                 "compiling function (captured by mwcc_debug's debuglisting "
                 "hook) matches the given name exactly. Other functions in "
                 "the same TU compile naturally — prevents one function's "
                 "experimental overrides from corrupting earlier or later "
                 "functions. E.g. '--force-coalesce-fn mnVibration_802474C4 "
                 "--force-coalesce 32=87'.",
        ),
    ] = None,
    wibo: Annotated[
        Optional[Path],
        typer.Option(
            "--wibo",
            help="Path to wibo binary. Default: auto-resolve from "
                 "$MWCC_DEBUG_WIBO or ../melee-harness/bin/wibo.",
        ),
    ] = None,
    keep_obj: Annotated[
        Optional[Path],
        typer.Option(
            "--keep-obj",
            help="Preserve the compiled .o at this path instead of "
                 "discarding it. The default behavior is to discard, "
                 "but for force-coalesce / force-phys hypothesis "
                 "testing the .o is exactly what you need to feed into "
                 "objdiff/checkdiff. Path can be absolute or relative "
                 "to the melee root.",
        ),
    ] = None,
    diff: Annotated[
        bool,
        typer.Option(
            "--diff",
            help="After compile, run objdiff against the production "
                 "target.o for the function (or whole TU). Saves a "
                 "round-trip when you want to know 'does this "
                 "force-coalesce reach the target?' in one shot. "
                 "Implies --keep-obj (uses a temp path if --keep-obj "
                 "not given).",
        ),
    ] = False,
) -> None:
    """Local mwcc_debug pcdump (macOS+wibo+Zig-built DLL, no SSH).

    Compiles the given .c file locally via wibo + the patched
    mwcceppc_debug.exe. Produces the same pcdump.txt our SSH-based
    `debug pcdump` produces, in ~1 second vs ~30 seconds.

    Requires one-time setup: run `melee-agent debug setup-local`
    first to patch the compiler and deploy the DLL.

    Env-var hooks (--force-phys, --force-iter-first, --force-coalesce,
    --force-coalesce-fn) pass through to the DLL.

    Use --keep-obj PATH to preserve the compiled .o for downstream
    inspection (objdiff/checkdiff/etc.). Use --diff to run an integrated
    objdiff against the target — answers "does this match?" in one go.
    """
    melee_root = DEFAULT_MELEE_ROOT
    src_rel = _resolve_src_relative(c_file)

    # Resolve wibo
    wibo_path = wibo or _find_wibo()
    if wibo_path is None or not wibo_path.exists():
        typer.echo(
            "wibo binary not found. Run `melee-agent debug setup-local` "
            "first, or set $MWCC_DEBUG_WIBO.",
            err=True,
        )
        raise typer.Exit(2)

    compiler_dir = _find_compiler_dir()
    debug_compiler = compiler_dir / "mwcceppc_debug.exe"
    if not debug_compiler.exists():
        typer.echo(
            f"patched compiler not found: {debug_compiler}. "
            f"Run `melee-agent debug setup-local` first.",
            err=True,
        )
        raise typer.Exit(2)

    # Extract cflags from build.ninja
    cflags, _mw_version = _ninja_cflags_for_unit(src_rel)

    # Construct compile command. The patched DLL reads
    # MWCC_DEBUG_PCDUMP_PATH for its output filename (relative paths land
    # in cwd = melee_root). Use a unique per-PID + per-time name so
    # parallel pcdump-local runs don't race on a shared pcdump.txt.
    import time
    pcdump_name = f"pcdump_{os.getpid()}_{int(time.time() * 1000)}.txt"
    pcdump_path = melee_root / pcdump_name
    if pcdump_path.exists():
        pcdump_path.unlink()

    # Resolve where the .o lands. Default: discard via /tmp. When the
    # agent wants to inspect/diff the output, --keep-obj routes it to a
    # specific path. --diff implies keeping (a temp path if no --keep-obj
    # was given) so we have something to diff against.
    if keep_obj is not None:
        obj_target = keep_obj if keep_obj.is_absolute() else (melee_root / keep_obj)
        obj_target.parent.mkdir(parents=True, exist_ok=True)
        obj_out = str(obj_target)
        discard_obj_after = False
    elif diff:
        obj_target = Path(
            f"/tmp/pcdump_local_keep_{os.getpid()}_{int(time.time() * 1000)}.o"
        )
        obj_out = str(obj_target)
        discard_obj_after = True  # remove after diff if not user-requested
    else:
        obj_target = Path(
            f"/tmp/pcdump_local_discard_{os.getpid()}_{int(time.time() * 1000)}.o"
        )
        obj_out = str(obj_target)
        discard_obj_after = True

    # Args: cflags split + source + output.
    args = (
        [str(wibo_path), str(debug_compiler)]
        + shlex.split(cflags)
        + ["-c", src_rel, "-o", obj_out]
    )

    # Set env vars for our DLL's hooks
    env = os.environ.copy()
    env["MWCC_DEBUG_PCDUMP_PATH"] = pcdump_name
    if force_phys:
        env["MWCC_DEBUG_FORCE_PHYS"] = force_phys
    if force_phys_iter:
        env["MWCC_DEBUG_FORCE_PHYS_ITER"] = force_phys_iter
    if force_phys_fn:
        env["MWCC_DEBUG_FORCE_PHYS_FUNCTION"] = force_phys_fn
    if force_iter_first:
        env["MWCC_DEBUG_FORCE_ITER_FIRST"] = force_iter_first
    if force_coalesce:
        env["MWCC_DEBUG_FORCE_COALESCE"] = force_coalesce
    if force_coalesce_fn:
        env["MWCC_DEBUG_FORCE_COALESCE_FUNCTION"] = force_coalesce_fn

    # Safety guard: --force-coalesce without --force-coalesce-fn on a
    # multi-function TU is a known wibo-hanger. Virtual indices are
    # per-function; if the spec happens to be in-bounds for an unintended
    # function, the resulting compile can drive that function's state
    # into pathology and lock the wibo process in UE state (immune to
    # SIGKILL). Detect heuristically by counting function definitions
    # in the .c file and refuse the run with a clear error.
    # Distinguish "not provided" (None) from "explicit empty opt-out" (""):
    # the guard only fires on None.
    if force_coalesce and force_coalesce_fn is None:
        src_path = melee_root / src_rel
        if src_path.exists():
            n_fns = _count_function_defs(src_path.read_text())
            if n_fns >= 2:
                typer.echo(
                    f"refusing --force-coalesce without --force-coalesce-fn "
                    f"on a multi-function TU ({src_rel} has ~{n_fns} "
                    f"function definitions).\n"
                    f"Virtual indices are per-function; an override aimed at "
                    f"one function can corrupt others and may hang the wibo "
                    f"compile process in UE state.\n"
                    f"Re-run with `--force-coalesce-fn <function_name>` to "
                    f"scope the override. Pass `--force-coalesce-fn ''` to "
                    f"explicitly opt out of this check (NOT RECOMMENDED).",
                    err=True,
                )
                raise typer.Exit(2)
    # Same guard for --force-phys: same per-function issue, same wibo
    # risk if a per-function-class override happens to fit elsewhere.
    if (force_phys or force_phys_iter) and force_phys_fn is None:
        src_path = melee_root / src_rel
        if src_path.exists():
            n_fns = _count_function_defs(src_path.read_text())
            if n_fns >= 2:
                typer.echo(
                    f"refusing --force-phys/--force-phys-iter without "
                    f"--force-phys-fn on a multi-function TU "
                    f"({src_rel} has ~{n_fns} function definitions).\n"
                    f"Same per-function-virtual hazard as --force-coalesce. "
                    f"Re-run with `--force-phys-fn <function_name>` to scope. "
                    f"Pass `--force-phys-fn ''` to opt out (NOT RECOMMENDED).",
                    err=True,
                )
                raise typer.Exit(2)

    # Use Popen + a no-progress watchdog so a hung wibo (UE state from a
    # force-coalesce edge case, etc.) doesn't burn the full default
    # timeout. The watchdog kills the subprocess group after N seconds
    # without any progress on stdout/stderr. We can't actually kill a
    # wibo that's pinned in UE state (immune to SIGKILL — only a host
    # reboot reaps it), but we can stop OUR process from waiting and
    # stop accumulating new compile attempts behind it.
    WATCHDOG_TIMEOUT_S = float(os.environ.get(
        "MWCC_DEBUG_HANG_TIMEOUT", "45"))
    try:
        proc_handle = subprocess.Popen(
            args,
            cwd=melee_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,  # own pgrp for clean kill
        )
    except FileNotFoundError as e:
        typer.echo(f"failed to invoke wibo: {e}", err=True)
        raise typer.Exit(3)

    import select
    import signal as _signal
    out_buf: list[str] = []
    err_buf: list[str] = []
    last_progress = time.time()
    killed_by_watchdog = False
    while True:
        if proc_handle.poll() is not None:
            # Drain remaining output
            remaining_out, remaining_err = proc_handle.communicate()
            if remaining_out:
                out_buf.append(remaining_out)
            if remaining_err:
                err_buf.append(remaining_err)
            break
        # Wait for output (up to 1s at a time so we can check watchdog).
        ready, _, _ = select.select(
            [proc_handle.stdout, proc_handle.stderr], [], [], 1.0,
        )
        for stream in ready:
            chunk = stream.readline()
            if chunk:
                if stream is proc_handle.stdout:
                    out_buf.append(chunk)
                else:
                    err_buf.append(chunk)
                last_progress = time.time()
        if time.time() - last_progress > WATCHDOG_TIMEOUT_S:
            killed_by_watchdog = True
            try:
                os.killpg(os.getpgid(proc_handle.pid), _signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            # Drain whatever the OS still hands back (proc may be UE)
            try:
                remaining_out, remaining_err = proc_handle.communicate(timeout=2)
                if remaining_out:
                    out_buf.append(remaining_out)
                if remaining_err:
                    err_buf.append(remaining_err)
            except subprocess.TimeoutExpired:
                # wibo is in UE state — can't reap. Move on.
                pass
            break

    # Shim into the old proc.stderr/stdout/returncode contract so the
    # rest of the function works unchanged.
    class _ProcShim:
        def __init__(self, rc, out, err):
            self.returncode = rc
            self.stdout = out
            self.stderr = err
    proc = _ProcShim(
        rc=(proc_handle.returncode if proc_handle.returncode is not None else 124),
        out="".join(out_buf),
        err="".join(err_buf),
    )

    if killed_by_watchdog:
        typer.echo(
            f"[pcdump-local] no compile progress for "
            f"{WATCHDOG_TIMEOUT_S:.0f}s — likely wibo hang (UE state). "
            f"Subprocess killed; check `ps aux | grep wibo` for zombie. "
            f"Override via MWCC_DEBUG_HANG_TIMEOUT=<seconds>.",
            err=True,
        )

    if proc.returncode != 0:
        # Compile failed — surface stderr but keep going if pcdump.txt
        # got produced (mwcc sometimes errors after emitting partial dump).
        #
        # Filter out MWCC's "User break, cancelled..." noise: that message
        # fires from MWCC's interrupt handler during late-cleanup paths
        # (post-listing, post-flush). It does NOT indicate the dump is
        # bad — pcdump.txt is already written by the time this fires.
        # Echoing it makes successful runs look like errors. We only echo
        # stderr if there are non-noise lines left AND the dump is missing.
        filtered = "\n".join(
            line for line in proc.stderr.splitlines()
            if "User break" not in line
            and "cancelled..." not in line
        ).strip()
        if filtered:
            typer.echo(filtered, err=True)
        if not pcdump_path.exists():
            raise typer.Exit(proc.returncode)

    if not pcdump_path.exists():
        typer.echo("compile completed but no pcdump.txt was emitted", err=True)
        raise typer.Exit(4)

    # Run objdiff if --diff was requested. The integrated check
    # answers "did this compile reach the target?" without the agent
    # having to manually re-run objdiff-cli. We invoke checkdiff in
    # --no-build mode so it uses the .o we just produced.
    if diff:
        if not obj_target.exists():
            typer.echo(
                f"--diff requested but .o not produced at {obj_target}; "
                f"compile likely failed (see error above).",
                err=True,
            )
        else:
            # checkdiff finds the function by name across all .o files
            # the build emits; the simplest contract is to copy our .o
            # into the build path that checkdiff expects, then call it.
            unit_for_o = src_rel[:-2].removeprefix("src/")  # melee/mn/foo
            build_o = melee_root / "build" / "GALE01" / "src" / f"{unit_for_o}.o"
            build_o_existed = build_o.exists()
            saved_o: Optional[bytes] = None
            if build_o_existed:
                saved_o = build_o.read_bytes()
            try:
                build_o.parent.mkdir(parents=True, exist_ok=True)
                build_o.write_bytes(obj_target.read_bytes())
                print(f"[diff] running checkdiff against {build_o}...",
                      file=sys.stderr)
                # Pick the first function in the source as the target
                src_path = melee_root / src_rel
                fn_to_diff = None
                if src_path.exists():
                    src_text = src_path.read_text()
                    # First function definition; coarse heuristic
                    m = re.search(
                        r'^[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^)]*\)\s*'
                        r'(?:[A-Za-z_]\w*\s*)*\{',
                        src_text, re.MULTILINE,
                    )
                    if m:
                        fn_to_diff = m.group(1)
                if fn_to_diff is None:
                    print(
                        "[diff] could not find a function name to diff; "
                        "use checkdiff manually.", file=sys.stderr,
                    )
                else:
                    print(f"[diff] target function: {fn_to_diff}", file=sys.stderr)
                    diff_proc = subprocess.run(
                        ["python", "tools/checkdiff.py", fn_to_diff,
                         "--format", "plain", "--no-build"],
                        cwd=melee_root,
                    )
                    if diff_proc.returncode == 0:
                        print("[diff] MATCH — function bytes are identical.")
            finally:
                if build_o_existed and saved_o is not None:
                    build_o.write_bytes(saved_o)
                elif not build_o_existed and build_o.exists():
                    try:
                        build_o.unlink()
                    except OSError:
                        pass

    # Clean up the .o if it was temp-allocated (and not requested by user)
    if discard_obj_after:
        try:
            os.unlink(obj_out)
        except OSError:
            pass

    # Place output
    if str(output) == "-":
        print(pcdump_path.read_text())
        pcdump_path.unlink()
        return

    # Resolve the canonical cache location for this TU so we can ALWAYS
    # update it — even when --output specifies a different path.
    # Without this, downstream commands (analyze, var-to-virtual, guide)
    # auto-resolve via the cache and silently read stale data.
    unit = src_rel[:-2].removeprefix("src/")  # melee/mn/mnvibration
    from ..mwcc_debug import cache as pcdump_cache
    pcdump_cache.ensure_cache_dir(melee_root)
    cache_target = pcdump_cache.cache_path(melee_root, unit)

    if output is None:
        # No --output → cache is the destination, no extra copy needed.
        output = cache_target
        output.parent.mkdir(parents=True, exist_ok=True)
        pcdump_path.rename(output)
    else:
        # --output specified: write there AND mirror into the cache so
        # downstream auto-resolve doesn't read a stale dump.
        output.parent.mkdir(parents=True, exist_ok=True)
        # Move to user-requested path
        pcdump_path.rename(output)
        # Mirror to cache (best-effort; same content)
        try:
            cache_target.parent.mkdir(parents=True, exist_ok=True)
            cache_target.write_bytes(output.read_bytes())
            if cache_target != output:
                print(
                    f"wrote: {output} (also synced to cache {cache_target})",
                    file=sys.stderr,
                )
        except OSError as e:
            print(
                f"wrote: {output} (cache mirror failed: {e})",
                file=sys.stderr,
            )
            return
        return

    print(f"wrote: {output}", file=sys.stderr)


@debug_app.command(name="score-source")
def score_source(
    c_file: Annotated[
        str,
        typer.Argument(
            help="Path to a .c file to compile (relative to melee root). "
                 "Can be a staging path inside `nonmatchings/`.",
        ),
    ],
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function within the TU to score.",
        ),
    ],
    target: Annotated[
        Path,
        typer.Option(
            "--target", "-t",
            help="Target spec (YAML or JSON, from `debug derive-target`).",
        ),
    ],
    cflags_from: Annotated[
        Optional[str],
        typer.Option(
            "--cflags-from",
            help="Use cflags from this unit's ninja block instead of "
                 "inferring from c_file. Useful when c_file is a staged "
                 "candidate without its own ninja build block.",
        ),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet", "-q",
            help="Suppress everything except the integer score on stdout. "
                 "Designed for use as permuter's external scorer command.",
        ),
    ] = False,
) -> None:
    """Compile a source via pcdump-local, then score against a target.

    Single-command flow for use as decomp-permuter's external scorer.
    Outputs an integer score (lower = better; 0 = perfect target match).
    Use `--quiet` to silence everything except the score itself.

    Wires:
        c_file → mwcceppc_debug.exe → pcdump.txt → parse → score_function
    """
    from ..mwcc_debug import (
        find_function,
        parse_hook_events,
        parse_pcdump,
        score_function,
    )

    melee_root = DEFAULT_MELEE_ROOT
    src_rel = _resolve_src_relative(c_file)

    # Resolve wibo + compiler (re-use pcdump-local's resolution)
    wibo_path = _find_wibo()
    if wibo_path is None or not wibo_path.exists():
        typer.echo("wibo not found. Run `debug setup-local` first.", err=True)
        raise typer.Exit(2)
    debug_compiler = _find_compiler_dir() / "mwcceppc_debug.exe"
    if not debug_compiler.exists():
        typer.echo(
            "patched compiler not found. Run `debug setup-local` first.",
            err=True,
        )
        raise typer.Exit(2)

    # cflags: from the explicit unit OR from c_file's ninja block
    cflags_unit = cflags_from if cflags_from else c_file
    cflags_unit_rel = _resolve_src_relative(cflags_unit)
    cflags, _mw_version = _ninja_cflags_for_unit(cflags_unit_rel)

    # Compile, generating pcdump under a unique per-PID name so parallel
    # scorer runs don't race on a shared pcdump.txt. The patched DLL reads
    # MWCC_DEBUG_PCDUMP_PATH; we write the file relative to melee_root
    # (which is the subprocess cwd) and read it back from the same path.
    import time
    pcdump_name = f"pcdump_score_{os.getpid()}_{int(time.time() * 1000)}.txt"
    pcdump_path = melee_root / pcdump_name
    if pcdump_path.exists():
        pcdump_path.unlink()

    # Use unique discard .o to avoid races across parallel scorers
    discard_o = f"/tmp/score_source_discard_{os.getpid()}_{int(time.time()*1000)}.o"

    args = (
        [str(wibo_path), str(debug_compiler)]
        + shlex.split(cflags)
        + ["-c", src_rel, "-o", discard_o]
    )

    env = os.environ.copy()
    env["MWCC_DEBUG_PCDUMP_PATH"] = pcdump_name

    proc = subprocess.run(
        args, cwd=melee_root, env=env, capture_output=True, text=True,
    )
    if not pcdump_path.exists():
        if not quiet:
            typer.echo(proc.stderr, err=True)
        # Penalty for unscoreable candidates
        print(2**30)
        raise typer.Exit(0)

    pcdump_text = pcdump_path.read_text()
    pcdump_path.unlink()  # don't pollute repo
    # Clean up the discarded .o
    try:
        os.unlink(discard_o)
    except OSError:
        pass

    # Parse + score
    fns = parse_pcdump(pcdump_text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        if not quiet:
            typer.echo(
                f"function {function!r} not in compiled pcdump. "
                f"Candidate may have removed/renamed it.",
                err=True,
            )
        print(2**30)
        raise typer.Exit(0)

    events_list = parse_hook_events(pcdump_text)
    events = find_function(events_list, function)

    target_spec = _load_target_spec(target)
    result = score_function(fn, target_spec, events=events)

    # Permuter expects an integer
    print(int(result.total))


@debug_app.command(name="permute")
def permute(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to permute (required).",
        ),
    ],
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec for mwcc-debug scoring. Auto-derived from "
                 "current pcdump if omitted.",
        ),
    ] = None,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    blend: Annotated[
        float,
        typer.Option(
            "--blend",
            help="Weight α applied to mwcc-debug score when blending "
                 "with objdiff bytes. Final = bytes + α * mwcc.",
        ),
    ] = 0.1,
    threads: Annotated[
        int,
        typer.Option(
            "-j", "--threads",
            help="Permuter parallelism. score-source now uses unique "
                 "per-PID pcdump filenames so parallel threads no longer "
                 "race; safe to raise above 1.",
        ),
    ] = 1,
    extra: Annotated[
        Optional[list[str]],
        typer.Argument(
            help="Extra args passed through to permuter.py.",
        ),
    ] = None,
) -> None:
    """Tier 2: run decomp-permuter with mwcc-debug score blended in.

    Per-iteration, permuter scores candidates by combining objdiff
    byte-distance with `melee-agent debug score-source` (IGNode-distance
    from pcdump). Byte distance stays primary; the mwcc signal breaks
    ties between byte-equivalent candidates — useful for register-cascade
    stuck cases where the byte scorer can't distinguish many mutations.

    Prerequisites:
    - Run `melee-agent debug setup-local` (one-time).
    - `<perm-root>/nonmatchings/<function>/` exists with base.c, target.o,
      compile.sh. Create via `decomp-permuter/import.py`.
    - `melee-agent debug fix-perm-compile <perm_dir>` if compile.sh was
      generated on macOS (auto-applied by gen-permuter-config).

    Default is single-threaded for safety. score-source now emits
    per-PID pcdump filenames so parallel threads no longer race on a
    shared pcdump.txt — raise `-j` above 1 if you want concurrency.

    Note: stdout is set to line-buffering so that piping through `tail -N`
    shows live progress instead of buffering until the permuter exits.
    """
    # Force line-buffering on stdout so progress output is visible when
    # the command is piped (e.g. `melee-agent debug permute ... | tail -20`).
    # Without this, Python's stdio buffering holds all output until the
    # process exits — which never happens naturally for the permuter.
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

    melee_root = DEFAULT_MELEE_ROOT
    perm_dir = perm_root / "nonmatchings" / function

    if not perm_dir.exists():
        typer.echo(
            f"{perm_dir} not found. Run decomp-permuter's import.py first:\n"
            f"  cd {perm_root} && ./import.py <c_file> <target.s> "
            f"--function {function}",
            err=True,
        )
        raise typer.Exit(2)

    # Resolve TU for cflags
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(
            f"could not find {function!r} in report.json. "
            f"Rebuild via `ninja build/GALE01/report.json`.",
            err=True,
        )
        raise typer.Exit(3)
    unit_c = f"src/{unit}.c"

    # Derive target if not given
    if target is None:
        target = melee_root / "build" / "mwcc_debug_cache" / \
            f"{unit}_target.json"
        target.parent.mkdir(parents=True, exist_ok=True)

        cache_p = pcdump_cache.cache_path(melee_root, unit)
        if not cache_p.exists():
            print(
                f"[..] no cached pcdump for {unit}; "
                f"generating via pcdump-local..."
            )
            wibo_p = _find_wibo()
            cc_p = _find_compiler_dir() / "mwcceppc_debug.exe"
            if wibo_p is None or not wibo_p.exists() or not cc_p.exists():
                typer.echo(
                    "wibo or patched compiler missing. Run "
                    "`melee-agent debug setup-local` first.",
                    err=True,
                )
                raise typer.Exit(4)
            cflags, _ = _ninja_cflags_for_unit(unit_c)
            pcd_path = melee_root / "pcdump.txt"
            if pcd_path.exists():
                pcd_path.unlink()
            subprocess.run(
                [str(wibo_p), str(cc_p)]
                + shlex.split(cflags)
                + ["-c", unit_c, "-o", "/tmp/permute_init.o"],
                cwd=melee_root,
                check=True,
            )
            pcdump_cache.ensure_cache_dir(melee_root)
            pcd_path.rename(cache_p)
            print(f"[ok] pcdump → {cache_p}")

        from ..mwcc_debug import derive_target_from_function
        text = cache_p.read_text()
        fns = parse_pcdump(text)
        fn = next((f for f in fns if f.name == function), None)
        if fn is None:
            _abort_function_not_in_dump(function, [f.name for f in fns])
        spec = derive_target_from_function(fn)
        target.write_text(json.dumps(spec, indent=2))
        print(f"[ok] derived target → {target}")
    else:
        print(f"[ok] using target: {target}")

    # Locate the wrapper script
    wrapper = (
        melee_root / "tools" / "melee-agent" / "scripts"
        / "permute_with_mwcc.py"
    )
    if not wrapper.exists():
        typer.echo(f"wrapper not found: {wrapper}", err=True)
        raise typer.Exit(4)

    # Build env
    env = os.environ.copy()
    env["MELEE_PERMUTER_ROOT"] = str(perm_root)
    env["MELEE_ROOT"] = str(melee_root)
    env["MWCC_DEBUG_TARGET"] = str(target)
    env["MWCC_DEBUG_FN"] = function
    env["MWCC_DEBUG_UNIT"] = unit_c
    env["MWCC_DEBUG_BLEND"] = str(blend)

    cmd = ["python", str(wrapper), str(perm_dir), "-j", str(threads)]
    if extra:
        cmd.extend(extra)

    print(f"[ok] launching permuter (blend={blend} threads={threads})...")
    print(f"  {' '.join(cmd)}")
    print()

    proc = subprocess.run(cmd, env=env, cwd=perm_root)
    raise typer.Exit(proc.returncode)


@debug_app.command(name="var-to-virtual")
def var_to_virtual(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to look up (required).",
        ),
    ],
    var_name: Annotated[
        str,
        typer.Argument(help="Source-level variable name."),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
    basis: Annotated[
        bool,
        typer.Option(
            "--basis",
            help="Also dump the heuristic's evidence: parsed params/locals, "
                 "the cursor calculation step-by-step, observed virtuals in "
                 "the pre-pass, and any red flags that lowered confidence. "
                 "Use when you suspect var-to-virtual gave you a wrong "
                 "mapping — the basis tells you whether the cursor "
                 "shifted, a macro hid a decl, or the function has nested "
                 "blocks the parser skipped.",
        ),
    ] = False,
) -> None:
    """Bridge: given a source variable name, predict its MWCC virtual.

    Reports `confidence`: best-guess (heuristic matched, no concerns),
    low-confidence (matched but red flags present — cursor may be
    wrong), ambiguous (no observed virtual for this variable), or
    unsupported (e.g., variable lives in a macro the tokenizer can't
    see). Pass `--basis` to see the underlying evidence.
    """
    from ..mwcc_debug.symbol_bridge import (
        find_virtual_for_var,
        list_bindings_with_basis,
    )

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    text = pcdump_path.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre = fn.last_precolor_pass()
    if pre is None:
        typer.echo(
            f"no pre-coloring pass for {function}", err=True,
        )
        raise typer.Exit(3)

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    source = (melee_root / "src" / f"{unit}.c").read_text()
    bindings, basis_data = list_bindings_with_basis(source, function, pre)
    binding = next(
        (b for b in bindings if b.var_name == var_name), None
    )

    if binding is None:
        if json_out:
            payload: dict = {"var_name": var_name, "found": False}
            if basis and basis_data is not None:
                payload["basis"] = _basis_to_dict(basis_data)
            print(json.dumps(payload, indent=2))
        else:
            typer.echo(
                f"variable {var_name!r} not found in {function}",
                err=True,
            )
            if basis and basis_data is not None:
                _print_basis(basis_data, bindings)
        raise typer.Exit(1)

    if json_out:
        payload = {
            "var_name": binding.var_name,
            "virtual": binding.virtual,
            "kind": binding.kind,
            "type": binding.type_str,
            "confidence": binding.confidence,
            "found": True,
        }
        if basis and basis_data is not None:
            payload["basis"] = _basis_to_dict(basis_data)
        print(json.dumps(payload, indent=2))
    else:
        print(f"variable: {binding.var_name}")
        print(f"  virtual: r{binding.virtual}")
        print(f"  kind:    {binding.kind}")
        print(f"  type:    {binding.type_str}")
        print(f"  conf:    {binding.confidence}")
        if basis and basis_data is not None:
            print()
            _print_basis(basis_data, bindings)


@debug_app.command(name="suggest-coalesce-source")
def suggest_coalesce_source(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to analyze (required).",
        ),
    ],
    pair: Annotated[
        Optional[str],
        typer.Option(
            "-V", "--pair",
            help="Pair mode: 'virt=root' (e.g. '53=3'). Mutually "
                 "exclusive with --discover.",
        ),
    ] = None,
    discover: Annotated[
        bool,
        typer.Option(
            "--discover",
            help="Discover mode: find candidate coalesces that would "
                 "shorten the longest callee-save cascade. Mutually "
                 "exclusive with --pair.",
        ),
    ] = False,
    top: Annotated[
        int,
        typer.Option(
            "--top",
            help="Discover mode: max candidates (default 3). Raises "
                 "BadParameter if passed in pair mode.",
        ),
    ] = 3,
    pcdump: Annotated[
        Optional[Path],
        typer.Option(
            "--pcdump",
            help="Path to pcdump.txt. Auto-resolves from cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
    include_low_confidence: Annotated[
        bool,
        typer.Option(
            "--include-low-confidence",
            help="Use low-confidence bridge bindings for source-line "
                 "annotations.",
        ),
    ] = False,
) -> None:
    """Suggest C-source patterns producing a specific coalesce, or
    discover candidate coalesces that would shorten the cascade.

    Pair mode example:
        debug suggest-coalesce-source -f fn_802461BC -V 53=3

    Discover mode example:
        debug suggest-coalesce-source -f fn_802461BC --discover --top 5
    """
    from ..mwcc_debug.suggest_coalesce import render_json, render_text, run

    # Validation: exactly one of --pair / --discover (XOR check)
    if (pair is None) == (not discover):
        raise typer.BadParameter(
            "exactly one of --pair / --discover required"
        )
    # --top only makes sense in discover mode
    if pair is not None and top != 3:
        raise typer.BadParameter(
            "--top is only valid with --discover"
        )

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    text = pcdump_path.read_text()

    # Load source for the bridge — CLI handles this so the orchestrator
    # stays path-free (avoids circular import on cli.debug helpers).
    source_text = ""
    unit = _find_unit_for_function(function, melee_root)
    if unit is not None:
        src_path = melee_root / "src" / f"{unit}.c"
        if src_path.exists():
            source_text = src_path.read_text()

    parsed_pair: Optional[tuple[int, int]] = None
    if pair is not None:
        try:
            lhs, rhs = pair.split("=", 1)
            parsed_pair = (int(lhs), int(rhs))
        except (ValueError, TypeError):
            raise typer.BadParameter(
                f"invalid --pair {pair!r}; expected 'virt=root' (e.g. '53=3')"
            )

    try:
        report = run(
            function=function,
            pair=parsed_pair,
            discover=discover,
            top=top,
            include_low_confidence=include_low_confidence,
            pcdump_text=text,
            source_text=source_text,
        )
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(3)

    if json_out:
        print(render_json(report))
    else:
        print(render_text(report))


def _basis_to_dict(basis) -> dict:
    """Render a BindingBasis as a JSON-compatible dict."""
    return {
        "parsed_params": [
            {"name": p.name, "type": p.type_str, "decl_index": p.decl_index}
            for p in basis.parsed_params
        ],
        "parsed_locals": [
            {"name": ld.name, "type": ld.type_str, "decl_index": ld.decl_index}
            for ld in basis.parsed_locals
        ],
        "observed_virtuals": basis.observed_virtuals,
        "unrecognized_decls": basis.unrecognized_decls,
        "red_flags": basis.red_flags,
    }


def _print_basis(basis, bindings) -> None:
    """Human-readable dump of a BindingBasis + how the cursor mapped."""
    print("=== basis ===")
    if basis.red_flags:
        print(f"red flags: {', '.join(basis.red_flags)}")
        print("  (these demote 'best-guess' → 'low-confidence' for locals)")
    else:
        print("red flags: (none)")
    print()
    print(f"parsed params ({len(basis.parsed_params)}):")
    if not basis.parsed_params:
        print("  (none)")
    for p in basis.parsed_params:
        print(f"  [{p.decl_index}] {p.type_str:<22s} {p.name}")
    print()
    print(f"parsed locals ({len(basis.parsed_locals)}):")
    if not basis.parsed_locals:
        print("  (none)")
    for ld in basis.parsed_locals:
        print(f"  [{ld.decl_index}] {ld.type_str:<22s} {ld.name}")
    if basis.unrecognized_decls:
        print()
        print("unrecognized decl-shaped statements (parser couldn't handle):")
        for s in basis.unrecognized_decls:
            print(f"  • {s}")
    print()
    obs = basis.observed_virtuals
    obs_str = (
        ", ".join(f"r{v}" for v in obs[:16])
        + (f", ... (+{len(obs) - 16} more)" if len(obs) > 16 else "")
    ) if obs else "(none)"
    print(f"observed virtuals in pre-pass ({len(obs)}): {obs_str}")
    print()
    print("predicted bindings (cursor = 32 + position):")
    for b in bindings:
        marker = "✓" if b.virtual in obs else "·" if b.kind == "param" else "✗"
        print(f"  {marker} {b.var_name:<22s} r{b.virtual:<5d} "
              f"[{b.kind}/{b.confidence}]")


@debug_app.command(name="virtual-to-var")
def virtual_to_var(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to look up (required).",
        ),
    ],
    virtual: Annotated[
        str,
        typer.Argument(
            help="Virtual register number (32+) or ig_idx. Accepts "
                 "'62' or 'r62' — the 'r' prefix is stripped so you "
                 "can copy-paste straight from analyze/guide output.",
        ),
    ],
    pcdump: Annotated[
        Optional[Path],
        typer.Argument(
            help="Path to pcdump.txt. Auto-resolves from cache.",
        ),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit as JSON."),
    ] = False,
) -> None:
    """Bridge inverse: given a virtual register, predict the source
    variable name (decl-order heuristic). When no source variable
    binds to the requested virtual (compiler-introduced temps, spill
    nodes, etc.), falls back to showing the first defining IR op
    so you can correlate to the C source manually.
    """
    from ..mwcc_debug.symbol_bridge import (
        find_first_def,
        find_var_for_virtual,
    )

    # Accept 'r62' alongside '62' — easier to copy from analyze output.
    vstr = virtual.strip()
    if vstr.lower().startswith("r"):
        vstr = vstr[1:]
    try:
        virtual_int = int(vstr)
    except ValueError:
        typer.echo(
            f"invalid virtual register {virtual!r}; expected an integer "
            f"(optionally with 'r' prefix).", err=True,
        )
        raise typer.Exit(2)
    virtual = virtual_int  # downstream code uses int form

    melee_root = DEFAULT_MELEE_ROOT
    pcdump_path = _resolve_pcdump_path(pcdump, function, melee_root)
    text = pcdump_path.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre = fn.last_precolor_pass()
    if pre is None:
        typer.echo(
            f"no pre-coloring pass for {function}", err=True,
        )
        raise typer.Exit(3)

    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    source = (melee_root / "src" / f"{unit}.c").read_text()
    binding = find_var_for_virtual(source, function, virtual, pre)

    if binding is None:
        # Fallback: no source variable mapped (compiler temp, spill,
        # post-CSE intermediate, etc.). Surface the first-def IR op so
        # the agent can correlate to a C expression manually — e.g.,
        # `lwz r62, 44(r34)` means "r62 is something->field_at_0x2C
        # where something is in r34".
        first = find_first_def(virtual, pre)
        if json_out:
            payload: dict = {
                "virtual": virtual,
                "found": False,
            }
            if first is not None:
                payload["first_def"] = {
                    "block_idx": first.block_idx,
                    "opcode": first.opcode,
                    "operands": first.operands,
                    "annotations": first.annotations,
                }
            print(json.dumps(payload, indent=2))
        else:
            typer.echo(
                f"no source variable bound to r{virtual} in {function} "
                f"(likely a compiler-introduced temp — spill, CSE, or IV).",
                err=True,
            )
            if first is not None:
                typer.echo("", err=True)
                typer.echo("first defining op (in pre-coloring pass):", err=True)
                typer.echo(
                    f"  block {first.block_idx}: {first.opcode} {first.operands}",
                    err=True,
                )
                if first.annotations:
                    for a in first.annotations:
                        typer.echo(f"    {a}", err=True)
                typer.echo("", err=True)
                typer.echo(
                    "Hint: correlate the load address/offset back to a C "
                    "struct field, or trace the source register(s) to find "
                    "the originating expression.",
                    err=True,
                )
        raise typer.Exit(1)

    if json_out:
        print(json.dumps({
            "var_name": binding.var_name,
            "virtual": binding.virtual,
            "kind": binding.kind,
            "type": binding.type_str,
            "confidence": binding.confidence,
            "found": True,
        }, indent=2))
    else:
        print(f"r{virtual}: {binding.var_name} ({binding.kind})")
        print(f"  type:    {binding.type_str}")
        print(f"  conf:    {binding.confidence}")


mutate_app = typer.Typer(
    help="Tier 3: targeted source mutations on specific variables.",
)
debug_app.add_typer(mutate_app, name="mutate")


def _read_source_for(function: str, melee_root: Path) -> tuple[Path, str]:
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    p = melee_root / "src" / f"{unit}.c"
    return p, p.read_text()


@mutate_app.command(name="type-change")
def mutate_type_change_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function containing the variable.",
        ),
    ],
    var: Annotated[
        str,
        typer.Option("--var", help="Local variable name to retype."),
    ],
    new_type: Annotated[
        str,
        typer.Option("--type", help="New type string (e.g., 'u32')."),
    ],
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Write the mutated source back to the file. "
                 "Default: print to stdout.",
        ),
    ] = False,
) -> None:
    """Change a local variable's declared type."""
    from ..mwcc_debug.mutators import MutationUnsupported, mutate_type_change

    melee_root = DEFAULT_MELEE_ROOT
    src_path, source = _read_source_for(function, melee_root)
    try:
        out = mutate_type_change(source, function, var, new_type)
    except MutationUnsupported as e:
        typer.echo(f"mutation failed: {e}", err=True)
        raise typer.Exit(2)
    if apply:
        src_path.write_text(out)
        typer.echo(f"wrote: {src_path}", err=True)
    else:
        print(out, end="")


@mutate_app.command(name="insert-alias")
def mutate_insert_alias_cmd(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function containing the variable.",
        ),
    ],
    var: Annotated[
        str,
        typer.Option("--var", help="Local variable name to alias."),
    ],
    at: Annotated[
        int,
        typer.Option(
            "--at",
            help="0-indexed N-th reading statement to alias before.",
        ),
    ] = 0,
    new_name: Annotated[
        Optional[str],
        typer.Option(
            "--name",
            help="Alias variable name (default: <var>_alias).",
        ),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Write the mutated source back to the file. "
                 "Default: print to stdout.",
        ),
    ] = False,
) -> None:
    """Insert a fresh local copy of a variable before the N-th
    reading statement and rewrite that statement to use the alias."""
    from ..mwcc_debug.mutators import (
        MutationUnsupported, mutate_insert_alias_before_use,
    )

    melee_root = DEFAULT_MELEE_ROOT
    src_path, source = _read_source_for(function, melee_root)
    try:
        out = mutate_insert_alias_before_use(
            source, function, var, at_stmt_index=at, new_name=new_name,
        )
    except MutationUnsupported as e:
        typer.echo(f"mutation failed: {e}", err=True)
        raise typer.Exit(2)
    if apply:
        src_path.write_text(out)
        typer.echo(f"wrote: {src_path}", err=True)
    else:
        print(out, end="")


@debug_app.command(name="tier3-search")
def tier3_search(
    function: Annotated[
        str,
        typer.Option(
            "--function", "-f",
            help="Function to search (required).",
        ),
    ],
    budget: Annotated[
        int,
        typer.Option(
            "--budget",
            help="Maximum number of seed mutations to try. Hard cap "
                 "on seed count; truncated by priority order.",
        ),
    ] = 5,
    per_seed_iters: Annotated[
        int,
        typer.Option(
            "--per-seed-iters",
            help="Permuter iterations per seed.",
        ),
    ] = 200,
    perm_root: Annotated[
        Path,
        typer.Option(
            "--perm-root",
            help="Root of decomp-permuter clone.",
        ),
    ] = Path("~/code/decomp-permuter").expanduser(),
    target: Annotated[
        Optional[Path],
        typer.Option(
            "--target", "-t",
            help="Target spec; auto-derived if omitted.",
        ),
    ] = None,
    blend: Annotated[
        float,
        typer.Option("--blend", help="mwcc-score blend weight."),
    ] = 0.1,
    include_low_confidence: Annotated[
        bool,
        typer.Option(
            "--include-low-confidence",
            help="Also generate seeds from bindings the symbol-bridge "
                 "flagged as low-confidence (red flags present: nested "
                 "decls, statics, extra compiler-introduced virtuals). "
                 "Off by default — skip these to avoid bad seeds on "
                 "functions where the cursor heuristic is unreliable. "
                 "Verify the binding manually via "
                 "`debug var-to-virtual <var> -f FN --basis` before "
                 "opting in.",
        ),
    ] = False,
) -> None:
    """Tier 3: multi-start search over targeted mutation seeds.

    Workflow:
      1. Resolve pcdump + target.
      2. Enumerate variable bindings via the symbol bridge.
      3. Plan up to --budget seed mutations.
      4. Materialize each seed inside
         nonmatchings/<fn>/tier3_seed_<idx>/.
      5. Smoke-compile each. If all seeds fail, exit non-zero with a
         clear message.
      6. For each compiling seed, run `debug permute` (Tier 2) with
         --per-seed-iters iterations.
      7. Report the best result.
    """
    from ..mwcc_debug.symbol_bridge import list_bindings
    from ..mwcc_debug.tier3_search import (
        materialize_seed,
        plan_seeds,
        save_compile_failure,
        smoke_compile,
    )

    melee_root = DEFAULT_MELEE_ROOT

    # Resolve unit + sources
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        typer.echo(f"{function} not in report.json", err=True)
        raise typer.Exit(2)
    src_rel = f"src/{unit}.c"
    src_path = melee_root / src_rel
    base_source = src_path.read_text()

    # Resolve pcdump for the bridge
    pcdump_path = _resolve_pcdump_path(None, function, melee_root)
    text = pcdump_path.read_text()
    fns = parse_pcdump(text)
    fn = next((f for f in fns if f.name == function), None)
    if fn is None:
        _abort_function_not_in_dump(function, [f.name for f in fns])
    pre = fn.last_precolor_pass()
    if pre is None:
        typer.echo(
            f"no pre-coloring pass for {function}", err=True,
        )
        raise typer.Exit(3)

    bindings = list_bindings(base_source, function, pre)
    plans = plan_seeds(
        bindings, budget=budget,
        include_low_confidence=include_low_confidence,
    )
    if not plans:
        # Diagnostic: if there ARE low-confidence bindings, explain.
        n_low = sum(1 for b in bindings if b.confidence == "low-confidence")
        if n_low and not include_low_confidence:
            typer.echo(
                f"no Tier 3 targets — {n_low} local binding(s) demoted to "
                f"low-confidence by red flags. Run `debug var-to-virtual "
                f"<var> -f {function} --basis` to audit, then re-run "
                f"with --include-low-confidence if mapping looks correct.",
                err=True,
            )
        else:
            typer.echo(
                "no Tier 3 targets; fall back to `debug permute -f "
                f"{function}` for a vanilla Tier 2 run.",
                err=True,
            )
        raise typer.Exit(1)

    print(f"[tier3] {len(plans)} seed plans:")
    for i, p in enumerate(plans):
        print(f"  seed{i}: {p.description}")

    # Materialize + smoke-compile
    wibo = _find_wibo()
    debug_compiler = _find_compiler_dir() / "mwcceppc_debug.exe"
    if wibo is None or not wibo.exists() or not debug_compiler.exists():
        typer.echo(
            "wibo or patched compiler missing. "
            "Run `debug setup-local` first.",
            err=True,
        )
        raise typer.Exit(4)
    cflags, _mw = _ninja_cflags_for_unit(src_rel)

    perm_dir = perm_root / "nonmatchings" / function
    if not perm_dir.exists():
        typer.echo(
            f"{perm_dir} not found. Run decomp-permuter's "
            "import.py first.",
            err=True,
        )
        raise typer.Exit(2)

    materialized: list = []
    for i, plan in enumerate(plans):
        seed_dir = perm_dir / f"tier3_seed_{i}"
        out_c = materialize_seed(base_source, function, plan, seed_dir)
        if out_c is None:
            print(f"[tier3] seed{i}: mutation unsupported; skipping")
            continue
        result = smoke_compile(out_c, wibo, debug_compiler, cflags, melee_root)
        if result.ok:
            print(f"[tier3] seed{i}: compile=ok")
        else:
            log_path = save_compile_failure(seed_dir, result)
            print(f"[tier3] seed{i}: compile=FAIL — {result.one_line_reason}")
            print(f"         (full output: {log_path}, seed source: "
                  f"{seed_dir / 'base.c'})")
        materialized.append((plan, seed_dir, result))

    compiled = [m for m in materialized if m[2].ok]
    if not compiled:
        typer.echo(
            f"all {len(materialized)} tier3 seeds failed to compile.",
            err=True,
        )
        typer.echo("", err=True)
        typer.echo("Failed seeds (inspect each):", err=True)
        for i, (plan, seed_dir, result) in enumerate(materialized):
            typer.echo(
                f"  seed{i} ({plan.mutator} on {plan.target_var}): "
                f"{result.one_line_reason}",
                err=True,
            )
            typer.echo(
                f"    sources: {seed_dir / 'base.c'}",
                err=True,
            )
            typer.echo(
                f"    error:   {seed_dir / 'compile_error.txt'}",
                err=True,
            )
        typer.echo("", err=True)
        typer.echo(
            "Common causes: (a) symbol-bridge mapping is wrong (check "
            "`debug var-to-virtual -f FN --basis`); (b) the mutation "
            "produced invalid C (look at base.c); (c) the function uses "
            "a pattern the mutators don't handle yet.",
            err=True,
        )
        raise typer.Exit(5)

    print()
    print(
        f"[tier3] {len(compiled)}/{len(materialized)} seeds compiled. "
        f"Estimated wall-clock: {2 * len(compiled) * per_seed_iters} "
        f"to {3 * len(compiled) * per_seed_iters} seconds."
    )
    print(
        "[tier3] Per-seed permuter runs not yet wired in v1 — running "
        "`debug permute -f FN` against each seed dir manually is the "
        "current workaround. See "
        "docs/mwcc-debug-permuter-integration.md."
    )


@debug_app.command(name="verify-with-name-magic")
def verify_with_name_magic(
    function: Annotated[
        str,
        typer.Option("--function", "-f", help="Function name"),
    ],
    name_map: Annotated[
        Optional[str],
        typer.Option(
            "--map", "-m",
            help="Mapping of magic constant → named symbol. E.g., "
                 "'s32=mnVibration_804DC018,u32=mnVibration_804DC010'. "
                 "Keys: 's32' (signed int-to-float bias), 'u32' (unsigned), "
                 "any hex literal, or '@N' for direct anonymous-symbol "
                 "rename. If omitted, the .o is built and anonymous "
                 "magic symbols are LISTED with a suggested map "
                 "(useful for figuring out what to pass).",
        ),
    ] = None,
) -> None:
    """Compile, optionally rename anonymous SDA2 constants, then checkdiff.

    Separates 'this is just constant-label noise' from 'this is real
    codegen diff.' The agent runs this to confirm whether anonymous-vs-
    named SDA2 relocations are the only diff, or whether there's still
    a real .text mismatch.

    Common case: MWCC's int-to-float cast emits a magic constant
    (0x4330000080000000 signed, 0x4330000000000000 unsigned) into the
    .sdata2 literal pool under an anonymous `@N` name. The target .o
    references the same bytes via a named symbol (from symbols.txt).
    Reloc-target diff blocks byte matching even though the data is
    identical. `--map s32=<symname>,u32=<symname>` renames the @N
    symbols so checkdiff sees matching reloc targets.

    Flow:
      1. Build the function's TU object (`ninja build/GALE01/src/<unit>.o`)
      2. If `--map` given, rename anonymous @N .sdata2 symbols via objcopy
         If omitted, list anonymous symbols and suggest the map format.
      3. Run `tools/checkdiff.py <function> --format plain` and forward
         its output verbatim.
    """
    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        # Suggest similar names from report.json (mirrors verify-perm)
        try:
            report_path = melee_root / "build" / "GALE01" / "report.json"
            if report_path.exists():
                with report_path.open() as f:
                    rdata = json.load(f)
                all_names = [fn.get("name") for u in rdata.get("units", [])
                             for fn in u.get("functions", []) if fn.get("name")]
                suggestions = _suggest_similar_functions(function, all_names)
            else:
                suggestions = []
        except Exception:
            suggestions = []
        msg = f"function {function!r} not in report.json."
        if suggestions:
            msg += "\n\nDid you mean one of these?"
            for s in suggestions:
                msg += f"\n  - {s}"
        msg += "\n\nTry `ninja build/GALE01/report.json` to regenerate, then retry."
        typer.echo(msg, err=True)
        raise typer.Exit(2)

    obj_rel = Path("build") / "GALE01" / "src" / f"{unit}.o"
    obj_path = melee_root / obj_rel

    # 1. Build the .o
    print(f"[verify] building {obj_rel}...")
    proc = subprocess.run(
        ["ninja", str(obj_rel)],
        cwd=melee_root, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        err_summary = _extract_ninja_error(proc.stdout, proc.stderr)
        typer.echo(f"ninja failed building {obj_rel}:", err=True)
        typer.echo(err_summary, err=True)
        raise typer.Exit(3)
    if not obj_path.exists():
        typer.echo(
            f"ninja reported success but {obj_rel} not found", err=True,
        )
        raise typer.Exit(3)

    # 2. Rename anonymous SDA2 symbols if --map given, or surface what
    #    anonymous symbols exist so the agent can construct a map.
    if name_map:
        from ..mwcc_debug.o_rewriter import (
            parse_mapping,
            rename_magic_symbols,
        )
        try:
            mapping = parse_mapping(name_map)
        except ValueError as e:
            typer.echo(f"invalid --map: {e}", err=True)
            raise typer.Exit(2)
        try:
            renames = rename_magic_symbols(obj_path, mapping)
        except FileNotFoundError as e:
            typer.echo(
                f"objcopy not found: {e}. Install devkitPPC.",
                err=True,
            )
            raise typer.Exit(5)
        except subprocess.CalledProcessError as e:
            typer.echo(f"objcopy failed: {e}", err=True)
            raise typer.Exit(5)
        if renames:
            print(f"[verify] renamed {len(renames)} symbol(s):")
            for old, new in renames:
                print(f"          {old} -> {new}")
        else:
            print(
                "[verify] no matching anonymous symbols found to rename "
                "(use `debug name-magic <o_file> --list` to inspect)"
            )
    else:
        # No --map given. List anonymous magic constants in the freshly-
        # built .o so the agent can construct a map. Cross-reference with
        # the target .o (build/GALE01/obj/<unit>.o) to suggest concrete
        # named symbols instead of placeholders.
        try:
            from ..mwcc_debug.o_rewriter import suggest_name_magic_map
            target_o = melee_root / "build" / "GALE01" / "obj" / f"{unit}.o"
            syms, suggested = suggest_name_magic_map(obj_path, target_o)
        except Exception as e:
            syms, suggested = [], []
            print(f"[verify] no --map given (sym-list failed: {e})")
        if syms:
            named_for_sym: dict[str, str] = {s.name: n for s, n in suggested}
            print(f"[verify] no --map given; {len(syms)} anonymous .sdata2 "
                  f"symbol(s) found in {obj_rel}:")
            print(f"        {'name':<10}  {'sz':>2}  {'value':<18}  notes")
            print(f"        {'-'*10}  {'-'*2}  {'-'*18}  -----")
            import struct as _struct
            ready_pairs: list[str] = []
            placeholder_pairs: list[str] = []
            for s in syms:
                note = ""
                named = named_for_sym.get(s.name)
                if s.size == 8:
                    value_str = f"0x{s.value:016x}"
                    if s.value == 0x4330000080000000:
                        if named:
                            note = f"signed int-to-float bias → s32={named}"
                            ready_pairs.append(f"s32={named}")
                        else:
                            note = "int-to-float bias (signed) — try `s32=<sym>`"
                            placeholder_pairs.append("s32=<NAMED_SYMBOL>")
                    elif s.value == 0x4330000000000000:
                        if named:
                            note = f"unsigned int-to-float bias → u32={named}"
                            ready_pairs.append(f"u32={named}")
                        else:
                            note = "int-to-float bias (unsigned) — try `u32=<sym>`"
                            placeholder_pairs.append("u32=<NAMED_SYMBOL>")
                    elif named:
                        note = f"target named: {named}"
                        ready_pairs.append(f"{s.name}={named}")
                elif s.size == 4:
                    value_str = f"0x{s.value:08x}"
                    try:
                        f_val = _struct.unpack(">f", _struct.pack(">I", s.value))[0]
                        note = f"float ≈ {f_val:g}"
                    except Exception:
                        pass
                    if named:
                        note = f"{note + ' / ' if note else ''}target named: {named}"
                        ready_pairs.append(f"{s.name}={named}")
                else:
                    value_str = f"0x{s.value:x}"
                print(f"        {s.name:<10}  {s.size:>2}  {value_str:<18}  {note}")
            if ready_pairs:
                # Concrete map ready to copy-paste — built from target .o
                # cross-reference, so the agent doesn't have to grep
                # symbols.txt.
                print(
                    f"[verify] HINT: target .o ({target_o.relative_to(melee_root) if target_o.exists() else target_o}) "
                    f"has named counterparts. Re-run with:\n"
                    f"  --map '{','.join(ready_pairs)}'"
                )
                if placeholder_pairs:
                    print(
                        f"[verify] (some anonymous symbols had no target "
                        f"counterpart; fill in manually: "
                        f"{','.join(sorted(set(placeholder_pairs)))})"
                    )
            elif placeholder_pairs:
                print(
                    f"[verify] HINT: target .o not built or has no named "
                    f"counterparts at matching offsets. Build it first "
                    f"(`ninja build/GALE01/obj/{unit}.o`) for an auto-"
                    f"resolved map, or fill in manually: "
                    f"`--map '{','.join(sorted(set(placeholder_pairs)))}'`"
                )
            else:
                print(
                    "[verify] HINT: if checkdiff below complains about "
                    "@N relocs, you can pass `--map '@N=<sym>'` directly to "
                    "rename specific anonymous symbols."
                )
        else:
            print("[verify] no --map given; .o has no anonymous .sdata2 symbols")

    # 3. Run checkdiff — pass --no-build so its internal ninja invocation
    # doesn't clobber the objcopy rename we just made.
    print(f"[verify] running checkdiff.py {function}...")
    proc = subprocess.run(
        [
            "python", "tools/checkdiff.py", function,
            "--format", "plain", "--no-build",
        ],
        cwd=melee_root, capture_output=True, text=True,
    )
    # Forward stdout (the diff) and stderr verbatim
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        typer.echo(proc.stderr, err=True)
    raise typer.Exit(proc.returncode)
