"""Struct commands - lookup struct layouts, field offsets, and callback signatures."""

import asyncio
import json as _json
import re
import subprocess
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer
from rich.panel import Panel
from rich.table import Table

from ._common import console, get_agent_melee_root, get_local_api_url

struct_app = typer.Typer(help="Lookup struct layouts and field offsets")

# Known type issues in the headers that cause matching problems
# Format: (struct, field, declared_type, actual_type, notes)
KNOWN_TYPE_ISSUES = [
    ("Fighter.dmg", "x1894", "int", "HSD_GObj*", "Source gobj pointer, loaded with lwz then dereferenced"),
    ("Fighter.dmg", "x1898", "int", "float", "Damage rate, loaded with lfs instruction"),
    ("Fighter.dmg", "x1880", "int", "Vec3*", "Effect position pointer"),
    ("Item", "xD90", "union Struct2070", "union Struct2070", "Same as Fighter.x2070, access via xD90.x2073"),
]

# Common struct locations
STRUCT_FILES = {
    "Fighter": "src/melee/ft/types.h",
    "Item": "src/melee/it/types.h",
    "HSD_GObj": "src/sysdolphin/baselib/gobj.h",
    "ftCo_DatAttrs": "src/melee/ft/types.h",
    "CollData": "src/melee/lb/types.h",
}


def _parse_struct_fields(content: str, struct_name: str) -> list[dict]:
    """Parse struct fields from header content."""
    fields = []

    # Find struct definition
    # Match patterns like "struct Fighter {" or "struct dmg {"
    pattern = rf"struct\s+{re.escape(struct_name)}\s*\{{"
    match = re.search(pattern, content)
    if not match:
        return fields

    start = match.end()
    brace_count = 1
    end = start

    # Find matching closing brace
    for i, char in enumerate(content[start:], start):
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                end = i
                break

    struct_content = content[start:end]

    # Parse field lines with offset comments
    # Matches: /* fp+XXXX */ or /* +XXXX */ followed by type and name
    field_pattern = (
        r"/\*\s*(?:fp\+)?([0-9A-Fa-fx]+)(?::(\d+))?\s*\*/\s*([^;]+?)\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\[[^\]]*\])?)\s*;"
    )

    for match in re.finditer(field_pattern, struct_content):
        offset_str = match.group(1)
        bit_offset = match.group(2)
        field_type = match.group(3).strip()
        field_name = match.group(4).strip()

        # Parse offset (hex or decimal)
        try:
            if offset_str.lower().startswith("0x"):
                offset = int(offset_str, 16)
            else:
                offset = int(offset_str, 16)  # Assume hex if no prefix
        except ValueError:
            continue

        field_info = {
            "offset": offset,
            "offset_hex": f"0x{offset:X}",
            "bit_offset": int(bit_offset) if bit_offset else None,
            "type": field_type,
            "name": field_name,
        }
        fields.append(field_info)

    return sorted(fields, key=lambda f: (f["offset"], f["bit_offset"] or 0))


def _find_struct_in_files(melee_root: Path, struct_name: str) -> tuple[Path | None, str | None]:
    """Find which file contains a struct definition."""
    # Check known locations first
    if struct_name in STRUCT_FILES:
        path = melee_root / STRUCT_FILES[struct_name]
        if path.exists():
            return path, path.read_text()

    # Search in common type header files
    search_dirs = [
        melee_root / "src/melee/ft",
        melee_root / "src/melee/it",
        melee_root / "src/melee/lb",
        melee_root / "src/melee/gr",
        melee_root / "src/sysdolphin/baselib",
    ]

    pattern = rf"struct\s+{re.escape(struct_name)}\s*\{{"

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for header in search_dir.glob("*.h"):
            try:
                content = header.read_text()
                if re.search(pattern, content):
                    return header, content
            except Exception:
                continue

    return None, None


