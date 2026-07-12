"""Deterministic human rendering and CLI input parsing for delta minimization."""

from __future__ import annotations

import shlex
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


def _candidate_index(result: DeltaMinimizeResult) -> dict[str, Mapping[str, object]]:
    index: dict[str, Mapping[str, object]] = {}
    for row in result.candidates:
        candidate_id = row.get("candidate_id")
        if isinstance(candidate_id, str) and candidate_id not in index:
            index[candidate_id] = row
    return index


def _atom_summaries(result: DeltaMinimizeResult) -> tuple[tuple[str, str], ...]:
    rows = result.delta_manifest.get("atoms")
    atoms: list[tuple[str, str]] = []
    if not isinstance(rows, (list, tuple)):
        return ()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        atom_id = row.get("atom_id")
        summary = row.get("summary")
        if isinstance(atom_id, str) and atom_id:
            atoms.append((atom_id, str(summary) if summary else atom_id))
    return tuple(atoms)


def _candidate_edit_lines(
    candidate_id: str,
    *,
    candidate_index: Mapping[str, Mapping[str, object]],
    atoms: tuple[tuple[str, str], ...],
    direction: str,
    prefix: str,
) -> list[str]:
    row = candidate_index.get(candidate_id)
    if row is None:
        return [f"{prefix}{candidate_id}: candidate evidence unavailable"]
    raw_applied = row.get("applied_atoms")
    applied = (
        {atom_id for atom_id in raw_applied if isinstance(atom_id, str)}
        if isinstance(raw_applied, (list, tuple))
        else set()
    )
    if direction == "right":
        verb = "revert"
        edits = [(atom_id, summary) for atom_id, summary in atoms if atom_id not in applied]
    else:
        verb = "apply"
        edits = [(atom_id, summary) for atom_id, summary in atoms if atom_id in applied]
    lines = [f"{prefix}{candidate_id}:"]
    detail_prefix = " " * (len(prefix) - len(prefix.lstrip()) + 2)
    lines.append(f"{detail_prefix}applied atoms: {_join(sorted(applied))}")
    if not edits:
        lines.append(f"{detail_prefix}no edits from {direction}")
    else:
        lines.extend(f"{detail_prefix}{verb} {atom_id}: {summary}" for atom_id, summary in edits)
    return lines


def _frontier_edit_lines(result: DeltaMinimizeResult) -> list[str]:
    if result.pareto is None:
        return []
    index = _candidate_index(result)
    atoms = _atom_summaries(result)
    lines: list[str] = []
    for group_index, group in enumerate(result.pareto.groups, start=1):
        lines.append(f"frontier group {group_index} minimized edits:")
        for candidate_id in group.minimal_from_left:
            lines.extend(
                _candidate_edit_lines(
                    candidate_id,
                    candidate_index=index,
                    atoms=atoms,
                    direction="left",
                    prefix="  minimal-from-left candidate ",
                )
            )
        for candidate_id in group.minimal_from_right:
            lines.extend(
                _candidate_edit_lines(
                    candidate_id,
                    candidate_index=index,
                    atoms=atoms,
                    direction="right",
                    prefix="  minimal-from-right candidate ",
                )
            )
        lines.extend(
            _candidate_edit_lines(
                group.representative,
                candidate_index=index,
                atoms=atoms,
                direction="left",
                prefix="  representative candidate ",
            )
        )
        for candidate_id in group.candidate_ids:
            if candidate_id == group.representative:
                continue
            lines.extend(
                _candidate_edit_lines(
                    candidate_id,
                    candidate_index=index,
                    atoms=atoms,
                    direction="left",
                    prefix="  tied candidate ",
                )
            )
    minimized = set(result.pareto.joint_solutions)
    for candidate_id in result.pareto.joint_solutions:
        lines.extend(
            _candidate_edit_lines(
                candidate_id,
                candidate_index=index,
                atoms=atoms,
                direction="left",
                prefix="joint-zero minimized candidate ",
            )
        )
    for candidate_id in result.pareto.joint_zero_all_candidate_ids:
        if candidate_id in minimized:
            continue
        lines.extend(
            _candidate_edit_lines(
                candidate_id,
                candidate_index=index,
                atoms=atoms,
                direction="left",
                prefix="joint-zero tied candidate ",
            )
        )
    return lines


def _resume_command(result: DeltaMinimizeResult) -> str | None:
    left = result.inputs.get("left")
    right = result.inputs.get("right")
    out_dir = result.inputs.get("out_dir")
    if not all(isinstance(value, str) and value for value in (left, right, out_dir)):
        return None
    argv = [
        "melee-agent",
        "debug",
        "search",
        "delta-minimize",
        "--function",
        result.function,
        "--left",
        left,
        "--right",
        right,
        "--out-dir",
        out_dir,
    ]
    if isinstance(result.candidate_budget, int) and result.candidate_budget > 0:
        argv.extend(("--max-candidates", str(result.candidate_budget)))
    target = result.inputs.get("target_path")
    if isinstance(target, str) and target:
        argv.extend(("--target", target))
    overrides = result.inputs.get("donor_overrides")
    if isinstance(overrides, Mapping):
        for axis in sorted(overrides):
            donor = overrides[axis]
            if axis in _DONOR_AXES and donor in _DONOR_VALUES:
                argv.extend(("--donor", f"{axis}={donor}"))
    if result.inputs.get("include_objobjects") is False:
        argv.append("--no-objobjects")
    return shlex.join(argv)


def _recovery_lines(result: DeltaMinimizeResult) -> list[str]:
    blockers = set(result.blockers)
    lines: list[str] = []
    if "ambiguous-color-target" in blockers:
        lines.extend(
            (
                "required override: --target PATH_TO_VERSIONED_DELTA_MINIMIZE_COLOR_TARGET",
                "cross-parent role ambiguity requires a v2 target with reviewed cross-parent bindings",
            )
        )
    donor_axes = (
        ("ambiguous-color-donor", "color"),
        ("ambiguous-objobject-donor", "objobjects"),
        ("ambiguous-stack-home-donor", "stack-homes"),
    )
    for blocker, axis in donor_axes:
        if blocker in blockers:
            lines.append(f"required override: --donor {axis}=left|right")
    if any("inspector" in blocker or "inspect" in blocker for blocker in blockers):
        lines.append("next action: restore inspector infrastructure, then resume this run")
    if any(
        token in blocker
        for blocker in blockers
        for token in (
            "score-infrastructure",
            "checkdiff",
            "pcdump",
            "opcode-evidence",
            "color-evidence",
            "objobject-evidence",
            "stack-evidence",
            "stack-home-evidence",
        )
    ):
        lines.append("next action: restore compiler evidence generation, then resume this run")
    if not lines:
        lines.append("next action: resolve the listed evidence blocker, then resume this run")
    command = _resume_command(result)
    if command is not None:
        lines.append(f"resume command: {command}")
    else:
        lines.append("resume command unavailable: result does not contain a validated out-dir")
    return list(dict.fromkeys(lines))


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
        lines.extend(_frontier_edit_lines(result))

    lines.extend(_candidate_artifact_lines(result))
    if result.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in result.blockers)
        lines.extend(_recovery_lines(result))
    elif result.status == "incomplete":
        lines.extend(("blockers:", "- unspecified incomplete infrastructure"))
        lines.extend(_recovery_lines(result))
    return "\n".join(lines)
