from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Resolve tools/melee-agent dir by walking up from this file's location.
# tiers.py lives at tools/melee-agent/src/backtest/tiers.py, so parents[2] is tools/melee-agent.
MELEE_AGENT_DIR = str(Path(__file__).resolve().parents[2])

# (label, argv template). {fn} and {unit} are substituted. These invoke the CLI under
# test from the worktree (python -m src.cli), pinned per Global Constraints.
ADVISORY_TOOLS = [
    ("inspect_explain_diff", ["debug", "inspect", "explain-diff", "{fn}", "--json"]),
    ("suggest_inlines", ["debug", "suggest", "inlines", "-f", "{fn}", "--json"]),
    ("inspect_diagnose", ["debug", "inspect", "diagnose", "{fn}", "--json"]),
    ("patterns_similar", ["patterns", "similar", "{fn}"]),
]

GENERATIVE_TOOLS = [
    ("search_directed", ["debug", "search", "directed", "-f", "{fn}", "-u", "{unit_short}", "--max-iters", "{max_iters}"]),
    ("search_structure", ["debug", "search", "structure", "-f", "{fn}",
                          "--axis", "decl-order", "--axis", "control-flow", "--json"]),
    ("mutate_decl_orders", ["debug", "mutate", "decl-orders", "-f", "{fn}"]),
    ("suggest_coalesce", ["debug", "suggest", "coalesce", "-f", "{fn}", "--discover", "--top", "5", "--json"]),
]


def default_cli_runner(args, *, cwd: str, timeout: float):
    """Run the worktree CLI against the sandbox tree. cwd is the sandbox (so report.json
    resolves there); we invoke the pinned CLI via PYTHONPATH to the worktree package root."""
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = MELEE_AGENT_DIR + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, "-m", "src.cli", *args],
                          cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def _subst(template, case):
    short = case.unit.removeprefix("main/")  # e.g. melee/gr/gricemt
    return [t.replace("{fn}", case.function).replace("{unit}", case.unit).replace("{unit_short}", short)
            for t in template]


def run_advisory(case, *, sandbox: str, cli_runner=default_cli_runner, budget_s: float = 120) -> dict:
    out = {}
    for label, template in ADVISORY_TOOLS:
        args = _subst(template, case)
        try:
            rc, stdout, _ = cli_runner(args, cwd=sandbox, timeout=budget_s)
        except subprocess.TimeoutExpired:
            rc, stdout = 124, ""
        out[label] = {"rc": rc, "stdout": stdout[:8000]}
    return out


def run_generative(case, *, sandbox: str, cli_runner=default_cli_runner, score_fn=None,
                   budget_s: float = 600, max_iters: int = 8) -> dict:
    best_ndl = case.baseline_ndl
    best_pct = case.baseline_pct
    ran, timed_out = [], []
    for label, template in GENERATIVE_TOOLS:
        args = [a.replace("{max_iters}", str(max_iters)) for a in _subst(template, case)]
        try:
            cli_runner(args, cwd=sandbox, timeout=budget_s)
            ran.append(args)
        except subprocess.TimeoutExpired:
            timed_out.append(args)
            continue
        if score_fn is not None:
            pct, ndl = score_fn(sandbox, case.function)
            if ndl is not None and (best_ndl is None or ndl < best_ndl):
                best_ndl, best_pct = ndl, pct
    return {"best_ndl": best_ndl, "best_pct": best_pct, "ran": ran, "timed_out": timed_out}