@struct_app.command("show")
def struct_show(
    struct_name: Annotated[str, typer.Argument(help="Name of the struct (e.g., Fighter, Item, dmg)")],
    offset: Annotated[
        str | None, typer.Option("--offset", "-o", help="Filter to fields near this offset (hex)")
    ] = None,
    search: Annotated[str | None, typer.Option("--search", "-s", help="Search for field by name pattern")] = None,
):
    """Show struct layout with field offsets.

    Examples:
        melee-agent struct show Fighter
        melee-agent struct show Fighter --offset 0x1898
        melee-agent struct show dmg --search x189
    """
    melee_root = get_agent_melee_root()

    path, content = _find_struct_in_files(melee_root, struct_name)
    if not content:
        console.print(f"[red]Struct '{struct_name}' not found[/red]")
        console.print(f"[dim]Searched in: {melee_root}[/dim]")
        raise typer.Exit(1)

    fields = _parse_struct_fields(content, struct_name)
    if not fields:
        console.print(f"[yellow]Struct '{struct_name}' found but no fields parsed[/yellow]")
        console.print(f"[dim]File: {path}[/dim]")
        raise typer.Exit(1)

    # Filter by offset if specified
    target_offset = None
    if offset:
        try:
            target_offset = int(offset, 16) if offset.startswith("0x") else int(offset, 16)
        except ValueError:
            console.print(f"[red]Invalid offset: {offset}[/red]")
            raise typer.Exit(1)

        # Show fields within ±0x20 of target
        fields = [f for f in fields if abs(f["offset"] - target_offset) <= 0x20]

    # Filter by name pattern if specified
    if search:
        pattern = re.compile(search, re.IGNORECASE)
        fields = [f for f in fields if pattern.search(f["name"]) or pattern.search(f["type"])]

    if not fields:
        console.print("[yellow]No matching fields found[/yellow]")
        raise typer.Exit(0)

    # Build table
    table = Table(title=f"struct {struct_name}")
    table.add_column("Offset", style="cyan", justify="right")
    table.add_column("Type", style="green")
    table.add_column("Name", style="yellow")
    table.add_column("Notes", style="dim")

    for field in fields:
        offset_str = field["offset_hex"]
        if field["bit_offset"] is not None:
            offset_str += f":{field['bit_offset']}"

        # Check for known type issues
        notes = ""
        for issue in KNOWN_TYPE_ISSUES:
            issue_struct, issue_field, _, actual_type, issue_notes = issue
            if struct_name in issue_struct and field["name"] == issue_field:
                notes = f"⚠️ Should be {actual_type}"
                break

        table.add_row(offset_str, field["type"], field["name"], notes)

    console.print(table)
    console.print(f"\n[dim]Source: {path}[/dim]")


@struct_app.command("issues")
def struct_issues(
    struct_filter: Annotated[str | None, typer.Argument(help="Filter issues by struct name")] = None,
):
    """Show known type issues in struct definitions.

    These are fields where the declared type in the header doesn't match
    what the assembly actually expects. Use workaround casts when matching.
    """
    issues = KNOWN_TYPE_ISSUES
    if struct_filter:
        issues = [i for i in issues if struct_filter.lower() in i[0].lower()]

    if not issues:
        console.print("[green]No known type issues found[/green]")
        return

    table = Table(title="Known Type Issues")
    table.add_column("Struct.Field", style="cyan")
    table.add_column("Declared", style="red")
    table.add_column("Actual", style="green")
    table.add_column("Notes", style="dim")

    for struct_field, field_name, declared, actual, notes in issues:
        table.add_row(f"{struct_field}.{field_name}", declared, actual, notes)

    console.print(table)
    console.print("\n[bold]Workaround Example:[/bold]")
    console.print("""
[dim]When x1898 is declared as int but used as float:[/dim]
[green]#define DMG_X1898(fp) (*(float*)&(fp)->dmg.x1898)[/green]

[dim]When x1894 is declared as int but used as pointer:[/dim]
[green]#define DMG_X1894(fp) ((HSD_GObj*)(fp)->dmg.x1894)[/green]
""")


