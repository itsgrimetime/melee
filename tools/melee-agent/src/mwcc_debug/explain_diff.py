"""
Explain a checkdiff JSON output — structured, ranked diagnosis of the
assembly diff with specific source-level recommendations.

Usage (standalone):
    python3 -m tools.melee-agent.src.mwcc_debug.explain_diff <checkdiff.json>
    python3 -m tools.melee-agent.src.mwcc_debug.explain_diff <function> --from-repo

Usage (CLI):
    melee-agent debug inspect explain-diff <function>
    melee-agent debug inspect explain-diff <checkdiff.json>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any


# Each recommendation has: signal (what checkdiff detected),
# recommendation (what to do), command (how to do it),
# cost_seconds (estimated time), impact (high/medium/low).

RECOMMENDATIONS: list[dict] = [
    {
        "signals": ["register-only", "register-allocation"],
        "recommendation": "Register allocation differs. Try force-phys or iter-first probes to find the correct coloring.",
        "command": "melee-agent debug target match-iter-first -f {function} --regs gpr-volatile",
        "cost_seconds": 10,
        "impact": "high",
    },
    {
        "signals": ["PAD_STACK", "pad_stack"],
        "recommendation": "PAD_STACK(N) detected. Replace with natural C that reserves N bytes: try a local array/struct, address-taken local, volatile temp, or call-argument temps around the shifted stack references.",
        "command": None,
        "cost_seconds": 60,
        "impact": "high",
    },
    {
        "signals": ["indexed-struct-pointer-materialization", "indexed_struct_pointer_materialization"],
        "recommendation": "Target uses indexed loads/stores (e.g. lbzx/lhzx), current materializes element pointers with 'add'. Split the first field into a scalar local; keep later accesses as direct array.base+offset.",
        "command": None,
        "cost_seconds": 60,
        "impact": "medium",
    },
    {
        "signals": ["signature-type-mismatch", "signature type mismatch", "call shape"],
        "recommendation": "Call signature differs. Check prototypes, return types, and inline boundaries. Run signature audit.",
        "command": "melee-agent debug suggest signatures -f {function}",
        "cost_seconds": 30,
        "impact": "high",
    },
    {
        "signals": ["stack slot", "stack-layout", "stack_layout"],
        "recommendation": "Stack frame or slot layout differs. Run frame reservation analysis.",
        "command": "melee-agent debug inspect frame-reservations {function}",
        "cost_seconds": 20,
        "impact": "medium",
    },
    {
        "signals": ["data/symbol relocations", "data-symbol", "relocation"],
        "recommendation": "Data/symbol relocations differ. Check .data layout, named externs, and assert strings.",
        "command": None,
        "cost_seconds": 120,
        "impact": "medium",
    },
    {
        "signals": ["instruction-sequence", "instruction sequence", "opcode"],
        "recommendation": "Instruction sequence differs (opcodes differ). Try decl-reorder enumeration or check inline boundaries.",
        "command": "melee-agent debug mutate decl-orders -f {function}",
        "cost_seconds": 70,
        "impact": "medium",
    },
    {
        "signals": ["control-flow", "branch", "hunk"],
        "recommendation": "Control flow shape differs. Check inline boundaries, loop structure, and conditional logic.",
        "command": None,
        "cost_seconds": 180,
        "impact": "medium",
    },
    {
        "signals": ["reg-only", "register-only", "regalloc", "callee-save"],
        "recommendation": "Register-only diffs remain. These may be a register-coloring ceiling. Try 'debug inspect guide' for allocator-level diagnosis.",
        "command": "melee-agent debug inspect guide -f {function}",
        "cost_seconds": 30,
        "impact": "low",
    },
    {
        "signals": ["line count differs", "line count", "line_delta"],
        "recommendation": "Line count differs — suggests missing or extra instructions. Check for memset/memcpy inlining differences or loop unrolling.",
        "command": None,
        "cost_seconds": 180,
        "impact": "medium",
    },
    {
        "signals": ["decl order", "decl-order", "declaration order"],
        "recommendation": "Declaration order may affect register allocation. Run decl-order enumeration.",
        "command": "melee-agent debug mutate decl-orders -f {function}",
        "cost_seconds": 70,
        "impact": "low",
    },
    {
        "signals": ["cast", "casting", "prototype"],
        "recommendation": "Suspicious casts detected. Run cast audit.",
        "command": "melee-agent debug inspect diagnose -f {function}",
        "cost_seconds": 30,
        "impact": "medium",
    },
]


def _check_available(command: str | None) -> bool:
    """Check if a recommendation command is likely available."""
    if not command:
        return False
    return True  # Assume available; the user will see unavailable ones.


def parse_checkdiff_json(path: str) -> dict | None:
    """Read and parse a checkdiff JSON file."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return None


