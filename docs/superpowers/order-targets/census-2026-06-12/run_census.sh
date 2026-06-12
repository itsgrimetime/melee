#!/bin/zsh
# Order-class pool census driver (2026-06-12).
# Runs `melee-agent debug target order-target` SEQUENTIALLY over the FULLNORM-0
# pool functions. Each derivation runs builds + (for register-only, conflict-free
# functions) a Step-3 minimal-set force search with diagnostic probes (~minutes
# to tens of minutes). The repo lock serializes anyway.
#
# Every routing is DATA. A Step-1 ValueError (checkdiff primary not register-only)
# is captured (non-zero exit + traceback in stderr). Each derivation is wrapped in
# `timeout` so the issue-#588 union-probe hang can't stall the whole census; a
# wall-clock timeout (exit 124) is recorded as an infrastructure-timeout outcome.
set -u
ROOT=/Users/mike/code/melee/.claude/worktrees/mndiagram-802427B4-investigation
CENSUS=$ROOT/docs/superpowers/order-targets/census-2026-06-12
WALL=${WALL:-1500}   # per-function wall-clock cap (seconds)
cd "$ROOT" || exit 1

for fn in "$@"; do
  echo "==== START $fn $(date -u +%H:%M:%S) WALL=${WALL}s ===="
  /opt/homebrew/bin/timeout --signal=TERM --kill-after=20 "$WALL" \
    melee-agent debug target order-target -f "$fn" --json \
      --out "$CENSUS/$fn.yaml" \
      > "$CENSUS/$fn.json" 2> "$CENSUS/$fn.stderr.log"
  rc=$?
  echo "EXIT=$rc" >> "$CENSUS/$fn.stderr.log"
  echo "==== DONE  $fn EXIT=$rc $(date -u +%H:%M:%S) ===="
  # clean any stray pcdump temps the killed run left in the worktree root
  find "$ROOT" -maxdepth 1 -name 'pcdump_*.txt' -delete 2>/dev/null
done
echo "==== CENSUS BATCH COMPLETE $(date -u +%H:%M:%S) ===="
