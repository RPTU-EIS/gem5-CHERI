#!/bin/sh
# Rebuild bin/ from src/ with the CHERI SDK: each example as a static
# CheriBSD binary, purecap and plain RV64 (RV64GC code on the hybrid libc),
# and two freestanding RV64GC kernels of ../baseline/bench.c for SE mode.
#
# Usage: util/cheri/examples/build.sh
# Environment: SDK (default ~/cheri/output/sdk)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SDK=${SDK:-$HOME/cheri/output/sdk}
CC=$SDK/bin/clang
mkdir -p "$HERE/bin/se"

for p in hello bounds list; do
    "$CC" --config cheribsd-riscv64-purecap.cfg -O2 -static \
        -o "$HERE/bin/$p-purecap" "$HERE/src/$p.c"
    "$CC" --config cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg \
        -march=rv64imafdc -O2 -static \
        -o "$HERE/bin/$p-plain" "$HERE/src/$p.c"
done
"$SDK/bin/llvm-strip" "$HERE"/bin/*-purecap "$HERE"/bin/*-plain

for k in ptrchase matmul; do
    K=$(echo "$k" | tr a-z A-Z)
    "$CC" --target=riscv64-unknown-elf -march=rv64gc -mabi=lp64d \
        -mcmodel=medany -mno-relax -O2 -ffreestanding -fno-builtin \
        -nostdlib -static -fuse-ld=lld -Wl,-e,_start \
        -DKERNEL_"$K" -o "$HERE/bin/se/$k" "$HERE/../baseline/bench.c"
done
ls -l "$HERE"/bin "$HERE"/bin/se
