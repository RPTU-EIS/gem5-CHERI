#!/bin/sh
# Tag-cache size sweep, the counterpart of Joannou et al., "Efficient Tagged
# Memory" (ICCD 2017), Fig. 2: rerun a suite at several leaf tag-cache sizes
# (one results directory per point) to see how the tag table's DRAM traffic
# overhead depends on the tag cache. Their figure is trace driven (DRAM
# traffic only, no timing), so the default CPU is atomic: the tag
# controller counts the same tag-table reads and writes in atomic mode, at
# a fraction of Minor's cost. tagcache_sweep_collect.py gathers the points.
#
# Usage: util/cheri/tagcache_sweep.sh SUITE RESULTS [PREFIX]
#   SUITE   coremark | olden | tagval
#   PREFIX  results tag prefix (default tc): points go to
#           RESULTS/<SUITE>/<PREFIX>-<size>/
# Environment (defaults):
#   TAG_CACHES  "4KiB 8KiB 16KiB 32KiB 64KiB 128KiB 256KiB 512KiB 1MiB"
#   CONFIGS     atomic-flat,atomic-hierarchical  (flat: their uncompressed
#               table; hierarchical: their two-level table, GF 512)
#   ABIS        plain,purecap
#   plus WORKLOADS, JOBS, TIMEOUT, NO_CHECKPOINT of the suite's run_all.sh
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SUITE=${1:?usage: $0 coremark|olden|tagval RESULTS [PREFIX]}
RESULTS=${2:?usage: $0 coremark|olden|tagval RESULTS [PREFIX]}
PREFIX=${3:-tc}
TAG_CACHES=${TAG_CACHES-4KiB 8KiB 16KiB 32KiB 64KiB 128KiB 256KiB 512KiB 1MiB}
export CONFIGS=${CONFIGS:-atomic-flat,atomic-hierarchical}
export ABIS=${ABIS:-plain,purecap}
case $SUITE in coremark|olden|tagval) ;; *) echo "SUITE: coremark, olden or tagval" >&2; exit 1;; esac

for size in $TAG_CACHES; do
    echo "=== $SUITE: leaf tag cache $size"
    CHERI_TAG_CACHE=$size "$HERE/$SUITE/run_all.sh" "$RESULTS" \
        "$PREFIX-$size"
done
echo "next: util/cheri/tagcache_sweep_collect.py $RESULTS/$SUITE/$PREFIX-*"
