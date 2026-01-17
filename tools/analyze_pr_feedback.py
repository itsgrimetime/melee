#!/usr/bin/env python3
"""
Analyze PR feedback to identify common issue categories for pre-commit/pre-push hooks.
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IssueCategory:
    name: str
    description: str
    patterns: list[str]
    examples: list[dict] = field(default_factory=list)
    hookable: bool = True  # Whether this can be caught by automated hooks
    hook_suggestion: str = ""


# Define issue categories based on reviewer feedback patterns
ISSUE_CATEGORIES = [
    # === HIGH PRIORITY - Frequently flagged issues ===
    IssueCategory(
        name="raw_pointer_arithmetic",
        description="Using raw pointer arithmetic instead of proper struct field access or M2C_FIELD macro",
        patterns=[
            r"M2C_FIELD",
            r"pointer arithmetic",
            r"raw access",
            r"\*\s*\(\s*\w+\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)",
            r"access the proper field",
            r"unreadable pointer math",
        ],
        hookable=True,
        hook_suggestion="""
# Check for raw pointer arithmetic patterns
git diff --cached -- '*.c' | grep -E '\\*(.*\\*)\\(\\(char\\*\\)' && echo "ERROR: Use M2C_FIELD or proper struct fields"
git diff --cached -- '*.c' | grep -E '\\*(.*\\*)\\(\\(u8\\*\\)' && echo "ERROR: Use M2C_FIELD or proper struct fields"
""",
    ),
    IssueCategory(
        name="true_false_case",
        description="Using TRUE/FALSE macros instead of lowercase true/false",
        patterns=[
            r"use.*true.*false",
            r"not.*TRUE.*FALSE",
            r"\\bTRUE\\b",
            r"\\bFALSE\\b",
            r"all-caps versions",
        ],
        hookable=True,
        hook_suggestion="""
# Check for TRUE/FALSE usage (should use true/false)
git diff --cached -- '*.c' '*.h' | grep -E '^\\+.*\\b(TRUE|FALSE)\\b' && echo "ERROR: Use lowercase true/false instead of TRUE/FALSE"
""",
    ),
    IssueCategory(
        name="unnecessary_casts",
        description="Unnecessary casts, especially HSD_GObj casts - fix argument types instead",
        patterns=[
            r"HSD_GObj cast",
            r"casts should be removed",
            r"cast.*removed",
            r"don't need to cast",
            r"cast doesn't seem valid",
            r"--no-casts",
        ],
        hookable=True,
        hook_suggestion="""
# Check for suspicious HSD_GObj casts that might indicate wrong types
git diff --cached -- '*.c' | grep -E '^\\+.*(HSD_GObj\\s*\\*)' | grep -v 'user_data' && echo "WARNING: Check if HSD_GObj cast is necessary"
""",
    ),
    IssueCategory(
        name="orig_folder_modified",
        description="Accidentally modifying the /orig folder or adding unexpected files",
        patterns=[
            r"orig/",
            r"forbid.*orig",
            r"\.build_validated",
        ],
        hookable=True,
        hook_suggestion="""
# Block modifications to /orig folder and unexpected files
git diff --cached --name-only | grep -E '^orig/|\\.build_validated' && echo "ERROR: Do not modify /orig folder or add .build_validated"
""",
    ),
    IssueCategory(
        name="local_extern_declarations",
        description="Using local extern declarations instead of including proper headers",
        patterns=[
            r"extern.*not.*worst",
            r"extern.*never necessary",
            r"include.*relevant header",
            r"goes in its header",
            r"should include.*instead of duplicating",
        ],
        hookable=True,
        hook_suggestion="""
# Flag new extern declarations in .c files (should use headers)
git diff --cached -- '*.c' | grep -E '^\\+\\s*extern\\s+' && echo "WARNING: Consider using header includes instead of local extern"
""",
    ),
    IssueCategory(
        name="struct_naming",
        description="Struct names should not be prefixed with underscores",
        patterns=[
            r"don't prefix struct names",
            r"struct _",
            r"underscore",
        ],
        hookable=True,
        hook_suggestion="""
