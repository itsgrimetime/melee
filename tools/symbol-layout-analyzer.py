#!/usr/bin/env python3
"""Analyze symbol/data layout clues that commonly affect Melee decomp matches."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SYMBOL_RE = re.compile(r"^(?P<name>.+?)\s*=\s*(?P<section>[^:;]+):0x(?P<addr>[0-9A-Fa-f]+);\s*(?://\s*(?P<meta>.*))?$")
SOURCE_SUFFIXES = {".c", ".h", ".hpp", ".inc"}
LAYOUT_SUFFIXES = {".map", ".json"}
SMALL_DATA_SECTIONS = {"sdata", ".sdata", "sdata2", ".sdata2", "sbss", ".sbss", "sbss2", ".sbss2"}


@dataclass
class Symbol:
    name: str
    section: str
    address: int
    attrs: dict[str, str]
    flags: list[str]
    line: int

    @property
    def size(self) -> int | None:
        raw = self.attrs.get("size")
        if raw is None:
            return None
        try:
            return int(raw, 0)
        except ValueError:
            return None

    @property
    def end(self) -> int | None:
        if self.size is None:
            return None
        return self.address + self.size

    @property
    def type(self) -> str:
        return self.attrs.get("type", "")

    @property
    def scope(self) -> str:
        return self.attrs.get("scope", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "section": self.section,
            "address": f"0x{self.address:08X}",
            "size": self.size,
            "type": self.type,
            "scope": self.scope,
            "data": self.attrs.get("data", ""),
            "flags": self.flags,
            "line": self.line,
        }


def parse_symbol_line(line: str, line_no: int) -> Symbol | None:
    match = SYMBOL_RE.match(line.strip())
    if not match:
        return None

    attrs: dict[str, str] = {}
    flags: list[str] = []
    meta = match.group("meta") or ""
    for token in meta.split():
        if ":" in token:
            key, value = token.split(":", 1)
            attrs[key] = value
        else:
            flags.append(token)

    return Symbol(
        name=match.group("name").strip(),
        section=match.group("section").strip(),
        address=int(match.group("addr"), 16),
        attrs=attrs,
        flags=flags,
        line=line_no,
    )


def load_symbols(root: Path) -> list[Symbol]:
    path = root / "config" / "GALE01" / "symbols.txt"
    symbols: list[Symbol] = []
    for line_no, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
        symbol = parse_symbol_line(line, line_no)
        if symbol is not None:
            symbols.append(symbol)
    return sorted(symbols, key=lambda symbol: (symbol.section, symbol.address, symbol.line))


def find_symbol(symbols: list[Symbol], query: str) -> Symbol:
    if query.lower().startswith("0x"):
        address = int(query, 16)
        for symbol in symbols:
            if symbol.address == address or (symbol.end is not None and symbol.address <= address < symbol.end):
                return symbol
        raise ValueError(f"no symbol covers address {query}")

    for symbol in symbols:
        if symbol.name == query:
            return symbol
    raise ValueError(f"no symbol named {query}")


def source_occurrences(root: Path, symbol_name: str) -> list[dict[str, Any]]:
    occurrences: list[dict[str, Any]] = []
    for base_name in ("src", "include"):
        base = root / base_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            try:
                lines = path.read_text(errors="ignore").splitlines()
            except OSError:
                continue
            for line_no, line in enumerate(lines, 1):
                if symbol_name in line:
                    occurrences.append(
                        {
                            "path": str(path.relative_to(root)),
                            "line": line_no,
                            "text": line.strip(),
                        }
                    )
    return occurrences


def layout_artifacts(root: Path, symbol_name: str) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    build = root / "build"
    if not build.exists():
        return artifacts

    for path in build.rglob("*"):
        if not path.is_file() or path.suffix not in LAYOUT_SUFFIXES:
            continue
        try:
            lines = path.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            if symbol_name in line:
                artifacts.append(
                    {
                        "path": str(path.relative_to(root)),
                        "line": line_no,
                        "text": line.strip(),
                    }
                )
    return artifacts


def analyze_symbol(root: Path, query: str, window: int = 3) -> dict[str, Any]:
    symbols = load_symbols(root)
    target = find_symbol(symbols, query)
    same_section = [symbol for symbol in symbols if symbol.section == target.section]
    index = same_section.index(target)
    before = same_section[max(0, index - window) : index]
    after = same_section[index + 1 : index + 1 + window]
    occurrences = source_occurrences(root, target.name)
    artifacts = layout_artifacts(root, target.name)

    return {
        "query": query,
        "target": target.to_dict(),
        "neighbors": {
            "before": [symbol.to_dict() for symbol in before],
            "after": [symbol.to_dict() for symbol in after],
        },
        "source_occurrences": occurrences[:20],
        "layout_artifacts": artifacts[:20],
        "findings": build_findings(
            target,
            before[-1] if before else None,
            after[0] if after else None,
            occurrences,
            artifacts,
        ),
    }


def build_findings(
    target: Symbol,
    previous: Symbol | None,
    next_symbol: Symbol | None,
    occurrences: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    if artifacts:
        first_artifact = artifacts[0]
        findings.append(
            finding(
                "build-layout-evidence",
                f"Build layout artifact references this symbol at {first_artifact['path']}:{first_artifact['line']}.",
                "Compare this object/map placement with `symbols.txt` neighbors and C declarations before editing function bodies.",
            )
        )

    if target.type == "object" and not occurrences:
        findings.append(
            finding(
                "missing-source-declaration",
                "No source declaration/reference was found for this object symbol.",
                "Search callsites/xrefs and model the data directly instead of using raw address math.",
            )
        )

    if target.type == "object" and target.scope == "global":
        static_occurrence = next((occ for occ in occurrences if re.search(r"\bstatic\b", occ["text"])), None)
        if static_occurrence:
            findings.append(
                finding(
                    "scope-mismatch",
                    f"`symbols.txt` marks this global, but source has `static` at {static_occurrence['path']}:{static_occurrence['line']}.",
                    "Either the symbol scope is wrong or the C declaration is giving the linker the wrong visibility/order.",
                )
            )

    if target.type == "object" and (target.scope == "local" or "hidden" in target.flags):
        public_occurrence = next(
            (
                occ
                for occ in occurrences
                if occ["path"].endswith((".h", ".hpp")) or re.search(r"\bextern\b", occ["text"])
            ),
            None,
        )
        if public_occurrence:
            findings.append(
                finding(
                    "scope-mismatch",
                    f"`symbols.txt` marks this local/hidden, but source exposes it at {public_occurrence['path']}:{public_occurrence['line']}.",
                    "Keep file-local data in the C file or a `.static.h`; avoid public externs unless the symbol is truly global.",
                )
            )

    data_kind = target.attrs.get("data", "")
    if "string" in data_kind and previous is not None and previous.end == target.address:
        findings.append(
            finding(
                "tail-string-or-padding",
                f"String-like symbol starts immediately after `{previous.name}`.",
                "Consider whether the bytes are a named field inside the previous blob or an inline literal emitted after it.",
            )
        )

    if target.section.lower() in SMALL_DATA_SECTIONS:
        findings.append(
            finding(
                "small-data-placement",
                f"Symbol is in `{target.section}`, where declaration placement can affect SDA-relative codegen.",
                "Check nearby `.sdata`/`.sdata2` symbols and prefer declarations that preserve source order and constness.",
            )
        )

    if "bss" in target.section.lower() and target.type == "object":
        adjacent = []
        if previous is not None and previous.end == target.address:
            adjacent.append(previous.name)
        if next_symbol is not None and target.end == next_symbol.address:
            adjacent.append(next_symbol.name)
        if adjacent:
            findings.append(
                finding(
                    "bss-adjacency",
                    f"BSS object is adjacent to: {', '.join(adjacent)}.",
                    "For BSS mismatches, check static/global choice and declaration order before adding padding.",
                )
            )

    if target.size and target.size % 4 == 0:
        pointerish = next((occ for occ in occurrences if re.search(r"\*\s*" + re.escape(target.name), occ["text"])), None)
        if pointerish:
            findings.append(
                finding(
                    "array-pointer-shape",
                    f"Size is 4-byte aligned, but source occurrence looks pointer-like at {pointerish['path']}:{pointerish['line']}.",
                    "If assembly walks contiguous data, try an array/blob declaration rather than a standalone pointer.",
                )
            )

    return findings


def finding(kind: str, message: str, suggestion: str) -> dict[str, str]:
    return {"kind": kind, "message": message, "suggestion": suggestion}


def print_text(result: dict[str, Any]) -> None:
    target = result["target"]
    print(f"{target['name']} {target['section']}:{target['address']} size={target['size']} scope={target['scope']}")

    if result["neighbors"]["before"] or result["neighbors"]["after"]:
        print("\nNearby symbols:")
        for symbol in result["neighbors"]["before"]:
            print(f"  before {symbol['address']} {symbol['name']} size={symbol['size']} data={symbol['data']}")
        for symbol in result["neighbors"]["after"]:
            print(f"  after  {symbol['address']} {symbol['name']} size={symbol['size']} data={symbol['data']}")

    if result["source_occurrences"]:
        print("\nSource occurrences:")
        for occurrence in result["source_occurrences"]:
            print(f"  {occurrence['path']}:{occurrence['line']}: {occurrence['text']}")

    if result["layout_artifacts"]:
        print("\nBuild layout artifacts:")
        for artifact in result["layout_artifacts"]:
            print(f"  {artifact['path']}:{artifact['line']}: {artifact['text']}")

    if result["findings"]:
        print("\nFindings:")
        for item in result["findings"]:
            print(f"  [{item['kind']}] {item['message']}")
            print(f"      {item['suggestion']}")
    else:
        print("\nNo layout-specific findings.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Symbol name or 0x-address to inspect")
    parser.add_argument("--root", type=Path, default=ROOT, help="Melee repo root")
    parser.add_argument("--window", type=int, default=3, help="Nearby symbols to include on each side")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    try:
        result = analyze_symbol(args.root, args.query, args.window)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