@struct_app.command("offset")
def struct_offset(
    offset: Annotated[str, typer.Argument(help="Offset to look up (hex, e.g., 0x1898)")],
    struct_name: Annotated[str, typer.Option("--struct", "-s", help="Struct to search in")] = "Fighter",
):
    """Look up what field is at a specific offset.

    Useful when reading assembly and seeing an offset like 0x1898(r30).

    Examples:
        melee-agent struct offset 0x1898
        melee-agent struct offset 0x1898 --struct Fighter
        melee-agent struct offset 0xD93 --struct Item
    """
    try:
        target = int(offset, 16) if offset.startswith("0x") else int(offset, 16)
    except ValueError:
        console.print(f"[red]Invalid offset: {offset}[/red]")
        raise typer.Exit(1)

    melee_root = get_agent_melee_root()
    path, content = _find_struct_in_files(melee_root, struct_name)

    if not content:
        console.print(f"[red]Struct '{struct_name}' not found[/red]")
        raise typer.Exit(1)

    fields = _parse_struct_fields(content, struct_name)

    # Find exact match or closest containing field
    exact_match = None
    containing_field = None

    for field in fields:
        if field["offset"] == target:
            exact_match = field
            break
        elif field["offset"] < target:
            containing_field = field

    if exact_match:
        console.print(f"[green]Exact match at 0x{target:X}:[/green]")
        console.print(f"  Type: [cyan]{exact_match['type']}[/cyan]")
        console.print(f"  Name: [yellow]{exact_match['name']}[/yellow]")

        # Check for known issues
        for issue in KNOWN_TYPE_ISSUES:
            if struct_name in issue[0] and exact_match["name"] == issue[1]:
                console.print(f"\n[red]⚠️ TYPE ISSUE:[/red] Declared as {issue[2]}, actually {issue[3]}")
                console.print(f"[dim]{issue[4]}[/dim]")
    elif containing_field:
        inner_offset = target - containing_field["offset"]
        console.print(f"[yellow]No exact match. Offset 0x{target:X} is within:[/yellow]")
        console.print(f"  Field: [cyan]{containing_field['type']}[/cyan] [yellow]{containing_field['name']}[/yellow]")
        console.print(f"  Base offset: 0x{containing_field['offset']:X}")
        console.print(f"  Inner offset: +0x{inner_offset:X} ({inner_offset} bytes in)")

        # If it's a nested struct, suggest looking there
        if "struct" in containing_field["type"] or containing_field["type"].startswith("Vec"):
            console.print("\n[dim]This is a nested type. Check the inner struct layout.[/dim]")
    else:
        console.print(f"[red]Offset 0x{target:X} not found in {struct_name}[/red]")
        if fields:
            console.print(f"[dim]Struct range: 0x{fields[0]['offset']:X} - 0x{fields[-1]['offset']:X}[/dim]")


# Common callback typedefs used in Melee
KNOWN_CALLBACKS = {
    "FtCmd2": {
        "signature": "void (*FtCmd2)(Fighter_GObj* gobj, CommandInfo* cmd, int arg2)",
        "header": "<melee/ft/ftcmd.h>",
        "description": "Command interpreter callback for fighter actions",
        "example": "static void my_callback(Fighter_GObj* gobj, CommandInfo* cmd, int arg2) {}",
    },
    "HSD_GObjEvent": {
        "signature": "void (*HSD_GObjEvent)(HSD_GObj* gobj)",
        "header": "<baselib/gobj.h>",
        "description": "Generic gobj event callback",
        "example": "static void my_event(HSD_GObj* gobj) {}",
    },
    "HSD_GObjPredicate": {
        "signature": "bool (*HSD_GObjPredicate)(HSD_GObj* gobj)",
        "header": "<baselib/gobj.h>",
        "description": "Gobj predicate for filtering",
        "example": "static bool my_predicate(HSD_GObj* gobj) { return TRUE; }",
    },
    "GObj_RenderFunc": {
        "signature": "void (*GObj_RenderFunc)(HSD_GObj* gobj, int code)",
        "header": "<baselib/gobj.h>",
        "description": "Render function callback",
        "example": "static void my_render(HSD_GObj* gobj, int code) {}",
    },
    "HSD_UserDataEvent": {
        "signature": "void (*HSD_UserDataEvent)(void* user_data)",
        "header": "<baselib/gobj.h>",
        "description": "User data cleanup callback",
        "example": "static void my_cleanup(void* user_data) {}",
    },
    "ftCo_Callback": {
        "signature": "void (*ftCo_Callback)(HSD_GObj* gobj)",
        "header": "<melee/ft/ftcommon.h>",
        "description": "Common fighter callback",
        "example": "static void my_callback(HSD_GObj* gobj) {}",
    },
}


