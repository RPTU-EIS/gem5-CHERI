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
# Result: $WORK/builds/cheribsd-{purecap,hybrid}/clang-cheribsd-*/bin/*.exe
#         and stripped copies in .../bin-stripped/
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${1:-$HOME/hiwi/coremark-pro/coremark-pro}
WORK=${2:-$HOME/hiwi/coremark-pro-gem5}
export CHERI_SDK=${CHERI_SDK:-$HOME/cheri/output/sdk}

mkdir -p "$WORK"
rsync -a --delete --exclude builds --exclude '*:Zone.Identifier' \
    "$SRC"/ "$WORK"/
cp "$HERE"/make/*.mak "$WORK"/util/make/
for p in "$HERE"/patches/*.patch; do
    patch -d "$WORK" -p1 --forward --silent < "$p"
done
for abi in purecap hybrid; do
    # CoreMark-PRO's make uses done.build stamps and ignores source changes
    # (e.g. a new patch), so always build these targets from clean.
    rm -rf "$WORK"/builds/cheribsd-$abi
    make -C "$WORK" TARGET=cheribsd-$abi build
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
