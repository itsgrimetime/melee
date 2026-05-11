#!/usr/bin/env python3
"""
Bootstrap script to download PPC reference PDFs from a secure URL.

This script downloads the PDF reference manuals required by the /ppc-ref skill.
URLs should be provided via environment variables and should NEVER be committed.

Usage:
    # Set the URLs (get from secure storage, expires after set time)
    export PPC_REF_750CL_URL="https://your-bucket.../ppc_750cl.pdf?signature=..."
    export PPC_REF_CWG_URL="https://your-bucket.../powerpc-cwg.pdf?signature=..."
    export PPC_REF_MPC5XX_URL="https://your-bucket.../MPC5xxUG.pdf?signature=..."

    # Run bootstrap
    python tools/bootstrap_ppc_ref.py

    # Then use ppc-ref normally
    python tools/ppc-ref.py instr lwz

Environment Variables:
    PPC_REF_750CL_URL   Pre-signed URL for ppc_750cl.pdf (IBM PowerPC 750CL Manual)
    PPC_REF_CWG_URL     Pre-signed URL for powerpc-cwg.pdf (Compiler Writer's Guide)
    PPC_REF_MPC5XX_URL  Pre-signed URL for MPC5xxUG.pdf (CodeWarrior Targeting Manual)
    PPC_REF_DIR         Override default PDF directory (optional)

Security Notes:
    - NEVER commit URLs to git (they contain auth signatures)
    - URLs should be time-limited (1 hour recommended)
    - Use private storage (S3, R2, GCS) with pre-signed URLs
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from bootstrap_utils import BootstrapFile, download_file, sha1_file, verify_file

# Expected file locations
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

# Default paths (can be overridden via PPC_REF_DIR)
DEFAULT_PPC_REF_DIR = ROOT / ".claude" / "skills" / "ppc-ref"

# PDF definitions with known SHA-1 hashes
PDF_FILES = [
    BootstrapFile(
        name="ppc_750cl.pdf",
        env_var="PPC_REF_750CL_URL",
        dest=Path(),  # Set dynamically based on PPC_REF_DIR
        expected_sha1="0e701abd46ae6e3a72432337e6671564180e8103",
        description="IBM PowerPC 750CL User's Manual (primary reference)",
    ),
    BootstrapFile(
        name="powerpc-cwg.pdf",
        env_var="PPC_REF_CWG_URL",
        dest=Path(),
        expected_sha1="7c5e841245b5869cc19367a2fd6ec2b711c6e430",
        description="IBM PowerPC Compiler Writer's Guide",
    ),
    BootstrapFile(
        name="MPC5xxUG.pdf",
        env_var="PPC_REF_MPC5XX_URL",
        dest=Path(),
        expected_sha1="f836aefdd1a6c61c353652448b0cf0e34290a8c7",
        description="CodeWarrior MPC5xx Targeting Manual",
    ),
]


def get_ppc_ref_dir() -> Path:
    """Get the PPC reference directory, allowing override via env var."""
    if env_dir := os.environ.get("PPC_REF_DIR"):
        return Path(env_dir)
    return DEFAULT_PPC_REF_DIR


def main() -> int:
    """Main entry point."""
    ppc_ref_dir = get_ppc_ref_dir()

    # Update destinations based on directory
    for pdf in PDF_FILES:
        pdf.dest = ppc_ref_dir / pdf.name

    downloaded = 0
    skipped = 0
    failed = 0
    no_url = 0

    for pdf in PDF_FILES:
        print(f"\n--- {pdf.name} ---")
        print(f"    {pdf.description}")

        # Check if file already exists and is valid
        if pdf.dest.exists():
            if verify_file(pdf.dest, pdf.expected_sha1):
                print(f"  Already exists with valid hash, skipping.")
                skipped += 1
                continue
            else:
                print(f"  Exists but hash mismatch, will re-download if URL provided.")

        # Check for URL
        url = os.environ.get(pdf.env_var)
        if not url:
            print(f"  No URL provided ({pdf.env_var} not set).")
            if not pdf.dest.exists():
                no_url += 1
            continue

        # Validate URL doesn't look like it contains the variable name
        if pdf.env_var in url:
            print(f"  ERROR: URL appears to contain the literal string '{pdf.env_var}'", file=sys.stderr)
            print(f"    Make sure to use the actual URL value, not the variable name.", file=sys.stderr)
            failed += 1
            continue

        # Download
        if download_file(url, pdf.dest, pdf.expected_sha1):
            downloaded += 1
        else:
            failed += 1

    # Summary
    print("\n" + "=" * 50)
    print("Bootstrap Summary:")
    print(f"  Downloaded: {downloaded}")
    print(f"  Skipped (already present): {skipped}")
    print(f"  Failed: {failed}")
    print(f"  No URL provided: {no_url}")

    total_present = sum(1 for pdf in PDF_FILES if pdf.dest.exists())
    print(f"\nPDFs available: {total_present}/{len(PDF_FILES)}")

    if total_present == len(PDF_FILES):
        print("\nAll PDFs present! You can now use:")
        print("  python tools/ppc-ref.py sources")
        print("  python tools/ppc-ref.py instr lwz")
        return 0
    elif total_present > 0:
        print("\nSome PDFs available. Missing:")
        for pdf in PDF_FILES:
            if not pdf.dest.exists():
                print(f"  - {pdf.name} (set {pdf.env_var})")
        return 0
    else:
        print("\nNo PDFs available. To download, set environment variables:")
        for pdf in PDF_FILES:
            print(f"  export {pdf.env_var}='https://your-bucket/.../{pdf.name}?sig=...'")
        print("\nThen run this script again.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