@struct_app.command("callback")
def struct_callback(
    name: Annotated[str | None, typer.Argument(help="Callback type name (e.g., FtCmd2)")] = None,
    search: Annotated[str | None, typer.Option("--search", "-s", help="Search for callback by pattern")] = None,
    slug: Annotated[str | None, typer.Option("--slug", help="Search scratch context for callback type")] = None,
    api_url: Annotated[str | None, typer.Option("--api-url", help="Decomp.me API URL (auto-detected)")] = None,
):
    """Look up callback function signatures.

    When a function takes a callback parameter, use this to find the expected signature.

    Examples:
        melee-agent struct callback FtCmd2
        melee-agent struct callback --search Cmd
        melee-agent struct callback --slug abc123 --search lb_80014258
    """
    # If slug provided, search context for function and extract callback param
    if slug:
        if not search:
            console.print("[red]--search is required when using --slug[/red]")
            raise typer.Exit(1)

        api_url = api_url or get_local_api_url()
        from src.client import DecompMeAPIClient

        async def get():
            async with DecompMeAPIClient(base_url=api_url) as client:
                return await client.get_scratch(slug)

        scratch = asyncio.run(get())

        # Search for the function declaration
        pattern = re.compile(rf"\b{re.escape(search)}\s*\([^)]+\)", re.IGNORECASE)
        for match in pattern.finditer(scratch.context):
            # Get surrounding context
            start = max(0, match.start() - 100)
            end = min(len(scratch.context), match.end() + 50)
            snippet = scratch.context[start:end]

            console.print(f"[bold cyan]Found:[/bold cyan] {match.group()}")

            # Try to extract the signature
            func_text = match.group()
            console.print(f"\n[dim]{snippet}[/dim]")

            # Look for callback parameters (typedef'd function pointers)
            for cb_name, cb_info in KNOWN_CALLBACKS.items():
                if cb_name.lower() in func_text.lower():
                    console.print(f"\n[bold green]Callback parameter: {cb_name}[/bold green]")
                    console.print(f"  Signature: [cyan]{cb_info['signature']}[/cyan]")
                    console.print(f"  Header: [yellow]{cb_info['header']}[/yellow]")
                    console.print("\n  [dim]Example:[/dim]")
                    console.print(f"  [green]{cb_info['example']}[/green]")
            console.print()
        return

    # List known callbacks
    if not name and not search:
        table = Table(title="Known Callback Types")
        table.add_column("Name", style="cyan")
        table.add_column("Signature", style="green")
        table.add_column("Description", style="dim")

        for cb_name, cb_info in KNOWN_CALLBACKS.items():
            table.add_row(cb_name, cb_info["signature"], cb_info["description"])

        console.print(table)
        console.print("\n[dim]Use 'melee-agent struct callback <name>' for details[/dim]")
        return

    # Search by pattern
    if search:
        matches = {k: v for k, v in KNOWN_CALLBACKS.items() if search.lower() in k.lower()}
        if not matches:
            console.print(f"[yellow]No callbacks matching '{search}'[/yellow]")
            return

        for cb_name, cb_info in matches.items():
            console.print(f"\n[bold cyan]{cb_name}[/bold cyan]")
            console.print(f"  Signature: [green]{cb_info['signature']}[/green]")
            console.print(f"  Header: [yellow]{cb_info['header']}[/yellow]")
            console.print(f"  {cb_info['description']}")
            console.print("\n  [dim]Example:[/dim]")
            console.print(f"  [green]{cb_info['example']}[/green]")
        return

    # Look up specific callback
    if name not in KNOWN_CALLBACKS:
        console.print(f"[red]Unknown callback type: {name}[/red]")
        console.print("[dim]Known types:[/dim]")
        for cb_name in KNOWN_CALLBACKS:
            console.print(f"  • {cb_name}")
        raise typer.Exit(1)

    cb_info = KNOWN_CALLBACKS[name]
    console.print(f"\n[bold cyan]{name}[/bold cyan]")
    console.print(f"  Signature: [green]{cb_info['signature']}[/green]")
    console.print(f"  Header: [yellow]{cb_info['header']}[/yellow]")
    console.print(f"  {cb_info['description']}")
    console.print("\n[bold]Example implementation:[/bold]")
    console.print(f"[green]{cb_info['example']}[/green]")
    console.print(f"\n[dim]Include {cb_info['header']} to use this type.[/dim]")


