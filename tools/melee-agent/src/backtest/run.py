from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .paths import main_repo_root


def __getattr__(name: str):
    # Resolve MAIN_REPO lazily so importing this module never forces melee-root
    # detection (and so tests can monkeypatch the resolver). Kept as a string for
    # backwards compatibility with the literal it replaced.
    if name == "MAIN_REPO":
        return str(main_repo_root())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _structural_ndl(payload: dict):
    gate = (payload.get("classification") or {}).get("structural_truth_gate") or {}
    return gate.get("normalized_diff_lines")


def run_checkdiff_at(repo_root: str, function: str, *, timeout: float = 600.0) -> dict:
    env = os.environ.copy()
    env["CHECKDIFF_NO_LOCK"] = "1"
    env["CHECKDIFF_NO_FINGERPRINT"] = "1"
    proc = subprocess.run(
        [sys.executable, "tools/checkdiff.py", function, "--format", "json", "--no-tty"],
        cwd=repo_root, capture_output=True, text=True, timeout=timeout, env=env,
    )
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return json.loads(proc.stdout)


def score_at_commit(main_repo: str, function: str, sha: str, *,
                    scratch_root: Path, timeout: float = 600.0):
    from .provision import provision_worktree
    wt = scratch_root / f"at_{sha[:12]}_{function[:16]}"   # include fn -> no concurrent-name collision
    subprocess.run(["git", "-C", main_repo, "worktree", "add", "--detach", str(wt), sha], check=True,
                   capture_output=True, text=True)
    try:
        provision_worktree(str(wt), main_repo=main_repo)
        payload = run_checkdiff_at(str(wt), function, timeout=timeout)
        return payload.get("fuzzy_match_percent"), _structural_ndl(payload)
    finally:
        subprocess.run(["git", "-C", main_repo, "worktree", "remove", "--force", str(wt)], check=False)


def build_and_store_corpus_from_commits(*, limit: int, max_lines: int, db):
    from .build_corpus import build_corpus_from_commits
    from .corpus import default_git_runner
    from .discover import discover_match_commits
    from .store import BacktestStore
    main_repo = str(main_repo_root())
    gr = default_git_runner(main_repo)
    triples = discover_match_commits(gr, limit=limit, max_lines=max_lines)
    patterns = _load_patterns()
    scratch_root = Path(main_repo) / "build" / "backtest" / "ground_truth"
    scratch_root.mkdir(parents=True, exist_ok=True)

    def score_flip(fn, sha):
        return score_at_commit(main_repo, fn, sha, scratch_root=scratch_root)

    cases = build_corpus_from_commits(triples=triples, git_runner=gr, patterns=patterns, score_flip=score_flip)
    store = BacktestStore(db)
    store.ensure_schema()
    for c in cases:
        store.insert_case(c)
    return {"discovered": len(triples), "stored": len(cases),
            "held_out": sum(1 for c in cases if c.provenance == "held_out")}


def build_and_store_corpus(*, functions_file: Path, limit: int, db):
    from .build_corpus import build_corpus
    from .corpus import default_git_runner
    from .store import BacktestStore  # Task 3.1
    import subprocess as sp

    main_repo = str(main_repo_root())
    functions = [l.strip() for l in Path(functions_file).read_text().splitlines() if l.strip()]
    if limit:
        functions = functions[:limit]
    report = json.loads(Path(main_repo, "build/GALE01/report.json").read_text())
    patterns = _load_patterns()
    scratch_root = Path(main_repo) / "build" / "backtest" / "ground_truth"
    scratch_root.mkdir(parents=True, exist_ok=True)

    def score_flip(fn, sha):
        return score_at_commit(main_repo, fn, sha, scratch_root=scratch_root)

    cases = build_corpus(functions=functions, report=report,
                         git_runner=default_git_runner(main_repo),
                         patterns=patterns, score_flip=score_flip)
    store = BacktestStore(db)
    store.ensure_schema()
    for c in cases:
        store.insert_case(c)
    return {"considered": len(functions), "stored": len(cases),
            "held_out": sum(1 for c in cases if c.provenance == "held_out")}


def _load_patterns() -> list:
    try:
        out = subprocess.run(["melee-agent", "mismatch", "list", "--json"],
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out, strict=False)
    except Exception:
        return []


def run_cheap_tiers(*, store, sandbox_factory, advisory_judge, score_fn,
                    advisory_runner=None, generative_runner=None, limit: int = 0) -> dict:
    from .tiers import run_advisory, run_generative
    from .score import generative_verdict, rollup_verdict
    from .types import CaseResult, Case

    advisory_runner = advisory_runner or (lambda case, sandbox: run_advisory(case, sandbox=sandbox))
    generative_runner = generative_runner or (
        lambda case, sandbox, score_fn: run_generative(case, sandbox=sandbox, score_fn=score_fn))

    cases = store.list_cases()
    if limit:
        cases = cases[:limit]
    counts = {"SOLVED-BY-TOOLING": 0, "PARTIAL": 0, "GAP": 0}
    for row in cases:
        case = Case(**{k: row[k] for k in (
            "function", "c_sha", "cprev_sha", "unit", "file", "ground_truth_diff",
            "lever_locus", "author", "provenance", "lever_class", "baseline_pct",
            "baseline_ndl", "target_pct", "target_ndl")})
        with sandbox_factory(case) as sandbox:
            adv_out = advisory_runner(case, sandbox)
            adv_verdict = advisory_judge(case, adv_out)
            gen = generative_runner(case, sandbox, lambda sb, fn: score_fn(sb, fn))
        gv = generative_verdict(baseline_ndl=case.baseline_ndl, baseline_pct=case.baseline_pct,
                                best_ndl=gen["best_ndl"], best_pct=gen["best_pct"])
        rollup = rollup_verdict(adv_verdict, gv, None)
        counts[rollup] += 1
        store.upsert_result(CaseResult(case_id=case.case_id, advisory=adv_verdict,
                                       generative=gv, rollup=rollup,
                                       evidence={"advisory": adv_out, "generative": gen}))
    return counts


def cheap_tiers_with_real_judge(*, limit: int = 0, db=None) -> dict:
    """Wire real sandbox, score, and a deterministic keyword judge, then run cheap tiers.

    The real LLM judge is supplied by the Workflow (Task 4.4); this keyword judge is
    the non-LLM CLI fallback used when running `backtest run --cheap` directly.
    """
    import contextlib
    from .store import BacktestStore
    from .sandbox import build_sandbox, teardown_sandbox

    store = BacktestStore(db)
    store.ensure_schema()
    main_repo = str(main_repo_root())

    @contextlib.contextmanager
    def sandbox_factory(case):
        dest = Path(main_repo) / "build" / "backtest" / "sandboxes" / case.case_id
        build_sandbox(main_repo=main_repo, c_sha=case.c_sha, cprev_sha=case.cprev_sha, dest=dest)
        try:
            yield str(dest)
        finally:
            teardown_sandbox(dest)

    def score_fn(sb, fn):
        p = run_checkdiff_at(sb, fn)
        return p.get("fuzzy_match_percent"), _structural_ndl(p)

    def _keyword_judge(case, advisory_outputs):
        # The REAL judge is the LLM run via the orchestration Workflow (Task 4.4).
        # This keyword judge is the non-LLM CLI fallback — shared with `calibrate`.
        from .judge import keyword_advisory_verdict
        return keyword_advisory_verdict(case.ground_truth_diff, advisory_outputs)

    return run_cheap_tiers(store=store, sandbox_factory=sandbox_factory,
                           advisory_judge=_keyword_judge, score_fn=score_fn, limit=limit)
