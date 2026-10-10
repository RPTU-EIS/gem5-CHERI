#!/bin/sh
# Run the CoreMark-PRO purecap/hybrid experiment and keep everything under one
# results root:
#   RESULTS/checkpoints/ck-<kernel hash>-<binaries hash>-{notag,tagged}/
#                             (reused while kernel and binaries are unchanged)
#   RESULTS/coremark/<TAG>/<workload>/<abi>-<config>/   one gem5 run each
#   RESULTS/coremark/<TAG>/{manifest.json,results.csv,comparison.csv,
#                           all_stats.csv,tag_costs.csv}
#
# Usage: util/cheri/coremark/run_all.sh RESULTS [TAG]
#   TAG defaults to <date>-<kernel hash>.
# Environment (defaults):
#   CHERI_KERNEL  tests/kernel                CHERI_DISK  tests/cheribsd-...img
#   BUILDS        ~/hiwi/coremark-pro-gem5/builds   (from build.sh)
#   CONFIGS       atomic,minor,minor-passthrough,minor-flat,minor-hierarchical
#                 (CPU[-TAGMODEL]; tag model none if omitted)
#   ITER  1        JOBS  4
#   CORE_ARGS     -D=-I1  (core's 1000-iteration preset; empty = default)
#   plus any CHERI_L1D/L1I/L2/TAG_* knob of cheri-riscv-cheribsd-switch.py
set -eu
GEM5=$(cd "$(dirname "$0")/../../.." && pwd)
RESULTS=$(mkdir -p "${1:?usage: $0 RESULTS [TAG]}" && cd "$1" && pwd)
KERNEL=${CHERI_KERNEL:-$GEM5/tests/kernel}
BUILDS=${BUILDS:-$HOME/hiwi/coremark-pro-gem5/builds}
CONFIGS=${CONFIGS:-atomic,minor,minor-passthrough,minor-flat,minor-hierarchical}
ITER=${ITER:-1}
JOBS=${JOBS:-4}
CORE_ARGS=${CORE_ARGS--D=-I1}

khash=$(sha256sum "$KERNEL" | cut -c1-12)
bhash=$(cat "$BUILDS"/cheribsd-*/clang-cheribsd-*/bin/*.exe | sha256sum |
        cut -c1-12)
TAG=${2:-$(date +%Y%m%d-%H%M)-k$khash}
CKPT=$RESULTS/checkpoints/ck-k$khash-b$bhash
OUT=$RESULTS/coremark/$TAG
mkdir -p "$RESULTS/checkpoints" "$RESULTS/coremark"

set -- --out "$OUT" --builds "$BUILDS" --configs "$CONFIGS" --iterations "$ITER" \
    --jobs "$JOBS" --checkpoint "$CKPT"
[ -n "$CORE_ARGS" ] && set -- "$@" --wl-args "core=$CORE_ARGS"

echo "results:    $OUT"
echo "checkpoint: $CKPT"
python3 "$GEM5/util/cheri/coremark/run.py" "$@"
python3 "$GEM5/util/cheri/coremark/parse.py" "$OUT"