# ---------------------------------------------------------------------------
# struct verify command
# ---------------------------------------------------------------------------

def _render_verify_table(agg: list[dict], skipped: list[tuple]) -> None:
    """Render struct offset discrepancies as a Rich table to console."""
    t = Table(title="struct offset discrepancies")
    for col in ("field", "current", "expected", "delta", "n", "confidence"):
        t.add_column(col)
    for a in agg:
        if a["conflict"]:
            exp_str = "CONFLICT " + ",".join(hex(e) for e in a["expecteds"])
            delta_str = ""
        else:
            exp_str = hex(a["expected"])
            delta_str = f"{a['expected'] - a['current']:+d}"
        conf_str = a["confidence"]
        if a.get("ambiguous"):
            # Expected offset maps to a different known field: flag, don't drop.
            conf_str = f"{conf_str} AMBIGUOUS"
        t.add_row(
            a["field"],
            hex(a["current"]),
            exp_str,
            delta_str,
            str(a["n_functions"]),
            conf_str,
        )
    console.print(t)
    if skipped:
        items = ", ".join(f"{fn}({why})" for fn, why in skipped[:20])
        console.print(f"[yellow]skipped {len(skipped)}:[/] {items}")


_NON_STRUCT_BASE_REGS = {"r1", "r2", "r13"}


def _normalize_reg(reg: object) -> str:
    text = str(reg).strip().lower()
    if text.isdigit():
        text = f"r{text}"
    return text


def _parse_int_literal(value: object, label: str) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: {value!r}") from exc


def _infer_base_reg_from_discrepancies(discrepancies: list[dict]) -> tuple[str | None, str | None, str | None]:
    """Infer a usable base register from checkdiff offset rows."""
    regs = sorted({
        _normalize_reg(d.get("base_reg", ""))
        for d in discrepancies
        if _normalize_reg(d.get("base_reg", "")) and _normalize_reg(d.get("base_reg", "")) not in _NON_STRUCT_BASE_REGS
    })
    if len(regs) == 1:
        return regs[0], "unique-offset-discrepancy", None
    if not regs:
        return None, None, "no offset base candidates"
    return None, None, f"ambiguous offset base candidates: {', '.join(regs)}"


def _infer_base_offset_from_layout(layout: dict[str, int], discrepancies: list[dict]) -> tuple[int, str, list[int]]:
    """Infer an interior-pointer base offset from current displacements."""
    if not discrepancies:
        return 0, "zero-default", []
    offsets = set(layout.values())
    cur_disps = [_parse_int_literal(d["cur_disp"], "cur_disp") for d in discrepancies]
    if all(disp in offsets for disp in cur_disps):
        return 0, "exact-layout", [0]

    candidates: list[int] = []
    for field_offset in sorted(offsets):
        for cur in cur_disps:
            candidate = field_offset - cur
            if candidate < 0:
                continue
            if all((candidate + disp) in offsets for disp in cur_disps):
                candidates.append(candidate)
    unique = sorted(set(candidates))
    if len(unique) == 1:
        return unique[0], "unique-layout-fit", unique
    if len(unique) > 1:
        return 0, "ambiguous-layout-fit", unique
    return 0, "zero-default", []


