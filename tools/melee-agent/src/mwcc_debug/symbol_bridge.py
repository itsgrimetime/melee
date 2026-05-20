"""Source variable ↔ MWCC virtual register bridge.

Uses the same brace-tokenizer pattern as `source_patch.py` (proven on
real Melee TUs full of HSD_ASSERT, PAD_STACK, statement-expression
macros). Does NOT use pycparser. The trade-off: v1 only recognizes
simple top-of-body local declarations; nested-block decls are skipped
(documented limitation).

The bridge's accuracy is "good enough to bias seed selection," not
"exact." Callers see a `confidence` label and can invoke the
self-verification step in the orchestrator when committing to a seed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class LocalDecl:
    """One local variable declaration extracted from a function body."""
    name: str          # variable name
    type_str: str      # canonical type as written in source (e.g., "HSD_JObj*")
    decl_index: int    # 0-indexed position in source order


# Matches the type-prefix portion of a declaration:
#   <type-tokens> <first-name>
# We capture the FIRST declarator's name here so we know where the
# type ends. The rest of the statement (additional declarators,
# initializers, array dimensions) is parsed by the state machine
# inside `walk_local_decls`.
#
# The type+name boundary requires a real separator (`*` or whitespace)
# so we don't greedily consume the first character of the variable
# name into the trailing type-token (e.g. `MnEventData* data` must
# split as type=`MnEventData*`, name=`data`).
#
# The trailing lookahead `(?=\[|=|,|;|$)` distinguishes a declaration
# from a function call/prototype like `int foo()`: after the name
# we must see an array `[`, initializer `=`, declarator-separator `,`,
# statement-terminator `;`, or end-of-string.
_DECL_HEAD_RE = re.compile(
    r"""
    ^\s*
    (?P<type>
        (?:const\s+|volatile\s+|static\s+)*    # qualifiers (rare)
        [A-Za-z_][A-Za-z_0-9]*                 # base type identifier
        (?:\s*\*+\s*|\s+[A-Za-z_][A-Za-z_0-9]*)*  # ptrs OR space-separated tokens
        (?:\s*\*+\s*|\s+)                      # REQUIRED separator before name
    )
    (?P<name>[A-Za-z_][A-Za-z_0-9]*)
    \s*
    (?=\[|=|,|;|$)                             # lookahead: must be followed by
                                               # `[` (array dim), `=` (init),
                                               # `,` (next declarator), `;`, or end.
                                               # Lookahead, so cursor stays after name.
    """,
    re.VERBOSE,
)

# Matches just the bare name of a continuation declarator. The
# caller positions the cursor right after the `,` separator and
# whitespace; we just need to confirm there's an identifier here.
# Array brackets and initializers are skipped by the caller's
# state machine.
_DECLARATOR_NAME_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z_0-9]*)",
)

# C keywords that LOOK like type identifiers but introduce control flow
# or other statements. If the first token of a statement is one of these,
# the statement is NOT a declaration.
_NON_DECL_LEADERS = {
    "if", "else", "for", "while", "do", "switch", "case", "default",
    "return", "break", "continue", "goto",
}


def _strip_strings_and_comments(text: str) -> str:
    """Replace string-literal and comment content with same-length
    whitespace so brace/semicolon tokenization isn't fooled by them.
    Newlines preserved so line numbers stay aligned.
    """
    out = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == '"' or c == "'":
            quote = c
            out.append(c)
            i += 1
            while i < len(text) and text[i] != quote:
                if text[i] == "\\" and i + 1 < len(text):
                    out.append(" ")  # don't expose `\\` quirks
                    out.append(" ")
                    i += 2
                    continue
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < len(text):
                out.append(text[i])
                i += 1
            continue
        if c == "/" and i + 1 < len(text) and text[i + 1] == "/":
            while i < len(text) and text[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < len(text) and text[i + 1] == "*":
            while i + 1 < len(text) and not (
                text[i] == "*" and text[i + 1] == "/"
            ):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i + 1 < len(text):
                out.append(" ")
                out.append(" ")
                i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _top_level_statements(body: str) -> list[str]:
    """Split a function body (the `{...}` block) into top-level statements
    by tracking brace + paren depth. Strings/comments stripped first.
    Returns each statement WITHOUT the trailing semicolon, in source
    order. Nested-block contents are returned as a single statement-
    sized chunk (we DON'T descend into them in v1).
    """
    # Trim outer braces if present
    stripped = _strip_strings_and_comments(body).strip()
    if stripped.startswith("{"):
        stripped = stripped[1:]
    if stripped.endswith("}"):
        stripped = stripped[:-1]

    stmts: list[str] = []
    buf: list[str] = []
    depth_brace = 0
    depth_paren = 0
    for c in stripped:
        # Track depth changes
        if c == "{":
            depth_brace += 1
            buf.append(c)
            continue
        if c == "}":
            depth_brace -= 1
            buf.append(c)
            # Closing a top-level nested block ends the surrounding
            # statement (e.g. `if (...) { ... } int z;` should split
            # into `if (...) { ... }` and `int z`). Otherwise the trailing
            # decl would never get its own statement chunk.
            if depth_brace == 0 and depth_paren == 0:
                stmts.append("".join(buf).strip())
                buf = []
            continue
        if c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        if c == ";" and depth_brace == 0 and depth_paren == 0:
            stmts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(c)
    remainder = "".join(buf).strip()
    if remainder:
        stmts.append(remainder)
    return stmts


def _skip_initializer(stmt: str, start: int) -> int:
    """Starting at `start` (just past an `=` sign), skip past the
    initializer expression and return the index of the next top-level
    `,`, `;`, or end-of-string.

    Tracks paren/brace/bracket depth so commas inside `f(a, b)` or
    `{1, 2, 3}` aren't treated as declarator separators.
    """
    i = start
    depth = 0
    while i < len(stmt):
        c = stmt[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and (c == "," or c == ";"):
            return i
        i += 1
    return i


def _looks_like_decl(stmt: str) -> bool:
    """Heuristic: does this statement LOOK like a declaration even
    though `_DECL_HEAD_RE` didn't match it?

    True if it starts with an identifier (i.e. could be a type) that
    isn't a control-flow keyword. The existing caller already filters
    out control-flow leaders, so by the time this is called we only
    need to confirm there's substance to flag.

    The point is to surface things like `void (*cb)(int);` (function
    pointers) or other unrecognized decl shapes so callers can detect
    silent failures of the parser.
    """
    stmt = stmt.strip()
    if not stmt:
        return False
    # Must start with an identifier
    if not re.match(r"^[A-Za-z_]", stmt):
        return False
    # Bare expression statements like `x = 5` or `foo()` shouldn't
    # be flagged. Use a coarse check: if the first non-identifier
    # character is `=`, `(`, `.`, `-`, `+`, `[` (etc.), it's most
    # likely an expression statement, not a decl.
    #
    # Decl-looking statements have at least TWO identifiers separated
    # by whitespace or `*` (the type and the name) OR contain `(*`
    # (function-pointer syntax) before any `=`.
    if "(*" in stmt.split("=")[0]:
        return True
    # Look for `<ident><sep><ident>` where sep is whitespace or `*`
    if re.match(
        r"^[A-Za-z_][A-Za-z_0-9]*\s*(?:\*+\s*|\s+)[A-Za-z_]",
        stmt,
    ):
        return True
    return False


def walk_local_decls(
    body: str,
    on_unrecognized: Optional[Callable[[str], None]] = None,
) -> list[LocalDecl]:
    """Walk a function body, return one LocalDecl per top-level local
    variable declaration in source order.

    `body` may include or omit the outer braces.

    Multi-declarators (`int x, y, z;`) and array decls (`int arr[10];`)
    are recognized. Function-pointer decls (`void (*cb)(int);`) and
    other shapes the parser doesn't yet model are NOT silently dropped:
    if `on_unrecognized` is provided, it's called with the raw
    statement text for each such case. Callers can use this to detect
    silent failures of the parser (e.g. Task 3's calibration gate).
    """
    out: list[LocalDecl] = []
    idx = 0
    for stmt in _top_level_statements(body):
        # Skip control-flow leaders
        first_token_m = re.match(r"^\s*([A-Za-z_][A-Za-z_0-9]*)", stmt)
        if first_token_m and first_token_m.group(1) in _NON_DECL_LEADERS:
            continue
        m = _DECL_HEAD_RE.match(stmt)
        if not m:
            # Decl-looking but unparseable -> flag for caller.
            if on_unrecognized is not None and _looks_like_decl(stmt):
                on_unrecognized(stmt.strip())
            continue
        # Compact whitespace in the type
        type_str = re.sub(r"\s+", " ", m.group("type")).strip()
        # Move trailing pointer asterisks adjacent to type (canonical
        # "HSD_JObj*" rather than "HSD_JObj *")
        type_str = re.sub(r"\s*\*\s*", "*", type_str)

        # Emit first declarator
        out.append(LocalDecl(
            name=m.group("name"),
            type_str=type_str,
            decl_index=idx,
        ))
        idx += 1

        # Walk remainder for additional declarators (multi-declarator
        # form `int x, y, z;` or `int a = 1, b = 2;`).
        #
        # State machine: at each step the cursor `i` is positioned at
        # either an array-bracket, `=`, `,`, `;`, or end-of-statement.
        # - `[`: skip brackets (array dim on current declarator)
        # - `=`: skip initializer to next top-level `,` or `;`
        # - `,`: consume one new declarator (its name becomes a LocalDecl)
        # - `;` or end: done
        i = _skip_array_brackets(stmt, m.end())
        while i < len(stmt):
            while i < len(stmt) and stmt[i].isspace():
                i += 1
            if i >= len(stmt):
                break
            c = stmt[i]
            if c == ";":
                break
            if c == "[":
                i = _skip_array_brackets(stmt, i)
                continue
            if c == "=":
                i = _skip_initializer(stmt, i + 1)
                continue
            if c == ",":
                i += 1
                sub_m = _DECLARATOR_NAME_RE.match(stmt[i:])
                if not sub_m:
                    # Unrecognized continuation — flag and stop.
                    if on_unrecognized is not None:
                        on_unrecognized(stmt.strip())
                    break
                out.append(LocalDecl(
                    name=sub_m.group("name"),
                    type_str=type_str,
                    decl_index=idx,
                ))
                idx += 1
                i += sub_m.end()
                continue
            # Unexpected char in decl tail — bail.
            break
    return out


def _skip_array_brackets(s: str, start: int) -> int:
    """Skip optional `[...]` array brackets starting at `start`,
    handling nested brackets. Returns the position after the last
    closing bracket (or `start` if none present).
    """
    i = start
    while i < len(s) and s[i].isspace():
        i += 1
    while i < len(s) and s[i] == "[":
        depth = 1
        i += 1
        while i < len(s) and depth > 0:
            if s[i] == "[":
                depth += 1
            elif s[i] == "]":
                depth -= 1
            i += 1
        while i < len(s) and s[i].isspace():
            i += 1
    return i


@dataclass
class Binding:
    """A source variable bound to its predicted MWCC virtual register."""
    var_name: str
    virtual: int           # -1 if unmapped
    decl_line: int         # 1-indexed line in original source
    kind: str              # "local" | "param"
    type_str: str
    confidence: str        # "best-guess" | "verified" | "low-confidence"
                           # | "rejected" | "ambiguous" | "unsupported"
                           # NOTE: "low-confidence" is a recent addition —
                           # surfaces when the cursor heuristic LOOKS like
                           # it matched but red flags suggest the mapping
                           # may be off. tier3-search skips these by
                           # default; CLI --include-low-confidence opts in.


@dataclass
class BindingBasis:
    """Evidence + red-flag set for an entire function's bindings.

    Returned alongside the Binding list by `list_bindings_with_basis`.
    Lets callers explain WHY each binding got its confidence label,
    and lets `var-to-virtual --basis` surface the heuristic's inputs.
    """
    parsed_params: list[LocalDecl]
    parsed_locals: list[LocalDecl]
    observed_virtuals: list[int]      # destinations seen in pre-pass, ≥32, in order
    unrecognized_decls: list[str]     # decl-shaped statements the parser couldn't handle
    red_flags: list[str]              # human-readable concerns


def _collect_basis(
    body_text: str,
    params_text: str,
    pre_pass,
) -> tuple[list[LocalDecl], list[LocalDecl], list[int], list[str], list[str]]:
    """Collect the raw inputs used by `list_bindings`'s heuristic.

    Returns (params, locals, observed_virtuals, unrecognized_decls,
    red_flags). The red_flags list contains string descriptions of
    conditions that should lower the caller's trust in the cursor
    model:

      - "nested-decl"          : body contains nested-block decls the
                                 parser doesn't descend into (cursor
                                 model may be wrong beyond the first
                                 nested block)
      - "unrecognized-decl"    : a statement LOOKED like a decl but
                                 couldn't be parsed (function pointers,
                                 macros, etc.); raises by 1+
      - "static-local"         : function contains 'static' locals,
                                 which don't get virtuals
      - "extra-virtuals"       : pre-pass shows substantially more
                                 destination virtuals (≥+3) than parsed
                                 locals — compiler likely added temp
                                 virtuals (CSE, induction var) that
                                 shift the cursor
    """
    unrecognized: list[str] = []
    locals_ = walk_local_decls(body_text, on_unrecognized=unrecognized.append)
    params = _parse_params(params_text)
    virtuals = _collect_virtual_destinations(pre_pass)

    red_flags: list[str] = []
    if unrecognized:
        red_flags.append("unrecognized-decl")

    # Nested-block decl detection: look for `{` chars not part of init
    # braces. A coarse heuristic — any `{` that follows a `)` (i.e.
    # `if (...) {`, `for (...) {`, `while (...) {`) indicates a nested
    # scope where MWCC may declare additional virtuals we don't see.
    stripped = _strip_strings_and_comments(body_text)
    if re.search(r"\)\s*\{", stripped):
        red_flags.append("nested-decl")

    # Static-local detection.
    if re.search(r"\bstatic\s+[A-Za-z_]", stripped):
        red_flags.append("static-local")

    # Compiler-introduced virtuals overshoot.
    if len(virtuals) >= len(params) + len(locals_) + 3:
        red_flags.append("extra-virtuals")

    return params, locals_, virtuals, unrecognized, red_flags


_FN_HEADER_RE = re.compile(
    r"""
    (?P<retval>[^(){};\n]+?)            # return type / qualifiers
    \s+
    (?P<name>[A-Za-z_][A-Za-z_0-9]*)
    \s*
    \(
    (?P<params>[^()]*)                  # parameter list
    \)
    \s*
    (?=\{)
    """,
    re.VERBOSE | re.MULTILINE,
)


def _extract_function_text(
    source: str, fn_name: str
) -> Optional[tuple[str, str, int]]:
    """Return (params_text, body_text, start_line) for `fn_name`, or
    None if not found. params_text is the text inside (), body_text
    is the text including outer {}, start_line is 1-indexed."""
    cleaned = _strip_strings_and_comments(source)
    for m in _FN_HEADER_RE.finditer(cleaned):
        if m.group("name") != fn_name:
            continue
        # Find the matching body
        body_start = m.end()
        # m.end() points just before `{`
        idx = body_start
        depth = 0
        body_begin = None
        while idx < len(cleaned):
            c = cleaned[idx]
            if c == "{":
                if depth == 0:
                    body_begin = idx
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    body_end = idx + 1
                    body_text = source[body_begin:body_end]
                    params_text = m.group("params").strip()
                    start_line = source.count("\n", 0, m.start()) + 1
                    return (params_text, body_text, start_line)
            idx += 1
        return None
    return None


def _parse_params(params_text: str) -> list[LocalDecl]:
    """Parse a function's parameter list into LocalDecl entries (with
    kind set externally to 'param')."""
    params_text = params_text.strip()
    if not params_text or params_text == "void":
        return []
    out: list[LocalDecl] = []
    depth = 0
    buf: list[str] = []
    parts: list[str] = []
    for c in params_text:
        if c == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        buf.append(c)
    remainder = "".join(buf).strip()
    if remainder:
        parts.append(remainder)
    for i, part in enumerate(parts):
        m = re.match(
            r"^\s*(?P<type>.+?)\s+(?P<name>[A-Za-z_][A-Za-z_0-9]*)\s*$",
            part,
        )
        if m is None:
            continue
        type_str = re.sub(r"\s+", " ", m.group("type")).strip()
        type_str = re.sub(r"\s*\*\s*", "*", type_str)
        out.append(LocalDecl(
            name=m.group("name"),
            type_str=type_str,
            decl_index=i,
        ))
    return out


def _collect_virtual_destinations(pre_pass) -> list[int]:
    """Return the virtual register numbers (≥32) that appear as
    destinations in `pre_pass`, in first-occurrence order."""
    seen: list[int] = []
    seen_set: set[int] = set()
    for block in pre_pass.blocks:
        for ist in block.instructions:
            if not ist.regs:
                continue
            kind, num = ist.regs[0]
            if kind != "r":
                continue
            if num < 32:
                continue
            if num in seen_set:
                continue
            seen_set.add(num)
            seen.append(num)
    return seen


def list_bindings(source: str, fn_name: str, pre_pass) -> list[Binding]:
    """Return Binding entries (both params and locals) for `fn_name`.

    Thin wrapper around `list_bindings_with_basis` — returns only the
    bindings, dropping the basis evidence. Maintained for backward
    compatibility with the original API.
    """
    bindings, _basis = list_bindings_with_basis(source, fn_name, pre_pass)
    return bindings


def list_bindings_with_basis(
    source: str, fn_name: str, pre_pass,
) -> tuple[list[Binding], Optional[BindingBasis]]:
    """Return Bindings + the evidence used to derive them.

    Heuristic: MWCC numbers parameters then locals deterministically
    starting at virtual r32, in source declaration order. Each
    binding's predicted virtual is `32 + cursor`.

    For PARAMS: confidence is always 'best-guess'. MWCC always
    allocates a virtual slot for a parameter even when the value lives
    in the ABI register (r3/r4/...) without being re-defined in the
    function body — i.e. the param's expected virtual may legitimately
    NOT appear as a destination in the pre-coloring pass. That's the
    common case for `gobj` in proc callbacks and similar.

    For LOCALS:
      - If the predicted virtual IS observed as a destination AND no
        red flags are set → 'best-guess'.
      - If the predicted virtual IS observed but red flags ARE set →
        'low-confidence'. The cursor model may have shifted, the
        match could be coincidental, and tier3-search will skip it
        unless explicit opt-in.
      - If the predicted virtual is NOT observed → 'ambiguous'.

    The basis carries the raw inputs (parsed params/locals, observed
    virtuals, unrecognized decls, red flags) so callers can dump them
    for diagnosis or audit confidence assignments.

    Returns (None) basis if the function couldn't be extracted at all.
    """
    extracted = _extract_function_text(source, fn_name)
    if extracted is None:
        return [], None
    params_text, body_text, start_line = extracted

    (params, locals_, virtuals, unrecognized,
     red_flags) = _collect_basis(body_text, params_text, pre_pass)
    virtuals_set: set[int] = set(virtuals)

    out: list[Binding] = []
    cursor = 0
    for p in params:
        expected = 32 + cursor
        # Params are unconditionally best-guess (per docstring).
        out.append(Binding(
            var_name=p.name,
            virtual=expected,
            decl_line=start_line,
            kind="param",
            type_str=p.type_str,
            confidence="best-guess",
        ))
        cursor += 1
    for ld in locals_:
        expected = 32 + cursor
        if expected in virtuals_set:
            # Hit — but demote to low-confidence if red flags warn the
            # cursor model may be unreliable for this function.
            confidence = "low-confidence" if red_flags else "best-guess"
            out.append(Binding(
                var_name=ld.name,
                virtual=expected,
                decl_line=start_line,
                kind="local",
                type_str=ld.type_str,
                confidence=confidence,
            ))
        else:
            out.append(Binding(
                var_name=ld.name,
                virtual=-1,
                decl_line=start_line,
                kind="local",
                type_str=ld.type_str,
                confidence="ambiguous",
            ))
        cursor += 1

    basis = BindingBasis(
        parsed_params=params,
        parsed_locals=locals_,
        observed_virtuals=virtuals,
        unrecognized_decls=unrecognized,
        red_flags=red_flags,
    )
    return out, basis


def find_virtual_for_var(
    source: str, fn_name: str, var_name: str, pre_pass
) -> Optional[Binding]:
    """Look up the predicted MWCC virtual for a source variable.

    Returns the Binding for the variable named `var_name` in `fn_name`,
    or None if no such variable is found in the function body or params.
    """
    for b in list_bindings(source, fn_name, pre_pass):
        if b.var_name == var_name:
            return b
    return None


def find_var_for_virtual(
    source: str, fn_name: str, virtual: int, pre_pass
) -> Optional[Binding]:
    """Look up the source variable predicted to live in a virtual reg.

    Returns the Binding whose `virtual` equals `virtual`, or None if no
    such binding exists.
    """
    for b in list_bindings(source, fn_name, pre_pass):
        if b.virtual == virtual:
            return b
    return None
