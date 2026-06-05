from __future__ import annotations

import dataclasses
import enum
import re
from typing import Any


class NameMagicBlocker(str, enum.Enum):
    RAW_DIFF_NO_SUPPORTED_DATA_SYMBOL_PAIR = "raw-diff-no-supported-data-symbol-pair"
    TARGET_OBJECT_MISSING = "target-object-missing"
    CURRENT_OBJECT_MISSING = "current-object-missing"
    AMBIGUOUS_RELOCATION_PAIR = "ambiguous-relocation-pair"
    UNSUPPORTED_RELOC_KIND = "unsupported-reloc-kind"
    UNSUPPORTED_SECTION_ANCHOR_OFFSET = "unsupported-section-anchor-offset"
    UNSUPPORTED_SOURCE_SITE = "unsupported-source-site"
    AMBIGUOUS_SDATA2_VALUE = "ambiguous-sdata2-value"
    SDATA2_POOL_ORDER_DEPENDENT = "sdata2-pool-order-dependent"
    SECTION_ANCHOR_SOURCE_FIXABLE_RESIDUAL = "section-anchor-source-fixable-residual"
    DECLARATION_APPLY_UNSUPPORTED = "declaration-apply-unsupported"
    NO_NAME_MAGIC_VALIDATION_FAILED = "no-name-magic-validation-failed"
    NO_NAME_MAGIC_CANDIDATE = "no-name-magic-candidate"


@dataclasses.dataclass(frozen=True)
class NameMagicRelocation:
    offset: str
    kind: str
    expected_symbol: str
    current_symbol: str

    @property
    def operator_family(self) -> str:
        if self.current_symbol.startswith("@"):
            return "sdata2-named-float-load"
        return "data-symbol-static-to-global"


@dataclasses.dataclass(frozen=True)
class NameMagicEvidence:
    relocations: list[NameMagicRelocation]
    residual_diff_count: int
    blocker: NameMagicBlocker | None = None
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class NameMagicSourceEdit:
    start: int
    end: int
    replacement: str


@dataclasses.dataclass(frozen=True)
class NameMagicSourceProbe:
    label: str
    operator: str
    description: str
    source_text: str
    edits: tuple[NameMagicSourceEdit, ...]
    provenance: dict[str, Any]
    header_declarations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "label": self.label,
            "operator": self.operator,
            "description": self.description,
            "provenance": dict(self.provenance),
        }
        if self.header_declarations:
            payload["header_declarations"] = list(self.header_declarations)
        return payload


@dataclasses.dataclass(frozen=True)
class _StaticDefinition:
    decl_start: int
    decl_end: int
    static_start: int
    static_end: int


_RELOC_DIFF_RE = re.compile(
    r"^(?P<side>[-+])\+(?P<offset>[0-9a-fA-F]+):\s+"
    r"(?P<kind>R_PPC_[A-Za-z0-9_]+)\t(?P<symbol>\S+)"
)
_DIFF_OFFSET_RE = re.compile(r"^[+-]\+(?P<offset>[0-9a-fA-F]+):")


def _supported_current_symbol(symbol: str) -> bool:
    return symbol.startswith("@") or symbol.startswith("...data.")


def _apply_source_edits(
    source: str, edits: tuple[NameMagicSourceEdit, ...] | list[NameMagicSourceEdit]
) -> str:
    ordered = sorted(edits, key=lambda edit: (edit.start, edit.end))
    previous_end = -1
    for edit in ordered:
        if edit.start < 0 or edit.end < edit.start or edit.end > len(source):
            raise ValueError("source edit range is outside the source text")
        if edit.start < previous_end:
            raise ValueError("source edits overlap")
        previous_end = max(previous_end, edit.end)

    result = source
    for edit in sorted(edits, key=lambda edit: (edit.start, edit.end), reverse=True):
        result = result[: edit.start] + edit.replacement + result[edit.end :]
    return result