def _offset_to_field(layout: dict[str, int], offset: int) -> str | None:
    for field, field_offset in layout.items():
        if field_offset == offset:
            return field
    return None


def _finding_from_offset_discrepancy(
    function: str,
    discrepancy: dict,
    layout: dict[str, int],
    *,
    base_offset: int,
    base_offset_source: str,
    base_reg: str,
    base_reg_source: str,
) -> dict | None:
    cur_disp = _parse_int_literal(discrepancy["cur_disp"], "cur_disp")
    ref_disp = _parse_int_literal(discrepancy["ref_disp"], "ref_disp")
    current_abs = base_offset + cur_disp
    expected_abs = base_offset + ref_disp
    field = _offset_to_field(layout, current_abs)
    if field is None:
        return None
    ref_field = _offset_to_field(layout, expected_abs)
    return {
        "function": function,
        "field": field,
        "current": current_abs,
        "expected": expected_abs,
        "ref_field": ref_field,
        "base_reg": base_reg,
        "base_reg_source": base_reg_source,
        "base_offset": base_offset,
        "base_offset_source": base_offset_source,
        "cur_disp": cur_disp,
        "ref_disp": ref_disp,
        "current_abs": current_abs,
        "expected_abs": expected_abs,
    }


def _load_json_map(path: str, option: str) -> dict:
    try:
        data = _json.loads(Path(path).read_text())
    except Exception as exc:
        raise ValueError(f"failed to read {option} {path!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{option} must be a JSON object")
    return data


def _struct_body_span(content: str, struct_name: str) -> tuple[int, int] | None:
    """Return the character span of a struct body in a header."""
    patterns = [
        rf"struct\s+_?{re.escape(struct_name)}\s*\{{",
        rf"typedef\s+struct\s+_?{re.escape(struct_name)}\s*\{{",
        rf"typedef\s+struct\s*\{{",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, content):
            start = match.end()
            brace_count = 1
            end = start
            for i, char in enumerate(content[start:], start):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = i
                        break
            if brace_count != 0:
                continue
            suffix = content[end : min(len(content), end + 128)]
            if pattern == patterns[-1] and not re.search(rf"\}}\s*{re.escape(struct_name)}\s*;", suffix):
                continue
            return start, end
    return None


def _apply_struct_padding(
    header: Path,
    field: str,
    *,
    delta: int,
    verify: Callable[[], bool],
    struct_name: str | None = None,
) -> dict:
    """Insert positive padding before a top-level field and verify the result."""
    if "." in field or "[" in field:
        return {"status": "not_applicable", "reason": "only top-level fields can be applied safely"}
    if delta <= 0:
        return {"status": "not_applicable", "reason": "only positive padding deltas can be applied safely"}

    original = header.read_text()
    search_start = 0
    search_end = len(original)
    if struct_name is not None:
        span = _struct_body_span(original, struct_name)
        if span is None:
            return {"status": "not_applicable", "reason": f"struct {struct_name!r} body not found"}
        search_start, search_end = span

    body = original[search_start:search_end]
    decl_re = re.compile(rf"(?m)^([ \t]*).*?\b{re.escape(field)}\b(?:\s*\[[^\]]+\])?\s*;")
    matches = list(decl_re.finditer(body))
    if len(matches) != 1:
        return {
            "status": "not_applicable",
            "reason": f"expected one declaration line for {field!r}, found {len(matches)}",
        }

    match = matches[0]
    absolute_insert = search_start + match.start()
    indent = match.group(1)
    pad_name = re.sub(r"[^a-zA-Z0-9_]", "_", field)
    pad_line = f"{indent}u8 pad_struct_verify_{pad_name}[{delta}];\n"
    if pad_line in original:
        return {"status": "not_applicable", "reason": "padding line already present"}

    updated = original[:absolute_insert] + pad_line + original[absolute_insert:]
    header.write_text(updated)
    try:
        if verify():
            return {"status": "applied", "field": field, "delta": delta, "header": str(header)}
        header.write_text(original)
        return {"status": "failed", "reason": "post-edit offset verification failed"}
    except Exception as exc:
        header.write_text(original)
        return {"status": "failed", "reason": f"post-edit offset verification raised: {exc}"}


