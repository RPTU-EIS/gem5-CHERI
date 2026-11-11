#!/bin/sh
# Build gem5's m5 utility for CheriBSD (purecap, static) and install it with
# m5_init.sh into cheribuild's extra-files directory, which
# `cheribuild.py disk-image-riscv64-purecap` copies into the disk image.
# The configs boot with init_script=/etc/m5_init.sh: it runs the file that
# `m5 readfile` returns (CHERI_READFILE), then ends the simulation.
#
# Usage: util/cheri/guest/build_m5.sh [EXTRA_FILES]
#   EXTRA_FILES  default ~/cheri/extra-files (cheribuild's default)
# Environment: SDK (default ~/cheri/output/sdk)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
GEM5=$(cd "$HERE/../../.." && pwd)
X=${1:-$HOME/cheri/extra-files}
SDK=${SDK:-$HOME/cheri/output/sdk}
CFG="--config cheribsd-riscv64-purecap.cfg"
INC="-I. -I$GEM5/include"
B=$(mktemp -d)
trap 'rm -rf "$B"' EXIT

cd "$GEM5/util/m5/src"
objs=
for f in args.cc call_type.cc command.cc m5.cc usage.cc \
        $(ls command/*.cc | grep -v test); do
    o=$B/$(echo "$f" | tr / _).o
    "$SDK/bin/clang++" $CFG -O2 -std=c++17 $INC -c "$f" -o "$o"
    objs="$objs $o"
done
"$SDK/bin/clang++" $CFG -O2 -std=c++17 $INC -DCALL_TYPE_IS_DEFAULT=true \
    -c call_type/inst.cc -o "$B/inst.o"
"$SDK/bin/clang" $CFG -O2 $INC -c m5_mmap.c -o "$B/m5_mmap.o"
"$SDK/bin/clang" $CFG $INC -c abi/riscv/m5op.S -o "$B/m5op.o"
"$SDK/bin/clang++" $CFG -static -o "$B/m5" $objs \
    "$B/inst.o" "$B/m5_mmap.o" "$B/m5op.o"

mkdir -p "$X/sbin" "$X/etc"
"$SDK/bin/llvm-strip" -o "$X/sbin/m5" "$B/m5"
chmod 755 "$X/sbin/m5"
cp "$HERE/m5_init.sh" "$X/etc/m5_init.sh"
chmod 755 "$X/etc/m5_init.sh"
echo "installed $X/sbin/m5 and $X/etc/m5_init.sh"
