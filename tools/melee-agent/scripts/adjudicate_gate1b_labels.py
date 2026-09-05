#!/usr/bin/env python3
"""Draft source-grounded Gate-1b labels from two pcdump slices.

A label maps a reference-rev role (matched_ig) to its drifted-rev counterpart
(wip_ig). To stay non-circular, the ONLY auto-labels are roles whose
normalized first-def signature is UNIQUE within BOTH compiles -- i.e. a
source-grounded operation such as `lwz r#,44(r#)` (one specific struct-field
load) that pins the role independently of its ig number and independently of
the matcher's own use-site feature.

Roles with a generic/shared first-def (`mr r#,r#`, `add`, `li r#,0`) are
NOT auto-labeled: they are reported as candidates for optional hand
adjudication by def-operand lineage (the existing mnVibration corpus does
this for its mr/add roles). Excluding them keeps the auto metric honest.

The headline signal: among auto-labels, how many DRIFTED (matched_ig !=
wip_ig) -- those are the roles raw ig_idx gets wrong and the matcher must
recover via first-def identity.

Usage:
  adjudicate_gate1b_labels.py <matched_dump> <wip_dump> <function> <class_id> [out.json]
"""
import sys
import json
import collections
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # tools/melee-agent
from src.mwcc_debug import role_descriptor as rd  # noqa: E402


def unique_sig_map(descs):
    by_sig = collections.defaultdict(list)
    for ig, d in descs.items():
        by_sig[d.first_def_sig].append(ig)
    uniq = {sig: igs[0] for sig, igs in by_sig.items() if len(igs) == 1}
    return uniq, by_sig


def main():
    if len(sys.argv) < 5:
        raise SystemExit(__doc__)
    matched_p, wip_p, fn, cls = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    out = sys.argv[5] if len(sys.argv) > 5 else None

    md = rd.build_descriptors(rd.Compile.from_text(open(matched_p).read(), fn, ""), cls)
    wd = rd.build_descriptors(rd.Compile.from_text(open(wip_p).read(), fn, ""), cls)
    m_uniq, m_by = unique_sig_map(md)
    w_uniq, _ = unique_sig_map(wd)

    same, notes = {}, {}
    for sig, mig in m_uniq.items():
        if sig in w_uniq:
            same[mig] = w_uniq[sig]
            notes[mig] = sig

    raw_correct = sum(1 for mig, wig in same.items() if mig == wig)
    drifted = sum(1 for mig, wig in same.items() if mig != wig)
    generic = {sig: igs for sig, igs in m_by.items() if len(igs) > 1}

    print(f"== {fn} class{cls} ==")
    print(f"matched class0={len(md)}  wip class0={len(wd)}")
    print(f"auto unique-offset labels: {len(same)}  "
          f"(raw-ig agrees {raw_correct}, DRIFTED {drifted})")
    for mig in sorted(same):
        flag = "  <-- DRIFT (raw-ig wrong)" if mig != same[mig] else ""
        print(f"   {mig:>3} -> {same[mig]:<3}  {notes[mig]!r}{flag}")
    print("generic first-defs (hand-lineage candidates, NOT auto-labeled):")
    for sig, igs in sorted(generic.items(), key=lambda kv: -len(kv[1])):
        print(f"   {sig!r}: matched igs {igs}")

    doc = {
        "function": fn,
        "class_id": cls,
        "matched_dump": pathlib.Path(matched_p).name,
        "wip_dump": pathlib.Path(wip_p).name,
        "adjudication_basis": (
            "AUTO-DRAFT (hand-verify before trusting). Each 'same' label is a "
            "class-0 role whose normalized first-def signature is unique in BOTH "
            "compiles -- a source-grounded struct-access/immediate that identifies "
            "the role independent of ig number and of the matcher's use-site "
            "feature, so it is non-circular. Generic first-defs (mr/add/li 0) are "
            "left unadjudicated rather than labeled by the matcher's own "
            "discriminator. raw_ig_baseline_correct counts labels where "
            "matched_ig == wip_ig (what trusting raw ig_idx would get); the "
            "matcher must recover the DRIFTED remainder."
        ),
        "same": {str(k): same[k] for k in sorted(same)},
        "same_role_notes": {str(k): notes[k] for k in sorted(same)},
        "unadjudicated": sorted({ig for igs in generic.values() for ig in igs}),
        "raw_ig_baseline_correct": raw_correct,
    }
    if out:
        with open(out, "w") as f:
            f.write(json.dumps(doc, indent=2) + "\n")
        print(f"wrote draft -> {out}")


if __name__ == "__main__":
    main()
