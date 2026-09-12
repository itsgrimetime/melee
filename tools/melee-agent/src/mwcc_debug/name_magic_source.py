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
    BSS_ANCHOR_CEILING = "bss-anchor-ceiling"
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
        if self.current_symbol.startswith("...bss."):
            return "bss-anchor-ceiling"
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


@dataclasses.dataclass(frozen=True)
class _NamedDefinition:
    decl_start: int
    decl_end: int


_RELOC_DIFF_RE = re.compile(
    r"^(?P<side>[-+])\+(?P<offset>[0-9a-fA-F]+):\s+"
    r"(?P<kind>R_PPC_[A-Za-z0-9_]+)\t(?P<symbol>\S+)"
)
_DIFF_OFFSET_RE = re.compile(r"^[+-]\+(?P<offset>[0-9a-fA-F]+):")
_DEFAULT_MAX_RETAINED_AMBIGUOUS_RELOCATIONS = 12


def _supported_current_symbol(symbol: str) -> bool:
    return (
        symbol.startswith("@")
        or symbol.startswith("...data.")
        or symbol.startswith("...bss.")
    )


def _is_named_source_symbol(symbol: str) -> bool:
    return re.fullmatch(r"[A-Za-z_]\w*", symbol) is not None


def _is_section_anchor_offset_expression(symbol: str) -> bool:
    return symbol.startswith(("...data.", "...bss.")) and re.search(
        r"[+-](?:0x)?[0-9a-fA-F]+$", symbol
    ) is not None


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


def _matching_brace_index(text: str, open_index: int) -> int | None:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


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


def _declared_identifier_with_optional_static(declaration: str) -> str | None:
    initializer = _find_top_level_char(declaration, "=")
    declarator = declaration if initializer is None else declaration[:initializer]
    declarator = declarator.rstrip().rstrip(";").strip()

    if _has_top_level_paren(declarator):
        return None

    static_match = re.match(r"static\b", declarator)
    if static_match is not None:
        declarator = declarator[static_match.end() :].lstrip()
    if re.match(r"typedef\b", declarator):
        return None

    tag_match = re.match(r"(?:struct|union|enum)\b", declarator)
    if tag_match is not None:
        brace_open = declarator.find("{", tag_match.end())
        if brace_open != -1:
            brace_close = _matching_brace_index(declarator, brace_open)
            if brace_close is None:
                return None
            declarator = declarator[brace_close + 1 :].strip()
        else:
            tag_name = re.match(r"\s*[A-Za-z_]\w*\b", declarator[tag_match.end() :])
            if tag_name is None:
                return None
            declarator = declarator[tag_match.end() + tag_name.end() :].strip()
        if not declarator:
            return None

    without_brackets = _blank_bracket_contents(declarator)
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


def _match_named_definition(
    source: str, stripped: str, start: int, end: int, symbol: str
) -> _NamedDefinition | None:
    declaration = stripped[start:end]
    if re.search(rf"\b{re.escape(symbol)}\b", declaration) is None:
        return None
    if _preprocessor_depth_at(source, start) > 0:
        return None
    if _declaration_spans_preprocessor_line(source, start, end):
        return None
    if _has_top_level_comma(declaration):
        return None
    if _declared_identifier_with_optional_static(declaration) != symbol:
        return None
    return _NamedDefinition(start, end)


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


