#!/bin/sh
# Run the Olden purecap/hybrid experiment and keep everything under one
# results root (as util/cheri/coremark/run_all.sh):
#   RESULTS/checkpoints/olden-k<kernel hash>-b<binaries hash>-{notag,tagged}/
#   RESULTS/olden/<TAG>/<workload>/<abi>-<config>/      one gem5 run each
#   RESULTS/olden/<TAG>/{manifest.json,results.csv,comparison.csv,
#                        validation.csv,all_stats.csv,tag_costs.csv,plots/}
#
# Usage: util/cheri/olden/run_all.sh RESULTS [TAG]
#   TAG defaults to <date>-k<kernel hash>.
# Environment (defaults):
#   CHERI_KERNEL  tests/kernel        CHERI_DISK  tests/cheribsd-...img
#   WORK          ~/hiwi/olden-gem5   (from build.py)
#   CONFIGS       atomic,minor,minor-passthrough,minor-flat,minor-hierarchical
#   WORKLOADS     all built           JOBS  4
#   ABIS          all built (purecap,hybrid,plain); e.g. ABIS=plain
#   plus any CHERI_L1D/L1I/L2/TAG_* knob of cheri-riscv-cheribsd-switch.py
#   TIMEOUT       host seconds per gem5 run (default 48 h; Juliet 12 h)
#   CHECKPOINT    checkpoint base to use instead of the one named above,
#                 e.g. an existing ...-hybrid_plain_purecap one when running
#                 fewer ABIs (it may hold more binaries than needed)
#   JOB_ENV       run.py --job-env file, e.g. util/cheri/olden/phase-pcs.json
#                 (per-run CHERI_STATS_AT_PC phase boundaries)
set -eu
GEM5=$(cd "$(dirname "$0")/../../.." && pwd)
RESULTS=$(mkdir -p "${1:?usage: $0 RESULTS [TAG]}" && cd "$1" && pwd)
KERNEL=${CHERI_KERNEL:-$GEM5/tests/kernel}
WORK=${WORK:-$HOME/hiwi/olden-gem5}
CONFIGS=${CONFIGS:-atomic,minor,minor-passthrough,minor-flat,minor-hierarchical}
JOBS=${JOBS:-4}
ABIS=${ABIS:-$(python3 -c "import json,sys; print(','.join(json.load(open(sys.argv[1]))['abis']))" "$WORK/workloads.json")}

khash=$(sha256sum "$KERNEL" | cut -c1-12)
bhash=$(cat "$WORK"/builds/*/bin/* | sha256sum | cut -c1-12)
TAG=${2:-$(date +%Y%m%d-%H%M)-k$khash}
OUT=$RESULTS/olden/$TAG
mkdir -p "$RESULTS/checkpoints" "$RESULTS/olden"

CHECKPOINT=${CHECKPOINT:-$RESULTS/checkpoints/olden-k$khash-b$bhash-$(echo "$ABIS" | tr , _)}
set -- --out "$OUT" --work "$WORK" --configs "$CONFIGS" --jobs "$JOBS" \
    --abis "$ABIS" --checkpoint "$CHECKPOINT"
[ -n "${JOB_ENV:-}" ] && set -- "$@" --job-env "$JOB_ENV"
[ -n "${WORKLOADS:-}" ] && set -- "$@" --workloads "$WORKLOADS"

echo "results: $OUT"
[ -n "${TIMEOUT:-}" ] && set -- "$@" --timeout "$TIMEOUT"
python3 "$GEM5/util/cheri/olden/run.py" "$@"
python3 "$GEM5/util/cheri/olden/parse.py" "$OUT"
if python3 -c "import matplotlib, numpy" 2>/dev/null; then
    python3 "$GEM5/util/cheri/coremark/plot.py" "$OUT"
else
    echo "matplotlib/numpy missing: skipping plot.py"
fi
