#!/usr/bin/env python3
"""
Stage 3 of mutation-class × feature-gap correlation experiment.

For the top-scoring variants from each mutation class:
1. Compile through production compiler
2. Run checkdiff --format json for instruction-level diff
3. Extract structured feature gaps
4. Test for correlation between mutation class and feature gap

Usage:
    python tools/experiments/analyze_correlation.py [--top N] [--pass PASS,...]
"""

import argparse
import json
import os
import subprocess
import sys
import csv
import tempfile
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PERMUTER_DIR = "/Users/mike/code/decomp-permuter/nonmatchings/mnDiagram_InputProc"
WORKTREE = "/Users/mike/code/melee-wip-inputproc-experiment"
COMPILE_SH = f"{PERMUTER_DIR}/compile.sh"
STAGING = f"{WORKTREE}/tools/experiments/staging"
RESULTS_FILE = f"{WORKTREE}/tools/experiments/analysis_results.csv"

# Permuter Scorer
sys.path.insert(0, "/Users/mike/code/decomp-permuter")
from src.scorer import Scorer

TARGET_O = f"{PERMUTER_DIR}/target.o"
os.makedirs(STAGING, exist_ok=True)

def collect_variants() -> Dict[str, List[Dict]]:
    """Collect all saved variants grouped by mutation pass."""
    variants = defaultdict(list)

    for d in os.listdir(PERMUTER_DIR):
        if not d.startswith("output-"):
            continue
        mut_path = os.path.join(PERMUTER_DIR, d, "mutation.txt")
        score_path = os.path.join(PERMUTER_DIR, d, "score.txt")
        source_path = os.path.join(PERMUTER_DIR, d, "source.c")

        if not all(os.path.exists(p) for p in [mut_path, score_path, source_path]):
            continue

        with open(score_path) as f:
            score = int(f.read().strip())
        if score >= 1000000000:  # compile failure
            continue

        with open(mut_path) as f:
            mut = None
            for line in f:
                if line.startswith("mnDiagram_InputProc:"):
                    mut = line.strip().split(": ", 1)[1]
                    break

        if mut is None:
            continue

        variants[mut].append({
            "dir": d,
            "score": score,
            "source_path": source_path,
            "pass": mut,
        })

    # Sort each pass by score (ascending, lower is better)
    for p in variants:
        variants[p].sort(key=lambda v: v["score"])

    return dict(variants)


def compile_variant(source_path: str, output_path: str) -> bool:
    """Compile a variant .c to .o using the permuter's compile.sh."""
    # compile.sh uses realpath($1) and realpath($3) — create output first
    # and use absolute paths
    abs_source = os.path.abspath(source_path)
    abs_output = os.path.abspath(output_path)

    # Touch output so realpath succeeds
    if not os.path.exists(abs_output):
        Path(abs_output).touch()

    result = subprocess.run(
        [COMPILE_SH, abs_source, "-o", abs_output],
        capture_output=True, text=True, timeout=30,
        cwd=os.path.dirname(abs_source),
    )
    ok = os.path.exists(abs_output) and os.path.getsize(abs_output) > 0
    if not ok and os.path.exists(abs_output):
        os.unlink(abs_output)
    return ok


def run_checkdiff_json() -> Optional[Dict]:
    """Run checkdiff on the current build's InputProc. The variant .o must
    have been compiled to the right path for checkdiff to pick up.

    Instead of trying to hack checkdiff, we use the decomp-permuter's
    Scorer directly."""
    pass


def score_with_scorer(o_path: str) -> Optional[Tuple[int, str]]:
    """Score a variant .o against target using decomp-permuter Scorer."""
    scorer = Scorer(TARGET_O, algorithm="levenshtein")
    try:
        score, score_hash = scorer.score(o_path)
        return (score, score_hash)
    except Exception as e:
        print(f"  Scorer error: {e}", file=sys.stderr)
        return None


