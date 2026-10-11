# Olden on gem5 CHERI-RISC-V (purecap vs hybrid vs plain RV64)

Olden is the standard pointer-intensive suite: ten programs whose data are
trees, lists and graphs of malloc'd nodes linked by pointers. Under purecap
every pointer is a 16-byte capability instead of 8 bytes, so nodes grow,
fewer fit in each cache line, and more memory traffic and tag work follow.
This is the workload class where CHERI costs most, and where architectural
changes (capability compression, tag caching, prefetching) can help.

Same scheme as `util/cheri/coremark/` (whose run helpers, CSV parser and
plotting script are reused), so results have the same columns and plots,
and the same three builds: **purecap**, **hybrid** and **plain** RV64 (no
CHERI instructions, 8-byte-word `memcpy`; the baseline of a core without
CHERI; see the CoreMark-PRO README for why hybrid alone is not a neutral
baseline). In Olden this matters for bh: its hot recursion passes a 64-byte
struct by value; purecap and plain copy it inline, hybrid calls libc's
tag-preserving `memcpy`, which copies it a byte at a time (hybrid bh runs
3x+ more instructions than purecap).

## 1. Build (on a machine with the CHERI SDK)

```sh
git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/llvm/llvm-test-suite.git ~/hiwi/llvm-test-suite
git -C ~/hiwi/llvm-test-suite sparse-checkout set MultiSource/Benchmarks/Olden
util/cheri/olden/build.py [--src DIR] [--work ~/hiwi/olden-gem5] \
    [--abis purecap,hybrid,plain]     # e.g. --abis plain: keep the others
```

* Source: the LLVM test-suite's Olden (bh, bisort, em3d, health, mst,
  perimeter, power, treeadd, tsp, voronoi), `-DTORONTO` (sequential
  version), CHERI LLVM `-O2 -static` for both ABIs; only `--config` differs
  (as for CoreMark-PRO). Builds a patched copy; the source is untouched.
* Each program is also built for the host and run with the same arguments:
  `WORK/ref/<bench>.out` is the reference output.
* Arguments (`WORK/workloads.json`) are sized for detailed simulation: the
  test suite's small inputs (bisort, mst: scaled down), ~50-300 M
  instructions per run, data still far larger than the caches:

  | bench | args | bench | args |
  |---|---|---|---|
  | bh | `2000 5` | perimeter | `9` |
  | bisort | `100000` | power | (`-DSMALL_PROBLEM_SIZE`) |
  | em3d | `256 250 35` | treeadd | `20` |
  | health | `8 15 1` | tsp | `102400` |
  | mst | `1000` | voronoi | `10000 20 32 7` |

### What differs from the LLVM test-suite sources

| Change | Where | Why |
|---|---|---|
| `uptrint` is `uintptr_t` (was `unsigned long`) | voronoi `defines.h` | voronoi navigates its quad-edge records with integer arithmetic on pointers; only `uintptr_t` keeps the capability under purecap |
| operands of `|` swapped in `rot()`/`rotinv()` | voronoi `defines.h` | CHERI C takes a `uintptr_t` bitwise result's capability from the left operand; the original left operand is a small offset (far out of bounds, so the tag would be lost), now it is the record's base. Same value in both ABIs |

(`patches/voronoi-purecap.patch`.) mst truncates pointers to `unsigned int`
only to use them as hash keys (never dereferenced), which works unchanged in
both ABIs. The rest builds unmodified; the many `-Wcheri-prototypes`
warnings are about calls without prototypes, harmless on RISC-V (integers
and capabilities share registers).

## 2. Run

```sh
util/cheri/olden/run.py --out m5out/olden/<name> --checkpoint m5out/olden/ckpt \
    [--configs atomic,minor,minor-passthrough,minor-flat,minor-hierarchical] \
    [--abis purecap,hybrid,plain] [--workloads treeadd,mst] [--jobs 8] \
    [--wl-args NAME=ARGS]
```

* One gem5 run per (workload, ABI, config) in
  `OUT/<workload>/<abi>-<config>/`, restored from a checkpoint of booted
  CheriBSD with both ABIs' binaries (`BASE-notag`, `BASE-tagged` for the tag
  models; made on first use, ~20 min each). The program runs inside one
  `m5 workbegin`/`workend` region; its output is printed after the region
  (or its MD5 above 32 KiB, e.g. voronoi).
* The kernel's WITNESS lock-order checking is switched off before the
  region (`--witness on` keeps it): these programs fault in many pages, and
  WITNESS inflates kernel time that a production kernel does not have.
  (The CoreMark-PRO runs kept WITNESS on; their kernel share is small.)
* Host time: Atomic ~8-15 min per run; Minor ~3-4x longer.

## 3. Analyse and plot

```sh
util/cheri/olden/parse.py OUT [MORE_OUT ...] [--into DIR]
util/cheri/coremark/plot.py OUT [--png]
```

`parse.py` checks every run's output (`output_vs_native`: identical to the
native run, or equal within 1e-3 relative for numbers; `output_vs_plain`,
`output_vs_hybrid`: identical to the other ABIs' runs), counts a mismatch as
an error, and then writes
the same CSVs as CoreMark-PRO (`results.csv`, `comparison.csv`,
`all_stats.csv`, `tag_costs.csv`, per-workload `summary.csv`) plus
`validation.csv`. `plot.py` makes the same paper figures.

## Everything in one place (e.g. on a server)

```sh
JOBS=16 util/cheri/olden/run_all.sh ~/cheri-results [TAG]
ABIS=plain JOBS=16 util/cheri/olden/run_all.sh ~/cheri-results plain  # add plain only
util/cheri/olden/parse.py RESULTS/olden/<TAG> RESULTS/olden/plain --into RESULTS/olden/merged
```

Checkpoints in `RESULTS/checkpoints/olden-k<kernel>-b<binaries>-*`, the run
in `RESULTS/olden/<TAG>/`, then parse and plots. Needs on the server: this
gem5 tree built, the disk image, and `WORK/` (`builds/`, `ref/`,
`workloads.json`) copied from the build machine (`WORK=` points at it).
