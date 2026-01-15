#!/usr/bin/env python3
"""
Pre-commit hook to prevent fork-only files from being committed.

These files are specific to itsgrimetime/melee and should never be
included in PRs to doldecomp/melee.
"""

import subprocess
import sys
from pathlib import Path


def get_fork_only_patterns() -> list[str]:
    """Load fork-only file patterns from manifest."""
    manifest = Path(__file__).parent.parent / ".github" / "fork-only-files.txt"
    if not manifest.exists():
        return []

    patterns = []
    for line in manifest.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def get_staged_files() -> list[str]:
    """Get list of staged files."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().splitlines() if result.stdout.strip() else []


def matches_pattern(filepath: str, pattern: str) -> bool:
    """Check if filepath matches a fork-only pattern."""
    # Directory pattern (ends with /)
    if pattern.endswith("/"):
        return filepath.startswith(pattern) or filepath + "/" == pattern
    # Exact file match
    return filepath == pattern


def main() -> int:
    patterns = get_fork_only_patterns()
    if not patterns:
        return 0

    staged_files = get_staged_files()
    violations = []

    for filepath in staged_files:
        for pattern in patterns:
            if matches_pattern(filepath, pattern):
                violations.append((filepath, pattern))
                break

    if violations:
        print("ERROR: Fork-only files detected in commit!")
        print()
        print("The following files are specific to itsgrimetime/melee")
        print("and should NOT be included in PRs to doldecomp/melee:")
        print()
        for filepath, pattern in violations:
            print(f"  - {filepath}")
        print()
        print("If you're working on the fork itself, use:")
        print("  git commit --no-verify")
        print()
        print("See .github/fork-only-files.txt for the full list.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
