#!/usr/bin/env bash
# Compatibility launcher for the branch-local bounded MWCC Ghidra setup CLI.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MWCC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MELEE_ROOT="$(cd "$MWCC_DIR/../.." && pwd)"

PYTHONPATH="${MELEE_ROOT}/tools/melee-agent${PYTHONPATH:+:${PYTHONPATH}}" \
  python -m src.cli debug retro ghidra-setup "$@"
