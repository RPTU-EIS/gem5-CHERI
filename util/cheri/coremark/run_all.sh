#!/bin/sh
# Run the CoreMark-PRO purecap/hybrid experiment and keep everything under one
# results root:
#   RESULTS/checkpoints/ck-<kernel hash>-<binaries hash>-{notag,tagged}/
#                             (reused while kernel and binaries are unchanged)
#   RESULTS/coremark/<TAG>/<workload>/<abi>-<config>/   one gem5 run each
#   RESULTS/coremark/<TAG>/{manifest.json,results.csv,comparison.csv,
#                           all_stats.csv,tag_costs.csv,plots/}
#
# Usage: util/cheri/coremark/run_all.sh RESULTS [TAG]
#   TAG defaults to <date>-<kernel hash>.
# Environment (defaults):
#   CHERI_KERNEL  tests/kernel                CHERI_DISK  tests/cheribsd-...img
#   BUILDS        ~/hiwi/coremark-pro-gem5/builds   (from build.sh)
#   CONFIGS       atomic,minor,minor-passthrough,minor-flat,minor-hierarchical
#                 (CPU[-TAGMODEL]; tag model none if omitted)
#   ABIS          purecap,hybrid,plain (e.g. ABIS=plain adds only the plain
#                 RV64 baseline to existing purecap/hybrid results; merge with
#                 parse.py OUT_OLD OUT_NEW --into DIR)
#   WORKLOADS     all nine (comma list)
#   ITER  1        JOBS  4
#   CORE_ARGS     -D=-I1  (core's 1000-iteration preset; empty = default)
#   plus any CHERI_L1D/L1I/L2/TAG_* knob of cheri-riscv-cheribsd-switch.py
#   TIMEOUT       host seconds per gem5 run (default 48 h; Juliet 12 h)
#   NO_CHECKPOINT 1: no checkpoint, every run boots (boot kept as its own
#                 stats dump)     CHECKPOINT  checkpoint base override
#   REVOCATION    run.py --revocation: default | on | off
set -eu
GEM5=$(cd "$(dirname "$0")/../../.." && pwd)
RESULTS=$(mkdir -p "${1:?usage: $0 RESULTS [TAG]}" && cd "$1" && pwd)
KERNEL=${CHERI_KERNEL:-$GEM5/tests/kernel}
BUILDS=${BUILDS:-$HOME/hiwi/coremark-pro-gem5/builds}
CONFIGS=${CONFIGS:-atomic,minor,minor-passthrough,minor-flat,minor-hierarchical}
ABIS=${ABIS:-purecap,hybrid,plain}
ITER=${ITER:-1}
JOBS=${JOBS:-4}
CORE_ARGS=${CORE_ARGS--D=-I1}

khash=$(sha256sum "$KERNEL" | cut -c1-12)
bhash=$(cat "$BUILDS"/cheribsd-*/clang-cheribsd-*/bin/*.exe | sha256sum |
        cut -c1-12)
TAG=${2:-$(date +%Y%m%d-%H%M)-k$khash}
CKPT=$RESULTS/checkpoints/ck-k$khash-b$bhash-$(echo "$ABIS" | tr , _)
OUT=$RESULTS/coremark/$TAG
mkdir -p "$RESULTS/checkpoints" "$RESULTS/coremark"

CKPT=${CHECKPOINT:-$CKPT}
set -- --out "$OUT" --builds "$BUILDS" --abis "$ABIS" --configs "$CONFIGS" --iterations "$ITER" \
    --jobs "$JOBS"
# NO_CHECKPOINT=1: every run boots CheriBSD itself (run.py without
# --checkpoint); the boot is recorded as its own stats dump
[ "${NO_CHECKPOINT:-0}" = 1 ] || set -- "$@" --checkpoint "$CKPT"
[ -n "${REVOCATION:-}" ] && set -- "$@" --revocation "$REVOCATION"
[ -n "$CORE_ARGS" ] && set -- "$@" --wl-args "core=$CORE_ARGS"
[ -n "${WORKLOADS:-}" ] && set -- "$@" --workloads "$WORKLOADS"

echo "results:    $OUT"
echo "checkpoint: $CKPT"
[ -n "${TIMEOUT:-}" ] && set -- "$@" --timeout "$TIMEOUT"
python3 "$GEM5/util/cheri/coremark/run.py" "$@"
python3 "$GEM5/util/cheri/coremark/parse.py" "$OUT"
if python3 -c "import matplotlib, numpy" 2>/dev/null; then
    python3 "$GEM5/util/cheri/coremark/plot.py" "$OUT"
else
    echo "matplotlib/numpy missing: skipping plot.py"
fi
