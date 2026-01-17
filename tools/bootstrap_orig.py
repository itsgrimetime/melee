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
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

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


def sha1_file(path: Path) -> str:
    """Calculate SHA-1 hash of a file."""
    sha1 = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha1.update(chunk)
    return sha1.hexdigest()


def download_file(url: str, dest: Path, expected_sha1: str | None = None) -> bool:
    """
    Download a file from URL to destination.

    Args:
        url: URL to download from (should be pre-signed/authenticated)
        dest: Destination path
        expected_sha1: Optional SHA-1 hash to verify download

    Returns:
        True if download successful and verified
    """
    # Handle broken symlinks in the path - check each parent component
    for parent in list(reversed(dest.parents)):
        if parent.is_symlink() and not parent.exists():
            print(f"  Removing broken symlink: {parent}")
            parent.unlink()

    dest.parent.mkdir(parents=True, exist_ok=True)

    print(f"Downloading to {dest}...")
    print(f"  (URL not shown for security)")

    try:
        # Download with progress indication (update every 10%)
        last_percent_reported = [-1]  # Use list to allow mutation in nested function

        def report_progress(block_num, block_size, total_size):
            if total_size > 0:
                downloaded = block_num * block_size
                percent = min(100, downloaded * 100 // total_size)
                # Only report at 10% intervals to reduce noise
                report_threshold = (percent // 10) * 10
                if report_threshold > last_percent_reported[0]:
                    last_percent_reported[0] = report_threshold
                    mb_downloaded = downloaded / (1024 * 1024)
                    mb_total = total_size / (1024 * 1024)
                    print(f"  Progress: {percent}% ({mb_downloaded:.1f}/{mb_total:.1f} MB)")

        urllib.request.urlretrieve(url, dest, reporthook=report_progress)
        # Final 100% message if not already printed
        if last_percent_reported[0] < 100:
            print("  Progress: 100%")

    except urllib.error.HTTPError as e:
        print(f"\nError: HTTP {e.code} - {e.reason}", file=sys.stderr)
        if e.code == 403:
            print("  The URL may have expired. Generate a new pre-signed URL.", file=sys.stderr)
        elif e.code == 404:
            print("  File not found at the specified URL.", file=sys.stderr)
        return False
    except urllib.error.URLError as e:
        print(f"\nError: {e.reason}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return False

    # Verify hash if provided
    if expected_sha1:
        print("  Verifying SHA-1 hash...")
        actual_sha1 = sha1_file(dest)
        if actual_sha1.lower() != expected_sha1.lower():
            print(f"  ERROR: Hash mismatch!", file=sys.stderr)
            print(f"    Expected: {expected_sha1}", file=sys.stderr)
            print(f"    Got:      {actual_sha1}", file=sys.stderr)
            dest.unlink()  # Remove bad file
            return False
        print(f"  Verified: {actual_sha1}")

    print(f"  Downloaded successfully!")
    return True


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
