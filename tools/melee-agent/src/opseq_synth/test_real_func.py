#!/usr/bin/env python3
"""
Test the synthesis database against a real function: mnDataDel_8024FE4C
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.opseq_synth.compiler import Compiler
from src.opseq_synth.contexts import AdvancedContext, MinimalContext
from src.opseq_synth.opcodes import OpcodeSequence
from src.opseq_synth.storage import OpcodeDB
from src.opseq_synth.templates import ALL_TEMPLATES as BASIC_TEMPLATES
from src.opseq_synth.templates_advanced import ADVANCED_TEMPLATES

# Combined templates
ALL_TEMPLATES = BASIC_TEMPLATES + ADVANCED_TEMPLATES


def build_test_database():
    """Build a test database with all templates."""
    compiler = Compiler()

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db = OpcodeDB(db_path)

    print(f"Generating samples from {len(ALL_TEMPLATES)} templates...")

    minimal_ctx = MinimalContext()
    advanced_ctx = AdvancedContext()
    total_stored = 0
    total_failed = 0

    # Basic templates with MinimalContext
    for template in BASIC_TEMPLATES:
        expansions = template.expand()
        for snippet in expansions[:5]:
            result = compiler.compile_snippet(snippet, minimal_ctx, template_name=template.name)
            if result.success and result.opcodes.mnemonics:
                db.insert_sample(
                    source=snippet,
                    opcodes=result.opcodes,
                    template_name=template.name,
                    context_name=minimal_ctx.name,
                    asm="",
                )
                total_stored += 1
            else:
                total_failed += 1

        if total_stored % 50 == 0:
            print(f"  ... {total_stored} samples stored")

    # Advanced templates with AdvancedContext
    for template in ADVANCED_TEMPLATES:
        expansions = template.expand()
        for snippet in expansions[:5]:
            result = compiler.compile_snippet(snippet, advanced_ctx, template_name=template.name)
            if result.success and result.opcodes.mnemonics:
                db.insert_sample(
                    source=snippet,
                    opcodes=result.opcodes,
                    template_name=template.name,
                    context_name=advanced_ctx.name,
                    asm="",
                )
                total_stored += 1
            else:
                total_failed += 1

        if total_stored % 50 == 0:
            print(f"  ... {total_stored} samples stored")

    print(f"Stored {total_stored} samples ({total_failed} failed)")
    return db, db_path


def search_for_patterns(db):
    """Search for specific opcode patterns from mnDataDel_8024FE4C."""
    print("\n" + "=" * 60)
    print("SEARCHING FOR PATTERNS IN mnDataDel_8024FE4C")
    print("=" * 60)

    # Interesting opcode subsequences from the function
    # Use find_containing_opcodes for short patterns, find_subsequence for longer
    patterns_to_search = [
        # Rare/tricky opcodes
        ("cntlzw,extrwi (bool compare)", ["cntlzw", "extrwi"]),
        ("xoris,lfd,fsubs (int-to-float)", ["xoris", "lfd", "fsubs"]),
        ("crclr (variadic)", ["crclr"]),
        ("rlwimi (bitfield insert)", ["rlwimi"]),
        # Common patterns
        ("lbz (byte load)", ["lbz"]),
        ("lbzx (indexed byte)", ["lbzx"]),
        ("extsb (sign extend)", ["extsb"]),
    ]

    for name, pattern in patterns_to_search:
        print(f"\n--- {name} ---")
        results = db.find_containing_opcodes(pattern, require_all=True, limit=3)

        if results:
            for r in results:
                print(f"  Score: {r.score:.2f} | Template: {r.sample.template_name}")
                code_preview = r.sample.source.replace("\n", " ")[:60]
                print(f"    Code: {code_preview}...")
        else:
            print("  No matches found")


def main():
    print("=" * 60)
    print("TESTING SYNTHESIS AGAINST REAL FUNCTION")
    print("=" * 60)

    db, db_path = build_test_database()

    stats = db.get_stats()
    print(f"\nDatabase: {stats['total_samples']} samples, {stats['ngram_count']} n-grams")

    search_for_patterns(db)

    db.close()
    Path(db_path).unlink()

    return 0


if __name__ == "__main__":
    sys.exit(main())
