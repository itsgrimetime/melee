"""FPR G1 sweep (spec §5) — STAGED: sizing -> clean-fixture gate -> time-boxed
fallback. classify_sweep is PURE; run_fpr_sweep is the COMPLETE live driver.

STRICT contract (codex major 8 / rev3 §5 "do not relax"):
  pass             : zero G1 misses on clean class-1 fixtures.
  proceed_filtered : EVERY miss covered by a documented static exclusion
                     (fpr_coverage: filtered).
  hard_stop        : ANY uncharacterized clean-fixture miss. remedy:
                     "fix-fpr-dispense-reading" when the uncharacterized rate
                     is <= 5% (fix the dispense reading, re-run);
                     "ship-gpr-only" when > 5%. Both BLOCK the FPR pilot.

Live driver inputs (deterministic): the objdiff build report
(build/GALE01/report.json — schema probed in the plan's Step 3), iterated for
matched (100%) functions; each is dumped via `debug dump local --no-cache-sync`
under the caller-held repo lock (CHECKDIFF_NO_LOCK=1 children contract), and
its class-1 COLORGRAPH (if any) is G1-validated.
Run:  python -m src.search.solver.fpr_sweep [--limit N]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SweepTally:
    n_fpr: int                       # SIZING: class-1-COLORGRAPH-bearing matched fns
    clean: int                       # untruncated + complete-interferer fixtures
    excluded_truncated: int          # un-gradeable (excluded from denominator)
    g1_perfect: int
    g1_imperfect_clean: int
    characterized_exclusions: int    # misses explained by a documented static property


def classify_sweep(t: SweepTally) -> dict:
    base = {"n_fpr": t.n_fpr, "denominator_clean": t.clean,
            "excluded_truncated": t.excluded_truncated,
            "g1_perfect": t.g1_perfect,
            "g1_imperfect_clean": t.g1_imperfect_clean,
            "characterized_exclusions": t.characterized_exclusions}
    if t.g1_imperfect_clean == 0:
        return {**base, "verdict": "pass", "fpr_coverage": "full"}
    uncharacterized = t.g1_imperfect_clean - t.characterized_exclusions
    if uncharacterized <= 0:
        return {**base, "verdict": "proceed_filtered",
                "fpr_coverage": "filtered"}
    rate = uncharacterized / max(t.clean, 1)
    return {**base, "verdict": "hard_stop", "fpr_coverage": "gpr_only",
            "uncharacterized": uncharacterized, "uncharacterized_rate": rate,
            "remedy": "ship-gpr-only" if rate > 0.05
                      else "fix-fpr-dispense-reading"}


def _iter_matched_functions(report: dict):
    """Yield (unit_name, function_name) for 100%-matched functions.
    Accessor lines adjusted to the Step-3 schema probe if needed."""
    for unit in report.get("units", []):
        uname = unit.get("name", "")
        for fn in unit.get("functions", []):
            pct = fn.get("fuzzy_match_percent")          # accessor line 1
            name = fn.get("name")                        # accessor line 2
            if name and pct is not None and float(pct) >= 100.0:
                yield uname, name


def _unit_source_path(melee_root: Path, unit: dict) -> Path | None:
    """Resolve the .c TU for a report unit.

    DEVIATION (T17 self-review, justified): the plan's draft mapped the unit
    name with `uname.removesuffix(".o")` then `src/<unit>.c`. The Step-3 schema
    probe shows THIS repo's report units carry NO `.o` suffix and a `main/`
    build-group prefix (e.g. "main/melee/lb/lbcommand"), whose source lives at
    src/melee/lb/lbcommand.c — so the draft mapping yields a non-existent
    src/main/... path and the driver would size 0 FPR fixtures. This reuses the
    repo's proven normalization (search/structure_scoring.py
    `_normalize_report_unit_name` / `_source_path_for_unit`): strip `main/`,
    `.c`, and a leading `src/`, prefer an explicit unit source key, else
    src/<unit>.c. The pure classify_sweep (which carries the test coverage) is
    untouched.
    """
    for key in ("source_path", "source", "path"):
        raw = unit.get(key)
        if not raw:
            continue
        path = Path(str(raw))
        if not path.is_absolute():
            path = melee_root / path
        if path.suffix == ".c":
            return path
    unit_rel = (str(unit.get("name") or "")
                .removeprefix("main/").removesuffix(".c").removeprefix("src/"))
    if not unit_rel:
        return None
    return melee_root / "src" / f"{unit_rel}.c"


def run_fpr_sweep(*, melee_root: Path, limit: int | None = None,
                  exclusion_predicates: dict | None = None) -> dict:
    """COMPLETE live sweep. exclusion_predicates: {label: fn(ig)->bool} — the
    documented static properties that characterize a miss (starts empty; add
    one ONLY with a written justification in the sweep doc)."""
    sys.path.insert(0, str(melee_root / "tools" / "melee-agent"))
    from src.mwcc_debug import tiebreak as tb
    import src.cli.debug as debugcli

    report = json.loads((melee_root / "build" / "GALE01" / "report.json")
                        .read_text(encoding="utf-8"))
    units_by_name = {u.get("name", ""): u for u in report.get("units", [])}
    fns = list(_iter_matched_functions(report))
    if limit:
        fns = fns[:limit]

    n_fpr = clean = excl = perfect = imperfect = characterized = 0
    misses: list = []
    agent_root = melee_root / "tools" / "melee-agent"
    with debugcli._acquire_checkdiff_repo_lock(melee_root, label="fpr sweep"):
        env = debugcli._checkdiff_env_for_locked_child(disable_fingerprint=False)
        for uname, fname in fns:
            # unit name -> src/<unit>.c via the repo's proven normalization
            # (Step-3 probe: units carry a "main/" prefix, no ".o" suffix).
            tu = _unit_source_path(melee_root, units_by_name.get(uname, {}))
            if tu is None or not tu.exists():
                continue
            out = tu.parent / f".{fname}.fprsweep.{os.getpid()}.pcdump.txt"
            proc = subprocess.run(
                [sys.executable, "-m", "src.cli", "debug", "dump", "local",
                 str(tu), "--function", fname, "--output", str(out),
                 "--no-cache-sync"],
                cwd=agent_root, capture_output=True, text=True, timeout=600,
                env=env)
            if proc.returncode != 0 or not out.exists():
                out.unlink(missing_ok=True)
                continue
            text = out.read_text(encoding="utf-8")
            out.unlink(missing_ok=True)
            ig = tb.load_ig(text, fname, class_id=1)
            if ig is None:
                continue                                  # not FPR-bearing
            n_fpr += 1
            if any(n.incomplete for n in ig.nodes.values()):
                excl += 1
                continue
            clean += 1
            g1 = tb.validate_g1(ig, fname)
            if g1.rate == 1.0:
                perfect += 1
            else:
                imperfect += 1
                label = next((lab for lab, pred in
                              (exclusion_predicates or {}).items() if pred(ig)),
                             None)
                if label:
                    characterized += 1
                misses.append({"function": fname, "unit": uname,
                               "g1_rate": g1.rate, "exclusion": label})

    tally = SweepTally(n_fpr=n_fpr, clean=clean, excluded_truncated=excl,
                       g1_perfect=perfect, g1_imperfect_clean=imperfect,
                       characterized_exclusions=characterized)
    verdict = classify_sweep(tally)
    verdict["misses"] = misses
    return verdict


def _write_doc(verdict: dict, out_path: Path) -> None:
    lines = ["# Surrogate-solver FPR G1 sweep (spec §5)", "",
             f"VERDICT: {verdict['verdict']}", ""]
    for k in ("n_fpr", "denominator_clean", "excluded_truncated", "g1_perfect",
              "g1_imperfect_clean", "characterized_exclusions",
              "uncharacterized", "uncharacterized_rate", "remedy",
              "fpr_coverage"):
        if k in verdict:
            lines.append(f"- {k}: {verdict[k]}")
    lines += ["", "## Misses", ""]
    for m in verdict.get("misses", []):
        lines.append(f"- {m['function']} ({m['unit']}): g1={m['g1_rate']:.3f} "
                     f"exclusion={m['exclusion']}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    # DEVIATION (T17 self-review, justified): the plan's draft used
    # parents[4], but this file is tools/melee-agent/src/search/solver/...,
    # so parents[4]="tools" and parents[5]=melee root. The plan's own
    # type-consistency note pins the docs/ root at parents[5]; parents[4]
    # would look for tools/build/GALE01/report.json. Off-by-one fixed.
    ap.add_argument("--melee-root", type=Path,
                    default=Path(__file__).resolve().parents[5])
    args = ap.parse_args()
    v = run_fpr_sweep(melee_root=args.melee_root, limit=args.limit)
    _write_doc(v, args.melee_root / "docs" / "superpowers" / "results"
               / "2026-06-12-surrogate-solver-fpr-sweep.md")
    print(json.dumps({k: v[k] for k in v if k != "misses"}, indent=2))
