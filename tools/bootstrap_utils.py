#!/usr/bin/env python3
"""
Shared utilities for bootstrap scripts.

Provides common functionality for downloading and verifying files
from pre-signed URLs.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BootstrapFile:
    """Definition of a file to bootstrap."""
    name: str
    env_var: str
    dest: Path
    expected_sha1: str | None = None
    description: str = ""


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


def verify_file(path: Path, expected_sha1: str | None) -> bool:
    """
    Verify a file exists and has correct hash.

    Args:
        path: Path to file
        expected_sha1: Expected SHA-1 hash (if None, only checks existence)

    Returns:
        True if file exists and hash matches (or no hash check required)
    """
    if not path.exists():
        return False

    if expected_sha1:
        actual_sha1 = sha1_file(path)
        return actual_sha1.lower() == expected_sha1.lower()

    return True
