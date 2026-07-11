"""Deterministic human rendering and CLI input parsing for delta minimization."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .run import DeltaMinimizeResult

_DONOR_AXES = frozenset({"color", "objobjects", "stack-homes"})
_DONOR_VALUES = frozenset({"left", "right"})
_AXIS_ORDER = ("opcode", "color", "objobjects", "stack-homes")


def parse_donor_overrides(values: Iterable[str]) -> dict[str, str]:
    """Parse repeatable ``AXIS=SIDE`` overrides without silent normalization."""

    overrides: dict[str, str] = {}
    for raw in values:
        if not isinstance(raw, str) or raw.count("=") != 1 or raw.strip() != raw:
            raise ValueError(f"invalid --donor value {raw!r}; expected AXIS=left|right")
        axis, donor = raw.split("=", 1)
        if (
            not axis
            or not donor
            or axis.strip() != axis
            or donor.strip() != donor
            or axis not in _DONOR_AXES
            or donor not in _DONOR_VALUES
        ):
            raise ValueError(
                f"invalid --donor value {raw!r}; axis must be color, objobjects, "
                "or stack-homes and side must be left or right"
            )
        if axis in overrides:
            raise ValueError(f"duplicate --donor override for {axis}")
        overrides[axis] = donor
    return dict(sorted(overrides.items()))


def _tuple_text(values: object) -> str:
    if isinstance(values, (list, tuple)):
        return "(" + ", ".join(str(value) for value in values) + ")"
    return str(values)


def _join(values: object, *, empty: str = "none") -> str:
    if not isinstance(values, (list, tuple)) or not values:
        return empty
    return ", ".join(str(value) for value in values)


def _reference_lines(objective: Mapping[str, object]) -> list[str]:
    references = objective.get("references")
    if not isinstance(references, Mapping):
        return ["  unavailable"]
    lines: list[str] = []
    for axis in _AXIS_ORDER:
        raw = references.get(axis)
        if not isinstance(raw, Mapping):
            lines.append(f"  {axis}: unavailable")
            continue
        donor = raw.get("donor")
        donor_text = "none" if donor is None else str(donor)
        override = "yes" if raw.get("override") is True else "no"
        line = (
            f"  {axis}: {raw.get('reference_kind', 'unknown')} donor={donor_text} "
            f"override={override} reason={raw.get('inference_reason', 'unknown')}"
        )
        unresolved = raw.get("unresolved")
        if isinstance(unresolved, (list, tuple)) and unresolved:
            line += f" unresolved={_join(unresolved)}"
        artifact = raw.get("reference_artifact")
        if isinstance(artifact, str) and artifact:
            line += f" artifact={artifact}"
        lines.append(line)
    return lines


def _candidate_artifact_lines(result: DeltaMinimizeResult) -> list[str]:
    if result.best_next is None:
        return []
    for row in result.candidates:
        if row.get("candidate_id") != result.best_next:
            continue
        lines = [f"best next: {result.best_next}"]
        source = row.get("source_path")
        if isinstance(source, str) and source:
            lines.append(f"  retained source: {source}")
        evidence = row.get("evidence")
        if isinstance(evidence, Mapping):
            pcdump = evidence.get("pcdump_path")
            if isinstance(pcdump, str) and pcdump:
                lines.append(f"  pcdump: {pcdump}")
        return lines
    return [f"best next: {result.best_next}"]


def render_delta_minimize_text(result: DeltaMinimizeResult) -> str:
    """Render the complete result without collapsing Pareto ties or provenance."""

    mode = "exact four-axis" if result.exact_four_axis else "not exact four-axis"
    lines = [
        f"delta minimize: {result.function}",
        f"status: {result.status} ({mode})",
    ]
    if result.status == "provisional":
        lines.append("PROVISIONAL three-axis; ObjObject scoring disabled")
    lines.append(
        "candidates: "
        f"legal={result.candidate_counts.get('legal', 0)} "
        f"viable={result.candidate_counts.get('viable', 0)} "
        f"complete={result.candidate_counts.get('complete', 0)} "
        f"budget={result.candidate_budget}"
    )

    atoms = result.delta_manifest.get("atoms")
    atom_rows = atoms if isinstance(atoms, (list, tuple)) else ()
    lines.append(f"delta lattice: {len(atom_rows)} atom(s)")
    for index, atom in enumerate(atom_rows, start=1):
        if isinstance(atom, Mapping):
            atom_id = atom.get("atom_id", f"atom-{index}")
            summary = atom.get("summary", "")
            lines.append(f"  {index}. {atom_id}: {summary}")

    lines.append("objective references:")
    lines.extend(_reference_lines(result.objective_manifest))
    lines.append("ObjObject zero means matches the inferred donor, not proven retail identity.")

    if result.pareto is not None:
        lines.append(f"pareto candidates: {_join(result.pareto.candidate_ids)}")
        for index, group in enumerate(result.pareto.groups, start=1):
            vector = group.objective_vector
            lines.extend(
                [
                    f"frontier group {index}:",
                    "  vector: "
                    f"opcode={_tuple_text(vector.opcode)} "
                    f"color={_tuple_text(vector.color)} "
                    f"objobjects={_tuple_text(vector.objobjects)} "
                    f"stack-homes={_tuple_text(vector.stack_homes)}",
                    f"  candidates={_join(group.candidate_ids)}",
                    f"  minimal-from-left={_join(group.minimal_from_left)}",
                    f"  minimal-from-right={_join(group.minimal_from_right)}",
                    f"  representative={group.representative}",
                ]
            )
        lines.append(f"exact matches: {_join(result.pareto.exact_match_candidate_ids)}")
        lines.append(f"joint-zero minimized: {_join(result.pareto.joint_solutions)}")
        lines.append(f"joint-zero all candidates: {_join(result.pareto.joint_zero_all_candidate_ids)}")

    lines.extend(_candidate_artifact_lines(result))
    if result.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in result.blockers)
    elif result.status == "incomplete":
        lines.extend(("blockers:", "- unspecified incomplete infrastructure"))
    return "\n".join(lines)
