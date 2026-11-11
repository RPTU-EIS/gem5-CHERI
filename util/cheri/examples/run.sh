#!/bin/sh
# Boot CheriBSD on the atomic CPU, switch to CPU at the first `m5 workbegin`
# and run each binary in its own region of interest. OUT/stats.txt holds one
# dump for the boot, then one per binary in order; the guest console is in
# OUT/console.log.
#
# Usage: util/cheri/examples/run.sh CPU [BINARY ...]
#   CPU     atomic | timing | minor | o3
#   BINARY  default: hello, bounds and list, purecap then plain
# Environment: CHERI_KERNEL and CHERI_DISK (required), OUT (default
#   m5out/examples/CPU), GEM5 (default build/RISCV_CHERI/gem5.opt), and the
#   other CHERI_* variables of cheri-riscv-cheribsd-switch.py
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
CPU=${1:?usage: $0 atomic|timing|minor|o3 [BINARY ...]}
shift
if [ $# -eq 0 ]; then
    for abi in purecap plain; do
        for p in hello bounds list; do
            set -- "$@" "$HERE/bin/$p-$abi"
        done
    done
fi
: "${CHERI_KERNEL:?set CHERI_KERNEL to the kernel from kernel_for_gem5.py}"
: "${CHERI_DISK:?set CHERI_DISK to the CheriBSD disk image}"
OUT=${OUT:-$ROOT/m5out/examples/$CPU}
GEM5=${GEM5:-$ROOT/build/RISCV_CHERI/gem5.opt}
mkdir -p "$OUT"

# The binaries travel as a gzip'd tar appended to the job script, which
# extracts its own tail: much faster in the guest than decoding base64.
stage=$OUT/payload
rm -rf "$stage"
mkdir -p "$stage"
names=
for b in "$@"; do
    cp "$b" "$stage/"
    names="$names $(basename "$b")"
done
chmod 755 "$stage"/*
tar -czf "$OUT/payload.tgz" --owner=0 --group=0 -C "$stage" $names

# The job m5_init.sh runs: unpack, then run each binary between
# m5 workbegin and m5 workend. Its first line holds the payload's offset.
header() {
    printf '#!/bin/sh\ncd /tmp\n'
    printf 'tail -c +%s "$0" | tar xzf - || exit 1\n' "$1"
    for n in $names; do
        printf 'echo "=== %s"\n/sbin/m5 workbegin\n./%s\n' "$n" "$n"
        printf 's=$?\n/sbin/m5 workend\necho "=== %s exit $s"\n' "$n"
    done
    printf 'exit 0\n'
}
off=1
while [ "$(header "$off" | wc -c)" -ne $((off - 1)) ]; do
    off=$(($(header "$off" | wc -c) + 1))
done
job=$OUT/job.sh
{ header "$off"; cat "$OUT/payload.tgz"; } > "$job"

export CHERI_READFILE="$job" CHERI_SWITCH_CPU="$CPU"
export CHERI_VIRTIO_SEG_MAX="${CHERI_VIRTIO_SEG_MAX:-126}"
"$GEM5" --outdir "$OUT" \
    "$ROOT/configs/example/gem5_library/cheri-riscv-cheribsd-switch.py" \
    > "$OUT/console.log" 2>&1
# The guest's lines between the markers (they end in CR, gem5's do not)
cr=$(printf '\r')
sed -n '/^=== /,/^=== .* exit /p' "$OUT/console.log" | grep -a "$cr\$" |
    tr -d '\r'
