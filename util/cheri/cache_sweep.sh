#!/bin/sh
# Cache-size sweep: rerun a suite's experiment at several L1D and L2 sizes
# (one results directory per point), to see how much of purecap's cost is
# cache capacity. Each point is a normal run_all.sh run, so it reuses the
# suite's checkpoints (cache sizes do not affect them).
#
# Usage: util/cheri/cache_sweep.sh SUITE RESULTS [PREFIX]
#   SUITE   coremark | olden
#   PREFIX  results tag prefix (default sweep): points go to
#           RESULTS/<SUITE>/<PREFIX>-l1d<size>-l2<size>/
# Environment (defaults):
#   L2_SIZES    "128kB 512kB 1MB 2MB"   (L1D at its default, 16kB)
#   L1D_SIZES   "32kB 64kB"             (L2 at its default, 256kB)
#   CONFIGS     minor                   (no tag model: capacity only)
#   plus WORKLOADS, ABIS, JOBS, ITER, TIMEOUT of the suite's run_all.sh
# The default point (16kB L1D, 256kB L2) is the suite's main run; pass its
# directory to cache_sweep_collect.py with the sweep directories.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SUITE=${1:?usage: $0 coremark|olden RESULTS [PREFIX]}
RESULTS=${2:?usage: $0 coremark|olden RESULTS [PREFIX]}
PREFIX=${3:-sweep}
L2_SIZES=${L2_SIZES-128kB 512kB 1MB 2MB}
L1D_SIZES=${L1D_SIZES-32kB 64kB}
export CONFIGS=${CONFIGS:-minor}
case $SUITE in coremark|olden) ;; *) echo "SUITE: coremark or olden" >&2; exit 1;; esac

run_point() {
    echo "=== $SUITE: L1D $1, L2 $2"
    CHERI_L1D=$1 CHERI_L2=$2 "$HERE/$SUITE/run_all.sh" "$RESULTS" \
        "$PREFIX-l1d$1-l2$2"
}
for l2 in $L2_SIZES; do run_point 16kB "$l2"; done
for l1 in $L1D_SIZES; do run_point "$l1" 256kB; done
echo "next: util/cheri/cache_sweep_collect.py $RESULTS/$SUITE/<main run> $RESULTS/$SUITE/$PREFIX-*"