def _top_level_named_definition_span(source: str, symbol: str) -> _NamedDefinition | None:
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
            match = _match_named_definition(
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


def _bss_anchor_source_binding_probe(
    source: str, relocation: NameMagicRelocation, index: int
) -> tuple[NameMagicSourceProbe | None, NameMagicBlocker | None]:
    declaration = _top_level_named_definition_span(source, relocation.expected_symbol)
    if declaration is None:
        return None, NameMagicBlocker.UNSUPPORTED_SOURCE_SITE

    return (
        NameMagicSourceProbe(
            label=f"bss-anchor-source-binding-{index}",
            operator="bss-anchor-source-binding",
            description=(
                f"bind {relocation.current_symbol} to "
                f"{relocation.expected_symbol} source declaration"
            ),
            source_text=source,
            edits=(),
            provenance={
                **_probe_provenance(relocation),
                "declaration_start": declaration.decl_start,
                "declaration_end": declaration.decl_end,
            },
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


def _compatible_name_magic_relocations(
    offset: str,
    expected: list[tuple[str, str]],
    current: list[tuple[str, str]],
    *,
    limit: int,
) -> list[NameMagicRelocation]:
    relocations: list[NameMagicRelocation] = []
    seen: set[tuple[str, str, str, str]] = set()
    if limit <= 0:
        return relocations

    for expected_kind, expected_symbol in expected:
        if not _is_named_source_symbol(expected_symbol):
            continue
        for current_kind, current_symbol in current:
            if expected_kind != current_kind:
                continue
            if _is_section_anchor_offset_expression(current_symbol):
                continue
            if not _supported_current_symbol(current_symbol):
                continue
            key = (offset, expected_kind, expected_symbol, current_symbol)
            if key in seen:
                continue
            seen.add(key)
            relocations.append(
                NameMagicRelocation(
                    offset=offset,
                    kind=expected_kind,
                    expected_symbol=expected_symbol,
                    current_symbol=current_symbol,
                )
            )
            if len(relocations) >= limit:
                return relocations
    return relocations


def parse_name_magic_relocation_evidence(
    payload: dict[str, Any],
    *,
    max_ambiguous_relocations: int = _DEFAULT_MAX_RETAINED_AMBIGUOUS_RELOCATIONS,
) -> NameMagicEvidence:
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
        offset = match.group("offset").lower()
        if offset not in by_offset:
            by_offset[offset] = {"-": [], "+": []}
        by_offset[offset][match.group("side")].append(
            (match.group("kind"), match.group("symbol"))
        )

    relocations: list[NameMagicRelocation] = []
    ambiguous_reason: str | None = None
    hard_blocker: tuple[NameMagicBlocker, str] | None = None
    retained_ambiguous = 0
    for offset in sorted(by_offset):
        sides = by_offset[offset]
        expected = sides["-"]
        current = sides["+"]
        if len(expected) != 1 or len(current) != 1:
            remaining = max_ambiguous_relocations - retained_ambiguous
            compatible = _compatible_name_magic_relocations(
                offset,
                expected,
                current,
                limit=remaining,
            )
            relocations.extend(compatible)
            retained_ambiguous += len(compatible)
            if ambiguous_reason is None:
                ambiguous_reason = f"multiple relocation lines at offset {offset}"
            continue
        expected_kind, expected_symbol = expected[0]
        current_kind, current_symbol = current[0]
        if expected_kind != current_kind:
            if hard_blocker is None:
                hard_blocker = (
                    NameMagicBlocker.UNSUPPORTED_RELOC_KIND,
                    f"relocation kind mismatch at offset {offset}",
                )
            continue
        if not _is_named_source_symbol(expected_symbol):
            if hard_blocker is None:
                hard_blocker = (
                    NameMagicBlocker.UNSUPPORTED_RELOC_KIND,
                    f"expected relocation at offset {offset} is not a named symbol",
                )
            continue
        if _is_section_anchor_offset_expression(current_symbol):
            if hard_blocker is None:
                hard_blocker = (
                    NameMagicBlocker.UNSUPPORTED_SECTION_ANCHOR_OFFSET,
                    (
                        "section-anchor relocation at offset "
                        f"{offset} needs an offset field path"
                    ),
                )
            continue
        if not _supported_current_symbol(current_symbol):
            continue
        relocations.append(
            NameMagicRelocation(
                offset=offset,
                kind=expected_kind,
                expected_symbol=expected_symbol,
                current_symbol=current_symbol,
            )
        )

    if ambiguous_reason is not None:
        if not relocations:
            return NameMagicEvidence(
                [],
                len(residual_offsets),
                NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR,
                ambiguous_reason,
            )
        return NameMagicEvidence(
            relocations,
            len(residual_offsets),
            NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR,
            ambiguous_reason,
        )
    if not relocations:
        if hard_blocker is not None:
            blocker, reason = hard_blocker
            return NameMagicEvidence([], len(residual_offsets), blocker, reason)
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

    evidence = parse_name_magic_relocation_evidence(
        checkdiff_payload,
        max_ambiguous_relocations=max_probes,
    )
    if evidence.blocker is not None:
        if (
            evidence.blocker != NameMagicBlocker.AMBIGUOUS_RELOCATION_PAIR
            or not evidence.relocations
        ):
            return [], evidence.blocker
    function_span = find_function(source, function)
    if function_span is None:
        return [], NameMagicBlocker.UNSUPPORTED_SOURCE_SITE

    probes: list[NameMagicSourceProbe] = []
    blockers: list[NameMagicBlocker] = []
    seen_text: set[str] = set()
    seen_probe_keys: set[tuple[Any, ...]] = set()
    for relocation in evidence.relocations:
        probe = None
        blocker = None
        if relocation.current_symbol.startswith("...data."):
            probe, blocker = _static_to_global_probe(source, relocation, len(probes))
        elif relocation.current_symbol.startswith("...bss."):
            probe, blocker = _bss_anchor_source_binding_probe(
                source, relocation, len(probes)
            )
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
        if probe.operator == "bss-anchor-source-binding":
            probe_key = (
                probe.operator,
                probe.provenance["offset"],
                probe.provenance["kind"],
                probe.provenance["expected_symbol"],
                probe.provenance["current_symbol"],
                probe.provenance["declaration_start"],
                probe.provenance["declaration_end"],
            )
        else:
            probe_key = ("source", probe.source_text)
        if probe_key in seen_probe_keys:
            continue
        seen_probe_keys.add(probe_key)
        if probe.edits:
            seen_text.add(probe.source_text)
        probes.append(probe)
        if len(probes) >= max_probes:
            break

    if not probes:
        return [], blockers[0] if blockers else NameMagicBlocker.UNSUPPORTED_SOURCE_SITE
    if len(probes) > 1 and any(probe.edits for probe in probes):
        combined = _combined_probe(source, probes)
        if combined is not None and combined.source_text not in seen_text:
            probes.append(combined)
    return probes[:max_probes], None
