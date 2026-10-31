# Baseline check: does the CHERI work perturb plain RV64?

The same plain RV64GC ELF, run on three simulator builds with the same
core, caches and memory, should give the same committed instructions and
(nearly) the same cycles:

1. upstream gem5 v24.0 (`43769abaf0`, the base of this tree), `RISCV`
2. this tree, `RISCV` (shows the CHERI work's changes to shared CPU,
   cache and LSQ code do not affect a non-CHERI ISA)
3. this tree, `RISCV_CHERI`, integer mode (shows the CHERI ISA runs plain
   RV64 like RV64GC)

## Build the kernels

```sh
util/cheri/baseline/build.sh [OUT]      # default ~/hiwi/baseline-gem5
```

`bench.c`: six freestanding kernels (ptrchase, tree, qsort, matmul, crc32,
stream), no libc, only the write and exit syscalls, so nothing but the
simulator differs between runs.

## Run

```sh
gem5.opt --outdir D util/cheri/baseline/se.py --isa riscv|riscv_cheri \
    --cpu atomic|timing|minor|o3 --binary OUT/bin/<kernel>
```

SE mode with the stdlib's stock components (3 GHz, 16kB L1I/L1D, 256kB L2,
dual-channel DDR4-2400). Upstream v24.0 is built from
`git archive 43769abaf0` (outside this tree) with
`scons build/RISCV/gem5.opt PYTHON_CONFIG=/usr/bin/python3-config`.

`util/cheri/baseline/run.sh OUT` runs every kernel on atomic, Minor and O3
with each build; `compare.py OUT` tabulates instructions and cycles relative
to upstream (`OUT/baseline.csv`).

Result (2026-10-30): all three builds give identical committed instructions,
cycles and checksums for all six kernels on all three CPU models.

Making this check possible needed fixes in this tree: SE mode on the CHERI
build (fault dispatch, syscall number and arguments through the merged
register file, plain RV64 ELFs), and the non-CHERI builds (an empty
`CapRegClass` slot in the RISC-V ISA, else every register class after the
integers is shifted; the TimingSimpleCPU PCC check moved to
`cpu/simple/timing_cheri.cc`). The other ISAs (ARM, x86, MIPS, POWER, SPARC)
need the same empty `CapRegClass` slot.
