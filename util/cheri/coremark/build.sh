#!/bin/sh
# Build CoreMark-PRO for CheriBSD RISC-V, purecap and hybrid, with the same
# CHERI LLVM and flags (-O2), for the gem5 CHERI experiments.
#
# The source tree is copied to a work directory and patched there (the
# original stays untouched); the platform/toolchain files in make/ are added.
#
# Usage: util/cheri/coremark/build.sh [SRC] [WORK]
#   SRC   CoreMark-PRO source  (default ~/hiwi/coremark-pro/coremark-pro)
#   WORK  build tree           (default ~/hiwi/coremark-pro-gem5)
#   env CHERI_SDK              (default ~/cheri/output/sdk)
#   env ABIS                   ABIs to (re)build (default "purecap hybrid
#                              plain"); others in WORK/builds are kept, e.g.
#                              ABIS=plain adds the plain RV64 baseline only
# Result: $WORK/builds/cheribsd-{purecap,hybrid,plain}/clang-cheribsd-*/bin/*.exe
#         and stripped copies in .../bin-stripped/
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${1:-$HOME/hiwi/coremark-pro/coremark-pro}
WORK=${2:-$HOME/hiwi/coremark-pro-gem5}
export CHERI_SDK=${CHERI_SDK:-$HOME/cheri/output/sdk}
ABIS=${ABIS:-purecap hybrid plain}

mkdir -p "$WORK"
rsync -a --delete --exclude builds --exclude '*:Zone.Identifier' \
    "$SRC"/ "$WORK"/
cp "$HERE"/make/*.mak "$WORK"/util/make/
for p in "$HERE"/patches/*.patch; do
    patch -d "$WORK" -p1 --forward --silent < "$p"
done
# plain RV64: 8-byte-word memcpy/memmove instead of the hybrid libc's
# tag-preserving ones (see util/cheri/common/memcpy64.c)
# (an archive: CoreMark-PRO's make adds LINKER_LAST twice)
MEMCPY64=$WORK/libmemcpy64.a
"$CHERI_SDK"/bin/clang --config cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg \
    -march=rv64imafdc -O2 -fno-builtin -c -o "$WORK"/memcpy64.o \
    "$HERE"/../common/memcpy64.c
rm -f "$MEMCPY64"
"$CHERI_SDK"/bin/llvm-ar rcs "$MEMCPY64" "$WORK"/memcpy64.o
for abi in $ABIS; do
    # CoreMark-PRO's make uses done.build stamps and ignores source changes
    # (e.g. a new patch), so always build these targets from clean.
    rm -rf "$WORK"/builds/cheribsd-$abi
    make -C "$WORK" TARGET=cheribsd-$abi CHERI_MEMCPY64="$MEMCPY64" build
done
# Stripped copies for the guest payload (run.py prefers them), so a machine
# without the SDK (e.g. a server the builds are copied to) ships small
# binaries too.
for bin in "$WORK"/builds/cheribsd-*/clang-cheribsd-*/bin; do
    mkdir -p "$bin-stripped"
    for exe in "$bin"/*.exe; do
        "$CHERI_SDK"/bin/llvm-strip -o "$bin-stripped/${exe##*/}" "$exe"
    done
done
ls -l "$WORK"/builds/cheribsd-*/clang-cheribsd-*/bin*/*.exe
