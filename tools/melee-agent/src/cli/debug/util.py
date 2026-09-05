"""`debug util ...` — low-level helpers outside the main mwcc-debug loop.

Carved out of cli/debug/__init__.py. Contains the three util command handlers
(patterns, name-magic, verify-name-magic) and their dependencies.

Shared helpers (and module-level names the tests patch on the cli.debug
package) still live in cli/debug/__init__.py. They are reached via call-time
(deferred) ``from src.cli.debug import ...`` imports inside the function
bodies -- a load-time import would create a cycle (__init__ imports this
module) and would also break ``monkeypatch.setattr(debug_cli, ...)``
semantics, since the patched name must resolve against __init__ at call time.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import (
    Annotated,
    Optional,
)

import typer

from ...mwcc_debug.patterns import (
    PATTERNS,
    list_patterns,
)

util_app = typer.Typer(
    help="Low-level helpers outside the main mwcc-debug loop."
)

__all__: list[str] = []


@util_app.command(name="patterns")
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
    function; `debug inspect guide` will also cite pattern names directly.

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
        "Run `melee-agent debug util patterns <name>` for full details "
        "(example before/after, mechanism)."
    )


@util_app.command(name="name-magic")
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
    from ...mwcc_debug.o_rewriter import (
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


@util_app.command(name="verify-name-magic")
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
    apply_auto: Annotated[
        bool,
        typer.Option(
            "--apply-auto",
            help="Automatically resolve and apply the full anonymous → "
                 "production-symbol rename, no --map needed. Cross-"
                 "references the production .o "
                 "(`build/GALE01/obj/<unit>.o`) by value, renames every "
                 "anonymous @N .sdata2 symbol whose backing bytes match a "
                 "named symbol in the production .o, then globalizes "
                 "(STB_GLOBAL) the new symbols. Makes the 'named SDA2 "
                 "magic constants' matching blocker invisible to "
                 "subsequent checkdiff runs without manually constructing "
                 "a map. Mutually exclusive with --map.",
        ),
    ] = False,
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
    symbols so checkdiff sees matching reloc targets. Or pass
    `--apply-auto` to do the lookup + rename automatically from the
    production .o, no map required.

    Flow:
      1. Build the function's TU object (`ninja build/GALE01/src/<unit>.o`)
      2. If `--map` given, rename anonymous @N .sdata2 symbols via objcopy.
         If `--apply-auto` given, auto-resolve via value lookup against the
         production .o and apply renames + globalize in one step.
         If neither given, list anonymous symbols and suggest the map format.
      3. Run `tools/checkdiff.py <function> --format plain` and forward
         its output verbatim.
    """
    if name_map and apply_auto:
        typer.echo(
            "--map and --apply-auto are mutually exclusive; pick one. "
            "Use --apply-auto to auto-resolve, or --map to supply an "
            "explicit mapping.",
            err=True,
        )
        raise typer.Exit(2)

    from src.cli.debug import (  # noqa: PLC0415
        DEFAULT_MELEE_ROOT,
        _checkdiff_env_without_fingerprint,
        _extract_ninja_error,
        _find_unit_for_function,
        _suggest_similar_functions,
    )

    melee_root = DEFAULT_MELEE_ROOT
    unit = _find_unit_for_function(function, melee_root)
    if unit is None:
        # Suggest similar names from report.json (mirrors debug permute verify)
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

    # 2. Rename anonymous SDA2 symbols if --map / --apply-auto given,
    #    or surface what anonymous symbols exist so the agent can
    #    construct a map.
    if name_map:
        from ...mwcc_debug.o_rewriter import (
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
                "(use `debug util name-magic <o_file> --list` to inspect)"
            )
    elif apply_auto:
        from ...mwcc_debug.o_rewriter import apply_name_magic_auto

        target_o = melee_root / "build" / "GALE01" / "obj" / f"{unit}.o"
        if not target_o.exists():
            typer.echo(
                f"--apply-auto requires the production .o at "
                f"{target_o.relative_to(melee_root)} (not found). "
                f"Build it first (`ninja build/GALE01/obj/{unit}.o`) and "
                f"retry, or use --map to supply names manually.",
                err=True,
            )
            raise typer.Exit(2)
        try:
            result = apply_name_magic_auto(obj_path, target_o)
        except FileNotFoundError as e:
            typer.echo(
                f"objcopy not found: {e}. Install devkitPPC.",
                err=True,
            )
            raise typer.Exit(5)
        except subprocess.CalledProcessError as e:
            typer.echo(f"objcopy failed: {e}", err=True)
            raise typer.Exit(5)
        target_rel = target_o.relative_to(melee_root)
        if result.renames:
            print(
                f"[verify] --apply-auto: renamed {len(result.renames)} "
                f"symbol(s) via lookup against {target_rel}:"
            )
            globalized_set = set(result.globalized)
            for old, new in result.renames:
                glob_note = (
                    " (globalized)" if new in globalized_set else ""
                )
                print(f"          {old} -> {new}{glob_note}")
        else:
            print(
                f"[verify] --apply-auto: no anonymous .sdata2 symbols "
                f"matched named counterparts in {target_rel} "
                f"(found {len(result.anonymous_found)} anonymous; "
                f"unresolved {len(result.unresolved)})"
            )
        if result.unresolved:
            unresolved_names = ", ".join(
                s.name for s in result.unresolved[:8]
            )
            extra = (
                f" (+{len(result.unresolved) - 8} more)"
                if len(result.unresolved) > 8 else ""
            )
            print(
                f"[verify] --apply-auto: {len(result.unresolved)} "
                f"anonymous symbol(s) had no value-match in "
                f"{target_rel}: {unresolved_names}{extra}"
            )
    else:
        # No --map given. List anonymous magic constants in the freshly-
        # built .o so the agent can construct a map. Cross-reference with
        # the target .o (build/GALE01/obj/<unit>.o) to suggest concrete
        # named symbols instead of placeholders.
        try:
            from ...mwcc_debug.o_rewriter import suggest_name_magic_map
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
        env=_checkdiff_env_without_fingerprint(),
    )
    # Forward stdout (the diff) and stderr verbatim
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        typer.echo(proc.stderr, err=True)
    raise typer.Exit(proc.returncode)
