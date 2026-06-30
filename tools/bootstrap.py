#!/usr/bin/env python3
"""
Bootstrap script for the Melee decompilation environment.

This script sets up everything needed to start matching functions:
1. Downloads main.dol from a pre-signed URL
2. Runs configure.py to generate build files
3. Runs ninja to build the project
4. Prints workflow instructions

Usage:
    # Set the URL (get from secure storage, expires after set time)
    export MELEE_DOL_URL="https://your-bucket.../main.dol?signature=..."

    # Run bootstrap (does everything)
    python tools/bootstrap_orig.py

Environment Variables:
    MELEE_DOL_URL       Pre-signed URL to download main.dol from
    MELEE_ORIG_DIR      Override default orig/ directory (optional)

Security Notes:
    - NEVER commit URLs to git (they contain auth signatures)
    - URLs should be time-limited (1 hour recommended)
    - Use private storage (S3, R2, GCS) with pre-signed URLs
    - Add MELEE_DOL_URL to .gitignore patterns if using .env files
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from bootstrap_utils import download_file, sha1_file

# Expected file locations and checksums
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

# Default paths (can be overridden via MELEE_ORIG_DIR)
DEFAULT_ORIG_DIR = ROOT / "orig" / "GALE01" / "sys"
DOL_FILENAME = "main.dol"

# Known good SHA-1 hash of the NTSC 1.02 main.dol
# This ensures we don't accept corrupted or wrong files
EXPECTED_DOL_SHA1 = "08e0bf20134dfcb260699671004527b2d6bb1a45"


def get_orig_dir() -> Path:
    """Get the orig directory, allowing override via env var."""
    if env_dir := os.environ.get("MELEE_ORIG_DIR"):
        return Path(env_dir)
    return DEFAULT_ORIG_DIR


def run_build() -> bool:
    """Run configure.py and ninja to build the project."""
    print("\n" + "=" * 60)
    print("Building project...")
    print("=" * 60)

    # Run configure.py
    print("\nRunning configure.py...")
    result = subprocess.run([sys.executable, "configure.py"], cwd=ROOT)
    if result.returncode != 0:
        print("ERROR: configure.py failed", file=sys.stderr)
        return False

    # Run ninja
    print("\nRunning ninja...")
    result = subprocess.run(["ninja"], cwd=ROOT)
    if result.returncode != 0:
        print("ERROR: ninja build failed", file=sys.stderr)
        return False

    return True


def print_workflow_instructions():
    """Print instructions for matching functions."""
    print("\n" + "=" * 60)
    print("Setup complete! Ready to match functions.")
    print("=" * 60)
    print("""
WORKFLOW:
  1. Find a function to match in src/melee/
  2. Edit the source file to implement the function
  3. Check your progress:
     python tools/checkdiff.py <function_name>
  4. Iterate until 100% match

EXAMPLE:
  # Check diff for a function
  python tools/checkdiff.py my_function_80012345

  # The output shows:
  # - Left side: target assembly (what we want)
  # - Right side: your compiled code
  # - Goal: make them identical

TIPS:
  - Start with small functions (< 200 bytes)
  - Look at nearby matched functions for patterns
  - Check include/melee/ for struct definitions
  - Register allocation issues are common - try reordering variables
""")


def main(skip_verify: bool = False, skip_build: bool = False) -> int:
    """Main entry point."""
    orig_dir = get_orig_dir()
    dol_path = orig_dir / DOL_FILENAME
    dol_exists = False

    if skip_verify:
        print("WARNING: Hash verification disabled!", file=sys.stderr)

    # Check if file already exists
    if dol_path.exists():
        print(f"Found existing {dol_path}")

        if skip_verify:
            print("  Skipping hash verification.")
            dol_exists = True
        else:
            # Verify hash
            actual_sha1 = sha1_file(dol_path)
            if actual_sha1.lower() == EXPECTED_DOL_SHA1.lower():
                print(f"  Hash verified: {actual_sha1}")
                dol_exists = True
            else:
                print(f"  WARNING: Hash mismatch!", file=sys.stderr)
                print(f"    Expected: {EXPECTED_DOL_SHA1}", file=sys.stderr)
                print(f"    Got:      {actual_sha1}", file=sys.stderr)
                print("  Will re-download if URL is provided.", file=sys.stderr)

    # Download if needed
    if not dol_exists:
        dol_url = os.environ.get("MELEE_DOL_URL")
        if not dol_url:
            print("\nMissing required file and no download URL provided.", file=sys.stderr)
            print("\nTo bootstrap the build environment:", file=sys.stderr)
            print("  1. Upload main.dol to secure storage (S3, R2, etc.)", file=sys.stderr)
            print("  2. Generate a pre-signed URL", file=sys.stderr)
            print("  3. Set MELEE_DOL_URL environment variable", file=sys.stderr)
            print("  4. Run this script again", file=sys.stderr)
            print("\nExample:", file=sys.stderr)
            print("  export MELEE_DOL_URL='https://bucket.../main.dol?sig=...'", file=sys.stderr)
            print("  python tools/bootstrap_orig.py", file=sys.stderr)
            return 1

        # Validate URL doesn't look like it contains secrets that shouldn't be logged
        if "MELEE_DOL_URL" in dol_url:
            print("ERROR: URL appears to contain the literal string 'MELEE_DOL_URL'", file=sys.stderr)
            print("  Make sure to use the actual URL value, not the variable name.", file=sys.stderr)
            return 1

        # Download
        print(f"\nDownloading {DOL_FILENAME}...")
        expected_hash = None if skip_verify else EXPECTED_DOL_SHA1
        if not download_file(dol_url, dol_path, expected_hash):
            return 1

    # Build the project
    if not skip_build:
        if not run_build():
            return 1

    # Print workflow instructions
    print_workflow_instructions()

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap the Melee decompilation environment")
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip SHA-1 hash verification (use only for testing)",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip running configure.py and ninja (only download main.dol)",
    )
    args = parser.parse_args()
    sys.exit(main(skip_verify=args.skip_verify, skip_build=args.skip_build))
