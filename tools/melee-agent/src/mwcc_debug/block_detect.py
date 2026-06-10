"""Duplicate-block detection for `debug suggest inlines`.

Discovers repeated multi-statement blocks within and across functions and proposes
them as `static inline` helper candidates with inferred signatures.
"""
from __future__ import annotations
import difflib, re
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional
from .source_shape import InlineCandidate, SourceAnchor
from .source_spans import StatementSpan

@dataclass(frozen=True)
class BlockVariant:
    spans: tuple = ()
    text: str = ""
    scope_path: tuple = ()
    byte_range: tuple = (0, 0)
    line_range: tuple = (0, 0)
    extracted_reads: tuple = ()
    extracted_writes: tuple = ()

@dataclass(frozen=True)
class DuplicateBlock:
    block_id: str = ""
    variants: tuple = ()
    fingerprint: str = ""
    confidence: float = 0.0
    constant_lines: tuple = ()
    varying_tokens: tuple = ()

def _tokenize(text):
    return re.findall(r"[A-Za-z_][A-Za-z_0-9]*|\d+|0x[0-9a-fA-F]+|"
                      r"[+\-*/%&|^~!=<>]+|[(),;{}[\].]|->|\.\.\.?", text)

def _text_similarity(a, b):
    at, bt = _tokenize(a), _tokenize(b)
    if not at and not bt: return 1.0
    return difflib.SequenceMatcher(None, at, bt).ratio()

def _text_similarity_lines(a, b):
    return _text_similarity("\n".join(a), "\n".join(b))

def _anti_unify(texts):
    if len(texts) < 2: return ((), ())
    token_sets = [_tokenize(t) for t in texts]
    all_tokens = set()
    for tokens in token_sets: all_tokens.update(tokens)
    constant, varying = [], set()
    for token in sorted(all_tokens, key=lambda t: (-len(t), t)):
        count = sum(1 for tokens in token_sets if token in tokens)
        if count == len(token_sets): constant.append(token)
        elif count > 0: varying.add(token)
    return tuple(constant), tuple(sorted(varying))

def _find_function_start(lines, fn_name):
    prefix = (r"^(?:static\s+)?(?:inline\s+)?(?:void|int|s32|u32|u8|s8|u16|s16|f32|f64|bool|char|float|double|HSD_JObj\*|HSD_GObj\*|Menu\*|Diagram\*)\s+")
    pat = re.compile(prefix + re.escape(fn_name) + r"\s*\(")
    for i, line in enumerate(lines):
        if pat.search(line): return i
    return -1

def _find_function_end(lines, fn_start):
    depth, started = 0, False
    for i in range(fn_start, len(lines)):
        if "{" in lines[i]: depth += lines[i].count("{"); started = True
        if "}" in lines[i]: depth -= lines[i].count("}")
        if started and depth == 0: return i + 1
    return len(lines)

def find_similar_text_blocks(source, fn_name="", *, min_lines=5, max_lines=20, min_similarity=0.70, max_blocks=12):
    lines = source.splitlines()
    fn_start = _find_function_start(lines, fn_name)
    if fn_start < 0: return []
    fn_end = _find_function_end(lines, fn_start)
    if fn_end <= fn_start: return []
    fn_lines = lines[fn_start:fn_end]
    fn_offset = fn_start + 1
    blocks = []
    seen = set()
    for width in range(min_lines, min(max_lines + 1, len(fn_lines) - min_lines)):
        for i in range(0, len(fn_lines) - width * 2 + 1):
            for j in range(i + width, len(fn_lines) - width + 1):
                if (i, j) in seen: continue
                seen.add((i, j))
                a_text = "\n".join(fn_lines[i:i+width])
                b_text = "\n".join(fn_lines[j:j+width])
                sim = _text_similarity(a_text, b_text)
                if sim < min_similarity: continue
                if len(a_text.strip()) < 30 or len(b_text.strip()) < 30: continue
                has_call = bool(re.search(r"\w+\s*\(", a_text)) or bool(re.search(r"\w+\s*\(", b_text))
                if not has_call: continue
                constant_lines, varying_tokens = _anti_unify((a_text, b_text))
                blocks.append(DuplicateBlock(
                    block_id=f"text-block-{len(blocks)+1:04d}",
                    variants=(
                        BlockVariant(text=a_text, scope_path=(fn_name,), line_range=(fn_offset + i, fn_offset + i + width - 1)),
                        BlockVariant(text=b_text, scope_path=(fn_name,), line_range=(fn_offset + j, fn_offset + j + width - 1)),
                    ),
                    fingerprint=f"text-sim-{sim:.2f}",
                    confidence=sim,
                    constant_lines=constant_lines,
                    varying_tokens=varying_tokens,
                ))
    # Sort by confidence (highest first), then take top N
    blocks.sort(key=lambda d: d.confidence, reverse=True)
    return blocks[:max_blocks]

# Backward-compat alias
def find_duplicate_blocks(source, fn_name="", *, min_statements=2, max_statements=8, min_text_similarity=0.55, max_blocks=12):
    return find_similar_text_blocks(source, fn_name, min_similarity=min_text_similarity, max_blocks=max_blocks)


def block_to_candidate(function, block, candidate_id):
    first = block.variants[0]
    helper_name = f"inline_helper_{candidate_id:04d}"
    all_reads = []
    all_writes = []
    for v in block.variants:
        for name in v.extracted_reads:
            if name not in all_reads: all_reads.append(name)
        for name in v.extracted_writes:
            if name not in all_writes: all_writes.append(name)
    varying_idents = tuple(
        t for t in block.varying_tokens
        if re.match(r"^[A-Za-z_][A-Za-z_0-9]*$", t)
        and t not in {"if","else","while","do","for","goto","return","break","continue","void","int","char","float","double","sizeof","static","inline","const","volatile","unsigned","signed","struct","union"}
    )
    anchor = SourceAnchor(
        function=function, scope_path=first.scope_path,
        byte_range=first.byte_range, line_range=first.line_range,
        kind="duplicate-block",
        reason=f"repeated {len(first.text.splitlines())}-line block (x{len(block.variants)}, similarity={block.confidence:.1%})",
    )
    return InlineCandidate(
        candidate_id=f"{helper_name}",
        kind=f"duplicate-block-{len(first.text.splitlines())}lines",
        anchor=anchor, helper_name=helper_name,
        reads=tuple(all_reads), writes=tuple(all_writes),
        source_excerpt=first.text,
        metadata={
            "fingerprint": block.fingerprint,
            "num_variants": len(block.variants),
            "confidence": block.confidence,
            "constant_lines": list(block.constant_lines),
            "varying_tokens": list(varying_idents),
            "variant_byte_ranges": [(v.byte_range, v.line_range) for v in block.variants],
        },
    )
