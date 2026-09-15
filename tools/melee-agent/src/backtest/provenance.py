from __future__ import annotations


def _jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return (len(a & b) / len(a | b)) if (a | b) else 0.0


def weighted_jaccard(candidate: dict, pattern: dict) -> float:
    """Port of mismatch_db.backfill._compute_similarity (weights: opcodes .3,
    categories .2, name-words .3, signal-types .2; normalized by active weights)."""
    score = 0.0
    weights = 0.0
    if candidate.get("opcodes") and pattern.get("opcodes"):
        score += 0.30 * _jaccard(candidate["opcodes"], pattern["opcodes"]); weights += 0.30
    if candidate.get("categories") and pattern.get("categories"):
        score += 0.20 * _jaccard(candidate["categories"], pattern["categories"]); weights += 0.20
    if candidate.get("name") and pattern.get("name"):
        score += 0.30 * _jaccard(candidate["name"].lower().split(),
                                 pattern["name"].lower().split()); weights += 0.30
    c_types = {s.get("type") for s in candidate.get("signals", [])}
    p_types = {s.get("type") for s in pattern.get("signals", [])}
    if c_types and p_types:
        score += 0.20 * _jaccard(c_types, p_types); weights += 0.20
    return score / weights if weights else 0.0


def is_in_corpus(candidate: dict, all_patterns: list, *, threshold: float = 0.5) -> bool:
    return any(weighted_jaccard(candidate, p) >= threshold for p in all_patterns)


def diff_to_feature_vector(diff: str, lever_class: str) -> dict:
    # Source diffs carry no opcodes; category derives from lever_class, name from changed identifiers.
    cat_map = {
        "retype": ["type", "register"], "literal_vs_named": ["value", "float"],
        "backend_coloring": ["register", "ceiling"], "decl_reorder": ["register"],
        "struct_overlay": ["struct", "data-layout"], "inline_arg_or_schedule": ["inline"],
    }
    names = " ".join(
        tok for l in diff.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))
        for tok in l[1:].split() if tok.isidentifier()
    )
    return {"opcodes": [], "categories": cat_map.get(lever_class, [lever_class]),
            "name": names, "signals": []}