# Check for underscore-prefixed struct names
git diff --cached -- '*.h' | grep -E '^\\+.*struct\\s+_' && echo "ERROR: Don't prefix struct names with underscores"
""",
    ),
    IssueCategory(
        name="wrong_argument_type",
        description="Function argument uses void* or wrong type when a specific type should be used",
        patterns=[
            r"change argument type",
            r"change the argument",
            r"just change the.*type",
            r"function takes.*argument",
        ],
        hookable=False,
        hook_suggestion="# Manual review needed - verify function signature matches callees",
    ),
    IssueCategory(
        name="wrong_return_type",
        description="Function returns wrong type (e.g., int instead of bool)",
        patterns=[
            r"returns.*bool",
            r"return type",
            r"return `bool`",
        ],
        hookable=False,
        hook_suggestion="# Manual review - check if function should return bool",
    ),
    IssueCategory(
        name="struct_field_missing",
        description="Struct needs a new field added instead of using offset arithmetic",
        patterns=[
            r"add.*field",
            r"create a type",
            r"filling in datatypes",
            r"add.*member",
            r"added to the.*struct",
            r"essential part of the decomp",
        ],
        hookable=True,
        hook_suggestion="""
# Check for suspicious offset patterns that should be struct fields
git diff --cached -- '*.c' | grep -E '^\\+.*->\\s*0x[0-9a-fA-F]+' && echo "WARNING: Consider adding struct field instead of offset"
""",
    ),
    IssueCategory(
        name="wrong_variable_type",
        description="Using wrong type for variable (e.g., u8* instead of GXColor)",
        patterns=[
            r"this is.*GXColor",
            r"this is `\w+`",
            r"change.*type.*to",
        ],
        hookable=False,
        hook_suggestion="# Manual review - use known SDK types like GXColor",
    ),
    IssueCategory(
        name="unused_code_added",
        description="Adding unused code from merges or that's no longer needed",
        patterns=[
            r"unused",
            r"not needed",
            r"came from.*merge",
        ],
        hookable=False,
        hook_suggestion="# Manual review - check for dead code after merges",
    ),
    IssueCategory(
        name="union_motion_vars",
        description="Fighter motion vars should use union ftXxx_MotionVars instead of raw offsets",
        patterns=[
            r"union.*MotionVars",
            r"ftCrazyHand_MotionVars",
        ],
        hookable=False,
        hook_suggestion="# Manual review - check fighter code for MotionVars usage",
    ),
    # === HEADER ORGANIZATION ===
    IssueCategory(
        name="include_path_style",
        description="Headers should use angle brackets with full paths, .c files can use relative",
        patterns=[
            r"relative includes don't work",
            r"fully qualifying",
            r"relative.*in C files",
            r"<melee/",
        ],
        hookable=True,
        hook_suggestion="""
# Check for relative includes in headers (should use angle brackets)
git diff --cached -- '*.h' | grep -E '^\\+\\s*#include\\s+"' && echo "WARNING: Headers should use angle bracket includes with full paths"
""",
    ),
    IssueCategory(
        name="types_h_in_header",
        description="Don't include types.h from headers - use forward declarations instead",
        patterns=[
            r"avoid including types.h from headers",
            r"forward.h",
            r"forward declaration",
        ],
        hookable=True,
        hook_suggestion="""
# Check for types.h includes in headers
git diff --cached -- '*.h' | grep -E '^\\+.*#include.*types\\.h' && echo "WARNING: Use forward declarations instead of including types.h in headers"
""",
    ),
    IssueCategory(
        name="static_h_in_header",
        description=".static.h files should only be included from .c files",
        patterns=[
            r"\.static\.h.*only.*\.c",
            r"static definitions",
        ],
        hookable=True,
        hook_suggestion="""
