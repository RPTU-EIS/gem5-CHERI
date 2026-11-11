#!/bin/sh
# Build the baseline kernels of bench.c as static, freestanding RV64GC ELFs
# (no CHERI instructions, no libc) with the CHERI SDK's clang.
#
# Usage: util/cheri/baseline/build.sh [OUT]     OUT default ~/hiwi/baseline-gem5
# Environment: SDK (default ~/cheri/output/sdk), KERNELS
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$HOME/hiwi/baseline-gem5}
SDK=${SDK:-$HOME/cheri/output/sdk}
KERNELS=${KERNELS:-ptrchase tree qsort matmul crc32 stream}
mkdir -p "$OUT/bin"
for k in $KERNELS; do
    K=$(echo "$k" | tr a-z A-Z)
    "$SDK/bin/clang" --target=riscv64-unknown-elf -march=rv64gc -mabi=lp64d \
        -mcmodel=medany -mno-relax -O2 -ffreestanding -fno-builtin \
        -nostdlib -static -fuse-ld=lld -Wl,-e,_start \
        -DKERNEL_"$K" -o "$OUT/bin/$k" "$HERE/bench.c"
    echo "built $OUT/bin/$k"
done
