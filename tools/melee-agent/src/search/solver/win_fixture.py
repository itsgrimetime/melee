"""Self-contained win-fixture helpers (T10c — calibration unblock).

These are the PURE pieces of the redesigned win-fixture freeze path (the live
mwcc orchestration lives in the generator); they are unit-tested over frozen
fixture text with no compiler in the loop.

WHY THE REDESIGN (orchestrator ruling, plan "T10b outcome → BINDING design
amendment"). The original win path collected `phys_target` from the BASE state
vs the *dol*, then required that base-vs-dol diff to be register-only. After 114
commits of TU-context drift the win BASE states became FULLNORM-0-but-frame-
gapped `stack-layout` residuals vs the dol → excluded → 0/2 froze. The win's
*outcome*, however, is the POST state, which reproduces faithfully today. So the
win fixtures are now SELF-CONTAINED pre/post pairs:

1. `phys_target` := the POST-win build's ACTUAL coloring (the observed register
   of every node in the post IG), extracted from the post pcdump in the same
   build context — NOT the dol. The win's outcome IS that coloring; the gate
   asserts the surrogate reaches it (`predict_assignments(post_ig) ==
   phys_target`, which holds at G1=100%).
2. Admission is judged on the PRE-vs-POST object pair (their diff IS the win).
   "Register-only / pure coloring" is operationalized as the project's truth-gate
   FULLNORM-0 signal: `classify_asm_diff(...).normalized_diff_lines == 0` — the
   masked-structural diff (registers/immediates/labels/relocations masked out)
   is zero, so the bodies are structurally identical and every real difference
   is a register assignment. A win that grows/shrinks the frame by the slot the
   alias/temp local reserves still satisfies FULLNORM-0 (the frame delta is part
   of the win, recorded in provenance); it only fails the STRICTER
   `primary in REGISTER_ONLY_PRIMARIES` check because the stack-frame probe
   re-labels the primary `stack-layout`. The surrogate models the *coloring*
   change, which it reproduces at G1=100% on the post IG, so FULLNORM-0 is the
   mechanically faithful admission gate here (and the project's own
   order_target_derive comment calls FULLNORM-0 "the pool's STRONGEST admission
   signal").
3. The frozen artifact carries BOTH IGs (pre = the solver's input, post = the
   gate's re-extraction target) + the post-derived `phys_target` + provenance.

The disassembly extraction mirrors checkdiff's `get_asm_with_dtk` normalization
(strip the `/* addr addr bytes */` comment, emit `+<off>: <body>`), so the
admission verdict runs through the SAME `classify_asm_diff` arbiter checkdiff
uses for the live register-only classification.
"""
from __future__ import annotations

import re
from collections import Counter

from src.mwcc_debug import tiebreak as tb

# Mirror REGISTER_ONLY_PRIMARIES so the verdict can ALSO report the strict
# answer (informational); admission itself keys on FULLNORM-0 per the ruling.
from src.mwcc_debug.order_target_derive import REGISTER_ONLY_PRIMARIES

# verify-ib REL24 method (mirrors debug.py:_bootstrap_target_calls): a call edge
# is the `R_PPC_REL24 <sym>` reloc line (preferred) or a literal `bl <sym>`.
# Counting these as a MULTISET gives the bl-target multiset the direct-evidence
# admission compares between current and target (amendment-2 check (i)).
_REL24_RE = re.compile(r"\bR_PPC_REL24\s+([A-Za-z_.$]\w*)")
_BL_RE = re.compile(r"^bl\s+([A-Za-z_.$][\w.$]*)")


def extract_dtk_function(disasm_text: str, function: str) -> list[str]:
    """Extract one function's normalized instruction lines from a `dtk elf
    disasm` dump, mirroring checkdiff's `get_asm_with_dtk` normalization:
    strip the `/* addr addr bytes */` comment and emit `+<rel-off>: <body>`,
    one PPC instruction (4 bytes) per line; directives/labels skipped.

    dtk emits `.fn <name>, global` (current) or `<name>:` (older) block starts
    and ends the block at `.endfn` / the next `.fn ` / a `.section`."""
    out: list[str] = []
    in_func = False
    off = 0
    for raw in disasm_text.split("\n"):
        s = raw.strip()
        is_start = (
            s == f"{function}:"
            or s.startswith(f".fn {function},")
            or s == f".fn {function}"
        )
        if is_start:
            in_func = True
            off = 0
            out.append(f"<{function}>:")
            continue
        if not in_func:
            continue
        if s.startswith((".endfn", ".fn ", ".section")):
            break
        if not s or s.endswith(":"):
            continue
        body = re.sub(r"^/\*\s*[^*]*\*/\s*", "", s)
        if body and not body.startswith("."):
            out.append(f"+{off:03x}: {body}")
            off += 4
    return out


