"""Line-oriented source hunk primitives for bounded source recombination.

Internal coordinates are always zero-based, half-open line ranges:
``base_start`` is inclusive and ``base_end`` is exclusive. Insertions are
represented as zero-width ranges where ``base_start == base_end``. Human/JSON
output converts those ranges to one-based inclusive coordinates; for insertions
the output range is intentionally empty (``start == insertion_line + 1`` and
``end == insertion_line``) and carries ``empty: true``.

Overlap semantics are conservative. Non-empty replacements/deletions overlap
when their half-open intervals intersect. Two insertions overlap when they share
the same insertion point. A zero-width insertion overlaps a non-empty hunk when
the insertion point is inside or on either boundary of the non-empty hunk. This
keeps composed probes deterministic and avoids ambiguous ordering at changed
boundaries.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class SourceHunk:
    """A source line replacement using zero-based half-open coordinates."""

    hunk_id: str
    base_start: int
    base_end: int
    candidate_start: int
    candidate_end: int
    removed: tuple[str, ...]
    added: tuple[str, ...]
    kind: str = "statement"
    risk: str = "low"
    parent_hunk_id: str | None = None
    blockers: tuple[str, ...] = ()

    @property
    def base_width(self) -> int:
        return self.base_end - self.base_start

    @property
    def candidate_width(self) -> int:
        return self.candidate_end - self.candidate_start

    @property
    def is_insertion(self) -> bool:
        return self.base_start == self.base_end

    def overlaps(self, other: "SourceHunk") -> bool:
        return line_ranges_overlap(
            self.base_start,
            self.base_end,
            other.base_start,
            other.base_end,
        )

    def to_dict(self, *, one_based: bool = True) -> dict[str, object]:
        data: dict[str, object] = {
            "hunk_id": self.hunk_id,
            "base_start": self.base_start,
            "base_end": self.base_end,
            "candidate_start": self.candidate_start,
            "candidate_end": self.candidate_end,
            "removed": list(self.removed),
            "added": list(self.added),
            "kind": self.kind,
            "risk": self.risk,
        }
        if self.parent_hunk_id is not None:
            data["parent_hunk_id"] = self.parent_hunk_id
        if "manual-protected-expression-subhunk" in self.blockers:
            data["manual_subhunk"] = True
        if self.blockers:
            data["blockers"] = list(self.blockers)
        if one_based:
            data["base_range"] = _one_based_range(self.base_start, self.base_end)
            data["candidate_range"] = _one_based_range(
                self.candidate_start,
                self.candidate_end,
            )
        return data


@dataclass(frozen=True)
class HunkSplitPlan:
    """Result of conservative subhunk splitting."""

    hunks: tuple[SourceHunk, ...]
    blockers: tuple[dict[str, object], ...] = ()


def diff_line_hunks(
    base_text: str,
    candidate_text: str,
    *,
    hunk_prefix: str = "h",
) -> tuple[SourceHunk, ...]:
    """Return line hunks from ``base_text`` to ``candidate_text``.

    Coordinates are line indices relative to the supplied texts, not absolute
    file line numbers.
    """

    base_lines = split_source_lines(base_text)
    candidate_lines = split_source_lines(candidate_text)
    matcher = difflib.SequenceMatcher(
        None,
        base_lines,
        candidate_lines,
        autojunk=False,
    )
    hunks: list[SourceHunk] = []
    ordinal = 1
    for tag, base_start, base_end, cand_start, cand_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunk = SourceHunk(
            hunk_id=f"{hunk_prefix}{ordinal:03d}",
            base_start=base_start,
            base_end=base_end,
            candidate_start=cand_start,
            candidate_end=cand_end,
            removed=tuple(base_lines[base_start:base_end]),
            added=tuple(candidate_lines[cand_start:cand_end]),
            kind=classify_hunk_kind(
                base_lines[base_start:base_end],
                candidate_lines[cand_start:cand_end],
            ),
            risk=_initial_risk(
                base_lines[base_start:base_end],
                candidate_lines[cand_start:cand_end],
            ),
        )
        hunks.append(hunk)
        ordinal += 1
    return tuple(hunks)


def split_hunks_conservatively(
    hunks: Sequence[SourceHunk],
) -> HunkSplitPlan:
    """Split safe broad replacements into smaller statement hunks.

    V1 is intentionally conservative. A broad replacement is split only when
    each corresponding changed line is a self-contained statement/declaration
    without control/preprocessor/label/brace-boundary risk. If a broad hunk
    crosses those boundaries, the hunk is not guessed at and a
    ``manual-subhunk-range-required`` blocker is emitted.
    """

    out: list[SourceHunk] = []
    blockers: list[dict[str, object]] = []
    for hunk in hunks:
        split = split_hunk_conservatively(hunk)
        out.extend(split.hunks)
        blockers.extend(split.blockers)
    return HunkSplitPlan(tuple(out), tuple(blockers))


def split_hunk_conservatively(hunk: SourceHunk) -> HunkSplitPlan:
    boundary_blockers = brace_control_blockers(hunk)
    if boundary_blockers:
        return HunkSplitPlan(
            (),
            (
                {
                    "blocker": "manual-subhunk-range-required",
                    "hunk_id": hunk.hunk_id,
                    "reasons": list(boundary_blockers),
                    "base_range": _one_based_range(hunk.base_start, hunk.base_end),
                    "candidate_range": _one_based_range(
                        hunk.candidate_start,
                        hunk.candidate_end,
                    ),
                },
            ),
        )

    if (
        hunk.base_width > 1
        and hunk.base_width == hunk.candidate_width
        and all(
            _simple_statement_pair(removed, added)
            for removed, added in zip(hunk.removed, hunk.added)
        )
    ):
        split: list[SourceHunk] = []
        for index, (removed, added) in enumerate(
            zip(hunk.removed, hunk.added),
            start=1,
        ):
            split.append(
                SourceHunk(
                    hunk_id=f"{hunk.hunk_id}s{index}",
                    parent_hunk_id=hunk.hunk_id,
                    base_start=hunk.base_start + index - 1,
                    base_end=hunk.base_start + index,
                    candidate_start=hunk.candidate_start + index - 1,
                    candidate_end=hunk.candidate_start + index,
                    removed=(removed,),
                    added=(added,),
                    kind=classify_hunk_kind((removed,), (added,)),
                    risk="low",
                )
            )
        return HunkSplitPlan(tuple(split))

    return HunkSplitPlan((hunk,))


def source_hunk_from_mapping(
    raw: Mapping[str, Any],
    *,
    parent: SourceHunk | None = None,
    child_index: int = 1,
    line_offset: int = 0,
    manual_subhunk: bool = False,
) -> SourceHunk:
    """Normalize a JSON source hunk into zero-based half-open coordinates."""

    parent_id = parent.hunk_id if parent is not None else None
    hunk_id = _hunk_id(raw, parent_id=parent_id, child_index=child_index)
    base_start, base_end = _hunk_range(
        raw,
        start_key="base_start",
        end_key="base_end",
        range_key="base_range",
        legacy_start_key="old_start",
        legacy_lines_key="old_lines",
        fallback_lines_key="removed",
        line_offset=line_offset,
    )
    candidate_start, candidate_end = _hunk_range(
        raw,
        start_key="candidate_start",
        end_key="candidate_end",
        range_key="candidate_range",
        legacy_start_key="new_start",
        legacy_lines_key="new_lines",
        fallback_lines_key="added",
        line_offset=line_offset,
    )
    removed = _hunk_lines(
        raw,
        primary_key="removed",
        legacy_key="old_lines",
        parent=parent,
        start=base_start,
        end=base_end,
        parent_start=parent.base_start if parent is not None else 0,
        parent_lines=parent.removed if parent is not None else (),
    )
    added = _hunk_lines(
        raw,
        primary_key="added",
        legacy_key="new_lines",
        parent=parent,
        start=candidate_start,
        end=candidate_end,
        parent_start=parent.candidate_start if parent is not None else 0,
        parent_lines=parent.added if parent is not None else (),
    )
    raw_parent_id = raw.get("parent_hunk_id")
    parent_hunk_id = str(raw_parent_id) if raw_parent_id else parent_id
    blockers = tuple(str(item) for item in raw.get("blockers") or ())
    if manual_subhunk and "manual-protected-expression-subhunk" not in blockers:
        blockers = (*blockers, "manual-protected-expression-subhunk")
    kind = str(raw.get("kind") or classify_hunk_kind(removed, added))
    risk = str(raw.get("risk") or ("manual" if manual_subhunk else "low"))
    hunk = SourceHunk(
        hunk_id=hunk_id,
        base_start=base_start,
        base_end=base_end,
        candidate_start=candidate_start,
        candidate_end=candidate_end,
        removed=removed,
        added=added,
        kind=kind,
        risk=risk,
        parent_hunk_id=parent_hunk_id,
        blockers=blockers,
    )
    _validate_hunk_range(hunk)
    if parent is not None:
        _validate_child_hunk(parent, hunk)
    return hunk


def manual_subhunks_from_source_hunks(
    source_hunks: Sequence[Mapping[str, Any]],
    *,
    line_offset: int = 0,
) -> tuple[SourceHunk, ...]:
    """Return explicit protected/manual child hunks embedded in source hunks."""

    out: list[SourceHunk] = []
    for raw in source_hunks:
        if not isinstance(raw, Mapping):
            continue
        try:
            parent = source_hunk_from_mapping(raw, line_offset=line_offset)
        except (TypeError, ValueError):
            continue
        child_index = 1
        for key in (
            "protected_subhunks",
            "manual_subhunks",
            "continuation_subhunks",
        ):
            children = raw.get(key)
            if not isinstance(children, Sequence) or isinstance(
                children,
                (str, bytes, bytearray),
            ):
                continue
            for child_raw in children:
                if not isinstance(child_raw, Mapping):
                    continue
                try:
                    out.append(
                        source_hunk_from_mapping(
                            child_raw,
                            parent=parent,
                            child_index=child_index,
                            line_offset=line_offset,
                            manual_subhunk=True,
                        )
                    )
                except (TypeError, ValueError):
                    continue
                child_index += 1
    return tuple(out)


def brace_control_blockers(hunk: SourceHunk) -> tuple[str, ...]:
    """Return reasons a hunk should require manual subhunk ranges."""

    reasons: list[str] = []
    changed_lines = list(hunk.removed) + list(hunk.added)
    stripped = [line.strip() for line in changed_lines if line.strip()]
    if any(line.startswith("#") for line in stripped):
        reasons.append("preprocessor-boundary")
    if any(
        _LABEL_RE.match(line) or line.startswith(("case ", "default:"))
        for line in stripped
    ):
        reasons.append("label-boundary")
    if any(_CONTROL_RE.match(line) for line in stripped):
        reasons.append("control-boundary")

    removed_delta = _brace_delta(hunk.removed)
    added_delta = _brace_delta(hunk.added)
    brace_line_count = sum(1 for line in changed_lines if "{" in line or "}" in line)
    if removed_delta != 0 or added_delta != 0:
        reasons.append("unbalanced-braces")
    elif brace_line_count > 0 and (hunk.base_width > 1 or hunk.candidate_width > 1):
        reasons.append("brace-depth-transition")

    return tuple(dict.fromkeys(reasons))


def classify_hunk_kind(
    removed: Sequence[str],
    added: Sequence[str],
) -> str:
    changed = "\n".join([*removed, *added])
    added_text = "\n".join(added)
    if not removed and added:
        if all(_is_declaration_line(line) for line in added if line.strip()):
            return "declaration"
        return "statement"
    if added and all(_is_declaration_line(line) for line in added if line.strip()):
        return "declaration"
    if "mn_GetDigitCount" in changed:
        return "motion"
    if re.search(r"\w+\s*\([^;]*\(f32\)", added_text):
        return "callarg"
    if len(removed) != len(added):
        return "motion"
    return "statement"


def line_ranges_overlap(
    start_a: int,
    end_a: int,
    start_b: int,
    end_b: int,
) -> bool:
    """Return whether two zero-based half-open line ranges overlap."""

    empty_a = start_a == end_a
    empty_b = start_b == end_b
    if empty_a and empty_b:
        return start_a == start_b
    if empty_a:
        return start_b <= start_a <= end_b
    if empty_b:
        return start_a <= start_b <= end_a
    return max(start_a, start_b) < min(end_a, end_b)


def hunks_overlap(hunks: Sequence[SourceHunk]) -> bool:
    for index, hunk in enumerate(hunks):
        for other in hunks[index + 1:]:
            if hunk.overlaps(other):
                return True
    return False


def apply_hunks_to_text(source_text: str, hunks: Sequence[SourceHunk]) -> str:
    """Apply non-overlapping hunks to ``source_text`` and return patched text."""

    trailing_newline = source_text.endswith("\n")
    patched_lines = apply_hunks_to_lines(split_source_lines(source_text), hunks)
    return join_source_lines(patched_lines, trailing_newline=trailing_newline)


def apply_hunks_to_lines(
    source_lines: Sequence[str],
    hunks: Sequence[SourceHunk],
) -> list[str]:
    """Apply non-overlapping hunks to a line list.

    Raises ``ValueError`` if the hunks overlap or if any hunk no longer matches
    the expected removed text.
    """

    if hunks_overlap(hunks):
        raise ValueError("source hunks overlap")
    patched = list(source_lines)
    for hunk in sorted(hunks, key=lambda item: item.base_start, reverse=True):
        if hunk.base_start < 0 or hunk.base_end < hunk.base_start:
            raise ValueError(f"invalid hunk range: {hunk.hunk_id}")
        if hunk.base_end > len(patched):
            raise ValueError(f"hunk out of range: {hunk.hunk_id}")
        current = tuple(patched[hunk.base_start:hunk.base_end])
        if current != hunk.removed:
            raise ValueError(f"hunk removed text mismatch: {hunk.hunk_id}")
        patched[hunk.base_start:hunk.base_end] = list(hunk.added)
    return patched


def split_source_lines(source_text: str) -> list[str]:
    return source_text.splitlines()


def join_source_lines(lines: Sequence[str], *, trailing_newline: bool = True) -> str:
    text = "\n".join(lines)
    if trailing_newline:
        text += "\n"
    return text


def _one_based_range(start: int, end: int) -> dict[str, object]:
    empty = start == end
    return {
        "start": start + 1,
        "end": end if not empty else start,
        "empty": empty,
    }


def _hunk_id(
    raw: Mapping[str, Any],
    *,
    parent_id: str | None,
    child_index: int,
) -> str:
    raw_id = raw.get("hunk_id") or raw.get("id")
    if raw_id:
        return str(raw_id)
    if parent_id:
        return f"{parent_id}m{child_index}"
    return f"h{child_index:03d}"


def _hunk_range(
    raw: Mapping[str, Any],
    *,
    start_key: str,
    end_key: str,
    range_key: str,
    legacy_start_key: str,
    legacy_lines_key: str,
    fallback_lines_key: str,
    line_offset: int,
) -> tuple[int, int]:
    start = _int_or_none(raw.get(start_key))
    end = _int_or_none(raw.get(end_key))
    if start is not None and end is not None:
        return start - line_offset, end - line_offset

    raw_range = raw.get(range_key)
    if isinstance(raw_range, Mapping):
        range_start = _int_or_none(raw_range.get("start"))
        range_end = _int_or_none(raw_range.get("end"))
        if range_start is not None and range_end is not None:
            start = range_start - 1 - line_offset
            if raw_range.get("empty") is True:
                return start, start
            return start, range_end - line_offset
    elif (
        isinstance(raw_range, Sequence)
        and not isinstance(raw_range, (str, bytes, bytearray))
        and len(raw_range) == 2
    ):
        range_start = _int_or_none(raw_range[0])
        range_end = _int_or_none(raw_range[1])
        if range_start is not None and range_end is not None:
            return range_start - 1 - line_offset, range_end - line_offset

    legacy_start = _int_or_none(raw.get(legacy_start_key))
    if legacy_start is not None:
        lines = _raw_lines(raw.get(legacy_lines_key))
        if not lines:
            lines = _raw_lines(raw.get(fallback_lines_key))
        start = legacy_start - 1 - line_offset
        return start, start + len(lines)

    raise ValueError(f"missing source hunk range: {start_key}/{legacy_start_key}")


def _hunk_lines(
    raw: Mapping[str, Any],
    *,
    primary_key: str,
    legacy_key: str,
    parent: SourceHunk | None,
    start: int,
    end: int,
    parent_start: int,
    parent_lines: Sequence[str],
) -> tuple[str, ...]:
    lines = _raw_lines(raw.get(primary_key))
    if lines:
        return tuple(lines)
    lines = _raw_lines(raw.get(legacy_key))
    if lines:
        return tuple(lines)
    if parent is not None:
        rel_start = start - parent_start
        rel_end = end - parent_start
        if 0 <= rel_start <= rel_end <= len(parent_lines):
            return tuple(parent_lines[rel_start:rel_end])
    if start == end:
        return ()
    raise ValueError(f"missing source hunk lines: {primary_key}/{legacy_key}")


def _raw_lines(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(value.splitlines())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(line) for line in value)
    return ()


def _validate_hunk_range(hunk: SourceHunk) -> None:
    if hunk.base_start < 0 or hunk.candidate_start < 0:
        raise ValueError(f"negative hunk range: {hunk.hunk_id}")
    if hunk.base_end < hunk.base_start:
        raise ValueError(f"invalid base range: {hunk.hunk_id}")
    if hunk.candidate_end < hunk.candidate_start:
        raise ValueError(f"invalid candidate range: {hunk.hunk_id}")
    if len(hunk.removed) != hunk.base_width:
        raise ValueError(f"removed line count mismatch: {hunk.hunk_id}")
    if len(hunk.added) != hunk.candidate_width:
        raise ValueError(f"added line count mismatch: {hunk.hunk_id}")


def _validate_child_hunk(parent: SourceHunk, child: SourceHunk) -> None:
    if not (
        parent.base_start <= child.base_start <= child.base_end <= parent.base_end
    ):
        raise ValueError(f"child base range outside parent: {child.hunk_id}")
    if not (
        parent.candidate_start
        <= child.candidate_start
        <= child.candidate_end
        <= parent.candidate_end
    ):
        raise ValueError(f"child candidate range outside parent: {child.hunk_id}")


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def _initial_risk(removed: Sequence[str], added: Sequence[str]) -> str:
    return "high" if brace_control_blockers(
        SourceHunk(
            hunk_id="risk",
            base_start=0,
            base_end=len(removed),
            candidate_start=0,
            candidate_end=len(added),
            removed=tuple(removed),
            added=tuple(added),
        )
    ) else "low"


def _simple_statement_pair(removed: str, added: str) -> bool:
    return (
        _simple_statement_line(removed)
        and _simple_statement_line(added)
        and _brace_delta((removed,)) == 0
        and _brace_delta((added,)) == 0
    )


def _simple_statement_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return False
    if _LABEL_RE.match(stripped) or stripped.startswith(("case ", "default:")):
        return False
    if _CONTROL_RE.match(stripped):
        return False
    return stripped.endswith(";")


def _is_declaration_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped.endswith(";"):
        return False
    return bool(_DECL_RE.match(stripped))


def _brace_delta(lines: Iterable[str]) -> int:
    delta = 0
    for line in lines:
        scrubbed = _scrub_literals_and_comments(line)
        delta += scrubbed.count("{")
        delta -= scrubbed.count("}")
    return delta


def _scrub_literals_and_comments(line: str) -> str:
    out = []
    in_quote: str | None = None
    escaped = False
    index = 0
    while index < len(line):
        ch = line[index]
        if in_quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_quote:
                in_quote = None
            out.append(" ")
            index += 1
            continue
        if ch in {"'", '"'}:
            in_quote = ch
            out.append(" ")
            index += 1
            continue
        if ch == "/" and index + 1 < len(line) and line[index + 1] == "/":
            break
        out.append(ch)
        index += 1
    return "".join(out)


_LABEL_RE = re.compile(r"^[A-Za-z_]\w*\s*:")
_CONTROL_RE = re.compile(r"^(?:if|for|while|switch|else|do)\b")
_DECL_RE = re.compile(
    r"^(?:const\s+|volatile\s+|static\s+|register\s+|signed\s+|unsigned\s+)*"
    r"(?:struct\s+\w+|enum\s+\w+|union\s+\w+|[A-Za-z_]\w*)"
    r"(?:\s*\*|\s+)+[A-Za-z_]\w*(?:\s*=.*)?;"
)