# Check for .static.h includes in headers
git diff --cached -- '*.h' | grep -E '^\\+.*#include.*\\.static\\.h' && echo "ERROR: .static.h should only be included from .c files"
""",
    ),
    IssueCategory(
        name="missing_include_guard",
        description="All headers need include guards",
        patterns=[
            r"need.*guard",
            r"include guard",
            r"guard clause",
            r"gen_header",
        ],
        hookable=True,
        hook_suggestion="""
# Check for missing include guards in headers
for f in $(git diff --cached --name-only -- '*.h'); do
    if ! grep -q '#ifndef' "$f"; then
        echo "ERROR: $f missing include guard"
    fi
done
""",
    ),
    # === CODE STYLE ===
    IssueCategory(
        name="empty_function_style",
        description="Empty void functions should use {} not { return; }",
        patterns=[
            r"\{\s*\}",
            r"empty.*function",
        ],
        hookable=True,
        hook_suggestion="""
# Check for { return; } in void functions
git diff --cached -- '*.c' | grep -E '^\\+.*void.*\\{\\s*return;\\s*\\}' && echo "WARNING: Empty void functions should use {} not { return; }"
""",
    ),
    IssueCategory(
        name="stack_padding_macro",
        description="Use PAD_STACK(n) instead of manual stack padding variables",
        patterns=[
            r"PAD_STACK",
            r"FORCE_PAD_STACK",
            r"stack padding",
        ],
        hookable=True,
        hook_suggestion="""
# Check for manual stack padding patterns
git diff --cached -- '*.c' | grep -E '^\\+.*int\\s+_?pad|\\+.*\\(void\\)\\s*_?pad' && echo "WARNING: Use PAD_STACK macro instead of manual padding"
""",
    ),
    IssueCategory(
        name="array_size_macro",
        description="Use ARRAY_SIZE(arr) instead of hardcoded array sizes",
        patterns=[
            r"ARRAY_SIZE",
        ],
        hookable=False,
        hook_suggestion="# Manual review - check for hardcoded sizes matching nearby arrays",
    ),
    IssueCategory(
        name="use_int_not_s32",
        description="Use int (or bool) instead of s32, use UNK_T instead of M2C_UNK",
        patterns=[
            r"use `int`.*instead of `s32`",
            r"UNK_T.*M2C_UNK",
        ],
        hookable=True,
        hook_suggestion="""
# Check for s32 and M2C_UNK usage
git diff --cached -- '*.c' '*.h' | grep -E '^\\+.*(\\bs32\\b|M2C_UNK)' && echo "WARNING: Use int instead of s32, UNK_T instead of M2C_UNK"
""",
    ),
    IssueCategory(
        name="math_header_include",
        description="Include <math_ppc.h> for math functions instead of defining locally",
        patterns=[
            r"math_ppc.h",
            r"sqrtf",
            r"don't copy.*include",
        ],
        hookable=True,
        hook_suggestion="""
# Check for local sqrtf definitions
git diff --cached -- '*.c' | grep -E '^\\+.*(extern|static).*sqrtf' && echo "ERROR: Include <math_ppc.h> instead of defining sqrtf locally"
""",
    ),
    # === DOCUMENTATION ===
    IssueCategory(
        name="doxygen_comments",
        description="Use Doxygen-style comments (/// or /** */) for documentation",
        patterns=[
            r"doxygen",
            r"@tag",
            r"///",
            r"/\*\*",
        ],
        hookable=False,
        hook_suggestion="# Manual review - use Doxygen format for API documentation",
    ),
    IssueCategory(
        name="placeholder_removal",
        description="Don't remove stub/placeholder function declarations from headers",
        patterns=[
            r"do not remove.*placeholder",
            r"function order",
            r"--require-protos",
        ],
        hookable=False,
        hook_suggestion="# Manual review - placeholders maintain function order",
    ),
    IssueCategory(
        name="descriptive_name_removed",
        description="Don't replace descriptive names with addresses",
        patterns=[
            r"more descriptive",
            r"why.*rename",
            r"seems more",
        ],
        hookable=False,
        hook_suggestion="# Manual review - keep descriptive symbol names",
    ),
    # === ITEM-SPECIFIC ===
    IssueCategory(
        name="item_state_table",
        description="ItemStateTable: use -1 instead of 0xFFFFFFFF, infer types from position",
        patterns=[
            r"ItemStateTable",
            r"-1.*0xFFFFFFFF",
            r"position within the table",
        ],
        hookable=True,
        hook_suggestion="""
