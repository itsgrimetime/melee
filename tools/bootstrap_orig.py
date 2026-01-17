#!/usr/bin/env python3
"""
Bootstrap script to download original game files from a secure URL.

This script downloads the main.dol file required for building from a
pre-signed URL. The URL should be provided via environment variable
and should NEVER be committed to the repository.

Usage:
    # Set the URL (get from secure storage, expires after set time)
    export MELEE_DOL_URL="https://your-bucket.../main.dol?signature=..."

    # Run bootstrap
    python tools/bootstrap_orig.py

    # Then build normally
    python configure.py
    ninja

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


def main(skip_verify: bool = False) -> int:
    """Main entry point."""
    orig_dir = get_orig_dir()
    dol_path = orig_dir / DOL_FILENAME

    if skip_verify:
        print("WARNING: Hash verification disabled!", file=sys.stderr)

    # Check if file already exists
    if dol_path.exists():
        print(f"Found existing {dol_path}")

        if skip_verify:
            print("  Skipping hash verification.")
            print("  No download needed.")
            return 0

        # Verify hash
        actual_sha1 = sha1_file(dol_path)
        if actual_sha1.lower() == EXPECTED_DOL_SHA1.lower():
            print(f"  Hash verified: {actual_sha1}")
            print("  No download needed.")
            return 0
        else:
            print(f"  WARNING: Hash mismatch!", file=sys.stderr)
            print(f"    Expected: {EXPECTED_DOL_SHA1}", file=sys.stderr)
            print(f"    Got:      {actual_sha1}", file=sys.stderr)
            print("  Will re-download if URL is provided.", file=sys.stderr)

    # Check for URL
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

    print("\nBootstrap complete! You can now run:")
    print("  python configure.py")
    print("  ninja")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap original game files")
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip SHA-1 hash verification (use only for testing)",
    )
    args = parser.parse_args()
    sys.exit(main(skip_verify=args.skip_verify))
