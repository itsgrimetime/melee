#!/usr/bin/env python3
"""
PowerPC Instruction Set Reference Search Tool.

Searches multiple PPC reference manuals for instruction documentation.

Usage:
  tools/ppc-ref.py search <query>      # Full-text search across all manuals
  tools/ppc-ref.py instr <mnemonic>    # Get specific instruction (e.g., lwz, fcmpo)
  tools/ppc-ref.py list                # List all known instructions
  tools/ppc-ref.py index               # Rebuild the search index

PDF sources (in .claude/skills/ppc-ref/):
  - ppc_750cl.pdf: IBM PowerPC 750CL User's Manual (primary - has FP + paired singles)
  - MPC5xxUG.pdf: CodeWarrior MPC5xx Targeting Manual
  - powerpc-cwg.pdf: IBM PowerPC Compiler Writer's Guide

Override PDF directory with PPC_REF_DIR environment variable.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# Cache directory for the index
CACHE_DIR = Path.home() / ".cache" / "ppc-ref"

# Default PDF directory (relative to script location)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_PDF_DIR = PROJECT_ROOT / ".claude" / "skills" / "ppc-ref"

# PDF priority order (first = highest priority for instruction lookups)
PDF_PRIORITY = [
    "ppc_750cl.pdf",      # Primary: 750CL manual with FP + paired singles
    "MPC82XINSET.pdf",    # Integer instruction details (if present)
    "powerpc-cwg.pdf",    # Compiler writer's guide
    "MPC5xxUG.pdf",       # CodeWarrior targeting manual
]


def get_pdf_dir() -> Path:
    """Get PDF directory from environment or default."""
    env_dir = os.environ.get("PPC_REF_DIR")
    if env_dir:
        return Path(env_dir)
    return DEFAULT_PDF_DIR


def get_pdf_files() -> list[Path]:
    """Get list of PDF files in priority order."""
    pdf_dir = get_pdf_dir()
    if not pdf_dir.exists():
        return []

    # Get all PDFs
    all_pdfs = list(pdf_dir.glob("*.pdf"))

    # Sort by priority (known PDFs first, then alphabetically)
    def sort_key(p: Path) -> tuple[int, str]:
        name = p.name
        if name in PDF_PRIORITY:
            return (PDF_PRIORITY.index(name), name)
        return (len(PDF_PRIORITY), name)

    return sorted(all_pdfs, key=sort_key)


def get_combined_hash(pdf_files: list[Path]) -> str:
    """Get combined hash of all PDF files for cache invalidation."""
    hasher = hashlib.md5()
    for pdf_path in sorted(pdf_files):
        hasher.update(pdf_path.name.encode())
        hasher.update(str(pdf_path.stat().st_mtime).encode())
    return hasher.hexdigest()[:12]


def get_index_path(pdf_files: list[Path]) -> Path:
    """Get path to cached index file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    combined_hash = get_combined_hash(pdf_files)
    return CACHE_DIR / f"multi-index-{combined_hash}.json"