def _is_preprocessor_line(text: str, index: int) -> bool:
    line_start = text.rfind("\n", 0, index) + 1
    return text[line_start:index].strip() == ""


def _preprocessor_depth_at(source: str, index: int) -> int:
    depth = 0
    position = 0
    for line in source.splitlines(keepends=True):
        next_position = position + len(line)
        if next_position > index:
            break
        stripped = line.lstrip()
        if re.match(r"#\s*(?:if\b|ifdef\b|ifndef\b)", stripped):
            depth += 1
        elif re.match(r"#\s*endif\b", stripped):
            depth = max(0, depth - 1)
        position = next_position
    return depth


def _declaration_spans_preprocessor_line(source: str, start: int, end: int) -> bool:
    for line in source[start:end].splitlines():
        if line.lstrip().startswith("#"):
            return True
    return False


def _find_top_level_char(text: str, needle: str) -> int | None:
    brace_depth = 0
    bracket_depth = 0
    paren_depth = 0
    for index, char in enumerate(text):
        if char == "{" and bracket_depth == 0 and paren_depth == 0:
            brace_depth += 1
        elif char == "}" and bracket_depth == 0 and paren_depth == 0:
            brace_depth = max(0, brace_depth - 1)
        elif char == "[" and brace_depth == 0 and paren_depth == 0:
            bracket_depth += 1
        elif char == "]" and brace_depth == 0 and paren_depth == 0:
            bracket_depth = max(0, bracket_depth - 1)
        elif char == "(" and brace_depth == 0 and bracket_depth == 0:
            paren_depth += 1
        elif char == ")" and brace_depth == 0 and bracket_depth == 0:
            paren_depth = max(0, paren_depth - 1)
        elif (
            char == needle
            and brace_depth == 0
            and bracket_depth == 0
            and paren_depth == 0
        ):
            return index
    return None


def _has_top_level_comma(text: str) -> bool:
    return _find_top_level_char(text, ",") is not None


def _has_top_level_paren(text: str) -> bool:
    brace_depth = 0
    bracket_depth = 0
    for char in text:
        if char == "{" and bracket_depth == 0:
            brace_depth += 1
        elif char == "}" and bracket_depth == 0:
            brace_depth = max(0, brace_depth - 1)
        elif char == "[" and brace_depth == 0:
            bracket_depth += 1
        elif char == "]" and brace_depth == 0:
            bracket_depth = max(0, bracket_depth - 1)
        elif char == "(" and brace_depth == 0 and bracket_depth == 0:
            return True
    return False


def _blank_bracket_contents(text: str) -> str:
    chars = list(text)
    depth = 0
    for index, char in enumerate(chars):
        if char == "[":
            depth += 1
            chars[index] = " "
        elif char == "]" and depth > 0:
            chars[index] = " "
            depth -= 1
        elif depth > 0:
            chars[index] = " "
    return "".join(chars)


def _declared_identifier(declaration: str) -> str | None:
    initializer = _find_top_level_char(declaration, "=")
    declarator = declaration if initializer is None else declaration[:initializer]
    declarator = declarator.rstrip().rstrip(";")

    first_token = re.match(r"\s*([A-Za-z_]\w*)\b", declarator)
    if first_token is None or first_token.group(1) != "static":
        return None
    declarator_after_static = declarator[first_token.end(1) :]
    if _has_top_level_paren(declarator_after_static):
        return None

    without_brackets = _blank_bracket_contents(declarator_after_static)
    identifiers = re.findall(r"\b[A-Za-z_]\w*\b", without_brackets)
    if not identifiers:
        return None
    return identifiers[-1]


