# CoreMark-PRO on gem5 CHERI-RISC-V (purecap vs hybrid vs plain RV64)

Scripts to build, run and analyse EEMBC CoreMark-PRO on the gem5 CHERI-RISC-V
model under CheriBSD, in three builds of the same source, on the same kernel
and hardware model:

| ABI | What it is | Role |
|---|---|---|
| **purecap** | every pointer a 16-byte capability | CHERI-protected program |
| **hybrid** | integer pointers, built for a CHERI system (`xcheri`) | legacy code on a CHERI system |
| **plain** | RV64 built without CHERI (`-march=rv64imafdc`), 8-byte-word `memcpy` | **baseline**: what a core without CHERI runs |

Why plain and not only hybrid: hybrid code may hold capabilities in memory,
so the compiler copies 8-byte-aligned structs through libc's tag-preserving
`memcpy`, and CheriBSD's hybrid `memcpy` copies in 16-byte words, falling
back to single bytes when source and destination differ mod 16. Plain RV64
code inlines such copies. Hybrid therefore pays costs a non-CHERI system does
not (Olden bh: hybrid runs 3x+ more instructions than purecap), which
understates purecap's overhead. Plain uses the same sysroot (CheriBSD's
hybrid libc, apart from `memcpy`/`memmove`/`bcopy`, which
`util/cheri/common/memcpy64.c` replaces) and runs as an ordinary 64-bit
process on the same kernel, so OS effects are identical.

## 1. Build (once per CoreMark-PRO source / compiler change)

```sh
util/cheri/coremark/build.sh [SRC] [WORK]
#   SRC   default ~/hiwi/coremark-pro/coremark-pro   (left untouched)
#   WORK  default ~/hiwi/coremark-pro-gem5           (copy that is built)
#   ABIS="purecap hybrid plain" (default); ABIS=plain adds only plain and
#   keeps the existing purecap/hybrid builds
```

* All ABIs use the same CHERI LLVM (`$CHERI_SDK`, default
  `~/cheri/output/sdk`) and flags (`-O2 -static`); only the `--config` (and
  for plain `-march=rv64imafdc` plus `libmemcpy64.a`) differs
  (`make/clang-cheribsd-{purecap,hybrid,plain}.mak`).
* `patches/core-purecap.patch` makes `core` correct under purecap (likely
  what made it fail in CHERI-VP): (1) it aligns pointers through an integer
  type, which must be `intptr_t` or the pointer loses its tag; (2) it sized
  the list region assuming 16-byte list nodes (two 64-bit pointers), while a
  purecap node is 32 bytes, so the list overran its allocation. Both changes
  are no-ops for hybrid (same code and list length).
* `patches/zip-setup-linear.patch`: zip-test builds its 1 MB input with one
  `strcat` per ~50-byte record, rescanning the buffer each time (~1e10 byte
  reads: seconds on hardware, many hours under simulation, all before the
  timed region). The patch appends at a tracked end pointer; the generated
  input is byte-identical (zip-test's CRC check confirms it).
* The prebuilt `builds/riscv64` binaries are Linux (glibc) executables and
  cannot run on CheriBSD; use these builds instead.

### What differs from stock CoreMark-PRO (state this in any write-up)

| Change | Where | Affects | Why |
|---|---|---|---|
| `ee_ptr_int` is `intptr_t` under purecap | `core` (`core_portme.h`) | purecap code only | `align_mem()` round-trips pointers through it; a 64-bit integer drops the capability tag |
| list region sized with `sizeof(list_head)` instead of `16` | `core` (`core_mith.c`) | purecap memory layout only (hybrid value unchanged) | purecap list nodes are 32 B; the list overran its allocation, corrupting pointers (tag violation, the failure CHERI-VP saw) |
| input built with an end pointer instead of repeated `strcat` | `zip-test` setup (`zip_darkmark.c`) | untimed setup only, identical input (CRC checked) | quadratic setup took >12 h simulated |
| `core` run with `-D=-I1` | run option | `core` dataset | CoreMark-PRO's built-in preset 1: same data-structure sizes, 1,000 instead of 10,000 inner iterations, seeds 0/0 instead of 0x3415/0x3415 |
| `-v0 -c1 -w1 -i<N>` | run option | all | performance mode (CRC still checked), one context, one worker, N iterations (default 1) |
| CHERI LLVM `-O2 -static` for both ABIs | build | all | the provided `riscv64` build is Linux/GNU gcc; same compiler and flags isolate the ABI |

No other benchmark source is changed; `EE_SIZEOF_PTR=8` is kept (it only
sizes the integer type `ee_iptr_t`).

## 2. Run

```sh
util/cheri/coremark/run.py --out m5out/coremark/<name> \
    --configs atomic,minor,minor-passthrough,minor-flat,minor-hierarchical \
    --iterations 1 --wl-args core=-D=-I1 \
    --checkpoint m5out/coremark/ckpt-<kernel> [--jobs 4] \
    [--abis purecap,hybrid] [--workloads core,zip-test]
```

* `--checkpoint BASE` (recommended): boots CheriBSD once per memory layout,
  unpacks both ABIs' binaries to `/root/cm/` and checkpoints (~25 min
  each): `BASE-notag` for configs without a tag model, `BASE-tagged` for
  the tag-model configs (their tag table is reserved at the top of DRAM in
  the device tree, so the guest must have booted with that reservation);
  every later run restores DIR and starts the workloads immediately, on any
  CPU and cache/tag configuration. DIR stores the kernel, disk and binary
  hashes and is refused if they changed: use a new DIR per kernel/build.
  Without `--checkpoint` each run boots (~15 min) and unpacks its own copy.