def load_index(pdf_files: list[Path]) -> Optional[dict]:
    """Load cached index if it exists and is valid."""
    index_path = get_index_path(pdf_files)
    if index_path.exists():
        try:
            return json.loads(index_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def save_index(pdf_files: list[Path], index: dict) -> None:
    """Save index to cache."""
    index_path = get_index_path(pdf_files)
    index_path.write_text(json.dumps(index, indent=2))


def clean_page_text(text: str) -> str:
    """Remove PDF header/footer noise from page text."""
    noise_patterns = [
        r'\s*Freescale Semiconductor, I.*?nc\.\.\.',
        r'\s*Freescale Semiconductor, Inc\.',
        r'For More Information On This Product,\s*Go to: www\.freescale\.com',
        r'\s*nc\.\.\.\s*',
        r'Page \d+ of \d+',
        r'Version \d+\.\d+',
    ]
    for pattern in noise_patterns:
        text = re.sub(pattern, '', text, flags=re.DOTALL)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_instructions_from_toc(toc: list, pdf_name: str) -> dict:
    """Extract instruction mappings from TOC entries."""
    instructions = {}

    # For MPC82x-style TOCs with individual instruction entries
    in_instruction_section = False
    for entry in toc:
        title = entry["title"]
        page = entry["page"]

        if "Instruction Description" in title:
            in_instruction_section = True
            continue
        if "Instructions Sorted by" in title or "Instructions Grouped by" in title:
            in_instruction_section = False
            continue

        if in_instruction_section and page >= 7:
            mnemonic = title.strip().lower()
            base_mnemonic = mnemonic.rstrip('x') if mnemonic.endswith('x') else mnemonic
            base_no_dot = base_mnemonic.rstrip('.')

            entry_data = {
                "name": title.strip().upper(),
                "page": page,
                "source": pdf_name
            }

            instructions[mnemonic] = entry_data
            if base_mnemonic != mnemonic and base_mnemonic not in instructions:
                instructions[base_mnemonic] = entry_data
            if base_no_dot != base_mnemonic and base_no_dot not in instructions:
                instructions[base_no_dot] = entry_data

    return instructions


def build_index(force: bool = False) -> dict:
    """Build or load the combined index from all PDFs."""
    try:
        import fitz  # pymupdf
    except ImportError:
        print("Error: pymupdf not installed. Run: pip install pymupdf", file=sys.stderr)
        sys.exit(1)

    pdf_files = get_pdf_files()
    if not pdf_files:
        print(f"Error: No PDF files found in {get_pdf_dir()}", file=sys.stderr)
        sys.exit(1)

    if not force:
        cached = load_index(pdf_files)
        if cached:
            return cached

    print(f"Building index from {len(pdf_files)} PDFs...", file=sys.stderr)

    index = {
        "sources": {},      # pdf_name -> {pages: [...], toc: [...]}
        "instructions": {}, # mnemonic -> {page, source, name}
    }

    for pdf_path in pdf_files:
        pdf_name = pdf_path.name
        print(f"  Indexing {pdf_name}...", file=sys.stderr)

        doc = fitz.open(pdf_path)

        source_data = {
            "path": str(pdf_path),
            "pages": [],
            "toc": [],
            "page_count": len(doc)
        }

        # Get TOC
        toc = doc.get_toc()
        for level, title, page in toc:
            source_data["toc"].append({
                "level": level,
                "title": title,
                "page": page
            })

        # Extract instructions from TOC (works for MPC82x-style)
        toc_instructions = extract_instructions_from_toc(source_data["toc"], pdf_name)
        for mnemonic, data in toc_instructions.items():
            if mnemonic not in index["instructions"]:
                index["instructions"][mnemonic] = data

        # Store page text for full-text search
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = clean_page_text(page.get_text())
            source_data["pages"].append({
                "page": page_num + 1,
                "text": text
            })

        doc.close()
        index["sources"][pdf_name] = source_data

    save_index(pdf_files, index)
    print(f"Index built: {len(index['instructions'])} instructions from TOC, "
          f"{sum(s['page_count'] for s in index['sources'].values())} total pages",
          file=sys.stderr)

    return index


def get_page_content(pdf_path: Path, page_num: int) -> str:
    """Get cleaned content of a specific page."""
    try:
        import fitz
    except ImportError:
        print("Error: pymupdf not installed. Run: pip install pymupdf", file=sys.stderr)
        sys.exit(1)

    doc = fitz.open(pdf_path)
    if page_num < 1 or page_num > len(doc):
        doc.close()
        return f"Page {page_num} out of range (1-{len(doc)})"

    page = doc[page_num - 1]
    text = clean_page_text(page.get_text())
    doc.close()
    return text


def cmd_search(args: argparse.Namespace) -> None:
    """Full-text search across all PDFs."""
    index = build_index()
    query = args.query.lower()
    results = []

    for pdf_name, source in index["sources"].items():
        for page_data in source["pages"]:
            text = page_data["text"].lower()
            if query in text:
                lines = page_data["text"].split('\n')
                for i, line in enumerate(lines):
                    if query in line.lower():
                        start = max(0, i - 1)
                        end = min(len(lines), i + 3)
                        context = '\n'.join(lines[start:end])
                        results.append({
                            "source": pdf_name,
                            "page": page_data["page"],
                            "context": context
                        })

    if not results:
        print(f"No results found for '{args.query}'")
        return

    # Deduplicate
    seen = set()
    unique_results = []
    for r in results:
        key = (r["source"], r["page"], r["context"][:100])
        if key not in seen:
            seen.add(key)
            unique_results.append(r)

    limit = args.limit or 10
    for r in unique_results[:limit]:
        print(f"--- {r['source']} p.{r['page']} ---")
        print(r["context"])
        print()

    if len(unique_results) > limit:
        print(f"... and {len(unique_results) - limit} more results. Use --limit to see more.")


def cmd_instr(args: argparse.Namespace) -> None:
    """Look up a specific instruction by mnemonic."""
    index = build_index()
    mnemonic = args.mnemonic.lower().strip()

    # Direct lookup in TOC-based index
    if mnemonic in index["instructions"]:
        instr = index["instructions"][mnemonic]
        pdf_path = Path(index["sources"][instr["source"]]["path"])
        print(f"=== {instr['name']} ({mnemonic}) ===")
        print(f"Source: {instr['source']} p.{instr['page']}\n")
        print(get_page_content(pdf_path, instr['page']))
        return

    # Try variations
    variations = [
        mnemonic + ".",
        mnemonic.rstrip("."),
        mnemonic + "x",
        mnemonic.rstrip("x"),
    ]

    for var in variations:
        if var in index["instructions"]:
            instr = index["instructions"][var]
            pdf_path = Path(index["sources"][instr["source"]]["path"])
            print(f"=== {instr['name']} ({var}) ===")
            print(f"(Searched for '{mnemonic}', found as '{var}')")
            print(f"Source: {instr['source']} p.{instr['page']}\n")
            print(get_page_content(pdf_path, instr['page']))
            return

    # Fall back to full-text search
    print(f"Instruction '{mnemonic}' not in TOC index. Searching full text...\n")

    results = []
    # Search with word boundary pattern for better matches
    pattern = re.compile(rf'\b{re.escape(mnemonic)}\b', re.IGNORECASE)

    for pdf_name, source in index["sources"].items():
        for page_data in source["pages"]:
            if pattern.search(page_data["text"]):
                # Check if this looks like an instruction definition
                text = page_data["text"]
                lines = text.split('\n')
                for i, line in enumerate(lines):
                    if pattern.search(line):
                        # Get context around the match
                        start = max(0, i - 2)
                        end = min(len(lines), i + 8)
                        context = '\n'.join(lines[start:end])
                        results.append({
                            "source": pdf_name,
                            "page": page_data["page"],
                            "context": context,
                            "line": line
                        })

    if results:
        # Prioritize results that look like instruction definitions
        def score_result(r):
            text = r["context"].lower()
            line = r["line"].lower().strip()
            score = 0

            # Strong boost for instruction definition title (mnemonic or mnemonicx alone on line)
            if re.match(rf'^{re.escape(mnemonic)}x?\s*$', line, re.IGNORECASE):
                score += 25

            # Strong boost for instruction definition format (mnemonic at line start with operands)
            if re.search(rf'^{re.escape(mnemonic)}\.?\s+[rf][a-z0-9,\(\)]+', line, re.IGNORECASE):
                score += 20

            # Boost if context has operand pattern on next line (PDF often splits these)
            if re.search(rf'{re.escape(mnemonic)}\.?\s*\n\s*r[ad],', text, re.IGNORECASE):
                score += 15

            # Boost for being in instruction reference section (750CL p.347-620)
            if '750cl' in r["source"].lower() and 347 <= r["page"] <= 620:
                score += 12

            # Boost for instruction definition markers
            if '(rc = 0)' in text or '(rc = 1)' in text:
                score += 10
            if 'other registers altered' in text:
                score += 8
            if 'operand' in text or 'register' in text:
                score += 3

            # Prefer 750CL manual
            if '750cl' in r["source"].lower():
                score += 2

            return -score

        results.sort(key=score_result)

        # Show top results
        shown = 0
        for r in results[:5]:
            print(f"--- {r['source']} p.{r['page']} ---")
            print(r["context"])
            print()
            shown += 1

        if len(results) > 5:
            print(f"... and {len(results) - 5} more results.")
    else:
        # Suggest similar from index
        similar = [m for m in index["instructions"].keys()
                   if mnemonic in m or m in mnemonic or
                   (len(mnemonic) > 2 and m.startswith(mnemonic[:2]))]

        if similar:
            print(f"No matches found. Similar instructions in index:")
            for m in sorted(similar)[:10]:
                instr = index["instructions"][m]
                print(f"  {m}: {instr['name']} ({instr['source']} p.{instr['page']})")
        else:
            print(f"No matches found for '{mnemonic}'.")


def cmd_list(args: argparse.Namespace) -> None:
    """List all indexed instructions."""
    index = build_index()

    if args.filter:
        instructions = {k: v for k, v in index["instructions"].items()
                       if args.filter.lower() in k}
    else:
        instructions = index["instructions"]

    print(f"Found {len(instructions)} instructions in TOC index:\n")

    by_letter = {}
    for mnemonic in sorted(instructions.keys()):
        letter = mnemonic[0].upper()
        if letter not in by_letter:
            by_letter[letter] = []
        by_letter[letter].append(mnemonic)

    for letter in sorted(by_letter.keys()):
        mnemonics = by_letter[letter]
        print(f"{letter}: {', '.join(mnemonics)}")


def cmd_index(args: argparse.Namespace) -> None:
    """Rebuild the search index."""
    build_index(force=True)
    print("Index rebuilt successfully.")


def cmd_page(args: argparse.Namespace) -> None:
    """Show content of a specific page from a PDF."""
    index = build_index()

    # Find the source
    source_name = args.source
    if source_name not in index["sources"]:
        # Try partial match
        matches = [s for s in index["sources"] if source_name.lower() in s.lower()]
        if len(matches) == 1:
            source_name = matches[0]
        elif len(matches) > 1:
            print(f"Ambiguous source '{args.source}'. Matches: {', '.join(matches)}")
            return
        else:
            print(f"Source '{args.source}' not found. Available: {', '.join(index['sources'].keys())}")
            return

    pdf_path = Path(index["sources"][source_name]["path"])
    print(f"=== {source_name} p.{args.page} ===\n")
    print(get_page_content(pdf_path, args.page))


def cmd_sources(args: argparse.Namespace) -> None:
    """List available PDF sources."""
    index = build_index()

    print("Available PDF sources:\n")
    for name, source in index["sources"].items():
        print(f"  {name}")
        print(f"    Pages: {source['page_count']}")
        print(f"    TOC entries: {len(source['toc'])}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PowerPC Instruction Set Reference Search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # search command
    search_parser = subparsers.add_parser("search", help="Full-text search across all manuals")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", "-n", type=int, default=10,
                               help="Max results to show (default: 10)")
    search_parser.set_defaults(func=cmd_search)

    # instr command
    instr_parser = subparsers.add_parser("instr", help="Look up instruction by mnemonic")
    instr_parser.add_argument("mnemonic", help="Instruction mnemonic (e.g., lwz, fcmpo, ps_add)")
    instr_parser.set_defaults(func=cmd_instr)

    # list command
    list_parser = subparsers.add_parser("list", help="List all indexed instructions")
    list_parser.add_argument("--filter", "-f", help="Filter by pattern")
    list_parser.set_defaults(func=cmd_list)

    # index command
    index_parser = subparsers.add_parser("index", help="Rebuild the search index")
    index_parser.set_defaults(func=cmd_index)

    # page command
    page_parser = subparsers.add_parser("page", help="Show specific page from a PDF")
    page_parser.add_argument("source", help="PDF source name (or partial match)")
    page_parser.add_argument("page", type=int, help="Page number (1-indexed)")
    page_parser.set_defaults(func=cmd_page)

    # sources command
    sources_parser = subparsers.add_parser("sources", help="List available PDF sources")
    sources_parser.set_defaults(func=cmd_sources)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
