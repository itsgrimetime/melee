# tools/melee-agent/src/backtest/build_corpus.py
from __future__ import annotations

from .corpus import resolve_function_unit, find_match_commit, parent_sha, commit_author_is_us
from .diffutil import function_diff, is_small_singular
from .levers import classify_lever
from .provenance import diff_to_feature_vector, is_in_corpus
from .types import Case


def build_corpus_from_commits(*, triples, git_runner, patterns, score_flip) -> list:
    """Commit-first corpus build (C/C~1 known from discovery; no find_match_commit).
    Applies the structural confound gate + lever classification + provenance labeling."""
    cases: list[Case] = []
    for t in triples:
        fn, c_sha, cprev, file = t["function"], t["c_sha"], t["cprev_sha"], t["file"]
        unit = "main/" + file.removeprefix("src/").removesuffix(".c")
        try:
            diff = function_diff(git_runner, c_sha, file)
            c_pct, c_ndl = score_flip(fn, c_sha)
            p_pct, p_ndl = score_flip(fn, cprev)
        except Exception:
            # Candidate not scorable: fn absent from report.json (a parsed helper symbol,
            # or a stub_to_def whose fn is a `/// #stub` at C~1) -> skip, don't abort the batch.
            continue
        if c_ndl != 0 or (p_ndl is None) or p_ndl <= 0:
            continue  # structural confound gate
        lever = classify_lever(diff)
        feat = diff_to_feature_vector(diff, lever)
        provenance = "in_corpus" if is_in_corpus(feat, patterns) else "held_out"
        cases.append(Case(
            function=fn, c_sha=c_sha, cprev_sha=cprev, unit=unit, file=file,
            ground_truth_diff=diff, lever_locus="in_function",
            author="us" if commit_author_is_us(git_runner, c_sha) else "other",
            provenance=provenance, lever_class=lever,
            baseline_pct=p_pct, baseline_ndl=p_ndl, target_pct=c_pct, target_ndl=c_ndl,
        ))
    return cases


def build_corpus(*, functions, report, git_runner, patterns, score_flip,
                 max_changed_lines=30) -> list:
    cases: list[Case] = []
    for fn in functions:
        resolved = resolve_function_unit(report, fn)
        if not resolved:
            continue
        unit, file = resolved
        c_sha = find_match_commit(git_runner, fn, file)
        if not c_sha:
            continue
        cprev = parent_sha(git_runner, c_sha)
        diff = function_diff(git_runner, c_sha, file)
        if not is_small_singular(diff, max_changed_lines=max_changed_lines):
            continue
        # Confound guard (spec §4.3): structural flip must be real and attributable.
        c_pct, c_ndl = score_flip(fn, c_sha)
        p_pct, p_ndl = score_flip(fn, cprev)
        if c_ndl != 0 or (p_ndl is None) or p_ndl <= 0:
            continue  # not a genuine structural flip -> drop (mislabeled / header/caller lever)
        lever = classify_lever(diff)
        feat = diff_to_feature_vector(diff, lever)
        provenance = "in_corpus" if is_in_corpus(feat, patterns) else "held_out"
        cases.append(Case(
            function=fn, c_sha=c_sha, cprev_sha=cprev, unit=unit, file=file,
            ground_truth_diff=diff, lever_locus="in_function",
            author="us" if commit_author_is_us(git_runner, c_sha) else "other",
            provenance=provenance, lever_class=lever,
            baseline_pct=p_pct, baseline_ndl=p_ndl, target_pct=c_pct, target_ndl=c_ndl,
        ))
    return cases