def get_checkdiff_json(o_path: str) -> Optional[Dict]:
    """Get structured checkdiff output by temporarily swapping the variant
    .o into the build directory structure."""
    build_asm_dir = f"{WORKTREE}/build/GALE01/src/melee/mn"
    orig_o = f"{build_asm_dir}/mndiagram.c.o"
    backup_o = f"{orig_o}.bak"

    if not os.path.exists(orig_o):
        print(f"  Can't find original .o at {orig_o}")
        return None

    # Backup original, swap in variant
    shutil.copy2(orig_o, backup_o)
    shutil.copy2(o_path, orig_o)

    try:
        result = subprocess.run(
            [sys.executable,
             f"{WORKTREE}/tools/checkdiff.py",
             "mnDiagram_InputProc",
             "--format", "json"],
            capture_output=True, text=True, timeout=60,
            cwd=WORKTREE,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return None
        return None
    except Exception as e:
        print(f"  checkdiff error: {e}")
        return None
    finally:
        # Restore original
        shutil.move(backup_o, orig_o)


def extract_features(checkdiff_data: Optional[Dict]) -> Dict[str, Any]:
    """Extract feature-gap vector from checkdiff JSON output."""
    features = {
        "num_diffs": -1,
        "frame_mismatch": False,
        "reg_mismatches": -1,
        "has_stack_diff": False,
        "instruction_count_target": -1,
        "instruction_count_current": -1,
    }

    if checkdiff_data is None:
        return features

    try:
        # checkdiff JSON format varies; try common structures
        for fn_name, fn_data in checkdiff_data.items():
            if isinstance(fn_data, dict):
                # Count instruction-level diffs
                diffs = fn_data.get("diffs", [])
                features["num_diffs"] = len(diffs)

                # Count register mismatches
                reg_diffs = 0
                for diff in diffs:
                    diff_str = json.dumps(diff)
                    # Heuristic: count register number diffs
                    for reg_num in range(32):
                        if f"r{reg_num}" in diff_str:
                            reg_diffs += 1
                features["reg_mismatches"] = reg_diffs

                # Frame check
                frame = fn_data.get("stack_diffs", {})
                if isinstance(frame, dict) and any(v != 0 for v in frame.values()):
                    features["frame_mismatch"] = True
                    features["has_stack_diff"] = True

                # Instruction counts
                features["instruction_count_target"] = fn_data.get("target_instructions", -1)
                features["instruction_count_current"] = fn_data.get("current_instructions", -1)

    except Exception:
        pass

    return features


def main():
    parser = argparse.ArgumentParser(description="Analyze mutation-feature correlation")
    parser.add_argument("--top", type=int, default=3,
                       help="Top N per pass to analyze (default: 3)")
    parser.add_argument("--passes", type=str, default="",
                       help="Comma-separated passes to analyze (default: all)")
    parser.add_argument("--compile-only", action="store_true",
                       help="Compile variants but skip checkdiff")
    parser.add_argument("--extract-only", action="store_true",
                       help="Skip compilation, re-run checkdiff on existing .o files")
    args = parser.parse_args()

    variants = collect_variants()

    if args.passes:
        selected = set(args.passes.split(","))
        variants = {k: v for k, v in variants.items() if k in selected}

    print(f"Collected {sum(len(v) for v in variants.values())} variants across "
          f"{len(variants)} passes")
    print()

    results = []

    for pass_name, vlist in sorted(variants.items()):
        top_n = min(args.top, len(vlist))
        selected = vlist[:top_n]

        print(f"[{pass_name}] analyzing top {top_n}/{len(vlist)} (best={selected[0]['score']})")

        for v in selected:
            dir_name = v["dir"]
            variant_key = f"{pass_name}-{v['score']}-{dir_name.split('-')[-1]}"
            o_path = f"{STAGING}/{variant_key}.o"

            if not args.extract_only:
                if os.path.exists(o_path):
                    os.unlink(o_path)

                if not compile_variant(v["source_path"], o_path):
                    print(f"  [SKIP] {dir_name}: compile failed")
                    continue

                # Verify via scorer
                score_result = score_with_scorer(o_path)
                if score_result is None:
                    print(f"  [SKIP] {dir_name}: scoring failed")
                    continue
                permuter_score = score_result[0]
            else:
                if not os.path.exists(o_path):
                    print(f"  [SKIP] {variant_key}: no existing .o")
                    continue
                permuter_score = v["score"]

            features = {"score": permuter_score, "pass": pass_name}

            if not args.compile_only:
                cd = get_checkdiff_json(o_path)
                feat = extract_features(cd)
                features.update(feat)
                diff_summary = f"diffs={feat['num_diffs']}, reg={feat['reg_mismatches']}" + \
                              (", FRAME" if feat['frame_mismatch'] else "")
                print(f"  {dir_name}: score={permuter_score}, {diff_summary}")
            else:
                print(f"  {dir_name}: compiled OK, score={permuter_score}")

            results.append(features)

    # Save results
    if results:
        with open(RESULTS_FILE, "w") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            for r in results:
                writer.writerow(r)
        print(f"\nResults saved to {RESULTS_FILE}")

    # Quick correlation summary
    print("\n" + "=" * 60)
    print("DESCRIPTIVE STATISTICS")
    print("=" * 60)

    by_pass: Dict[str, List[Dict]] = defaultdict(list)
    for r in results:
        by_pass[r["pass"]].append(r)

    print(f"\n{'Pass':35s} {'N':>4s} {'Score':>8s} {'Diffs':>7s} {'Reg':>5s} {'Frame':>6s}")
    print("-" * 68)
    for pname in sorted(by_pass.keys()):
        items = by_pass[pname]
        scores = [i["score"] for i in items]
        diffs = [i.get("num_diffs", -1) for i in items if i.get("num_diffs", -1) >= 0]
        regs = [i.get("reg_mismatches", -1) for i in items if i.get("reg_mismatches", -1) >= 0]
        frames = [i.get("frame_mismatch", False) for i in items]

        best = min(scores)
        avg_diffs = sum(diffs) / len(diffs) if diffs else -1
        avg_regs = sum(regs) / len(regs) if regs else -1
        frame_pct = sum(frames) / len(frames) * 100 if frames else 0

        print(f"{pname:35s} {len(items):4d} {best:8d} {avg_diffs:7.1f} {avg_regs:5.1f} {frame_pct:5.0f}%")


if __name__ == "__main__":
    main()