* `--wl-args core=-D=-I1`: `core`'s default dataset (10,000 CoreMark
  iterations, billions of instructions) is too long for detailed CPUs;
  `-D=-I1` selects CoreMark-PRO's built-in 1,000-iteration preset. Recorded
  in the manifest as `per_workload_args`.

* One gem5 run per (workload, ABI, CPU), in
  `OUT/<workload>/<abi>-<config>/` (`console.log`, `stats.txt`,
  `config.ini`, `run_info.json`). A config is `CPU[-TAGMODEL]`: `atomic`,
  `minor` (no tag model), `minor-passthrough` (tag controller, no tag
  traffic: the baseline for the next two), `minor-flat`,
  `minor-hierarchical`.
  The workload runs inside an `m5 workbegin`/`workend` region
  (`-v0 -c1 -w1 -i<N>`), so `stats.txt` covers exactly that workload. The
  workbegin switches from the boot CPU to `minor` (or `timing`, `o3`);
  `atomic` stays on the atomic CPU (fast instruction counts).
* `--iterations` takes `N` or `name=N,name=N` (others 1).
* Binaries are shipped to the guest as a shell script followed by a raw
  tar.gz (the guest's `/etc/m5_init.sh` runs the readfile from a file, so the
  script extracts its own tail); base64 decoding in the guest is far slower.
* Everything about the system comes from the environment and is recorded in
  `OUT/manifest.json` (gem5 revision, kernel/disk paths and kernel hash,
  binary hashes, iterations, knobs):

  | Variable | Meaning (default) |
  |---|---|
  | `CHERI_KERNEL` | kernel ELF (`tests/kernel`) |
  | `CHERI_DISK` | disk image (`tests/cheribsd-riscv64-purecap.img`) |
  | `CHERI_L1D`, `CHERI_L1I`, `CHERI_L2` | cache sizes (16kB, 16kB, 256kB) |
  | `CHERI_TAG_MODEL` | none, passthrough, nocache, flat, hierarchical (none) |
  | `CHERI_TAG_CACHE`, `CHERI_TAG_ASSOC` | leaf tag cache (32KiB, 8) |
  | `CHERI_TAG_ROOT_CACHE` | root tag cache, hierarchical (1KiB) |

  Tag models (configs `minor-<model>`): `passthrough` (tag controller, no
  tag traffic: the baseline), `nocache` (flat tag table without a tag cache:
  every lookup reads the table in DRAM, every tag write is a read-modify-
  write), `flat` (table + 32 KiB leaf tag cache), `hierarchical` (leaf
  cache + root level with zero elision).

### Adding plain to existing purecap/hybrid results

The purecap and hybrid binaries do not change, so earlier runs stay valid:

```sh
ABIS=plain util/cheri/coremark/build.sh            # build machine
ABIS=plain JOBS=8 util/cheri/coremark/run_all.sh RESULTS plain   # server
util/cheri/coremark/parse.py RESULTS/coremark/<old tag> RESULTS/coremark/plain \
    --into RESULTS/coremark/merged
util/cheri/coremark/plot.py RESULTS/coremark/merged
```

## 3. Analyse

```sh
util/cheri/coremark/parse.py m5out/coremark/<name>
```