def win_admission_verdict(pre_asm_lines: list[str], post_asm_lines: list[str],
                          *, classify_asm_diff) -> dict:
    """Decide whether a win's PRE-vs-POST object diff is admissible as a
    self-contained register-only (pure-coloring) win, via the project's
    `classify_asm_diff` truth-gate.

    `classify_asm_diff` is injected (it lives in tools/checkdiff.py, outside the
    package) so this stays a pure, importable, unit-testable decision.

    Returns a dict with:
      admitted               : bool — FULLNORM-0 (the binding admission rule)
      primary                : classify_asm_diff primary (informational)
      normalized_diff_lines  : the masked-structural diff size (0 ⟹ pure coloring)
      strict_register_only   : primary in REGISTER_ONLY_PRIMARIES (informational —
                               the *older*, frame-suppressed gate; NOT used for
                               admission)
      pre_lines / post_lines : raw instruction-line counts
    """
    cls = classify_asm_diff(pre_asm_lines, post_asm_lines)
    primary = cls.get("primary", "unknown")
    # classify_asm_diff exposes the truth-gate via reasons + a primary; the
    # normalized_diff_lines count is the authoritative FULLNORM-0 signal. When
    # the bodies are instruction-identical the gate short-circuits before
    # computing the structural diff, so treat that as 0.
    if primary == "instruction-identical":
        norm_lines = 0
    else:
        gate = cls.get("structural_truth_gate")
        norm_lines = (gate or {}).get("normalized_diff_lines")
    return {
        "admitted": norm_lines == 0,
        "primary": primary,
        "normalized_diff_lines": norm_lines,
        "strict_register_only": primary in REGISTER_ONLY_PRIMARIES,
        "pre_lines": len(pre_asm_lines),
        "post_lines": len(post_asm_lines),
    }


def _bl_target_multiset(asm_lines: list[str]) -> Counter:
    """The verify-ib REL24 call-target multiset for one disassembly: each
    `R_PPC_REL24 <sym>` reloc (preferred) or literal `bl <sym>` contributes one
    count of the callee. Mirrors debug.py:_bootstrap_target_calls but keeps
    MULTIPLICITY (a Counter), so a call added/removed/duplicated is visible."""
    counts: Counter = Counter()
    for line in asm_lines:
        body = _asm_diff_body(line)
        m = _REL24_RE.search(body)
        if m is not None:
            counts[m.group(1)] += 1
            continue
        m = _BL_RE.match(body.strip())
        if m is not None:
            counts[m.group(1)] += 1
    return counts


def _asm_diff_body(line: str) -> str:
    """Strip a leading `+<off>: ` normalized-offset prefix (checkdiff/dtk asm
    line shape) so the mnemonic/operands start at column 0."""
    m = re.match(r"^\+[0-9a-fA-F]+:\s*(.*)$", line)
    return m.group(1) if m is not None else line


def _normalized_line_mnemonic(norm_line: str) -> str:
    """Leading token of a normalized truth-gate line (the mnemonic, or `RELOC`
    for a relocation line). The truth-gate emits e.g. `li rN,IMM`,
    `addi rN,rN,IMM`, `lwz rN,IMM(rN)`, or `RELOC R_PPC_EMB_SDA21`."""
    return norm_line.split(None, 1)[0] if norm_line else ""


