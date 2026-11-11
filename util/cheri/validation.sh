#!/bin/sh
# The validation experiments for one results root, on the 2026 setup of
# holygrail.sh (kernel, disk, virtio), every gem5 run limited to TIMEOUT.
# Stages (each also runs its analysis):
#   juliet  Juliet 1.3 (13,395 tests x good/bad) purecap, hybrid, plain on
#           the atomic CPU          -> RESULTS/juliet/<tag>/detection.csv
#   cbt     cheribsdtest purecap + hybrid on minor and o3 (the 8 variants
#           on atomic are done: results-validation/cheribsdtest/local-*)
#           -> RESULTS/cheribsdtest/2026-minor-o3/
#   tvmain  tag-validation workloads (tagval: MiBench, Octane/Duktape,
#           FFmpeg) plain + purecap on Minor with every tag model
#           -> RESULTS/tagval/hg-main
#   tvtc    tagval leaf tag-cache sweep, 4 KiB..1 MiB, atomic flat +
#           hierarchical (Joannou et al. Figs. 2, 3, 7, 9)
#           -> RESULTS/tagval/hg-tc-<size>
#   tvswe   tagval with silent-write elimination, atomic flat, 3 sizes
#           -> RESULTS/tagval/hgswe-tc-<size>
#   tccyc   Olden and CoreMark-PRO tag-cache sweep on Minor: the cycle
#           cost of the tag cache size, which trace studies cannot give
#           -> RESULTS/{olden,coremark}/hg-tc-<size>
#
# Usage: util/cheri/validation.sh RESULTS
# Environment (defaults):
#   STAGES   "juliet cbt tvmain tvtc tvswe tccyc"
#   JOBS     16          TIMEOUT  180000 (50 h per gem5 run)
#   CHERI_KERNEL, CHERI_DISK, CHERI_VIRTIO_SEG_MAX  as holygrail.sh
#   JULIET_BUILDS  ~/hiwi/juliet-gem5/out     (util/cheri/juliet/build.py)
#   TAGVAL_WORK    ~/hiwi/tagval-gem5         (util/cheri/tagval/build.py)
#   QEMU_REF       cheribsdtest results.csv of run_qemu.py, for --ref
#   CBT_SETS       "minor,o3:purecap,hybrid" (CONFIGS:VARIANTS ...;
#                  "atomic:all" reruns the atomic ones)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
GEM5=$(cd "$HERE/../.." && pwd)
RESULTS=$(mkdir -p "${1:?usage: $0 RESULTS}" && cd "$1" && pwd)
STAGES=${STAGES-juliet cbt tvmain tvtc tvswe tccyc}
export JOBS=${JOBS:-16} TIMEOUT=${TIMEOUT:-180000}
export CHERI_KERNEL=${CHERI_KERNEL:-$GEM5/tests/kernel-2026-nodebug}
export CHERI_DISK=${CHERI_DISK:-$GEM5/tests/cheribsd-2026-riscv64-purecap.img}
export CHERI_VIRTIO_SEG_MAX=${CHERI_VIRTIO_SEG_MAX:-126}
for f in "$CHERI_KERNEL" "$CHERI_DISK"; do
    [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }
done
TV_WORK=${TAGVAL_WORK:-$HOME/hiwi/tagval-gem5}

for stage in $STAGES; do
    echo "=== $stage ($(date))"
    case $stage in
    juliet)
        BUILDS=${JULIET_BUILDS:-$HOME/hiwi/juliet-gem5/out} \
            ABIS=purecap,hybrid,plain \
            "$HERE/juliet/run_all.sh" "$RESULTS" ;;
    cbt)
        # the detailed CPUs are slow: O3 may reach TIMEOUT, finished tests
        # are kept
        for set in ${CBT_SETS:-minor,o3:purecap,hybrid}; do
            out=$RESULTS/cheribsdtest/2026-$(echo "${set%%:*}" | tr , -)
            python3 "$HERE/cheribsdtest/run.py" --out "$out" \
                --variants "${set#*:}" --configs "${set%%:*}" \
                --jobs "$JOBS" --timeout "$TIMEOUT"
            python3 "$HERE/cheribsdtest/parse.py" "$out" \
                ${QEMU_REF:+--ref "$QEMU_REF"}
        done ;;
    tvmain)
        WORK=$TV_WORK STAGES=main MAIN_ABIS=plain,purecap \
            "$HERE/holygrail.sh" tagval "$RESULTS" ;;
    tvtc)
        WORK=$TV_WORK STAGES=tc "$HERE/holygrail.sh" tagval "$RESULTS" ;;
    tvswe)
        WORK=$TV_WORK CHERI_TAG_SWE=1 STAGES=tc TC_CONFIGS=atomic-flat \
            TAG_CACHES=${SWE_TAG_CACHES:-8KiB 32KiB 128KiB} \
            "$HERE/holygrail.sh" tagval "$RESULTS" hgswe ;;
    tccyc)
        for s in olden coremark; do
            STAGES=tc TC_CONFIGS=minor-flat,minor-hierarchical \
                TAG_CACHES=${CYC_TAG_CACHES:-4KiB 128KiB 1MiB} \
                "$HERE/holygrail.sh" "$s" "$RESULTS"
        done ;;
    *)
        echo "unknown stage $stage" >&2; exit 1 ;;
    esac
done

# tag-cache comparison with Joannou et al. (whatever sweeps exist)
set -- "$RESULTS"/tagval/hg-tc-* "$RESULTS"/tagval/hgswe-tc-*
if [ -e "$1" ] || [ -e "${2:-}" ]; then
    pts=$(ls -d "$RESULTS"/tagval/hg-tc-* "$RESULTS"/tagval/hgswe-tc-* \
          2>/dev/null)
    python3 "$HERE/tagcache_sweep_collect.py" $pts \
        --out "$RESULTS/tagval/tagcache_sweep.csv"
    python3 "$HERE/tagval/joannou_compare.py" \
        "$RESULTS/tagval/tagcache_sweep.csv" \
        | tee "$RESULTS/tagval/joannou_compare.txt"
fi
echo "done: $RESULTS ($(date))"
