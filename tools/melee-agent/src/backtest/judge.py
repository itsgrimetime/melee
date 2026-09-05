# tools/melee-agent/src/backtest/judge.py
from __future__ import annotations

import json
import re

_VALID = {"names-lever", "hints-adjacent", "silent-or-wrong"}

JUDGE_PROMPT = """You are scoring whether a set of tool outputs would lead an engineer to a
specific known source fix, WITHOUT being told the fix in advance by the tools.

You are given: the function name, the ground-truth diff (the fix), the lever class, and the
raw outputs of several advisory tools that were run BLIND (they did not see the fix).

Decide one verdict:
- "names-lever": a tool output explicitly identifies the change in the ground-truth diff
  (the same variable/type/literal/structural move). An engineer reading it would make the fix.
- "hints-adjacent": a tool points at the right region/mechanism but not the specific change.
- "silent-or-wrong": no tool references the actual lever (DEFAULT when uncertain).

Return STRICT JSON only: {"verdict": "<one of the three>", "rationale": "<one sentence>"}.
"""


def build_judge_input(case, advisory_outputs: dict) -> dict:
    return {
        "function": case.function,
        "ground_truth_diff": case.ground_truth_diff,
        "lever_class": case.lever_class,
        "tool_outputs": advisory_outputs,
    }


def _changed_identifiers(ground_truth_diff: str) -> set:
    """Identifiers that appear on added/removed lines of a unified diff."""
    tokens: set[str] = set()
    for line in ground_truth_diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            for tok in line[1:].split():
                if tok.isidentifier():
                    tokens.add(tok)
    return tokens


def keyword_advisory_verdict(ground_truth_diff: str, advisory_outputs: dict) -> str:
    """Deterministic keyword judge: does any advisory tool's stdout mention an
    identifier that changed in the ground-truth diff?

    Returns ``"names-lever"`` if so, else ``"silent-or-wrong"``. This is the
    non-LLM CLI fallback AND the logic the Phase-0 calibration gate exercises;
    both ``cheap_tiers_with_real_judge`` and ``calibrate`` call it (DRY).
    """
    changed_tokens = _changed_identifiers(ground_truth_diff)
    for tool_out in advisory_outputs.values():
        stdout = tool_out.get("stdout", "") if isinstance(tool_out, dict) else ""
        for tok in changed_tokens:
            if tok in stdout:
                return "names-lever"
    return "silent-or-wrong"


def parse_judge_verdict(text: str) -> str:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON object in judge output: {text[:200]}")
    verdict = json.loads(m.group(0)).get("verdict")
    if verdict not in _VALID:
        raise ValueError(f"out-of-vocabulary verdict: {verdict!r}")
    return verdict