@struct_app.command("verify")
def struct_verify_cmd(
    target: Annotated[
        str,
        typer.Argument(help="Function name or TU substring (e.g. thp/THPDec)"),
    ],
    struct: Annotated[
        str,
        typer.Option("--struct", help="Struct type name"),
    ],
    base: Annotated[
        Optional[str],
        typer.Option("--base", help="Base register, e.g. r3 (single function or TU default)"),
    ] = None,
    base_map: Annotated[
        Optional[str],
        typer.Option("--base-map", help="JSON file mapping {function: register}"),
    ] = None,
    base_offset: Annotated[
        Optional[str],
        typer.Option("--base-offset", help="Interior-pointer base offset to add before field lookup"),
    ] = None,
    base_offset_map: Annotated[
        Optional[str],
        typer.Option("--base-offset-map", help="JSON file mapping {function: interior offset}"),
    ] = None,
    tu_src: Annotated[
        str,
        typer.Option("--tu-src", help="Path to the TU .c file (for cflags lookup)"),
    ] = ...,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of a table"),
    ] = False,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Apply a guarded top-level padding edit when safely verifiable"),
    ] = False,
) -> None:
    """Detect wrong struct-field offsets by comparing per-function displacements.

    Runs checkdiff on each function, maps current displacements to field paths
    via the MWCC offsetof-probe resolver, and aggregates findings across the TU.

    Examples:
        melee-agent struct verify __THPRestartDefinition --struct THPFileInfo --base r3 --tu-src extern/dolphin/src/dolphin/thp/THPDec.c
        melee-agent struct verify thp/THPDec --struct THPFileInfo --base r3 --tu-src extern/dolphin/src/dolphin/thp/THPDec.c
        melee-agent struct verify thp/THPDec --struct THPFileInfo --base-map bases.json --tu-src extern/dolphin/src/dolphin/thp/THPDec.c --json
        melee-agent struct verify fn --struct THPFileInfo --base-offset 0x838 --tu-src extern/dolphin/src/dolphin/thp/THPDec.c --json
    """
    from ..common import struct_layout, struct_verify
    from ..extractor.report import functions_for_unit

    repo = get_agent_melee_root()

    # Resolve the layout once (compile probe)
    try:
        layout = struct_layout.resolve_layout(repo, struct, tu_src)
    except Exception as exc:
        console.print(f"[red]Failed to resolve layout for {struct!r}: {exc}[/red]")
        raise typer.Exit(1)

    # Load per-function maps if provided. --base-map accepts either
    # {function: "r31"} or {function: {"base": "r31", "offset": "0x20"}}.
    bmap: dict = {}
    if base_map:
        try:
            bmap = _load_json_map(base_map, "--base-map")
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    offset_map: dict = {}
    if base_offset_map:
        try:
            offset_map = _load_json_map(base_offset_map, "--base-offset-map")
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    cli_base_offset: int | None = None
    if base_offset is not None:
        try:
            cli_base_offset = _parse_int_literal(base_offset, "--base-offset")
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    # Resolve function list
    if "/" in target:
        try:
            fns = functions_for_unit(repo / "build/GALE01/report.json", target)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
    else:
        fns = [target]

    findings: list[dict] = []
    skipped: list[tuple] = []

    for fn in fns:
        # Run checkdiff in JSON mode (no-build: use existing .o)
        result = subprocess.run(
            ["python", "tools/checkdiff.py", fn, "--no-tty", "--format", "json", "--no-build"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        try:
            data = _json.loads(result.stdout)
            cls = data["classification"]
        except Exception:
            skipped.append((fn, "checkdiff failed"))
            continue

        discrepancies = cls.get("offset_discrepancies", [])
        base_entry = bmap.get(fn)
        reg: str | None = None
        reg_source: str | None = None
        mapped_offset: int | None = None
        mapped_offset_source: str | None = None

        if isinstance(base_entry, dict):
            if base_entry.get("base") is not None:
                reg = _normalize_reg(base_entry["base"])
                reg_source = "base-map"
            if base_entry.get("offset") is not None:
                try:
                    mapped_offset = _parse_int_literal(base_entry["offset"], "--base-map offset")
                    mapped_offset_source = "base-map"
                except ValueError as exc:
                    skipped.append((fn, str(exc)))
                    continue
        elif base_entry is not None:
            reg = _normalize_reg(base_entry)
            reg_source = "base-map"

        if reg is None and base is not None:
            reg = _normalize_reg(base)
            reg_source = "cli"
        if reg is None:
            reg, reg_source, reason = _infer_base_reg_from_discrepancies(discrepancies)
            if reg is None:
                skipped.append((fn, reason or "no base"))
                continue

        if fn in offset_map:
            try:
                raw_offset = offset_map[fn]
                if isinstance(raw_offset, dict):
                    raw_offset = raw_offset.get("offset", 0)
                mapped_offset = _parse_int_literal(raw_offset, "--base-offset-map")
                mapped_offset_source = "base-offset-map"
            except ValueError as exc:
                skipped.append((fn, str(exc)))
                continue
        elif mapped_offset is None and cli_base_offset is not None:
            mapped_offset = cli_base_offset
            mapped_offset_source = "cli"

        selected = [
            d for d in discrepancies
            if _normalize_reg(d.get("base_reg", "")) == reg
        ]
        if not selected:
            skipped.append((fn, f"no offset discrepancies for base {reg}"))
            continue

        if mapped_offset is None:
            mapped_offset, mapped_offset_source, candidates = _infer_base_offset_from_layout(layout, selected)
        else:
            candidates = [mapped_offset]
        assert reg_source is not None
        assert mapped_offset_source is not None

        for d in selected:
            finding = _finding_from_offset_discrepancy(
                fn,
                d,
                layout,
                base_offset=mapped_offset,
                base_offset_source=mapped_offset_source,
                base_reg=reg,
                base_reg_source=reg_source,
            )
            if finding is None:
                # unmapped: likely interior-pointer or genuine register diff, not struct bug
                cur_disp = _parse_int_literal(d["cur_disp"], "cur_disp")
                cur_abs = mapped_offset + cur_disp
                note = f"unmapped cur 0x{cur_abs:x} (disp 0x{cur_disp:x})"
                if mapped_offset_source == "ambiguous-layout-fit":
                    note += "; base-offset candidates " + ",".join(hex(c) for c in candidates[:8])
                skipped.append((fn, note))
                continue
            findings.append(finding)

    agg = struct_verify.aggregate(findings)
    apply_result: dict | None = None
    if apply:
        if len(agg) != 1:
            apply_result = {
                "status": "not_applicable",
                "reason": f"--apply requires exactly one aggregate finding, got {len(agg)}",
            }
        else:
            item = agg[0]
            if item.get("conflict"):
                apply_result = {"status": "not_applicable", "reason": "conflicting expected offsets"}
            elif item.get("ambiguous"):
                apply_result = {"status": "not_applicable", "reason": "expected offset maps to a different known field"}
            else:
                field = item["field"]
                expected = item["expected"]
                delta = expected - item["current"]
                try:
                    header = struct_layout.find_struct_header(repo, struct)
                    apply_result = _apply_struct_padding(
                        header,
                        field,
                        delta=delta,
                        verify=lambda: struct_layout.verify_offsets(repo, struct, tu_src, {field: expected}),
                        struct_name=struct,
                    )
                except Exception as exc:
                    apply_result = {"status": "failed", "reason": str(exc)}

    if as_json:
        import sys
        payload = {"findings": agg, "skipped": [[fn, why] for fn, why in skipped]}
        if apply_result is not None:
            payload["apply"] = apply_result
        _json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    _render_verify_table(agg, skipped)
    if apply_result is not None:
        console.print(Panel(_json.dumps(apply_result, indent=2), title="apply"))
