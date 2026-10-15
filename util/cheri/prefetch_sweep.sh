#!/bin/sh
# Prefetcher sweep: rerun a suite's experiment once per hardware prefetcher
# (the same prefetcher at L1D and L2; one results directory per point), to
# see which purecap memory stalls stock prefetchers recover. Each point is
# a normal run_all.sh run, so it reuses the suite's checkpoints (prefetchers
# do not affect them). The default prefetcher (stride, trained on misses) is
# the suite's main run.
#
# Usage: util/cheri/prefetch_sweep.sh SUITE RESULTS [PREFIX]
#   SUITE   olden | coremark
#   PREFIX  results tag prefix (default pf): points go to
#           RESULTS/<SUITE>/<PREFIX>-<prefetcher>/
# Environment (defaults):
#   PREFETCHERS  "none tagged bop ampm dcpt isb"  (CHERI_L1D_PF/CHERI_L2_PF
#                values; indirect and spp panic in this gem5 version:
#                tagged_entry.hh "Need is_secure arg")
#   CONFIGS      minor
#   plus WORKLOADS, ABIS, JOBS, TIMEOUT, CHECKPOINT, JOB_ENV of the suite's
#   run_all.sh and any CHERI_* knob (e.g. CHERI_PRIV_STATS=1,
#   CHERI_PF_ON_ACCESS=1)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SUITE=${1:?usage: $0 olden|coremark RESULTS [PREFIX]}
RESULTS=${2:?usage: $0 olden|coremark RESULTS [PREFIX]}
PREFIX=${3:-pf}
PREFETCHERS=${PREFETCHERS-none tagged bop ampm dcpt isb}
export CONFIGS=${CONFIGS:-minor}
case $SUITE in olden|coremark) ;; *) echo "SUITE: olden or coremark" >&2; exit 1;; esac

for pf in $PREFETCHERS; do
    echo "=== $SUITE: L1D and L2 prefetcher $pf"
    CHERI_L1D_PF=$pf CHERI_L2_PF=$pf "$HERE/$SUITE/run_all.sh" "$RESULTS" \
        "$PREFIX-$pf"
done
