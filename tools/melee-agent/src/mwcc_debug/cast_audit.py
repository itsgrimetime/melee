"""Static lint over function-call cast arguments.

Tier 7d — surfaces explicit casts on call-site arguments so the
matching agent can audit them quickly. Optional ASM cross-ref detects
the specific class of mismatch the agent's session findings called out:
source has `(f32) int_var` but the expected ASM doesn't show an int-to-
float conversion sequence (so the cast is spurious).

Detection model:

1. Source parse: find all function calls in the target function. For
   each, extract argument expressions and identify explicit casts.
2. (Optional) ASM parse: for each call site, locate the corresponding
   `bl <fn>` in the unit's .s file. Walk the ~15 instructions before it
   to determine arg-load patterns.
3. Compare: flag casts whose source type disagrees with what the ASM
   loaded.

Both parses are heuristic. For shipping in the MVP we provide the
source-only pass and a flag-on-suspicion heuristic that catches the
`(f32) <name>` pattern. ASM cross-ref is best-effort.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .source_patch import find_function


# ----------------------------------------------------------------------------
# Source parsing
# ----------------------------------------------------------------------------

# Common PowerPC cast prefixes that matter for int/float distinction.
_CAST_RE = re.compile(
    r"\(\s*"
    r"(?P<type>(?:unsigned|signed)?\s*"
    r"(?:char|short|int|long|long\s+long|"
    r"s8|u8|s16|u16|s32|u32|s64|u64|"
    r"f32|f64|float|double|"
    r"void\s*\*|[A-Za-z_]\w*(?:\s*\*+)?))"
    r"\s*\)"
)

_INTEGER_TYPES = {"char", "short", "int", "long", "long long",
                  "s8", "u8", "s16", "u16", "s32", "u32", "s64", "u64",
                  "unsigned char", "unsigned short", "unsigned int",
                  "unsigned long", "signed char", "signed int", "signed long"}

_FLOAT_TYPES = {"f32", "f64", "float", "double"}


@dataclass
class CallSite:
    """One function-call expression with its arguments."""

    call_target: str  # name of the function being called
    line: int  # 1-based line number in the source file
    col: int  # column of the `(` after the call target
    args: list["CallArg"]  # parsed argument expressions


@dataclass
class CallArg:
    """One argument expression at a call site."""

    text: str  # raw text of the argument expression
    cast_type: Optional[str]  # explicit cast type, or None if no cast
    inner_expr: str  # expression after any leading cast
    arg_index: int  # 0-based position in the arg list


@dataclass
class CastWarning:
    """One flagged cast — likely worth auditing."""

    line: int
    call_target: str
    arg_index: int
    cast_type: str
    inner_expr: str
    severity: str  # "high" / "medium" / "low"
    reason: str


def _split_args(args_text: str) -> list[str]:
    """Split a parenthesized argument list at top-level commas.

    Honors nested parens, brackets, braces, string literals, char literals.
    Comments are assumed already stripped.
    """
    parts: list[str] = []
    depth = 0
    bracket = 0
    brace = 0
    i = 0
    last = 0
    n = len(args_text)
    while i < n:
        c = args_text[i]
        if c == '"' or c == "'":
            # Skip string literal
            quote = c
            i += 1
            while i < n and args_text[i] != quote:
                if args_text[i] == "\\" and i + 1 < n:
                    i += 2
                else:
                    i += 1
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "[":
            bracket += 1
        elif c == "]":
            bracket -= 1
        elif c == "{":
            brace += 1
        elif c == "}":
            brace -= 1
        elif c == "," and depth == 0 and bracket == 0 and brace == 0:
            parts.append(args_text[last:i].strip())
            last = i + 1
        i += 1
    if last < n:
        tail = args_text[last:].strip()
        if tail:
            parts.append(tail)
    return parts


def _parse_arg(arg_text: str, arg_index: int) -> CallArg:
    """Identify whether `arg_text` begins with an explicit cast."""
    s = arg_text.strip()
    m = _CAST_RE.match(s)
    if m is None:
        return CallArg(text=arg_text, cast_type=None,
                       inner_expr=s, arg_index=arg_index)
    inner = s[m.end():].strip()
    return CallArg(text=arg_text,
                   cast_type=m.group("type").strip(),
                   inner_expr=inner,
                   arg_index=arg_index)


_CALL_RE = re.compile(r"\b([A-Za-z_][\w]*)\s*\(")


def find_call_sites(function_text: str) -> list[CallSite]:
    """Find function calls in a function body.

    `function_text` is the text from a function's body (everything between
    `{` and `}` inclusive). Returns CallSites in source order.

    Heuristic: matches `<identifier>(`, walks to the matching `)`, then
    splits args. Skips identifiers that look like C keywords (if, while,
    for, sizeof, return, switch).
    """
    from .source_patch import _strip_c_comments

    stripped = _strip_c_comments(function_text)
    keywords = {"if", "while", "for", "switch", "return", "sizeof",
                "do", "else", "case", "default", "break", "continue",
                "goto", "static", "const", "volatile", "inline"}
    sites: list[CallSite] = []
    for m in _CALL_RE.finditer(stripped):
        name = m.group(1)
        if name in keywords:
            continue
        paren_open = m.end() - 1
        # Find matching ')'
        depth = 1
        j = paren_open + 1
        while j < len(stripped) and depth > 0:
            c = stripped[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        if depth != 0:
            continue
        paren_close = j - 1
        args_text = function_text[paren_open + 1 : paren_close]
        arg_strs = _split_args(args_text)
        args = [_parse_arg(a, i) for i, a in enumerate(arg_strs)
                if a]

        # Compute line/col of the call
        prefix = function_text[: m.start()]
        line = prefix.count("\n") + 1
        last_nl = prefix.rfind("\n")
        col = (m.start() - last_nl) if last_nl >= 0 else m.start() + 1
        sites.append(CallSite(call_target=name, line=line, col=col, args=args))
    return sites


# ----------------------------------------------------------------------------
# Cast warning heuristics
# ----------------------------------------------------------------------------

# Identifiers whose name suggests an integer type. Conservative — only
# matches names with clear integer signals (typed prefix, integer suffix,
# or single-letter loop counters). Just `value` or `result` does NOT match.
_INT_PREFIX_RE = re.compile(r"^(?:[ius]\d+|u8|s8|u16|s16|u32|s32|u64|s64)_")
_INT_SUFFIX_RE = re.compile(
    r"_(idx|index|offset|count|size|len|length|flag|flags|id|num|n|i)"
    r"\d*$"
)
_LOOP_COUNTER_NAMES = {"i", "j", "k", "n", "m", "x", "y", "z",
                       "ii", "jj", "kk", "iter"}


def _looks_integer(expr: str) -> bool:
    """Heuristic: does this expression look integer-typed?

    Returns True for:
      - integer literals (e.g. 0, -1, 0xFF)
      - identifiers with explicit integer prefix/suffix or known loop-
        counter names. CONSERVATIVE — generic names like "value" or
        "result" do NOT match (we'd rather miss a few than false-flag).
      - bitwise/shift expressions
    """
    expr = expr.strip()
    # Integer literal (decimal or hex, with optional suffixes)
    if re.match(r"^-?\d+[uUlL]*$", expr):
        return True
    if re.match(r"^-?0[xX][0-9a-fA-F]+[uUlL]*$", expr):
        return True
    # Float literal — definitely not integer
    if re.match(r"^-?\d+\.\d*[fFlL]?$", expr):
        return False
    if re.match(r"^-?\.\d+[fFlL]?$", expr):
        return False
    # Identifier?
    if re.match(r"^[A-Za-z_]\w*$", expr):
        low = expr.lower()
        if low in _LOOP_COUNTER_NAMES:
            return True
        if _INT_PREFIX_RE.match(low):
            return True
        if _INT_SUFFIX_RE.search(low):
            return True
        return False
    # Bitwise/shift expressions are integer
    if re.search(r"(>>|<<|&|\||\^)\s*\w", expr):
        return True
    return False


def _extract_local_types(function_text: str) -> dict[str, str]:
    """Walk the function's local declaration block and parameter list,
    returning a {name: declared_type_string} map.

    Handles simple cases: `<type> <name>;`, `<type> <name>, <name>;`,
    and the parameters in the function signature. Type strings are
    normalized to single-space.
    """
    types: dict[str, str] = {}

    # Parameters: pull out everything in the function's `(...)`. Quick
    # and dirty.
    sig_match = re.search(r"\(([^)]*)\)", function_text)
    if sig_match:
        params = sig_match.group(1)
        for p in _split_args(params):
            p = p.strip()
            if not p or p == "void":
                continue
            m = re.match(r"^(.+?)\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$", p)
            if m:
                types[m.group(2)] = " ".join(m.group(1).split())

    # Locals: scan lines for decl-shaped patterns until the first non-
    # decl line.
    open_idx = function_text.find("{")
    if open_idx >= 0:
        body = function_text[open_idx + 1:]
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("//") or line.startswith("/*"):
                continue
            # Match: <type> <name>(, <name>)*;
            m = re.match(
                r"^((?:static\s+|extern\s+|const\s+|volatile\s+|register\s+|"
                r"inline\s+|auto\s+)*[A-Za-z_][\w\s\*]*?)\s+"
                r"([A-Za-z_]\w*(?:\s*\[[^\]]*\])?"
                r"(?:\s*=\s*[^,;]+)?"
                r"(?:\s*,\s*[A-Za-z_]\w*(?:\s*\[[^\]]*\])?(?:\s*=\s*[^,;]+)?)*)"
                r"\s*;\s*$",
                line,
            )
            if not m:
                break  # first non-decl line ends the block
            base_type = " ".join(m.group(1).split())
            for entry in m.group(2).split(","):
                ent = entry.strip()
                # Strip array dims + initializer
                ent = re.sub(r"\s*=\s*[^,;]+$", "", ent).strip()
                ent = re.sub(r"\s*\[[^\]]*\]", "", ent).strip()
                # Strip leading pointer asterisks (they're part of the type
                # in a strict reading, but for our purposes name only)
                while ent.startswith("*"):
                    ent = ent[1:].strip()
                if ent and re.match(r"^[A-Za-z_]\w*$", ent):
                    types[ent] = base_type
    return types


def _is_integer_type(type_str: str) -> bool:
    """Conservative check: does `type_str` denote an integer-typed value?"""
    t = type_str.strip()
    # Strip pointer asterisks and leading qualifiers
    t = re.sub(r"^(?:static|extern|const|volatile|register|inline|auto)\s+", "", t)
    t = t.replace("*", "").strip()
    return t in _INTEGER_TYPES


def _is_float_type(type_str: str) -> bool:
    t = type_str.strip()
    t = re.sub(r"^(?:static|extern|const|volatile|register|inline|auto)\s+", "", t)
    t = t.replace("*", "").strip()
    return t in _FLOAT_TYPES


def audit_function_casts(
    file_text: str,
    function: str,
) -> list[CastWarning]:
    """Find all explicit casts in the function's call arguments and flag
    suspicious patterns.

    Three-tier classification:
      HIGH: (f32)/(f64) cast on a value the function declares as integer-
        typed (param or local). Very likely the agent's `drop-variadic-
        cast` pattern.
      MEDIUM: (f32)/(f64) cast on an expression that LOOKS integer (by
        name heuristic, literal, or bitwise op) but we can't prove the
        type from local context. Worth a manual audit.
      LOW: Any other explicit cast. Surfaced so the agent can scan all
        casts at once.
    """
    span = find_function(file_text, function)
    if span is None:
        return []
    fn_text = file_text[span.sig_start : span.full_end]
    sites = find_call_sites(fn_text)
    local_types = _extract_local_types(fn_text)
    warnings: list[CastWarning] = []
    sig_line_offset = file_text[: span.sig_start].count("\n")
    for site in sites:
        for arg in site.args:
            if arg.cast_type is None:
                continue
            cast = arg.cast_type
            inner = arg.inner_expr.strip()

            # Tier 1 (HIGH): can prove from local context that the value
            # is integer-typed when cast to float.
            if cast in _FLOAT_TYPES and inner in local_types and \
                    _is_integer_type(local_types[inner]):
                warnings.append(CastWarning(
                    line=sig_line_offset + site.line,
                    call_target=site.call_target,
                    arg_index=arg.arg_index,
                    cast_type=cast,
                    inner_expr=arg.inner_expr,
                    severity="high",
                    reason=(
                        f"`({cast}) {inner}` casts {inner} (declared "
                        f"`{local_types[inner]}`) to float. If the "
                        f"expected ASM passes this as an integer (no "
                        f"int-to-float conversion), drop the cast — "
                        f"see pattern `drop-variadic-cast`."
                    ),
                ))
                continue

            # Tier 2 (MEDIUM): heuristic suggests integer but can't prove.
            if cast in _FLOAT_TYPES and _looks_integer(inner):
                warnings.append(CastWarning(
                    line=sig_line_offset + site.line,
                    call_target=site.call_target,
                    arg_index=arg.arg_index,
                    cast_type=cast,
                    inner_expr=arg.inner_expr,
                    severity="medium",
                    reason=(
                        f"`({cast}) {inner}` casts what looks like an "
                        f"integer expression to float. Couldn't prove "
                        f"from local context. Audit against expected "
                        f"ASM for int-to-float conversion."
                    ),
                ))
                continue

            # Tier 3 (LOW): generic cast — worth surfacing.
            warnings.append(CastWarning(
                line=sig_line_offset + site.line,
                call_target=site.call_target,
                arg_index=arg.arg_index,
                cast_type=cast,
                inner_expr=arg.inner_expr,
                severity="low",
                reason=(
                    f"Explicit cast `({cast})` on argument {arg.arg_index} "
                    f"of `{site.call_target}`. Audit against expected ASM."
                ),
            ))
    return warnings


# ----------------------------------------------------------------------------
# Optional ASM cross-ref
# ----------------------------------------------------------------------------

# Instructions that load a float into the FP-arg registers (f1..f8).
_FLOAT_ARG_LOAD_RE = re.compile(r"\b(lfs|lfd|fmr|fneg|fabs|fadds?|fsubs?|fmuls?|fdivs?|fmadds?|fmsubs?|fres|frsqrte|frsp)\s+(f[1-8])\b")

# Magic-constant load patterns characteristic of int-to-float conversion
# on Broadway/gekko (uses sdata2 magic constants).
_INT_TO_FLOAT_RE = re.compile(r"\b(lfd)\s+f\d+,\s*[^@]+@sda21\(r2\)|xoris|stfd")


def asm_arg_register_kinds_before_call(
    asm_lines: list[str],
    bl_line_idx: int,
    window: int = 18,
) -> dict[str, str]:
    """For a `bl` at `asm_lines[bl_line_idx]`, walk backward up to `window`
    instructions and classify which arg registers were loaded with what.

    Returns a dict mapping register name → kind:
      "int" — loaded via li/lwz/addi/mr-from-int
      "float" — loaded via lfs/lfd/fmr/fp-arith
      "unknown" — couldn't determine

    Best-effort. Only useful for the immediately-prior load sequence.
    """
    kinds: dict[str, str] = {}
    for i in range(bl_line_idx - 1, max(-1, bl_line_idx - window - 1), -1):
        line = asm_lines[i]
        # Stop at the previous bl — args don't survive a call
        if " bl " in line or "\tbl\t" in line:
            break
        # Float-class destination?
        mf = re.search(r"\b(lfs|lfd|fmr|fneg|fabs)\s+(f[1-8])\b", line)
        if mf:
            reg = mf.group(2)
            kinds.setdefault(reg, "float")
            continue
        # Int-class destination into r3..r10?
        mi = re.search(r"\b(li|lwz|addi|mr|lbz|lhz|lha|lis|lwzu|or|and|xor|"
                       r"rlwinm|slwi|srwi)\s+(r([3-9]|10))\b", line)
        if mi:
            reg = mi.group(2)
            kinds.setdefault(reg, "int")
            continue
    return kinds


@dataclass
class CallContext:
    """Source call-site + asm context for cross-ref."""

    source_site: CallSite
    asm_line_idx: Optional[int]
    arg_register_kinds: dict[str, str]


def crossref_with_asm(
    sites: list[CallSite],
    asm_path: Path,
    enclosing_function: str,
) -> list[CallContext]:
    """For each source CallSite, find the corresponding `bl <target>` in
    asm_path within the section for `enclosing_function`, and extract
    arg-register kinds from the preceding instructions.

    Returns one CallContext per site (asm_line_idx=None if not found).
    """
    if not asm_path.exists():
        return [CallContext(source_site=s, asm_line_idx=None,
                            arg_register_kinds={}) for s in sites]
    lines = asm_path.read_text().splitlines()
    # Locate the function section
    fn_start = -1
    fn_end = len(lines)
    for i, ln in enumerate(lines):
        if ln.startswith(".fn ") and enclosing_function in ln:
            fn_start = i
        elif fn_start >= 0 and ln.startswith(".endfn"):
            fn_end = i
            break
    if fn_start < 0:
        return [CallContext(source_site=s, asm_line_idx=None,
                            arg_register_kinds={}) for s in sites]
    # Collect bl call sequences in this function in order.
    bl_calls: list[tuple[int, str]] = []  # (line_idx, target)
    for i in range(fn_start, fn_end):
        m = re.search(r"\bbl\s+([A-Za-z_]\w*)", lines[i])
        if m:
            bl_calls.append((i, m.group(1)))
    # Match source sites to bls positionally — same call target, in order.
    contexts: list[CallContext] = []
    used = set()
    for site in sites:
        match_idx = None
        for j, (line_idx, target) in enumerate(bl_calls):
            if j in used:
                continue
            if target == site.call_target:
                match_idx = line_idx
                used.add(j)
                break
        if match_idx is None:
            contexts.append(CallContext(source_site=site, asm_line_idx=None,
                                        arg_register_kinds={}))
            continue
        kinds = asm_arg_register_kinds_before_call(lines, match_idx)
        contexts.append(CallContext(source_site=site, asm_line_idx=match_idx,
                                    arg_register_kinds=kinds))
    return contexts
