from __future__ import annotations

from .score import rollup_verdict


def calibrate(fixtures: list, *, score_advisory, score_generative) -> dict:
    failures = []
    positives_ok = negatives_ok = 0
    for f in fixtures:
        rollup = rollup_verdict(score_advisory(f), score_generative(f), None)
        if rollup == f["expected_rollup"]:
            if f["kind"] == "positive":
                positives_ok += 1
            else:
                negatives_ok += 1
        else:
            failures.append({"name": f["name"], "kind": f["kind"],
                             "expected": f["expected_rollup"], "got": rollup})
    return {"passed": not failures, "failures": failures,
            "positives_ok": positives_ok, "negatives_ok": negatives_ok}