def _match_static_definition(
    source: str, stripped: str, start: int, end: int, symbol: str
) -> _StaticDefinition | None:
    declaration = stripped[start:end]
    if re.search(rf"\b{re.escape(symbol)}\b", declaration) is None:
        return None
    if _preprocessor_depth_at(source, start) > 0:
        return None
    if _declaration_spans_preprocessor_line(source, start, end):
        return None
    if _has_top_level_comma(declaration):
        return None

    first_token = re.match(r"\s*([A-Za-z_]\w*)\b", declaration)
    if first_token is None or first_token.group(1) != "static":
        return None
    if _declared_identifier(declaration) != symbol:
        return None

    static_start = start + first_token.start(1)
    static_end = start + first_token.end(1)
    while static_end < end and source[static_end] in " \t":
        static_end += 1
    return _StaticDefinition(start, end, static_start, static_end)


def _top_level_static_definition_span(
    source: str, symbol: str
) -> _StaticDefinition | None:
    from .source_patch import _strip_c_comments

    stripped = _strip_c_comments(source)
    candidate_start: int | None = None
    brace_depth = 0
    index = 0
    while index < len(stripped):
        char = stripped[index]
        if brace_depth == 0 and candidate_start is None:
            if char.isspace():
                index += 1
                continue
            if char == "#" and _is_preprocessor_line(stripped, index):
                newline = stripped.find("\n", index)
                if newline == -1:
                    break
                index = newline + 1
                continue
            candidate_start = index

        if char == "{":
            brace_depth += 1
        elif char == "}":
            if brace_depth > 0:
                brace_depth -= 1
            if brace_depth == 0 and candidate_start is not None:
                lookahead = index + 1
                while lookahead < len(stripped) and stripped[lookahead].isspace():
                    lookahead += 1
                if lookahead >= len(stripped) or stripped[lookahead] != ";":
                    candidate_start = None
        elif char == ";" and brace_depth == 0 and candidate_start is not None:
            match = _match_static_definition(
                source, stripped, candidate_start, index + 1, symbol
            )
            if match is not None:
                return match
            candidate_start = None
        index += 1
    return None


def _probe_provenance(relocation: NameMagicRelocation) -> dict[str, Any]:
    return {
        "offset": relocation.offset,
        "kind": relocation.kind,
        "expected_symbol": relocation.expected_symbol,
        "current_symbol": relocation.current_symbol,
    }


def _static_to_global_probe(
    source: str, relocation: NameMagicRelocation, index: int
) -> tuple[NameMagicSourceProbe | None, NameMagicBlocker | None]:
    static_definition = _top_level_static_definition_span(
        source, relocation.expected_symbol
    )
    if static_definition is None:
        return None, NameMagicBlocker.UNSUPPORTED_SOURCE_SITE

    edit = NameMagicSourceEdit(
        static_definition.static_start, static_definition.static_end, ""
    )
    source_text = _apply_source_edits(source, [edit])
    return (
        NameMagicSourceProbe(
            label=f"data-symbol-static-to-global-{index}",
            operator="data-symbol-static-to-global",
            description=f"promote {relocation.expected_symbol} to file-scope global data",
            source_text=source_text,
            edits=(edit,),
            provenance=_probe_provenance(relocation),
        ),
        None,
    )


_FLOAT_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_.])"
    r"(?P<literal>[+-]?(?:(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+))"
    r"(?P<suffix>[fF]?)"
    r"(?![A-Za-z0-9_])"
)
_INT_TO_FLOAT_BIAS_VALUES = {
    0x4330000000000000,
    0x4330000080000000,
}


def _find_simple_literal_sites(
    source: str, start: int, end: int, value: float, size: int
) -> list[tuple[int, int]]:
    from .source_patch import _strip_c_comments

    stripped = _strip_c_comments(source[start:end])
    sites: list[tuple[int, int]] = []
    for match in _FLOAT_LITERAL_RE.finditer(stripped):
        if _line_is_preprocessor_directive(source, start + match.start()):
            continue
        literal = match.group("literal")
        suffix = match.group("suffix")
        if size == 4 and suffix.lower() != "f":
            continue
        if size == 8 and suffix:
            continue
        try:
            parsed = float(literal)
        except ValueError:
            continue
        if parsed != value:
            continue
        sites.append((start + match.start(), start + match.end()))
    return sites


