#!/bin/sh
# Baseline check: every kernel on every CPU model with each simulator build,
# one gem5 run per point in OUT/<build>/<cpu>/<kernel>/ (gem5's stdout, with
# the kernel's checksum, in run.log). compare.py OUT tabulates them.
#
# Usage: util/cheri/baseline/run.sh OUT
# Environment (defaults):
#   BUILDS   "stock=~/hiwi/gem5-stock-v24/build/RISCV/gem5.opt:riscv
#             tree=<this tree>/build/RISCV/gem5.opt:riscv
#             cheri=<this tree>/build/RISCV_CHERI/gem5.opt:riscv_cheri"
#            (name=binary:isa; builds whose binary is missing are skipped)
#   CPUS     "atomic minor o3"
#   KERNELS  "ptrchase tree qsort matmul crc32 stream"
#   BIN      ~/hiwi/baseline-gem5/bin (build.sh)        JOBS  4
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
GEM5=$(cd "$HERE/../../.." && pwd)
OUT=$(mkdir -p "${1:?usage: $0 OUT}" && cd "$1" && pwd)
BUILDS=${BUILDS:-"stock=$HOME/hiwi/gem5-stock-v24/build/RISCV/gem5.opt:riscv tree=$GEM5/build/RISCV/gem5.opt:riscv cheri=$GEM5/build/RISCV_CHERI/gem5.opt:riscv_cheri"}
CPUS=${CPUS:-atomic minor o3}
KERNELS=${KERNELS:-ptrchase tree qsort matmul crc32 stream}
BIN=${BIN:-$HOME/hiwi/baseline-gem5/bin}
JOBS=${JOBS:-4}

for b in $BUILDS; do
    name=${b%%=*}; rest=${b#*=}; exe=${rest%:*}; isa=${rest##*:}
    if [ ! -x "$exe" ]; then
        echo "skipping $name: no $exe" >&2
        continue
    fi
    for cpu in $CPUS; do
        for k in $KERNELS; do
            d=$OUT/$name/$cpu/$k
            mkdir -p "$d"
            echo "$exe --outdir $d $HERE/se.py --isa $isa --cpu $cpu --binary $BIN/$k > $d/run.log 2>&1"
        done
    done
done | xargs -P "$JOBS" -I{} sh -c '{}' ||
    echo "some runs failed: see their run.log (compare.py lists them)" >&2
echo "next: util/cheri/baseline/compare.py $OUT"
