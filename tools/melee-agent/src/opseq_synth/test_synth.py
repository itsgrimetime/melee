#!/usr/bin/env python3
"""
Test script to validate the opseq synthesis approach.

This script:
1. Compiles a few template variations
2. Stores them in a test database
3. Does some lookups to see if matching works
"""

import sys
import tempfile
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parents[2]))

from src.opseq_synth.compiler import Compiler, CompileResult
from src.opseq_synth.contexts import ALL_CONTEXTS, GameLikeContext, MinimalContext
from src.opseq_synth.opcodes import OpcodeSequence
from src.opseq_synth.storage import OpcodeDB
from src.opseq_synth.templates import BRANCH_TEMPLATES, LOOP_TEMPLATES, Template


def test_single_compile():
    """Test compiling a single snippet."""
    print("=" * 60)
    print("TEST: Single compilation")
    print("=" * 60)

    compiler = Compiler()
    context = MinimalContext()

    snippet = """s32 i;
    for (i = 0; i < n; i++) {
        sum += arr[i];
    }"""

    result = compiler.compile_snippet(snippet, context, template_name="test_loop")

    if result.success:
        print("SUCCESS: Compiled snippet")
        print(f"Mnemonics ({len(result.opcodes.mnemonics)}): {','.join(result.opcodes.mnemonics[:20])}...")
        print(f"Normalized ({len(result.opcodes.normalized)}): {result.opcodes.normalized[:5]}...")
        print()
        print("ASM (target function):")
        print("-" * 40)
        # Print just the target function asm
        in_func = False
        for line in result.asm.splitlines():
            if "target_func" in line:
                in_func = True
            if in_func:
                print(line)
            if line.startswith(".endfn") and in_func:
                break
    else:
        print(f"FAILED: {result.error}")

    return result


def test_template_expansion():
    """Test expanding a template."""
    print("\n" + "=" * 60)
    print("TEST: Template expansion")
    print("=" * 60)

    # Pick a simple template
    template = LOOP_TEMPLATES[0]  # for_lt_inc
    print(f"Template: {template.name}")
    print(f"Description: {template.description}")
    print(f"Total combinations: {template.count()}")

    expansions = template.expand()
    print("\nFirst 3 expansions:")
    for i, exp in enumerate(expansions[:3]):
        print(f"\n--- Expansion {i + 1} ---")
        print(exp)

    return expansions


def test_compile_variations():
    """Compile several variations and compare opcodes."""
    print("\n" + "=" * 60)
    print("TEST: Compile variations")
    print("=" * 60)

    compiler = Compiler()
    context = MinimalContext()

    # Simple variations of the same loop
    variations = [
        (
            "for i++",
            """s32 i;
    for (i = 0; i < n; i++) {
        sum += arr[i];
    }""",
        ),
        (
            "for ++i",
            """s32 i;
    for (i = 0; i < n; ++i) {
        sum += arr[i];
    }""",
        ),
        (
            "for i+=1",
            """s32 i;
    for (i = 0; i < n; i += 1) {
        sum += arr[i];
    }""",
        ),
        (
            "while",
            """s32 i = 0;
    while (i < n) {
        sum += arr[i];
        i++;
    }""",
        ),
    ]

    results = []
    for name, snippet in variations:
        result = compiler.compile_snippet(snippet, context, template_name=name)
        if result.success:
            print(f"\n{name}:")
            print(f"  Mnemonics: {','.join(result.opcodes.mnemonics[:15])}...")
            print(f"  Length: {len(result.opcodes.mnemonics)} opcodes")
            print(f"  Hash: {result.opcodes.mnemonic_hash}")
            results.append((name, result))
        else:
            print(f"\n{name}: FAILED - {result.error}")

    # Compare hashes
    print("\n--- Hash comparison ---")
    hashes = [(name, r.opcodes.mnemonic_hash) for name, r in results]
    for name, h in hashes:
        print(f"  {name}: {h}")

    # Check which are identical
    unique_hashes = set(h for _, h in hashes)
    print(f"\nUnique patterns: {len(unique_hashes)} / {len(hashes)}")

    return results


