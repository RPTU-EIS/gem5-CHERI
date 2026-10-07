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
#
# With MKRUNNER_ROI=1 the runs are wrapped in `m5 workbegin` / `m5 workend`
# (region of interest; cheri-riscv-cheribsd-switch.py switches to the
# detailed CPU at workbegin). All binaries are decoded before workbegin.
set -e
printf '#!/bin/sh\n'
printf 'cd /tmp\n'
# Pass 1: embed and decode every binary.
i=0
while [ $# -gt 0 ]; do
    bin=$1
    args=${2-}
    shift
    [ $# -gt 0 ] && shift
    i=$((i + 1))
    printf "b64decode -r > /tmp/guestbin%d <<'__B64_EOF__'\n" $i
    base64 -w 76 "$bin"
    printf '__B64_EOF__\n'
    printf 'chmod +x /tmp/guestbin%d\n' $i
    eval "name_$i=\$(basename \"\$bin\")"
    eval "args_$i=\$args"
done
n=$i
# Pass 2: run them.
[ -n "${MKRUNNER_ROI-}" ] && printf '/sbin/m5 workbegin\n'
i=1
while [ $i -le $n ]; do
    eval "name=\$name_$i"
    eval "args=\$args_$i"
    printf 'echo "=== RUN: %s %s"\n' "$name" "$(echo "$args" | sed 's/"/\\"/g')"
    printf '/tmp/guestbin%d %s\n' $i "$args"
    printf 'echo "=== EXIT_STATUS=$?"\n'
    i=$((i + 1))
done
[ -n "${MKRUNNER_ROI-}" ] && printf '/sbin/m5 workend\n'
i=1
while [ $i -le $n ]; do
    printf 'rm -f /tmp/guestbin%d\n' $i
    i=$((i + 1))
done
exit 0
