#!/bin/sh
# Build a minimal static FFmpeg for CheriBSD RISC-V, plain and purecap, for
# tagval/build.py --ffmpeg: the fork cheribuild's ffmpeg target uses (CHERI
# fixes), no assembly (the ffmpeg tool needs threads; the workload runs
# with -threads 1), with only what the workload needs:
# MPEG-4 encoding of a lavfi test pattern, and the MD5 muxer so the output
# can be compared across ABIs. Runs FFmpeg's configure on this machine.
#
# Usage: util/cheri/tagval/build_ffmpeg.sh [SRC] [WORK]
#   SRC   default ~/hiwi/tagval-src/FFmpeg
#   WORK  default ~/hiwi/tagval-gem5/ffmpeg (WORK/<abi>/ffmpeg)
# Environment: SDK (default ~/cheri/output/sdk), JOBS (default 8)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "${1:-$HOME/hiwi/tagval-src/FFmpeg}" && pwd)
WORK=${2:-$HOME/hiwi/tagval-gem5/ffmpeg}
SDK=${SDK:-$HOME/cheri/output/sdk}
JOBS=${JOBS:-8}

for abi in plain purecap; do
    B=$WORK/build-$abi
    mkdir -p "$B" "$WORK/$abi"
    case $abi in
    purecap) cfg=cheribsd-riscv64-purecap.cfg; march=; extra= ;;
    plain)   cfg=cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg
             march=-march=rv64imafdc
             # 8-byte-word memcpy/memmove, as olden/build.py
             "$SDK/bin/clang" --config "$cfg" $march -O2 -fno-builtin -c \
                 -o "$B/memcpy64.o" "$HERE/../common/memcpy64.c"
             extra=$B/memcpy64.o ;;
    esac
    # compiler wrapper: configure takes one word for --cc
    printf '#!/bin/sh\nexec "%s" --config %s %s "$@"\n' \
        "$SDK/bin/clang" "$cfg" "$march" > "$B/cc"
    chmod +x "$B/cc"
    (cd "$B" && "$SRC/configure" \
        --enable-cross-compile --arch=riscv64 --target-os=freebsd \
        --cc="$B/cc" --ld="$B/cc" --host-cc=cc \
        --ar="$SDK/bin/llvm-ar" --nm="$SDK/bin/llvm-nm" \
        --ranlib="$SDK/bin/llvm-ranlib" --strip="$SDK/bin/llvm-strip" \
        --extra-cflags="-O2" --extra-ldflags="-static $extra" \
        --enable-static --disable-shared --disable-autodetect \
        --disable-everything --disable-doc --disable-ffplay \
        --disable-ffprobe --disable-network --disable-asm \
        --disable-inline-asm --disable-debug \
        --enable-avfilter --enable-swscale \
        --enable-indev=lavfi --enable-filter=testsrc,scale,format,null \
        --enable-encoder=mpeg4 --enable-decoder=wrapped_avframe \
        --enable-muxer=md5 \
        --enable-protocol=pipe,file > configure.log 2>&1) || {
        echo "configure failed ($abi): $B/configure.log" >&2; exit 1; }
    make -C "$B" -j"$JOBS" ffmpeg > "$B/make.log" 2>&1 || {
        echo "make failed ($abi): $B/make.log" >&2; exit 1; }
    cp "$B/ffmpeg" "$WORK/$abi/ffmpeg"
    echo "built $WORK/$abi/ffmpeg"
done
echo "next: util/cheri/tagval/build.py --ffmpeg $WORK"
