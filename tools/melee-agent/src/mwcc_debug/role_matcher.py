from __future__ import annotations
import enum
from dataclasses import dataclass, field
from typing import Union

_STRONG_CONF = {"best-guess", "verified"}  # the codebase's strong tiers (cf. suggest_coalesce, tier3_search)


def _multiset_distance(a: tuple, b: tuple) -> float:
    da, db = dict(a), dict(b)
    keys = set(da) | set(db)
    if not keys:
        return 0.0
    inter = sum(min(da.get(k, 0), db.get(k, 0)) for k in keys)
    union = sum(max(da.get(k, 0), db.get(k, 0)) for k in keys)
    return 1.0 - (inter / union if union else 1.0)


def min_cost_assignment(rows, cols, cost, unmatched_cost: float) -> dict:
    """Exact one-to-one assignment via min-cost max-flow over the sparse pruned
    graph. Each row maps to a distinct column (at ``cost[(r, c)]``) or to ``None``
    (at ``unmatched_cost``); any number of rows may be unmatched.

    This is polynomial in any N — no branch-and-bound blowup on equal-cost ties
    and no silent greedy fallback above a row cap — so the re-anchoring loop never
    silently degrades to a suboptimal assignment on functions with many target
    roles (carry-forward #1). A tiny tie-break (``EPS``) favours the self-column
    (``c == r``) so a self-match stays identity-stable; it is far below the
    6-decimal rounding of real costs, so it only separates exact ties.

    Costs are assumed non-negative (``role_cost`` and ``unmatched_cost`` are),
    which keeps the successive-shortest-path search on a graph with non-negative
    reduced costs (Johnson potentials start at 0).
    """
    import heapq
    rows = list(rows)
    if not rows:
        return {}

    eff_cols, seen = [], set()
    for (r, c), cc in cost.items():
        if cc is not None and cc < unmatched_cost and c not in seen:
            seen.add(c)
            eff_cols.append(c)

    n, m = len(rows), len(eff_cols)
    S, U, T = 0, 1 + n + m, 2 + n + m
    V = T + 1
    row_node = {r: 1 + i for i, r in enumerate(rows)}
    col_node = {c: 1 + n + j for j, c in enumerate(eff_cols)}
    graph: list = [[] for _ in range(V)]

    def add(u, v, cap, cst):
        graph[u].append([v, cap, cst, len(graph[v])])
        graph[v].append([u, 0, -cst, len(graph[u]) - 1])

    EPS = 1e-9
    row_out = {}  # r -> [(col_or_None, index of its forward edge in graph[row_node[r]])]
    for r in rows:
        add(S, row_node[r], 1, 0.0)
        outs = []
        for c in eff_cols:
            cc = cost.get((r, c))
            if cc is not None and cc < unmatched_cost:
                outs.append((c, len(graph[row_node[r]])))
                add(row_node[r], col_node[c], 1, cc + (0.0 if c == r else EPS))
        outs.append((None, len(graph[row_node[r]])))
        add(row_node[r], U, 1, unmatched_cost)
        row_out[r] = outs
    for c in eff_cols:
        add(col_node[c], T, 1, 0.0)
    add(U, T, n, 0.0)

    INF = float("inf")
    h = [0.0] * V
    for _ in range(n):                       # send one unit per row
        dist = [INF] * V
        dist[S] = 0.0
        prevv = [-1] * V
        preve = [-1] * V
        pq = [(0.0, S)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for i, (v, cap, cst, _rev) in enumerate(graph[u]):
                if cap > 0:
                    nd = d + cst + h[u] - h[v]
                    if nd < dist[v] - 1e-15:
                        dist[v] = nd
                        prevv[v] = u
                        preve[v] = i
                        heapq.heappush(pq, (nd, v))
        if dist[T] == INF:
            break                            # U->T always exists, so unreachable
        for v in range(V):
            if dist[v] < INF:
                h[v] += dist[v]
        v = T
        while v != S:
            graph[prevv[v]][preve[v]][1] -= 1
            graph[v][graph[prevv[v]][preve[v]][3]][1] += 1
            v = prevv[v]

    assign = {}
    for r in rows:
        assign[r] = next(
            (c for c, idx in row_out[r] if graph[row_node[r]][idx][1] == 0), None)
    return assign


class MatchStatus(enum.Enum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    GONE = "gone"
    SPLIT = "split"
    MERGED = "merged"
    REMATERIALIZED = "rematerialized"
    NON_COMPARABLE = "non_comparable"


@dataclass(frozen=True)
class RoleMatch:
    original_ig: int
    new_ig: Union[int, tuple, None]
    confidence: float                          # 1 - cost (higher = better); 0 if gone
    status: MatchStatus
    evidence: dict = field(default_factory=dict)


MATCH_THRESHOLD = 0.45                          # cost below this is a viable candidate
AMBIGUOUS_MARGIN = 0.10                         # 2nd-best within this cost -> ambiguous
TOP_K = 6                                       # candidate pruning per role
DEFAULT_WEIGHTS = {"first_def": 0.55, "use_sites": 0.30, "is_param": 0.05, "var": 0.20}
WEAK_SIG_CEILING = 0.33    # best_cost above this -> signature too weak to call a confident SPLIT


def match_roles(ref_descs: dict, cand_descs: dict, weights: dict = DEFAULT_WEIGHTS) -> dict:
    """Map each reference role (ig -> RoleDescriptor) to a candidate node.
    `cand_descs` should already span the broadened candidate universe
    (decisions + coalesced/spilled markers) so GONE vs MERGED is distinguishable."""
    rows = list(ref_descs)
    cols = list(cand_descs)
    cost = {}
    per_row_sorted = {}
    for r in rows:
        scored = sorted(((role_cost(ref_descs[r], cand_descs[c], weights), c) for c in cols),
                        key=lambda t: t[0])[:TOP_K]
        # Guarantee self is always in the candidate set (may be pruned by TOP_K when
        # many identical nodes tie at cost 0.0 and self ranks beyond position TOP_K-1).
        if r in cand_descs and not any(c == r for _, c in scored):
            self_cost = role_cost(ref_descs[r], cand_descs[r], weights)
            scored = scored[:TOP_K - 1] + [(self_cost, r)]
        per_row_sorted[r] = scored
        for ccost, c in scored:
            cost[(r, c)] = ccost
    assign = min_cost_assignment(rows, cols, cost, unmatched_cost=MATCH_THRESHOLD)

    want = {r: (per_row_sorted[r][0] if per_row_sorted[r] else (float("inf"), None))
            for r in rows}
    out = {}
    for r in rows:
        c = assign.get(r)
        scored = per_row_sorted[r]
        best_cost = scored[0][0] if scored else float("inf")
        second = scored[1][0] if len(scored) > 1 else float("inf")
        if c is None:
            wcost, wcol = want[r]
            merged = wcol is not None and wcost < MATCH_THRESHOLD and assign.get(
                next((rr for rr in rows if assign.get(rr) == wcol), None)) == wcol
            status = MatchStatus.MERGED if merged else MatchStatus.GONE
            out[r] = RoleMatch(r, None, 0.0, status, {"best_cost": round(best_cost, 4)})
            continue
        # near-tie among MULTIPLE viable candidates -> SPLIT (one ref, many current)
        viable = [(cc, cv) for cc, cv in scored if cc < MATCH_THRESHOLD]
        tied = [cv for cc, cv in viable if cc - best_cost < AMBIGUOUS_MARGIN]
        # SPLIT only if THIS row is the sole claimant of >=2 tied candidates;
        # if other rows took the tied candidates, it's an ambiguous 1:1, not a split.
        tied_uncontested = [cv for cv in tied
                            if not any(assign.get(rr) == cv for rr in rows if rr != r)]
        if len(tied_uncontested) >= 2:
            # distinguishing evidence? if best_cost is itself high (weak sig), NON_COMPARABLE
            status = MatchStatus.NON_COMPARABLE if best_cost > WEAK_SIG_CEILING else MatchStatus.SPLIT
            out[r] = RoleMatch(r, tuple(sorted(tied_uncontested)), round(1.0 - best_cost, 4),
                               status, {"tied": tied_uncontested})
            continue
        # AMBIGUOUS when another candidate scored within the margin — we cannot
        # tell which mapping is canonical. This fires even for a self-assignment
        # (c == r): "the node kept its ig number" is NOT a confidence signal,
        # since ig numbers are not stable across compiles (the whole reason this
        # layer exists). A correctly self-identified node that ties an identical
        # sibling is honestly AMBIGUOUS, not MATCHED.
        status = MatchStatus.MATCHED
        if second - cost[(r, c)] < AMBIGUOUS_MARGIN:
            status = MatchStatus.AMBIGUOUS
        out[r] = RoleMatch(r, c, round(1.0 - cost[(r, c)], 4), status,
                           {"second_best_gap": round(second - cost[(r, c)], 4)})
    return out


def role_cost(a, b, weights: dict = DEFAULT_WEIGHTS) -> float:
    """Cost in [0, ~1.x]. Identity-core only; allocator-state features
    (assigned_reg/live_range/use_count) are intentionally NOT used — they are
    what edits change (spec section 5, review #9). `weights` is injectable so
    Gate 1c can ablate individual features."""
    cost = 0.0
    cost += weights["first_def"] * (0.0 if a.first_def_sig == b.first_def_sig else 1.0)
    cost += weights["use_sites"] * _multiset_distance(a.use_site_multiset, b.use_site_multiset)
    cost += weights["is_param"] * (0.0 if a.is_param == b.is_param else 1.0)
    # var-name booster (only when BOTH are strong-confidence)
    if (a.var_name and b.var_name and a.var_confidence in _STRONG_CONF
            and b.var_confidence in _STRONG_CONF):
        # both arms scale with the weight so ablation (weights["var"]=0) is clean
        cost += -weights["var"] if a.var_name == b.var_name else 0.5 * weights["var"]
    return max(0.0, round(cost, 6))