# Check for 0xFFFFFFFF in ItemStateTable
git diff --cached -- '*.c' | grep -E '^\\+.*0xFFFFFFFF' && echo "WARNING: Use -1 instead of 0xFFFFFFFF in ItemStateTable"
""",
    ),
    IssueCategory(
        name="item_var_struct",
        description="Create item-specific var structs instead of reusing other items' structs",
        patterns=[
            r"item.*var.*struct",
            r"xDD4_itemVar",
            r"instead of reusing",
        ],
        hookable=False,
        hook_suggestion="# Manual review - item functions need their own ItemVars struct",
    ),
    # === BUILD/WORKFLOW ===
    IssueCategory(
        name="symbol_rename_mismatch",
        description="When renaming in symbols.txt, also rename the function definition",
        patterns=[
            r"rename.*corresponding",
            r"decomp.dev.*regressed",
        ],
        hookable=True,
        hook_suggestion="""
# CI check: symbol renames should include function definition renames
""",
    ),
    IssueCategory(
        name="use_m2c_tool",
        description="Use m2c decompiler with --valid-syntax flag",
        patterns=[
            r"did.*try.*m2c",
            r"running.*through m2c",
            r"--valid-syntax",
        ],
        hookable=False,
        hook_suggestion="# Workflow guidance - use m2c for initial decompilation",
    ),
    IssueCategory(
        name="wrong_assert_filename",
        description="Assert macro filename should match the inline header source",
        patterns=[
            r"filename in the assert",
            r"assert.*isn't correct",
            r"should be.*\.h",
        ],
        hookable=False,
        hook_suggestion="# Manual review - assert filenames indicate inline source",
    ),
    IssueCategory(
        name="gobj_wrapper_type",
        description="Don't create unnecessary GObj wrapper types - use HSD_GObj directly",
        patterns=[
            r"wrapper type for.*GObj",
            r"using it directly",
        ],
        hookable=False,
        hook_suggestion="# Manual review - avoid unnecessary wrapper types",
    ),
]


def categorize_comment(comment: dict) -> list[str]:
    """Categorize a comment based on its content."""
    body = comment.get("body", "").lower()
    matches = []

    for cat in ISSUE_CATEGORIES:
        for pattern in cat.patterns:
            if re.search(pattern, body, re.IGNORECASE):
                matches.append(cat.name)
                break

    return matches


# Associations that indicate collaborator/maintainer status
COLLABORATOR_ASSOCIATIONS = {"COLLABORATOR", "MEMBER", "OWNER"}


def analyze_feedback(comments: list[dict], collaborators_only: bool = False) -> dict:
    """Analyze all feedback and categorize issues."""
    # Filter to human reviewers
    human_comments = [c for c in comments if c["author"] not in ["decomp-dev[bot]"]]

    # Optionally filter to collaborators only
    if collaborators_only:
        human_comments = [
            c for c in human_comments
            if c.get("author_association", "NONE") in COLLABORATOR_ASSOCIATIONS
        ]

    category_counts = defaultdict(int)
    category_examples = defaultdict(list)
    uncategorized = []

    for comment in human_comments:
        categories = categorize_comment(comment)
        if not categories:
            uncategorized.append(comment)
        for cat in categories:
            category_counts[cat] += 1
            if len(category_examples[cat]) < 3:  # Keep up to 3 examples
                category_examples[cat].append({
                    "pr": comment["pr_number"],
                    "file": comment.get("path", ""),
                    "comment": comment["body"][:200],
                    "reviewer": comment["author"],
                })

    return {
        "category_counts": dict(category_counts),
        "category_examples": dict(category_examples),
        "uncategorized": uncategorized,
        "total_human_comments": len(human_comments),
    }


def generate_hooks_file(analysis: dict) -> str:
    """Generate a pre-commit hooks script based on analysis."""
    lines = [
        "#!/bin/bash",
        "# Pre-commit hooks for melee decompilation",
        "# Generated from PR feedback analysis",
        "",
        "set -e",
        "",
        "# Get list of staged C files",
        'STAGED_C_FILES=$(git diff --cached --name-only --diff-filter=ACMR | grep -E "\\.(c|h)$" || true)',
        "",
        'if [ -z "$STAGED_C_FILES" ]; then',
        '    exit 0',
        'fi',
        "",
    ]

    # Add checks for hookable categories
    for cat in ISSUE_CATEGORIES:
        if cat.hookable and cat.name in analysis["category_counts"]:
            count = analysis["category_counts"][cat.name]
            lines.append(f"# {cat.name} ({count} occurrences in PR feedback)")
            lines.append(f"# {cat.description}")
            if cat.hook_suggestion:
                lines.append(cat.hook_suggestion.strip())
            lines.append("")

    return "\n".join(lines)


def print_report(analysis: dict):
    """Print analysis report to console."""
    print("=" * 80)
    print("PR FEEDBACK ANALYSIS - Issue Categories for Hooks")
    print("=" * 80)
    print(f"\nTotal human reviewer comments: {analysis['total_human_comments']}")
    print(f"Categorized: {sum(analysis['category_counts'].values())}")
    print(f"Uncategorized: {len(analysis['uncategorized'])}")

    print("\n" + "-" * 60)
    print("ISSUE CATEGORIES (sorted by frequency)")
    print("-" * 60)

    sorted_cats = sorted(
        analysis["category_counts"].items(),
        key=lambda x: x[1],
        reverse=True
    )

    for cat_name, count in sorted_cats:
        cat = next((c for c in ISSUE_CATEGORIES if c.name == cat_name), None)
        if cat:
            hookable = "✓" if cat.hookable else "✗"
            print(f"\n[{hookable}] {cat_name}: {count} occurrences")
            print(f"    {cat.description}")

            if cat_name in analysis["category_examples"]:
                print("    Examples:")
                for ex in analysis["category_examples"][cat_name][:2]:
                    print(f"      - PR #{ex['pr']} ({ex['reviewer']}): {ex['comment'][:80]}...")

    print("\n" + "-" * 60)
    print("UNCATEGORIZED COMMENTS")
    print("-" * 60)
    for comment in analysis["uncategorized"][:5]:
        print(f"\nPR #{comment['pr_number']} ({comment['author']}):")
        print(f"  {comment['body'][:150]}...")

    print("\n" + "=" * 80)
    print("LEGEND: [✓] = Can be automated in hooks, [✗] = Requires manual review")
    print("=" * 80)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Analyze PR feedback for hook patterns")
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=Path("pr_feedback.json"),
        help="Input JSON file from fetch_pr_feedback.py"
    )
    parser.add_argument(
        "--hooks-output", "-o",
        type=Path,
        help="Output file for generated pre-commit hooks"
    )
    parser.add_argument(
        "--collaborators-only", "-c",
        action="store_true",
        help="Only analyze comments from collaborators/members/owners"
    )

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: {args.input} not found. Run fetch_pr_feedback.py first.")
        return 1

    with open(args.input) as f:
        comments = json.load(f)

    analysis = analyze_feedback(comments, collaborators_only=args.collaborators_only)
    print_report(analysis)

    if args.hooks_output:
        hooks_content = generate_hooks_file(analysis)
        with open(args.hooks_output, "w") as f:
            f.write(hooks_content)
        print(f"\nHooks script written to: {args.hooks_output}")


if __name__ == "__main__":
    main()
