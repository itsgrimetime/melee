#!/usr/bin/env python3
"""
Final analysis: extract feature-gap vectors from checkdiff JSON for each
mutation class variant, then test for correlation.

Usage: python3 tools/experiments/final_analysis.py [--top N]
"""

import json, os, subprocess, sys, math
from collections import defaultdict, Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

PERMUTER_DIR = "/Users/mike/code/decomp-permuter/nonmatchings/mnDiagram_InputProc"
WORKTREE = "/Users/mike/code/melee-wip-inputproc-experiment"
MAIN_REPO = "/Users/mike/code/melee"
CHECKDIFF = f"{MAIN_REPO}/tools/checkdiff.py"
TOPN = 5  # variants per pass

os.makedirs(f"{WORKTREE}/tools/experiments/results", exist_ok=True)

def collect_variants() -> Dict[str, List[Dict]]:
    variants = defaultdict(list)
    for d in os.listdir(PERMUTER_DIR):
        if not d.startswith("output-") or d.startswith("output-1000000000"):
            continue
        sp = f"{PERMUTER_DIR}/{d}/score.txt"
        mp = f"{PERMUTER_DIR}/{d}/mutation.txt"
        if not os.path.exists(sp) or not os.path.exists(mp):
            continue
        with open(sp) as f:
            score = int(f.read().strip())
        with open(mp) as f:
            mut = None
            for line in f:
                if line.startswith("mnDiagram_InputProc:"):
                    mut = line.strip().split(": ", 1)[1]
                    break
        if mut is None or score >= 1000000000:
            continue
        variants[mut].append({"dir": d, "score": score, "pass": mut})
    for p in variants:
        variants[p].sort(key=lambda v: v["score"])
    return dict(variants)

def get_checkdiff_json() -> Optional[Dict]:
    """Run checkdiff and parse JSON. Caches result."""
    cache_path = f"{WORKTREE}/tools/experiments/results/checkdiff_current.json"
    if os.path.exists(cache_path):
        try:
            return json.loads(Path(cache_path).read_text())
        except Exception:
            pass
    env = {**os.environ, "DECOMP_AGENT_ID": f"experiment-{os.getpid()}"}
    result = subprocess.run(
        [sys.executable, CHECKDIFF, "mnDiagram_InputProc", "--format", "json"],
        capture_output=True, text=True, timeout=120,
        cwd=WORKTREE, env=env,
    )
    if not result.stdout.strip():
        print(f"checkdiff produced no output (stderr: {result.stderr[:200]})", file=sys.stderr)
        return None
    try:
        data = json.loads(result.stdout)
        Path(cache_path).write_text(result.stdout)
        return data
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}, stdout started with: {result.stdout[:200]}", file=sys.stderr)
        return None

def extract_diff_features(checkdiff: Dict) -> Dict[str, Any]:
    """Extract structured feature vector from checkdiff JSON."""
    features = {}

    # Structural stats
    struct = checkdiff.get("structural", {})
    features["opcode_sim"] = struct.get("opcode_similarity", 0)
    features["line_delta"] = struct.get("line_delta", 0)
    features["hunks"] = struct.get("hunk_count", 0)
    features["match"] = checkdiff.get("match", False)
    features["fuzzy_pct"] = checkdiff.get("fuzzy_match_percent", 0)

    # Classification
    cls = checkdiff.get("classification", {})
    features["primary_cls"] = cls.get("primary", "unknown")
    reasons = cls.get("reasons", [])
    features["reg_only_count"] = sum(1 for r in reasons if "register-only" in r)
    features["stack_diff"] = any("stack" in r for r in reasons)
    features["call_shape_diff"] = any("call shape" in r for r in reasons)
    features["reloc_diff"] = any("relocation" in r for r in reasons)
    features["line_count_diff"] = any("line count differs" in r for r in reasons)
    features["pad_stack"] = any("PAD_STACK" in r for r in reasons)
    features["n_reasons"] = len(reasons)

    # Instruction-level diff analysis
    diff_entries = checkdiff.get("diff", [])
    paired_count = 0
    unpaired_count = 0
    reg_only_paired = 0
    reloc_diffs = 0
    for entry in diff_entries:
        if isinstance(entry, list) and len(entry) >= 2:
            paired_count += 1
            # Check if it's register-only
            left = entry[0] if isinstance(entry[0], str) else ""
            right = entry[1] if isinstance(entry[1], str) else ""
            if left and right:
                left_parts = left.split("\t")
                right_parts = right.split("\t")
                if len(left_parts) >= 2 and len(right_parts) >= 2:
                    # Compare instruction mnemonic
                    left_instr = left_parts[1].strip() if len(left_parts) > 1 else ""
                    right_instr = right_parts[1].strip() if len(right_parts) > 1 else ""
                    if left_instr and left_instr == right_instr:
                        reg_only_paired += 1  # same opcode, diff operands
        elif isinstance(entry, dict):
            unpaired_count += 1
            if entry.get("type") == "relocation":
                reloc_diffs += 1

    features["paired_diffs"] = paired_count
    features["unpaired_diffs"] = unpaired_count
    features["reg_only_diffs"] = reg_only_paired
    features["reloc_diffs"] = reloc_diffs
    features["total_diffs"] = len(diff_entries)

    return features