def test_context_impact():
    """Test how different contexts affect code generation."""
    print("\n" + "=" * 60)
    print("TEST: Context impact on codegen")
    print("=" * 60)

    compiler = Compiler()

    snippet = """s32 i;
    for (i = 0; i < n; i++) {
        func(i);
    }"""

    results = []
    for context in ALL_CONTEXTS:
        result = compiler.compile_snippet(snippet, context, template_name="context_test")
        if result.success:
            print(f"\nContext: {context.name}")
            print(f"  Mnemonics: {','.join(result.opcodes.mnemonics[:15])}...")
            print(f"  Hash: {result.opcodes.mnemonic_hash}")
            results.append((context.name, result))
        else:
            print(f"\nContext: {context.name} - FAILED: {result.error}")

    # Compare
    unique = len(set(r.opcodes.mnemonic_hash for _, r in results))
    print(f"\nUnique patterns: {unique} / {len(results)} contexts")

    return results


def test_database_workflow():
    """Test the full database workflow."""
    print("\n" + "=" * 60)
    print("TEST: Database workflow")
    print("=" * 60)

    compiler = Compiler()
    context = MinimalContext()

    # Use a temp database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db = OpcodeDB(db_path)

    # Generate and store some samples
    print("\nGenerating samples...")
    template = LOOP_TEMPLATES[0]  # for_lt_inc
    expansions = template.expand()[:10]  # Just first 10 for testing

    stored = 0
    for i, snippet in enumerate(expansions):
        result = compiler.compile_snippet(snippet, context, template_name=template.name)
        if result.success:
            db.insert_sample(
                source=snippet,
                opcodes=result.opcodes,
                template_name=template.name,
                context_name=context.name,
                asm=result.asm,
            )
            stored += 1

    print(f"Stored {stored} samples")

    # Get stats
    stats = db.get_stats()
    print("\nDatabase stats:")
    print(f"  Total samples: {stats['total_samples']}")
    print(f"  N-grams: {stats['ngram_count']}")

    # Try a search
    print("\n--- Search test ---")

    # Compile a query snippet
    query_snippet = """s32 i;
    for (i = 0; i < n; i++) {
        sum += arr[i];
    }"""
    query_result = compiler.compile_snippet(query_snippet, context)

    if query_result.success:
        print(f"Query mnemonics: {','.join(query_result.opcodes.mnemonics[:10])}...")

        matches = db.search(query_result.opcodes, limit=5)
        print(f"\nFound {len(matches)} matches:")
        for m in matches:
            print(f"  - Score: {m.score:.3f}, Type: {m.match_type}")
            print(f"    Template: {m.sample.template_name}")
            print(f"    Snippet: {m.sample.source[:60]}...")

    db.close()

    # Clean up
    db_path.unlink()

    return stats


def test_register_normalization():
    """Test that register normalization works correctly."""
    print("\n" + "=" * 60)
    print("TEST: Register normalization")
    print("=" * 60)

    from src.opseq_synth.opcodes import normalize_instruction

    test_cases = [
        ("mr r3, r4", "mr rA, rB"),
        ("addi r3, r3, 1", "addi rA, rA, 1"),
        ("lwz r5, 0x10(r3)", "lwz rA, 0x10(rB)"),
        ("fmuls f1, f2, f3", "fmuls fA, fB, fC"),
        ("stw r0, 0x0(r1)", "stw rA, 0x0(rB)"),
    ]

    all_pass = True
    for input_instr, expected in test_cases:
        result = normalize_instruction(input_instr)
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  {status}: '{input_instr}' -> '{result}' (expected '{expected}')")

    return all_pass


def main():
    """Run all tests."""
    print("OPSEQ SYNTHESIS TEST SUITE")
    print("=" * 60)

    try:
        # Basic tests
        test_register_normalization()
        test_single_compile()
        test_template_expansion()

        # Variation tests (these take longer)
        test_compile_variations()
        test_context_impact()

        # Database test
        test_database_workflow()

        print("\n" + "=" * 60)
        print("ALL TESTS COMPLETED")
        print("=" * 60)

    except Exception as e:
        print("\n\nTEST FAILED WITH EXCEPTION:")
        print(f"  {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
