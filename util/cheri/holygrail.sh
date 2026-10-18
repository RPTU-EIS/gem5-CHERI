#!/bin/sh
# The complete checkpoint-free experiment for one suite: every run boots
# CheriBSD from scratch (the boot is its own "[boot-stats]" stats dump, so
# boot and workload are reported separately), with per-privilege-mode stats
# and per-mnemonic instruction profiles (capability vs integer loads/stores)
# in every run. Stages, each a normal run_all.sh / sweep run under
# RESULTS/<SUITE>/:
#   main  <PREFIX>-main       plain, hybrid, purecap on Minor with every tag
#                             model (none, passthrough, nocache, flat,
#                             hierarchical) and the function profile
#                             (CHERI_PC_PROFILE): overheads, instruction mix,
#                             tag scatter, Olden phases, function breakdown
#   l2    <PREFIX>-l2-...     L2 size sweep (L1D at 16kB), plain + purecap
#   pf    <PREFIX>-pf-<pf>    prefetchers trained on misses, plain + purecap
#   pfacc <PREFIX>-pfacc-<pf> prefetchers trained on every access
#
# Usage: util/cheri/holygrail.sh SUITE RESULTS [PREFIX]
#   SUITE   olden | coremark          PREFIX  default hg
# Environment (defaults):
#   STAGES        "main l2 pf pfacc"
#   CHERI_KERNEL  tests/kernel-2026-nodebug
#   CHERI_DISK    tests/cheribsd-2026-riscv64-purecap.img
#   CHERI_VIRTIO_SEG_MAX  126 (CheriBSD 2026 needs it; 0 for 2024 setups)
#   MAIN_CONFIGS  minor,minor-passthrough,minor-nocache,minor-flat,
#                 minor-hierarchical
#   L2_SIZES      "128kB 512kB 1MB 2MB" (256kB is the main run)
#   PREFETCHERS   "none tagged ampm dcpt"  (stride, the default, is main)
#   ACC_PREFETCHERS "stride dcpt isb"
#   JOBS, TIMEOUT, WORKLOADS, REVOCATION, WORK / BUILDS as run_all.sh
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
GEM5=$(cd "$HERE/../.." && pwd)
SUITE=${1:?usage: $0 olden|coremark RESULTS [PREFIX]}
RESULTS=${2:?usage: $0 olden|coremark RESULTS [PREFIX]}
PREFIX=${3:-hg}
case $SUITE in olden|coremark) ;; *) echo "SUITE: olden or coremark" >&2; exit 1;; esac
STAGES=${STAGES-main l2 pf pfacc}

export NO_CHECKPOINT=1 CHERI_PRIV_STATS=1 CHERI_INST_PROFILE=1
export CHERI_KERNEL=${CHERI_KERNEL:-$GEM5/tests/kernel-2026-nodebug}
export CHERI_DISK=${CHERI_DISK:-$GEM5/tests/cheribsd-2026-riscv64-purecap.img}
export CHERI_VIRTIO_SEG_MAX=${CHERI_VIRTIO_SEG_MAX:-126}
for f in "$CHERI_KERNEL" "$CHERI_DISK"; do
    [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }
done
# Olden: per-binary phase boundaries (startup, build, compute, exit)
[ "$SUITE" = olden ] && export JOB_ENV=${JOB_ENV:-$HERE/olden/phase-pcs.json}

for stage in $STAGES; do
    case $stage in
    main)
        echo "=== $SUITE main batch"
        CONFIGS=${MAIN_CONFIGS:-minor,minor-passthrough,minor-nocache,minor-flat,minor-hierarchical} \
            ABIS=plain,hybrid,purecap CHERI_PC_PROFILE=1 \
            "$HERE/$SUITE/run_all.sh" "$RESULTS" "$PREFIX-main" ;;
    l2)
        ABIS=plain,purecap L1D_SIZES="" \
            L2_SIZES=${L2_SIZES-128kB 512kB 1MB 2MB} \
            "$HERE/cache_sweep.sh" "$SUITE" "$RESULTS" "$PREFIX-l2" ;;
    pf)
        ABIS=plain,purecap PREFETCHERS=${PREFETCHERS-none tagged ampm dcpt} \
            "$HERE/prefetch_sweep.sh" "$SUITE" "$RESULTS" "$PREFIX-pf" ;;
    pfacc)
        ABIS=plain,purecap CHERI_PF_ON_ACCESS=1 \
            PREFETCHERS=${ACC_PREFETCHERS-stride dcpt isb} \
            "$HERE/prefetch_sweep.sh" "$SUITE" "$RESULTS" "$PREFIX-pfacc" ;;
    *)
        echo "unknown stage $stage (main l2 pf pfacc)" >&2; exit 1 ;;
    esac
done
echo "done: $RESULTS/$SUITE/$PREFIX-*"