def classify_normalized_diff(target_norm: list[str], current_norm: list[str]
                             ) -> dict:
    """Classify the NORMALIZED truth-gate diff (registers/immediates/labels/
    relocation symbols already masked) into register-class vs non-register-class
    hunks, for amendment-2 check (ii).

    KEY INSIGHT: the normalized space already masks physical registers to `rN`.
    So a PURE register reassignment vanishes from this diff entirely (the two
    bodies normalize identically). Any line that SURVIVES as a normalized diff
    is therefore, by construction, NOT a register-class delta — it is an
    instruction-count change (insert/delete), an instruction-selection change
    (a `replace` whose mnemonics differ, e.g. addi->li), or a reloc-KIND change
    (RELOC R_PPC_X vs RELOC R_PPC_Y). All three are exactly the
    "instruction-count, call-shape, or reloc-symbol" deltas the amendment
    disqualifies. A `replace` hunk whose paired lines share the SAME mnemonic
    differs only in a masked field (an immediate/offset that the truth gate
    masks but that survives because difflib paired them) — those are coloring/
    alignment cascade lines and count as register-class.

    Returns dict(nonregister_class_lines, register_class_lines,
    normalized_diff_lines, hunks) — `hunks` is a small evidence list.
    """
    import difflib

    sm = difflib.SequenceMatcher(None, target_norm, current_norm,
                                 autojunk=False)
    nonreg = 0
    reg = 0
    total = 0
    hunks: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        t = target_norm[i1:i2]
        c = current_norm[j1:j2]
        span = max(i2 - i1, j2 - j1)
        total += span
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            # paired lines: register-class iff mnemonics match (only a masked
            # field — immediate/offset — differs, a coloring/alignment cascade).
            local_nonreg = 0
            for tl, cl in zip(t, c):
                if _normalized_line_mnemonic(tl) == _normalized_line_mnemonic(cl):
                    reg += 1
                else:
                    nonreg += 1
                    local_nonreg += 1
            hunks.append({"tag": tag, "span": span,
                          "nonregister_class": local_nonreg,
                          "target": t, "current": c})
        else:
            # insert / delete / unequal-length replace -> instruction-count or
            # instruction-sequence delta -> NOT register-class.
            nonreg += span
            hunks.append({"tag": tag, "span": span,
                          "nonregister_class": span,
                          "target": t, "current": c})
    return {
        "normalized_diff_lines": total,
        "register_class_lines": reg,
        "nonregister_class_lines": nonreg,
        "hunks": hunks,
    }


def direct_evidence_verdict(target_asm: list[str], current_asm: list[str], *,
                            normalized_structural_lines) -> dict:
    """Amendment-2 DIRECT-EVIDENCE admission for a reject/flag fixture, decided
    WITHOUT the checkdiff primary label (#611 leaves that label FP for two of
    these). A fixture is admitted (register-only / pure-coloring vs its live
    target) iff BOTH:

      (i)  bl-target multisets byte-identical (verify-ib REL24 method): no call
           added, removed, or re-pointed.
      (ii) every NORMALIZED truth-gate diff line is register-class (no
           instruction-count, call-shape/selection, or non-sanctioned
           reloc-symbol delta).

    `normalized_structural_lines` is injected (it lives in tools/checkdiff.py,
    outside the package) so this stays a pure, importable, unit-testable
    decision on the SAME normalization the live checkdiff path uses.

    Returns a verdict dict; `admitted` is the binding answer. A failing fixture
    is honestly EXCLUDED by the caller, with this dict recorded as the evidence.
    """
    tgt_bl = _bl_target_multiset(target_asm)
    cur_bl = _bl_target_multiset(current_asm)
    bl_equal = tgt_bl == cur_bl
    bl_delta = {
        "added": dict(cur_bl - tgt_bl),       # callees current has that target lacks
        "removed": dict(tgt_bl - cur_bl),     # callees target has that current lacks
    }

    tgt_norm = normalized_structural_lines(target_asm)
    cur_norm = normalized_structural_lines(current_asm)
    norm = classify_normalized_diff(tgt_norm, cur_norm)
    all_register_class = norm["nonregister_class_lines"] == 0

    admitted = bl_equal and all_register_class
    return {
        "admitted": admitted,
        "check_i_bl_multiset_equal": bl_equal,
        "check_ii_all_normalized_lines_register_class": all_register_class,
        "bl_target_multiset_delta": bl_delta,
        "normalized_diff_lines": norm["normalized_diff_lines"],
        "nonregister_class_lines": norm["nonregister_class_lines"],
        "register_class_lines": norm["register_class_lines"],
        "normalized_hunks": norm["hunks"],
        "target_instr_lines": len(target_asm),
        "current_instr_lines": len(current_asm),
    }