def _line_is_preprocessor_directive(source: str, index: int) -> bool:
    line_start = source.rfind("\n", 0, index) + 1
    return source[line_start:index].lstrip().startswith("#")


def _sdata2_named_float_probe(
    source: str,
    insert_at: int,
    body_start: int,
    body_close: int,
    relocation: NameMagicRelocation,
    anon: dict[str, Any] | None,
    index: int,
) -> tuple[NameMagicSourceProbe | None, NameMagicBlocker | None]:
    if anon is None:
        return None, NameMagicBlocker.AMBIGUOUS_SDATA2_VALUE
    if anon.get("ambiguous") is True:
        return None, NameMagicBlocker.AMBIGUOUS_SDATA2_VALUE

    size = anon.get("size")
    if size == 4 and "float" in anon:
        c_type = "f32"
        value = float(anon["float"])
    elif size == 8:
        if anon.get("bias") is not None or anon.get("value") in _INT_TO_FLOAT_BIAS_VALUES:
            return None, NameMagicBlocker.UNSUPPORTED_RELOC_KIND
        if "double" not in anon:
            return None, NameMagicBlocker.UNSUPPORTED_RELOC_KIND
        c_type = "f64"
        value = float(anon["double"])
    else:
        return None, NameMagicBlocker.UNSUPPORTED_RELOC_KIND

    sites = _find_simple_literal_sites(source, body_start, body_close, value, size)
    if len(sites) != 1:
        return None, NameMagicBlocker.UNSUPPORTED_SOURCE_SITE

    literal_start, literal_end = sites[0]
    edits = (
        NameMagicSourceEdit(literal_start, literal_end, relocation.expected_symbol),
    )
    source_text = _apply_source_edits(source, edits)
    return (
        NameMagicSourceProbe(
            label=f"sdata2-named-float-load-{index}",
            operator="sdata2-named-float-load",
            description=f"replace unique literal with {relocation.expected_symbol}",
            source_text=source_text,
            edits=edits,
            provenance={
                **_probe_provenance(relocation),
                "anonymous_symbol": relocation.current_symbol,
                "size": size,
                "value": value,
            },
            header_declarations=(
                f"extern volatile {c_type} {relocation.expected_symbol};",
            ),
        ),
        None,
    )


def _combined_probe(
    source: str, probes: list[NameMagicSourceProbe]
) -> NameMagicSourceProbe | None:
    edits = tuple(edit for probe in probes for edit in probe.edits)
    header_declarations = tuple(
        dict.fromkeys(
            declaration
            for probe in probes
            for declaration in probe.header_declarations
        )
    )
    try:
        source_text = _apply_source_edits(source, edits)
    except ValueError:
        return None
    return NameMagicSourceProbe(
        label="name-magic-source-combined",
        operator="name-magic-source-combined",
        description="apply all non-overlapping name-magic source declaration edits",
        source_text=source_text,
        edits=edits,
        provenance={"operators": [probe.operator for probe in probes]},
        header_declarations=header_declarations,
    )