def run_checkdiff(function: str, melee_root: str) -> dict | None:
    """Run checkdiff on a function and return parsed JSON."""
    # checkdiff.py may be in tools/ relative to melee_root, or in the main
    # repo if melee_root is a fork/worktree without its own checkdiff.
    checkdiff_candidates = [
        Path(melee_root) / "tools" / "checkdiff.py",
        Path(melee_root).parent / "melee" / "tools" / "checkdiff.py",
        Path.home() / "code" / "melee" / "tools" / "checkdiff.py",
    ]
    checkdiff_path = None
    for p in checkdiff_candidates:
        if p.exists():
            checkdiff_path = p
            break
    if checkdiff_path is None:
        return None

    try:
        env = {**os.environ, "DECOMP_AGENT_ID": "explain-diff"}
        proc = subprocess.run(
            ["python", str(checkdiff_path), function, "--format", "json",
             "--no-name-magic", "--no-fingerprint"],
            cwd=melee_root,
            capture_output=True, text=True, timeout=120,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1) or not proc.stdout:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def detect_relevant_signals(classification: dict, structural: dict) -> list[str]:
    """Extract signal keywords from checkdiff classification."""
    signals = []
    primary = classification.get("primary", "")
    reasons = classification.get("reasons") or []

    # Primary classification
    if primary:
        signals.append(primary)

    # Reason keywords
    for reason in reasons:
        reason_lower = reason.lower()
        for keyword in ["register-only", "register-only", "relocation", "stack",
                         "pad_stack", "call shape", "line count differs",
                         "inline boundary", "indexed struct", "register-allocation",
                         "control-flow", "instruction-sequence",
                         "signature-type-mismatch", "decl order", "cast"]:
            if keyword in reason_lower and keyword not in signals:
                signals.append(keyword)

    # Structural hints
    if structural:
        hunk_count = structural.get("hunk_count", 0)
        line_delta = abs(structural.get("line_delta", 0))
        if hunk_count >= 5:
            signals.append("control-flow")
        if line_delta >= 5:
            signals.append("line count differs")

    return signals


def rank_recommendations(signals: list[str]) -> list[dict]:
    """Rank applicable recommendations by match strength and impact."""
    matched = []
    for rec in RECOMMENDATIONS:
        match_count = sum(1 for s in signals if any(
            rs in s for rs in rec["signals"]))
        if match_count > 0:
            entry = dict(rec)
            entry["match_strength"] = match_count
            matched.append(entry)

    # Sort: more matches first, then higher impact, then lower cost.
    impact_order = {"high": 0, "medium": 1, "low": 2}
    matched.sort(key=lambda r: (
        -r["match_strength"],
        impact_order.get(r["impact"], 99),
        r["cost_seconds"],
    ))
    return matched