def is_register_only_admission(checkdiff_primary: str,
                               target_asm: list[str], current_asm: list[str],
                               *, normalized_structural_lines,
                               register_only_primaries=REGISTER_ONLY_PRIMARIES
                               ) -> dict:
    """#619 — the solve-coloring admission predicate. Admission keys on the
    COMPUTED direct-evidence register-only property, NOT the checkdiff PRIMARY
    label.

    The old gate (`primary in REGISTER_ONLY_PRIMARIES`) wrongly abstained on
    coloring walls labelled `register-allocation` / `instruction-sequence` /
    normalized-structural-near-match (8024227C is labelled `register-allocation`
    yet is a PROVABLE pure permutation). This predicate keeps the label only as a
    fast-path HINT — a primary already in the register-only set admits
    immediately (matching the historical gate so the calibrated wins are
    unaffected) — but for everything else the authoritative answer is the T10d
    DIRECT-EVIDENCE verdict: bl-target-multiset parity (no call added/removed/
    re-pointed) AND every normalized truth-gate diff line register-class (no
    instruction-count, call-shape/selection, or non-sanctioned reloc-symbol
    delta). `normalized_structural_lines` is injected (it lives in
    tools/checkdiff.py, outside the package) so this stays a pure, importable,
    unit-testable decision on the SAME normalization the live checkdiff path
    uses.

    Returns dict(admitted, via_label, direct_evidence) — `admitted` is binding;
    `direct_evidence` is the full `direct_evidence_verdict` dict (recorded as the
    admission evidence even on the fast path)."""
    direct = direct_evidence_verdict(
        target_asm, current_asm,
        normalized_structural_lines=normalized_structural_lines)
    via_label = checkdiff_primary in register_only_primaries
    return {
        "admitted": bool(via_label or direct["admitted"]),
        "via_label": via_label,
        "direct_evidence": direct,
    }


def extract_phys_target_from_ig(pcdump_text: str, function: str,
                                class_id: int = 0) -> dict[int, int]:
    """The POST-win `phys_target`: every node's OBSERVED register in the post
    IG (the actual coloring the winning alias produced). Keyed by ig_idx in the
    post IG's index space — exactly what `gate.re_extract_and_classify` /
    `compare_assignments` consume for the actual-vs-target check.

    Spill/incomplete nodes (observed_reg == SPILL) are dropped: a spill is not a
    physical-register target the surrogate can be asked to reproduce."""
    ig = tb.load_ig(pcdump_text, function, class_id=class_id)
    if ig is None:
        raise ValueError(
            f"{function}: no COLORGRAPH class={class_id} section in post pcdump")
    return {
        idx: node.observed_reg
        for idx, node in ig.nodes.items()
        if node.observed_reg != tb.SPILL
    }


def post_ig_reproduces_target(pcdump_text: str, function: str,
                              phys_target: dict[int, int],
                              class_id: int = 0) -> tuple[bool, float, dict]:
    """The §3 actual-vs-target self-check the gate will run, computed PURELY
    over the post pcdump text (no mwcc): load the post IG, run
    `predict_assignments` (G1), and confirm the surrogate's prediction equals
    the target on EVERY contested register (codex Blocker-2 binding). Returns
    ``(all_match, g1_rate, register_match)``."""
    from src.search.solver.gate import compare_assignments
    ig = tb.load_ig(pcdump_text, function, class_id=class_id)
    if ig is None:
        return False, 0.0, {}
    g1 = tb.validate_g1(ig, function)
    predicted = tb.predict_assignments(ig)
    register_match, all_match = compare_assignments(predicted, predicted,
                                                    phys_target)
    # Mirrors gate.re_extract_and_classify exactly: there `actual =
    # predict_assignments(ig)`, so for a frozen post artifact the "actual
    # landing" the gate compares against the target IS the surrogate's
    # prediction over the post IG. `all_match` is therefore "the surrogate
    # predicts the post-derived target on EVERY contested register" — the
    # codex Blocker-2 actual-vs-target check, which holds at post G1=100%
    # (also reported for the regression guard: break predict_assignments and
    # post G1 drops, failing the fixture).
    return all_match, g1.rate, register_match
