"""
Pattern discovery tools for finding idiomatic code patterns.

Helps discover wrapper functions, similar structures, and API usage patterns
from the codebase to avoid overcomplicated solutions during decompilation.
"""

import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table
from typing_extensions import Annotated

from ._common import DEFAULT_MELEE_ROOT

console = Console()

# Main patterns app
patterns_app = typer.Typer(
    name="patterns",
    help="Discover code patterns, wrapper functions, and API idioms from matched code.",
)


# =============================================================================
# WRAPPER FUNCTION DISCOVERY
# =============================================================================

# Known wrapper functions mapping field access -> wrapper
KNOWN_WRAPPERS = {
    # GObj wrappers
    "gobj->user_data": {
        "wrapper": "HSD_GObjGetUserData(gobj)",
        "header": "baselib/gobjuserdata.h",
        "note": "Cleaner than direct field access",
    },
    "gobj->hsd_obj": {
        "wrapper": "HSD_GObjGetHSDObj(gobj)",
        "header": "baselib/gobjobject.h",
        "note": "Returns the HSD object (JObj, etc.)",
    },
    # JObj wrappers
    "jobj->child": {
        "wrapper": "HSD_JObjGetChild(jobj)",
        "header": "baselib/jobj.h",
        "note": "Gets first child, handles NULL safely",
    },
    "jobj->next": {
        "wrapper": "HSD_JObjGetSibling(jobj)",
        "header": "baselib/jobj.h",
        "note": "Gets next sibling",
    },
    "jobj->parent": {
        "wrapper": "HSD_JObjGetParent(jobj)",
        "header": "baselib/jobj.h",
        "note": "Gets parent JObj",
    },
    # Common null-check-then-access patterns
    "tmp = x; if (tmp == NULL) tmp = NULL; else tmp = tmp->field": {
        "wrapper": "Use wrapper function (e.g., HSD_JObjGetChild)",
        "header": "various",
        "note": "This ternary pattern usually means a wrapper exists",
    },
}

# Patterns that indicate overcomplicated code
ANTI_PATTERNS = {
    "pointer arithmetic for array": {
        "pattern": r"\(\w+\*\)\s*\(\(u8\*\)\s*\w+\s*\+\s*\(?\w+\s*<<\s*\d+\)?",
        "symptom": "Using pointer arithmetic like ((Type*)((u8*)ptr + (i << 2)))->field[0]",
        "solution": "Use direct array indexing: ptr->field[i]",
        "example_bad": "((Diagram2*) ((u8*) data + (i << 2)))->row_labels[0]",
        "example_good": "data->row_labels[i]",
    },
    "repeated null-check-clear pattern": {
        "pattern": r"if\s*\([^)]+\s*!=\s*NULL\)\s*\{[^}]*SisLib[^}]*=\s*NULL",
        "symptom": "Repeated if (x != NULL) { SisLib(x); x = NULL; } pattern",
        "solution": "Consider inline: static inline void SisLib_ClearText(HSD_Text** p) { if (*p) { HSD_SisLib_803A5CC4(*p); *p = NULL; } }",
        "example_bad": "if (data->text != NULL) { HSD_SisLib_803A5CC4(data->text); data->text = NULL; }",
        "example_good": "SisLib_ClearText(&data->text);",
    },
    "manual null check cascade": {
        "pattern": r"tmp\s*=\s*\w+;\s*if\s*\(tmp\s*==\s*NULL\)",
        "symptom": "tmp = x; if (tmp == NULL) { tmp = NULL; } else { tmp = tmp->field; }",
        "solution": "Look for wrapper functions like HSD_JObjGetChild()",
        "example_bad": "tmp = jobj; if (tmp == NULL) tmp = NULL; else tmp = tmp->child;",
        "example_good": "child = HSD_JObjGetChild(jobj);",
    },
    "increment pointer in loop": {
        "pattern": r"\w+\s*=\s*\(\w+\*\)\s*\(\(u8\*\)\s*\w+\s*\+\s*\d+\)",
        "symptom": "ptr = (Type*) ((u8*) ptr + 4) in a loop",
        "solution": "Use array indexing or ptr++ if it's a real array",
        "example_bad": "base = (Diagram2*) ((u8*) base + 4);",
        "example_good": "for (i = 0; i < 10; i++) { use array[i] }",
    },
}