def format_diagnosis(data: dict, function: str | None = None) -> str:
    """Format a human-readable diagnosis from checkdiff JSON."""
    cls = data.get("classification", {})
    struct = data.get("structural", {})
    match_pct = data.get("fuzzy_match_percent", 0)
    is_match = data.get("match", False)

    lines = []
    lines.append(f"Function: {function or data.get('function', '?')}")
    match_str = f"{match_pct:.1f}%" if match_pct is not None else "?%"
    lines.append(f"Match: {match_str} {'✓ MATCH' if is_match else '✗ NOT MATCHED'}")
    op_sim = struct.get('opcode_similarity', 0) or 0
    lines.append(f"Hunks: {struct.get('hunk_count', '?')}  "
                 f"Line delta: {struct.get('line_delta', '?')}  "
                 f"Opcode similarity: {op_sim*100:.1f}%")
    lines.append("")

    # Primary classification
    primary = cls.get("primary", "unknown")
    lines.append(f"Classification: {primary}")
    for reason in cls.get("reasons", []):
        lines.append(f"  • {reason}")
    lines.append("")

    # Recommendations
    signals = detect_relevant_signals(cls, struct)
    recommendations = rank_recommendations(signals)

    if recommendations:
        lines.append("Recommendations (ranked):")
        for i, rec in enumerate(recommendations, 1):
            impact_mark = {
                "high": "██",
                "medium": "▒▒",
                "low": "░░",
            }.get(rec["impact"], "░░")
            lines.append(f"")
            lines.append(f"  {i}. [{impact_mark}] {rec['recommendation']}")
            lines.append(f"     Estimated: ~{rec['cost_seconds']}s  "
                         f"Impact: {rec['impact']}")
            cmd = rec.get("command", "")
            if cmd:
                cmd_text = cmd.format(function=function or data.get('function', ''))
                lines.append(f"     Run: {cmd_text}")
    else:
        lines.append("No specific recommendations match this diff pattern.")
        lines.append("Consider running the general stuck-function diagnosis:")
        lines.append(f"  melee-agent debug inspect stuck {function or data.get('function', '')}")
        lines.append(f"  melee-agent debug inspect diagnose -f {function or data.get('function', '')}")

    lines.append("")
    lines.append("─" * 60)
    lines.append("Debug resources:")
    lines.append(f"  melee-agent debug inspect guide -f {function or data.get('function', '')}")
    lines.append(f"  melee-agent debug inspect stuck {function or data.get('function', '')}")
    lines.append(f"  melee-agent debug inspect diagnose -f {function or data.get('function', '')}")
    lines.append(f"  melee-agent debug mutate decl-orders -f {function or data.get('function', '')}")

    return "\n".join(lines)


def produce_diagnosis(data: dict, function: str | None = None) -> dict:
    """Produce a structured machine-readable diagnosis."""
    cls = data.get("classification", {})
    struct = data.get("structural", {})
    signals = detect_relevant_signals(cls, struct)
    recommendations = rank_recommendations(signals)

    return {
        "function": function or data.get("function", ""),
        "match": data.get("match", False),
        "fuzzy_match_percent": data.get("fuzzy_match_percent", 0),
        "classification": {
            "primary": cls.get("primary", "unknown"),
            "reasons": cls.get("reasons", []),
            "indexed_struct_pointer_materialization": cls.get(
                "indexed_struct_pointer_materialization"),
            "register_allocation_guidance": cls.get(
                "register_allocation_guidance"),
            "diagnostic_pad_stack": cls.get("diagnostic_pad_stack"),
        },
        "structural": struct,
        "signals": signals,
        "recommendations": [
            {
                "rank": i + 1,
                "recommendation": rec["recommendation"],
                "command": (rec.get("command", "") or "").format(
                    function=function or data.get("function", "")),
                "cost_seconds": rec["cost_seconds"],
                "impact": rec["impact"],
                "match_strength": rec["match_strength"],
            }
            for i, rec in enumerate(recommendations)
        ],
    }


def main() -> int:
    """Standalone entry point."""
    if len(sys.argv) < 2:
        print("Usage: explain_diff.py <checkdiff.json>")
        print("   or: explain_diff.py <function> --from-repo <melee_root>")
        print()
        print("Reads checkdiff JSON output and produces a structured, ranked")
        print("diagnosis with specific source-level recommendations.")
        return 1

    target = sys.argv[1]

    # Determine input source
    if len(sys.argv) >= 4 and "--from-repo" in sys.argv:
        melee_root = sys.argv[sys.argv.index("--from-repo") + 1]
        data = run_checkdiff(target, melee_root)
        function = target
    elif os.path.isfile(target):
        data = parse_checkdiff_json(target)
        function = data.get("function") if data else None
    else:
        # Assume it's a function name; try auto-detecting melee root
        candidates = [Path.cwd(), Path.cwd().parent / "melee", Path.home() / "code" / "melee"]
        for root in candidates:
            if (root / "tools" / "checkdiff.py").exists():
                data = run_checkdiff(target, str(root))
                function = target
                break
        else:
            data = None
            function = target

    if data is None:
        print(f"Error: could not load checkdiff data for {target}", file=sys.stderr)
        return 1

    # Output
    if "--json" in sys.argv:
        diagnosis = produce_diagnosis(data, function)
        print(json.dumps(diagnosis, indent=2))
    else:
        diagnosis = format_diagnosis(data, function)
        print(diagnosis)

    return 0


if __name__ == "__main__":
    sys.exit(main())