def parse_name_magic_relocation_evidence(payload: dict[str, Any]) -> NameMagicEvidence:
    diff = payload.get("diff")
    if not isinstance(diff, list):
        return NameMagicEvidence(
            [],
            0,
            NameMagicBlocker.RAW_DIFF_NO_SUPPORTED_DATA_SYMBOL_PAIR,
            "checkdiff JSON did not include a diff list",
        )

    by_offset: dict[str, dict[str, list[tuple[str, str]]]] = {}
    residual_offsets: set[str] = set()
    for raw_line in diff:
        if not isinstance(raw_line, str):
            continue
        match = _RELOC_DIFF_RE.match(raw_line)
        if match is None:
            diff_offset = _DIFF_OFFSET_RE.match(raw_line)
            if diff_offset is not None:
                residual_offsets.add(diff_offset.group("offset").lower())
            continue
        by_offset.setdefault(match.group("offset").lower(), {"-": [], "+": []})[
            match.group("side")
        ].append((match.group("kind"), match.group("symbol")))

    relocations: list[NameMagicRelocation] = []
    for offset, sides in sorted(by_offset.items()):
        expected = sides["-"]
        current = sides["+"]
        if len(expected) != 1 or len(current) != 1:
            return NameMagicEvidence(
                [],
                len(residual_offsets),
                NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR,
                f"multiple relocation lines at offset {offset}",
            )
        expected_kind, expected_symbol = expected[0]
        current_kind, current_symbol = current[0]
        if expected_kind != current_kind:
            return NameMagicEvidence(
                [],
                len(residual_offsets),
                NameMagicBlocker.UNSUPPORTED_RELOC_KIND,
                f"relocation kind mismatch at offset {offset}",
            )
        if (
            expected_symbol.startswith("@")
            or expected_symbol.startswith("...")
            or expected_symbol.startswith(".")
        ):
            return NameMagicEvidence(
                [],
                len(residual_offsets),
                NameMagicBlocker.UNSUPPORTED_RELOC_KIND,
                f"expected relocation at offset {offset} is not a named symbol",
            )
        if not _supported_current_symbol(current_symbol):
            continue
        if current_symbol.startswith("...data.") and re.search(
            r"[+-](?:0x)?[0-9a-fA-F]+$", current_symbol
        ):
            return NameMagicEvidence(
                [],
                len(residual_offsets),
                NameMagicBlocker.UNSUPPORTED_SECTION_ANCHOR_OFFSET,
                f"section-anchor relocation at offset {offset} needs an offset field path",
            )
        relocations.append(
            NameMagicRelocation(
                offset=offset,
                kind=expected_kind,
                expected_symbol=expected_symbol,
                current_symbol=current_symbol,
            )
        )

    if not relocations:
        return NameMagicEvidence(
            [],
            len(residual_offsets),
            NameMagicBlocker.RAW_DIFF_NO_SUPPORTED_DATA_SYMBOL_PAIR,
            "no same-offset anonymous or section-anchor data relocations found",
        )
    return NameMagicEvidence(relocations, len(residual_offsets))


def generate_name_magic_source_probes(
    source: str,
    function: str,
    checkdiff_payload: dict[str, Any],
    anonymous_sdata2: dict[str, dict[str, Any]],
    *,
    max_probes: int = 12,
) -> tuple[list[NameMagicSourceProbe], NameMagicBlocker | None]:
    from .source_patch import find_function

    evidence = parse_name_magic_relocation_evidence(checkdiff_payload)
    if evidence.blocker is not None:
        return [], evidence.blocker
    function_span = find_function(source, function)
    if function_span is None:
        return [], NameMagicBlocker.UNSUPPORTED_SOURCE_SITE

    probes: list[NameMagicSourceProbe] = []
    blockers: list[NameMagicBlocker] = []
    seen_text: set[str] = set()
    for relocation in evidence.relocations:
        probe = None
        if relocation.current_symbol.startswith("...data."):
            probe, blocker = _static_to_global_probe(source, relocation, len(probes))
        elif relocation.current_symbol.startswith("@"):
            probe, blocker = _sdata2_named_float_probe(
                source,
                function_span.sig_start,
                function_span.body_open + 1,
                function_span.body_close,
                relocation,
                anonymous_sdata2.get(relocation.current_symbol),
                len(probes),
            )
        else:
            blocker = NameMagicBlocker.UNSUPPORTED_RELOC_KIND
        if blocker is not None:
            blockers.append(blocker)
            continue
        if probe is None:
            continue
        if probe.source_text in seen_text:
            continue
        seen_text.add(probe.source_text)
        probes.append(probe)
        if len(probes) >= max_probes:
            break

    if not probes:
        return [], blockers[0] if blockers else NameMagicBlocker.UNSUPPORTED_SOURCE_SITE
    if len(probes) > 1:
        combined = _combined_probe(source, probes)
        if combined is not None and combined.source_text not in seen_text:
            probes.append(combined)
    return probes[:max_probes], None
