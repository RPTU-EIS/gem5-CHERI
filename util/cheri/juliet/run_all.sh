#!/bin/sh
# Run the Juliet purecap/hybrid experiment and keep everything under one
# results root:
#   RESULTS/checkpoints/juliet-k<kernel hash>-{notag,tagged}/  (reused)
#   RESULTS/juliet/<TAG>/CWE<n>/<abi>-<config>/<shard>/        one gem5 run each
#   RESULTS/juliet/<TAG>/{manifest.json,results.csv,summary.csv,detection.csv}
#
# Usage: util/cheri/juliet/run_all.sh RESULTS [TAG]
#   TAG defaults to <date>-k<kernel hash>.
# Environment (defaults):
#   CHERI_KERNEL  tests/kernel        CHERI_DISK  tests/cheribsd-...img
#   BUILDS        ~/hiwi/juliet-gem5/out   (from build.py)
#   CONFIGS       atomic              CWES   all built (comma list)
#   JOBS          4                   TEST_TIMEOUT  1 (guest seconds)
#   MISALIGNED    emulate (or trap)
set -eu
GEM5=$(cd "$(dirname "$0")/../../.." && pwd)
RESULTS=$(mkdir -p "${1:?usage: $0 RESULTS [TAG]}" && cd "$1" && pwd)
KERNEL=${CHERI_KERNEL:-$GEM5/tests/kernel}
BUILDS=${BUILDS:-$HOME/hiwi/juliet-gem5/out}
CONFIGS=${CONFIGS:-atomic}
JOBS=${JOBS:-4}
TEST_TIMEOUT=${TEST_TIMEOUT:-1}
MISALIGNED=${MISALIGNED:-emulate}

khash=$(sha256sum "$KERNEL" | cut -c1-12)
TAG=${2:-$(date +%Y%m%d-%H%M)-k$khash}
OUT=$RESULTS/juliet/$TAG
mkdir -p "$RESULTS/checkpoints" "$RESULTS/juliet"

set -- --out "$OUT" --builds "$BUILDS" --configs "$CONFIGS" --jobs "$JOBS" \
    --test-timeout "$TEST_TIMEOUT" --misaligned "$MISALIGNED" \
    --checkpoint "$RESULTS/checkpoints/juliet-k$khash"
[ -n "${CWES:-}" ] && set -- "$@" --cwes "$CWES"

echo "results: $OUT"
python3 "$GEM5/util/cheri/juliet/run.py" "$@"
python3 "$GEM5/util/cheri/juliet/parse.py" "$OUT"