Writes `OUT/<workload>/summary.csv` (that workload's rows) and, for all
workloads, `results.csv` (per ABI/CPU/workload: CoreMark-PRO's own iterations,
time and workloads/sec, CRC errors, instructions, cycles, IPC, loads/stores,
L1D/L1I/L2 misses and MPKI, DRAM bytes, branch mispredictions, tag traffic)
and `comparison.csv` (ratios for every ABI pair present: purecap/plain,
hybrid/plain, purecap/hybrid), and prints the ratios with geometric means.
`plot.py` draws ratios against plain when plain results are present
(`--baseline hybrid` to override). `insts_ratio` on the atomic CPU is the metric CHERI-VP
reports; `cycles_ratio` on Minor/O3 is the timing overhead.

Host time (16-core machine, 4 runs in parallel): a 1-iteration workload is
~70-140 M instructions; Atomic runs ~0.7 M instructions/s, Minor ~0.25 M/s.

## 4. Plot

```sh
pip install matplotlib numpy          # once
util/cheri/coremark/plot.py RESULTS/coremark/<TAG> [more dirs...] \
    [--out DIR] [--png] [--hatch]
```

Writes paper figures (default `<first dir>/plots/`), sized for two-column
IEEE/ACM templates (3.5 in / 7.16 in, 8 pt, TrueType fonts embedded):

| File | Shows | Needs configs |
|---|---|---|
| `overhead.pdf` | purecap overhead over hybrid: instructions (Atomic) and cycles (Minor), geomean | `atomic`, `minor` |
| `memory.pdf` | L1D MPKI, L2 MPKI, DRAM bytes/kinst, hybrid vs purecap (log) | `minor` |
| `instmix.pdf` | dynamic instruction mix normalised to hybrid's count | `atomic` |
| `tags.pdf` | flat/hierarchical tag storage vs passthrough: cycles, DRAM traffic, tag-cache hit rate | `minor-passthrough`, `minor-flat`/`-hierarchical` |
| `endtoend.pdf` | purecap with each tag model vs hybrid without tags | `minor`, tag configs |
| `tables.tex` | per-workload table, simulation cost (booktabs) | |
| `plot_data.csv` | every plotted value | |

Several directories are merged (later ones replace runs with the same ABI,
config and workload); failed runs (non-zero status or CRC errors) are listed
and left out. Geometric means cover only workloads present in every series
of a figure. `--hatch` adds hatching for grayscale printing.

## Cache-size sweep

How much of purecap's cost is cache capacity: rerun the experiment at
several L1D and L2 sizes (config `minor`, no tag model), one results
directory per point, reusing the checkpoints:

```sh
WORKLOADS=parser-125k,core ABIS=purecap,hybrid,plain JOBS=8 \
    util/cheri/cache_sweep.sh coremark RESULTS          # or: olden
util/cheri/cache_sweep_collect.py RESULTS/coremark/<main run> \
    RESULTS/coremark/sweep-*
```

`L2_SIZES` (default `128kB 512kB 1MB 2MB`, at L1D 16kB) and `L1D_SIZES`
(default `32kB 64kB`, at L2 256kB) choose the points; the main run is the
default point (16kB / 256kB). `cache_sweep.csv` has one row per (L1D, L2,
ABI, workload); the printout gives every ABI's cycles relative to the
baseline ABI at the default sizes, and the simulated points at which
purecap is at least as fast as that.

## Re-running with another kernel

Nothing in these scripts depends on the kernel. Point `CHERI_KERNEL` (and
`CHERI_DISK` if the userland changes) at the new files and repeat step 2 into
a new output directory; compare the two `comparison.csv` files.

```sh
CHERI_KERNEL=/path/to/new/kernel util/cheri/coremark/run.py \
    --out m5out/coremark/<name>-newkernel \
    --configs atomic,minor,minor-passthrough,minor-flat,minor-hierarchical \
    --iterations 1 --wl-args core=-D=-I1 \
    --checkpoint m5out/coremark/ckpt-newkernel
util/cheri/coremark/parse.py m5out/coremark/<name>-newkernel
```

`build.sh` always rebuilds its two targets from clean (CoreMark-PRO's own
make ignores source changes), so rerun it after changing a patch.

## Everything in one place (e.g. on a server)

`run_all.sh RESULTS [TAG]` wraps steps 2-3 and keeps all output under one
root: checkpoints in `RESULTS/checkpoints/ck-k<kernel hash>-b<binaries
hash>-{notag,tagged}/` (created once, reused while kernel and binaries are
unchanged) and each experiment in
`RESULTS/coremark/<TAG>/<workload>/<abi>-<config>/`, with
the manifest and CSVs in `RESULTS/coremark/<TAG>/`.

```sh
JOBS=8 ITER=1 util/cheri/coremark/run_all.sh ~/cheri-results            # baseline
JOBS=8 CHERI_L1D=32kB util/cheri/coremark/run_all.sh ~/cheri-results l1d32k
CHERI_KERNEL=/path/new/kernel JOBS=8 util/cheri/coremark/run_all.sh ~/cheri-results
```

The server needs: this gem5 tree built (`build/RISCV_CHERI/gem5.opt`), the
disk image (`tests/cheribsd-riscv64-purecap.img`, not in git) and the
CoreMark-PRO binaries (`BUILDS=`, either built there with `build.sh` and the
CHERI SDK + rootfs, or copied from a machine that has them). Without the
SDK, `run.py` strips binaries with any `llvm-strip` on PATH, or ships them
unstripped. Each gem5 instance uses a few GB of RAM; size `JOBS` to memory
as well as cores.