def search_codebase_for_pattern(pattern: str, melee_root: Path) -> list[dict]:
    """Search matched source files for a pattern."""
    results = []
    src_dir = melee_root / "src" / "melee"

    try:
        # Use ripgrep for fast searching
        cmd = ["rg", "-n", "--json", pattern, str(src_dir)]
        proc = subprocess.run(cmd, capture_output=True, text=True)

        for line in proc.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match_data = data["data"]
                    results.append({
                        "file": match_data["path"]["text"],
                        "line": match_data["line_number"],
                        "text": match_data["lines"]["text"].strip(),
                    })
            except json.JSONDecodeError:
                continue
    except FileNotFoundError:
        # Fallback to grep if rg not available
        cmd = ["grep", "-rn", pattern, str(src_dir)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        for line in proc.stdout.strip().split("\n"):
            if ":" in line:
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    results.append({
                        "file": parts[0],
                        "line": int(parts[1]),
                        "text": parts[2].strip(),
                    })

    return results


def find_wrapper_usages(wrapper_name: str, melee_root: Path) -> list[dict]:
    """Find how many times a wrapper function is used in matched code."""
    return search_codebase_for_pattern(wrapper_name, melee_root)


@patterns_app.command("wrapper")
def wrapper_search(
    pattern: Annotated[str, typer.Argument(help="Field access pattern to search for (e.g., 'gobj->user_data')")],
    melee_root: Annotated[Path, typer.Option("--root", help="Melee repo root")] = DEFAULT_MELEE_ROOT,
):
    """Find wrapper functions for common field access patterns.

    Examples:
        melee-agent patterns wrapper "gobj->user_data"
        melee-agent patterns wrapper "jobj->child"
        melee-agent patterns wrapper "null check"
    """
    pattern_lower = pattern.lower()

    # Check known wrappers
    found_wrappers = []
    for field_pattern, info in KNOWN_WRAPPERS.items():
        if pattern_lower in field_pattern.lower() or pattern_lower in info["wrapper"].lower():
            found_wrappers.append((field_pattern, info))

    if found_wrappers:
        rprint("\n[bold green]Known wrapper functions:[/bold green]\n")
        for field_pattern, info in found_wrappers:
            rprint(f"  [cyan]Pattern:[/cyan] {field_pattern}")
            rprint(f"  [green]Wrapper:[/green] {info['wrapper']}")
            rprint(f"  [dim]Header:[/dim] {info['header']}")
            rprint(f"  [dim]Note:[/dim] {info['note']}")

            # Show usage count
            wrapper_name = info['wrapper'].split('(')[0]
            usages = find_wrapper_usages(wrapper_name, melee_root)
            rprint(f"  [yellow]Used in {len(usages)} places in matched code[/yellow]")
            rprint()
    else:
        rprint(f"\n[yellow]No known wrapper for pattern: {pattern}[/yellow]")
        rprint("\nSearching codebase for similar patterns...\n")

        # Search for the pattern in code
        results = search_codebase_for_pattern(pattern, melee_root)
        if results:
            rprint(f"Found {len(results)} occurrences:")
            for r in results[:10]:
                rprint(f"  {r['file']}:{r['line']}: {r['text'][:80]}")
            if len(results) > 10:
                rprint(f"  ... and {len(results) - 10} more")


@patterns_app.command("anti-pattern")
def check_anti_patterns(
    code: Annotated[Optional[str], typer.Argument(help="Code snippet to check (or 'list' to show all)")] = None,
):
    """Check if code uses known anti-patterns and suggest fixes.

    Examples:
        melee-agent patterns anti-pattern "list"
        melee-agent patterns anti-pattern "((u8*) data + (i << 2))"
    """
    if code == "list" or code is None:
        rprint("\n[bold]Known Anti-Patterns (overcomplicated code that should be simpler):[/bold]\n")
        for name, info in ANTI_PATTERNS.items():
            rprint(f"[bold red]{name}[/bold red]")
            rprint(f"  [yellow]Symptom:[/yellow] {info['symptom']}")
            rprint(f"  [green]Solution:[/green] {info['solution']}")
            rprint(f"  [dim]Bad:[/dim]  {info['example_bad']}")
            rprint(f"  [dim]Good:[/dim] {info['example_good']}")
            rprint()
        return

    # Check if code matches any anti-pattern
    matches = []
    for name, info in ANTI_PATTERNS.items():
        if re.search(info["pattern"], code):
            matches.append((name, info))

    if matches:
        rprint("\n[bold red]Anti-patterns detected![/bold red]\n")
        for name, info in matches:
            rprint(f"[bold]{name}[/bold]")
            rprint(f"  [yellow]Problem:[/yellow] {info['symptom']}")
            rprint(f"  [green]Fix:[/green] {info['solution']}")
            rprint(f"  [dim]Example fix:[/dim] {info['example_bad']} -> {info['example_good']}")
            rprint()
    else:
        rprint("[green]No obvious anti-patterns detected.[/green]")


# =============================================================================
# SIMILAR STRUCTURE FINDER
# =============================================================================

def get_function_structure(func_name: str, melee_root: Path) -> Optional[dict]:
    """Extract structural info from a function (loops, array accesses, API calls)."""
    # Find the function in source
    src_dir = melee_root / "src" / "melee"

    # Search for function definition
    cmd = ["rg", "-l", f"^\\w[^\\n]*{func_name}\\s*\\(", str(src_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    if not proc.stdout.strip():
        return None

    source_file = Path(proc.stdout.strip().split("\n")[0])

    # Read the file and extract function
    content = source_file.read_text()

    # Simple extraction - find function and count patterns
    structure = {
        "name": func_name,
        "file": str(source_file),
        "loops": {
            "for": len(re.findall(r'\bfor\s*\(', content)),
            "while": len(re.findall(r'\bwhile\s*\(', content)),
            "do_while": len(re.findall(r'\bdo\s*\{', content)),
        },
        "api_calls": [],
        "array_accesses": len(re.findall(r'\[\w+\]', content)),
    }

    # Find HSD_* and other API calls
    api_pattern = r'\b(HSD_\w+|lb_\w+|mn_\w+|gm_\w+)\s*\('
    for match in re.finditer(api_pattern, content):
        if match.group(1) not in structure["api_calls"]:
            structure["api_calls"].append(match.group(1))

    return structure


def find_similar_functions(target_structure: dict, melee_root: Path, limit: int = 10) -> list[dict]:
    """Find matched functions with similar structure."""
    similar = []

    # Load report for matched functions
    report_path = melee_root / "build" / "GALE01" / "report.json"
    if not report_path.exists():
        return similar

    with open(report_path) as f:
        report = json.load(f)

    # Get list of 100% matched functions
    matched_funcs = []
    for unit in report.get("units", []):
        for func in unit.get("functions", []):
            if func.get("fuzzy_match_percent", 0) == 100:
                matched_funcs.append(func["name"])

    # Compare structures (simplified - just check API calls overlap)
    target_apis = set(target_structure.get("api_calls", []))

    for func_name in matched_funcs[:200]:  # Limit search
        struct = get_function_structure(func_name, melee_root)
        if not struct:
            continue

        func_apis = set(struct.get("api_calls", []))
        overlap = len(target_apis & func_apis)

        if overlap >= 2:  # At least 2 common API calls
            similar.append({
                "name": func_name,
                "file": struct["file"],
                "common_apis": list(target_apis & func_apis),
                "score": overlap,
            })

    # Sort by score
    similar.sort(key=lambda x: -x["score"])
    return similar[:limit]


@patterns_app.command("similar")
def find_similar(
    function: Annotated[str, typer.Argument(help="Function name to find similar matches for")],
    melee_root: Annotated[Path, typer.Option("--root", help="Melee repo root")] = DEFAULT_MELEE_ROOT,
    limit: Annotated[int, typer.Option("-n", "--limit", help="Max results")] = 10,
):
    """Find matched functions with similar structure to a target function.

    Looks for functions that use similar API calls, loop patterns, and array accesses.
    Useful for finding reference implementations when stuck.

    Examples:
        melee-agent patterns similar mnDiagram2_ClearStatRows
    """
    rprint(f"\nAnalyzing structure of {function}...")

    target = get_function_structure(function, melee_root)
    if not target:
        rprint(f"[red]Could not find function: {function}[/red]")
        raise typer.Exit(1)

    rprint(f"  File: {target['file']}")
    rprint(f"  API calls: {', '.join(target['api_calls'][:10])}")
    rprint(f"  Array accesses: {target['array_accesses']}")

    rprint(f"\nSearching for similar matched functions...")
    similar = find_similar_functions(target, melee_root, limit)

    if not similar:
        rprint("[yellow]No similar functions found.[/yellow]")
        return

    rprint(f"\n[bold green]Similar matched functions:[/bold green]\n")

    table = Table()
    table.add_column("Function", style="cyan")
    table.add_column("Common APIs", style="green")
    table.add_column("Score")

    for func in similar:
        table.add_row(
            func["name"],
            ", ".join(func["common_apis"][:3]),
            str(func["score"]),
        )

    console.print(table)

    rprint("\n[dim]Tip: Read these matched functions to see how they solved similar patterns.[/dim]")


# =============================================================================
# API USAGE PATTERNS
# =============================================================================

def analyze_api_usage(api_pattern: str, melee_root: Path) -> dict:
    """Analyze how an API is used across matched code."""
    src_dir = melee_root / "src" / "melee"

    results = {
        "pattern": api_pattern,
        "total_uses": 0,
        "files": defaultdict(int),
        "examples": [],
    }

    # Search for the pattern
    matches = search_codebase_for_pattern(api_pattern, melee_root)
    results["total_uses"] = len(matches)

    for match in matches:
        file_name = Path(match["file"]).name
        results["files"][file_name] += 1
        if len(results["examples"]) < 5:
            results["examples"].append(match)

    return results


@patterns_app.command("api")
def api_usage(
    topic: Annotated[str, typer.Argument(help="API or topic to search for (e.g., 'user_data', 'JObjGetChild')")],
    melee_root: Annotated[Path, typer.Option("--root", help="Melee repo root")] = DEFAULT_MELEE_ROOT,
):
    """Show how APIs are commonly used in matched code.

    Helps discover idiomatic patterns by showing real usage examples.

    Examples:
        melee-agent patterns api "user_data"
        melee-agent patterns api "HSD_JObjGetChild"
        melee-agent patterns api "SisLib"
    """
    rprint(f"\nAnalyzing API usage for: {topic}\n")

    # Search for different forms
    patterns_to_check = [
        (f"HSD_.*{topic}", "Wrapper function"),
        (f"->.*{topic}", "Direct field access"),
        (topic, "General usage"),
    ]

    for pattern, desc in patterns_to_check:
        results = analyze_api_usage(pattern, melee_root)
        if results["total_uses"] > 0:
            rprint(f"[bold]{desc}:[/bold] {results['total_uses']} uses")

            # Show file distribution
            if results["files"]:
                top_files = sorted(results["files"].items(), key=lambda x: -x[1])[:5]
                for fname, count in top_files:
                    rprint(f"  {fname}: {count}")

            # Show examples
            if results["examples"]:
                rprint("\n  [dim]Examples:[/dim]")
                for ex in results["examples"][:3]:
                    rprint(f"    {ex['text'][:70]}...")
            rprint()


# =============================================================================
# SIMPLICITY CHECKER
# =============================================================================

@patterns_app.command("check")
def check_simplicity(
    file_path: Annotated[Path, typer.Argument(help="Source file to check for anti-patterns")],
):
    """Check a source file for common anti-patterns and suggest simplifications.

    Examples:
        melee-agent patterns check src/melee/mn/mndiagram2.c
    """
    if not file_path.exists():
        rprint(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)

    content = file_path.read_text()
    issues = []

    # Check each anti-pattern
    for name, info in ANTI_PATTERNS.items():
        matches = list(re.finditer(info["pattern"], content))
        if matches:
            for match in matches:
                # Find line number
                line_num = content[:match.start()].count('\n') + 1
                issues.append({
                    "line": line_num,
                    "pattern": name,
                    "text": match.group(0)[:50],
                    "fix": info["solution"],
                })

    # Check for known wrapper opportunities
    wrapper_opportunities = [
        (r'(\w+)->user_data(?!\s*\))', "gobj->user_data", "HSD_GObjGetUserData(gobj)"),
        (r'(\w+)->child(?!\s*\))', "jobj->child", "HSD_JObjGetChild(jobj)"),
    ]

    for pattern, desc, wrapper in wrapper_opportunities:
        matches = list(re.finditer(pattern, content))
        if matches:
            for match in matches:
                line_num = content[:match.start()].count('\n') + 1
                issues.append({
                    "line": line_num,
                    "pattern": f"Direct field access ({desc})",
                    "text": match.group(0),
                    "fix": f"Consider using {wrapper}",
                })

    if issues:
        rprint(f"\n[bold yellow]Found {len(issues)} potential simplifications:[/bold yellow]\n")
        for issue in sorted(issues, key=lambda x: x["line"]):
            rprint(f"  Line {issue['line']}: [red]{issue['pattern']}[/red]")
            rprint(f"    Code: {issue['text']}")
            rprint(f"    [green]Fix: {issue['fix']}[/green]")
            rprint()
    else:
        rprint("[green]No obvious anti-patterns found![/green]")


# =============================================================================
# INLINE CANDIDATE FINDER
# =============================================================================

# Patterns that suggest inline function opportunities
INLINE_CANDIDATES = {
    "null-check-cleanup": {
        "pattern": r"if\s*\((\w+(?:->[\w\[\]]+)*)\s*!=\s*NULL\)\s*\{\s*\w+\([^)]*\1[^)]*\);\s*\1\s*=\s*NULL;\s*\}",
        "description": "Null check → function call → set to null",
        "suggested_inline": """\
static inline void ClearAndFree_{name}({type}** p) {{
    if (*p != NULL) {{
        {cleanup_func}(*p);
        *p = NULL;
    }}
}}""",
    },
    "get-child-null-check": {
        "pattern": r"(\w+)\s*=\s*(\w+);\s*if\s*\(\1\s*==\s*NULL\)\s*\{\s*\1\s*=\s*NULL;\s*\}\s*else\s*\{\s*\1\s*=\s*\2->(\w+);\s*\}",
        "description": "tmp = x; if (tmp == NULL) tmp = NULL; else tmp = x->field",
        "suggested_inline": "Use HSD_JObjGetChild() or similar wrapper",
    },
    "sislib-text-cleanup": {
        "pattern": r"HSD_SisLib_803A5CC4\([^)]+\);\s*[^=]+=\s*NULL",
        "description": "SisLib cleanup followed by NULL assignment",
        "suggested_inline": """\
static inline void SisLib_ClearText(HSD_Text** text) {
    if (*text != NULL) {
        HSD_SisLib_803A5CC4(*text);
        *text = NULL;
    }
}""",
    },
}


def find_inline_candidates(file_path: Path) -> list[dict]:
    """Find patterns that could be extracted into inline functions."""
    content = file_path.read_text()
    candidates = []

    # Count SisLib cleanup pattern occurrences
    sislib_pattern = r"if\s*\([^)]+\s*!=\s*NULL\)\s*\{[^}]*HSD_SisLib_803A5CC4[^}]*=\s*NULL[^}]*\}"
    sislib_matches = list(re.finditer(sislib_pattern, content, re.DOTALL))
    if len(sislib_matches) >= 3:
        candidates.append({
            "type": "sislib-text-cleanup",
            "count": len(sislib_matches),
            "lines": [content[:m.start()].count('\n') + 1 for m in sislib_matches[:5]],
            "suggestion": INLINE_CANDIDATES["sislib-text-cleanup"]["suggested_inline"],
        })

    # Count is_name_mode conditional pattern
    name_mode_pattern = r"if\s*\(\w+\s*!=\s*0\)\s*\{[^}]*GetNameByIndex[^}]*\}\s*else\s*\{[^}]*GetFighterByIndex"
    name_mode_matches = list(re.finditer(name_mode_pattern, content, re.DOTALL))
    if len(name_mode_matches) >= 2:
        candidates.append({
            "type": "is-name-mode-conditional",
            "count": len(name_mode_matches),
            "lines": [content[:m.start()].count('\n') + 1 for m in name_mode_matches],
            "suggestion": """\
static inline u8 mnDiagram_GetEntityByIndex(u8 is_name_mode, u8 idx) {
    if (is_name_mode != 0) {
        return mnDiagram_GetNameByIndex(idx);
    }
    return mnDiagram_GetFighterByIndex(idx);
}""",
        })

    # Count null-check-then-child pattern
    child_pattern = r"tmp\s*=\s*\w+;\s*if\s*\(tmp\s*==\s*NULL\)"
    child_matches = list(re.finditer(child_pattern, content))
    if len(child_matches) >= 2:
        candidates.append({
            "type": "get-child-null-check",
            "count": len(child_matches),
            "lines": [content[:m.start()].count('\n') + 1 for m in child_matches],
            "suggestion": "Use HSD_JObjGetChild() or create custom getter inline",
        })

    # Count direct gobj->user_data accesses
    userdata_pattern = r"(\w+)->user_data"
    userdata_matches = list(re.finditer(userdata_pattern, content))
    if len(userdata_matches) >= 5:
        candidates.append({
            "type": "gobj-user-data",
            "count": len(userdata_matches),
            "lines": [content[:m.start()].count('\n') + 1 for m in userdata_matches[:5]],
            "suggestion": "Add GET_DIAGRAM2(gobj) macro to inlines.h",
        })

    return candidates


@patterns_app.command("inlines")
def find_inlines(
    file_path: Annotated[Path, typer.Argument(help="Source file to analyze")],
):
    """Find patterns that could be extracted into inline functions.

    Analyzes a source file for repeated patterns that suggest inline opportunities.

    Examples:
        melee-agent patterns inlines src/melee/mn/mndiagram2.c
    """
    if not file_path.exists():
        rprint(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)

    candidates = find_inline_candidates(file_path)

    if not candidates:
        rprint("[green]No obvious inline candidates found.[/green]")
        return

    rprint(f"\n[bold]Inline Function Candidates in {file_path.name}:[/bold]\n")

    for c in candidates:
        rprint(f"[bold cyan]{c['type']}[/bold cyan] - found {c['count']} occurrences")
        rprint(f"  Lines: {', '.join(str(l) for l in c['lines'][:5])}{'...' if len(c['lines']) > 5 else ''}")
        rprint(f"\n  [green]Suggested inline:[/green]")
        for line in c['suggestion'].split('\n'):
            rprint(f"    {line}")
        rprint()


def main():
    patterns_app()


if __name__ == "__main__":
    main()
