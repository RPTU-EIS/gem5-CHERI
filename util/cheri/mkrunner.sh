#!/bin/sh
# Bundle guest binaries into a self-extracting /bin/sh script so they can be
# delivered with `m5 readfile` (the image's /etc/m5_init.sh runs whatever
# readfile returns) and invoked with arguments, all in one boot.
#
# Usage: util/cheri/mkrunner.sh <binary> '<args>' [<binary> '<args>' ...] \
#            > runner.sh
#   e.g. util/cheri/mkrunner.sh cheri_faults '' \
#            cheribsdtest-purecap "-g 'fault_*'" > run.sh
# Then: CHERI_READFILE=run.sh build/RISCV_CHERI/gem5.opt ... or
#       util/cheri/run_cheribsd_test.py --binary run.sh ...
set -e
printf '#!/bin/sh\n'
printf 'cd /tmp\n'
n=0
while [ $# -gt 0 ]; do
    bin=$1
    args=${2-}
    shift
    [ $# -gt 0 ] && shift
    n=$((n + 1))
    printf "b64decode -r > /tmp/guestbin%d <<'__B64_EOF__'\n" $n
    base64 -w 76 "$bin"
    printf '__B64_EOF__\n'
    printf 'chmod +x /tmp/guestbin%d\n' $n
    printf 'echo "=== RUN: %s %s"\n' "$(basename "$bin")" "$(echo "$args" | sed 's/"/\\"/g')"
    printf '/tmp/guestbin%d %s\n' $n "$args"
    printf 'echo "=== EXIT_STATUS=$?"\n'
    printf 'rm -f /tmp/guestbin%d\n' $n
done
