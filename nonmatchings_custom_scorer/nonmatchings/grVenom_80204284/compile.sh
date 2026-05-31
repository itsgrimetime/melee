#!/usr/bin/env bash
# Wrapped by melee-agent debug permute setup-simplify-order-scorer
set -e
INPUT_ABS="$(realpath "$1")"
OUTPUT_ABS="$(realpath "$3")"
cd /Users/mike/code/melee
STAGE="nonmatchings/.permuter_stage_$$.c"
mkdir -p nonmatchings
cp "$INPUT_ABS" "$STAGE"
trap 'rm -f "$STAGE"' EXIT
# Deposit the pcdump as a sibling of the .o so
# `debug target score-simplify-order` finds it via the fast path.
export MWCC_DEBUG_PCDUMP_PATH="${OUTPUT_ABS}.pcdump.txt"
/Users/mike/code/melee/tools/mwcc_debug/bin/wibo /Users/mike/code/melee/build/compilers/GC/1.2.5n/mwcceppc_debug.exe -Cpp_exceptions off -proc gekko -fp hard -fp_contract on -O4,p -enum int -nodefaults -inline auto -c "$STAGE" -o "$OUTPUT_ABS"