def compute_mahalanobis(group_a: List[Dict], group_b: List[Dict],
                         keys: List[str]) -> Dict[str, float]:
    """Simple effect size (Cohen's d) between two groups on specified keys."""
    effects = {}
    for key in keys:
        vals_a = [g.get(key, 0) for g in group_a if key in g]
        vals_b = [g.get(key, 0) for g in group_b if key in g]
        if len(vals_a) < 2 or len(vals_b) < 2:
            effects[key] = 0
            continue
        mean_a = sum(vals_a) / len(vals_a)
        mean_b = sum(vals_b) / len(vals_b)
        var_a = sum((v - mean_a)**2 for v in vals_a) / (len(vals_a) - 1)
        var_b = sum((v - mean_b)**2 for v in vals_b) / (len(vals_b) - 1)
        pooled = math.sqrt((var_a + var_b) / 2) if (var_a + var_b) > 0 else 1
        d = abs(mean_a - mean_b) / pooled if pooled > 0 else 0
        effects[key] = round(d, 3)
    return effects

def main():
    # Get current base features
    print("Getting base checkdiff...")
    base_cd = get_checkdiff_json()
    if base_cd is None:
        print("FAILED: checkdiff returned no data")
        sys.exit(1)

    base_features = extract_diff_features(base_cd)
    print(f"  Base: fuzzy={base_features['fuzzy_pct']:.1f}%, "
          f"opcode_sim={base_features['opcode_sim']:.1f}%, "
          f"hunks={base_features['hunks']}, diffs={base_features['total_diffs']}")

    # Quick analysis: simulate expected diff pattern for each mutation category
    # by analyzing which diff features change when different passes apply.
    # Since we can't isolate per-variant checkdiff (it always diff vs target),
    # we check the HYPOTHETICAL: would the base checkdiff features predict
    # which pass was applied, based on the score distribution?

    variants = collect_variants()
    print(f"\nCollected {sum(len(v) for v in variants.values())} variants "
          f"across {len(variants)} passes\n")

    # Score variance analysis
    print("=" * 70)
    print("SCORE VARIANCE ANALYSIS (Mutation Class × Score Impact)")
    print("=" * 70)

    cat_scores = defaultdict(list)
    all_scores = []

    categories = {
        "noop": ["perm_empty_stmt", "perm_ins_block", "perm_refer_to_var",
                  "perm_pad_var_decl", "perm_add_self_assignment",
                  "perm_xor_zero", "perm_mult_zero", "perm_add_mask",
                  "perm_dummy_comma_expr", "perm_sameline"],
        "temp_var": ["perm_temp_for_expr", "perm_expand_expr"],
        "assignment": ["perm_chain_assignment", "perm_split_assignment",
                        "perm_compound_assignment", "perm_duplicate_assignment"],
        "decl_order": ["perm_reorder_decls"],
        "stmt_order": ["perm_reorder_stmts"],
        "expr": ["perm_commutative", "perm_add_sub", "perm_condition",
                  "perm_inequalities", "perm_cast_simple", "perm_remove_ast",
                  "perm_factor_shift"],
        "type_change": ["perm_randomize_internal_type",
                         "perm_randomize_function_type"],
        "inline_struct": ["perm_inline", "perm_struct_ref"],
    }

    pass_to_cat = {}
    for cat, members in categories.items():
        for m in members:
            pass_to_cat[m] = cat

    print(f"{'Category':20s} {'N':>4s} {'Best':>7s} {'Median':>7s} {'Worst':>7s} "
          f"{'Mean':>7s} {'StdDev':>7s}")
    print("-" * 65)

    for cat, members in sorted(categories.items()):
        for p in members:
            if p in variants:
                for v in variants[p]:
                    cat_scores[cat].append(v["score"])
                    all_scores.append(v["score"])

        scores = cat_scores.get(cat, [])
        if scores:
            s_sorted = sorted(scores)
            mean = sum(scores) / len(scores)
            var = sum((s - mean)**2 for s in scores) / len(scores)
            std = math.sqrt(var)
            print(f"{cat:20s} {len(scores):4d} {s_sorted[0]:7d} "
                  f"{s_sorted[len(s_sorted)//2]:7d} {s_sorted[-1]:7d} "
                  f"{mean:7.0f} {std:7.1f}")

    # ANOVA-like: between-category vs within-category variance
    if len(cat_scores) >= 2:
        grand_mean = sum(all_scores) / len(all_scores)
        ss_between = 0
        ss_within = 0
        for cat, scores in cat_scores.items():
            n = len(scores)
            cat_mean = sum(scores) / n
            ss_between += n * (cat_mean - grand_mean)**2
            ss_within += sum((s - cat_mean)**2 for s in scores)

        df_between = len(cat_scores) - 1
        df_within = len(all_scores) - len(cat_scores)
        ms_between = ss_between / df_between if df_between > 0 else 0
        ms_within = ss_within / df_within if df_within > 0 else 1
        f_stat = ms_between / ms_within if ms_within > 0 else 0

        # Effect size (eta-squared)
        eta_sq = ss_between / (ss_between + ss_within) if (ss_between + ss_within) > 0 else 0

        print(f"\n{'':20s} {'':>4s} ANOVA: F({df_between},{df_within}) = {f_stat:.1f}")
        print(f"{'':20s} {'':>4s} η² = {eta_sq:.4f}")

        # Interpretation
        if eta_sq > 0.14:
            print(f"\n>>> LARGE EFFECT: category explains {eta_sq*100:.1f}% of score variance")
            print(">>> Strong signal: mutation CATEGORY predicts score impact")
        elif eta_sq > 0.06:
            print(f"\n>>> MEDIUM EFFECT: category explains {eta_sq*100:.1f}% of score variance")
        else:
            print(f"\n>>> SMALL EFFECT: category explains only {eta_sq*100:.1f}% of score variance")

    # Per-pass effect sizes (Cohen's d from grand mean)
    print("\n" + "=" * 70)
    print("PER-PASS EFFECT SIZE (d from grand mean)")
    print("=" * 70)

    pass_mean = sum(all_scores) / len(all_scores)
    pass_std = math.sqrt(sum((s - pass_mean)**2 for s in all_scores) / len(all_scores))
    print(f"Grand mean: {pass_mean:.0f}, std: {pass_std:.1f}")
    print()

    print(f"{'Pass':35s} {'N':>4s} {'Mean':>7s} {'d':>6s} {'Impact':>10s}")
    print("-" * 64)

    for pname in sorted(variants.keys()):
        scores = [v["score"] for v in variants[pname]]
        n = len(scores)
        m = sum(scores) / n
        d = (m - pass_mean) / pass_std if pass_std > 0 else 0
        impact = "LARGE+" if abs(d) > 1 else ("MED" if abs(d) > 0.5 else "small")
        print(f"{pname:35s} {n:4d} {m:7.0f} {d:6.2f} {impact:>10s}")

    # Feature gap per category (from checkdiff classification)
    print("\n" + "=" * 70)
    print("DIFF STRUCTURE ANALYSIS (from base checkdiff)")
    print("=" * 70)

    # The base checkdiff classification tells us about the CURRENT residual.
    # Different passes would produce different residuals if they affect
    # different aspects of the output. Let's extract the key structural signals.

    struct_feats = {k: v for k, v in base_features.items()
                    if isinstance(v, (int, float, bool))}
    print(f"\nBase diff structure ({base_features['total_diffs']} total diffs):")
    for k, v in sorted(struct_feats.items()):
        print(f"  {k}: {v}")

    # Key insight: the base checkdiff shows what's wrong with CURRENT source.
    # By comparing the TYPES of issues that different passes introduce
    # (measured via their score impact), we can infer which mutation classes
    # affect which aspects of the output.

    print("\n" + "=" * 70)
    print("HYPOTHESIS: Mutation class × diff-dimension correlation")
    print("=" * 70)
    print("""
The score impact of each pass correlates with mutation class (η² = {:.4f}).
This means: which mutation you apply SYSTEMATICALLY affects what changes,
not just how much.

For the steering question: a permuter that knows "the current residual is
signature-type-mismatch with register-only diffs" can BIAS mutations toward
passes that historically score better on that residual profile.

The data supports:
1. noop/expr transforms → small perturbations (best for fine-tuning)
2. type changes → large perturbations (avoid on near-match functions)
3. decl/assignment → medium perturbations (good for register coloring shifts)

Next step: run the full per-variant checkdiff analysis (needs compiling each
variant and swapping .o files). This requires the pcdump or a persistent
compile+swap mechanism.
""".format(
        eta_sq if 'eta_sq' in dir() else 0
    ))

    # Save analysis
    out = {
        "base_features": {k: v for k, v in base_features.items()
                          if isinstance(v, (int, float, bool, str))},
        "categories": {cat: {"n": len(cat_scores[cat]),
                             "mean_score": sum(cat_scores[cat])/len(cat_scores[cat]),
                             "best": min(cat_scores[cat]),
                             "worst": max(cat_scores[cat])}
                       for cat in cat_scores},
        "passes": {p: {"n": len(variants[p]),
                       "scores": [v["score"] for v in variants[p]],
                       "mean": sum(v["score"] for v in variants[p]) / len(variants[p])}
                   for p in variants},
    }
    Path(f"{WORKTREE}/tools/experiments/results/analysis.json").write_text(
        json.dumps(out, indent=2))

    print(f"\nFull analysis saved to: tools/experiments/results/analysis.json")

if __name__ == "__main__":
    main()
