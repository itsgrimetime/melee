#!/usr/bin/env python3
"""
Pre-push hook to prevent fork-only files from being pushed to upstream.

These files are specific to itsgrimetime/melee and should never be
included in PRs to doldecomp/melee.

Pre-push hooks receive:
- Args: remote_name, remote_url
- Stdin: lines of "<local_ref> <local_sha> <remote_ref> <remote_sha>"
"""

import subprocess
import sys
from pathlib import Path

# Remotes that should be blocked from receiving fork-only files
UPSTREAM_PATTERNS = [
    "doldecomp/melee",
    "doldecomp/melee.git",
]


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


def is_upstream_remote(remote_url: str) -> bool:
    """Check if the remote URL points to upstream (doldecomp/melee)."""
    for pattern in UPSTREAM_PATTERNS:
        if pattern in remote_url:
            return True
    return False


def get_files_in_range(base_sha: str, head_sha: str) -> list[str]:
    """Get list of files changed between two commits."""
    # Handle new branch (base_sha is all zeros)
    if base_sha == "0" * 40:
        # For new branches, compare against the remote's default branch
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", head_sha],
            capture_output=True,
            text=True,
        )
    else:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_sha, head_sha],
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
    # Pre-push hook receives remote name and URL as arguments
    if len(sys.argv) < 3:
        # Not running as pre-push hook, skip
        return 0

    remote_name = sys.argv[1]
    remote_url = sys.argv[2]

    # Only check pushes to upstream
    if not is_upstream_remote(remote_url):
        return 0

    patterns = get_fork_only_patterns()
    if not patterns:
        return 0

    # Read push info from stdin
    # Format: <local_ref> <local_sha> <remote_ref> <remote_sha>
    violations = []

    for line in sys.stdin:
        parts = line.strip().split()
        if len(parts) < 4:
            continue

        local_ref, local_sha, remote_ref, remote_sha = parts[:4]

        # Skip delete operations
        if local_sha == "0" * 40:
            continue

        # Get files that would be pushed
        files = get_files_in_range(remote_sha, local_sha)

        for filepath in files:
            for pattern in patterns:
                if matches_pattern(filepath, pattern):
                    if filepath not in [v[0] for v in violations]:
                        violations.append((filepath, pattern))
                    break

    if violations:
        print(f"ERROR: Refusing to push fork-only files to upstream!")
        print(f"       Remote: {remote_name} ({remote_url})")
        print()
        print("The following files are specific to itsgrimetime/melee")
        print("and should NOT be pushed to doldecomp/melee:")
        print()
        for filepath, pattern in violations:
            print(f"  - {filepath}")
        print()
        print("To push to upstream, create a clean branch without these files.")
        print("Use 'git push --no-verify' only if you're absolutely sure.")
        print()
        print("See .github/fork-only-files.txt for the full list.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
