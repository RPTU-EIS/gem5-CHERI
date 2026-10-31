# Tag-model validation workloads (tagval)

The programs Joannou et al. ("Efficient Tagged Memory", ICCD 2017) used to
characterise tag-table caching, built for CheriBSD RISC-V (plain RV64 and
purecap), so gem5-CHERI's tag controller can be compared with their study on
the same software. Olden and CoreMark-PRO then show what a trace study cannot
(cycle cost on a pipeline, kernel effects).

| workload | their use | here |
|---|---|---|
| qsort, jpeg, dijkstra, sha, crc32, fft | MiBench, FPGA (Fig. 9) | CHERI's llvm-test-suite fork, "large" inputs |
| earley-boyer | pointer-heavy trace case (Figs. 2, 3, 7), FPGA | Octane under Duktape 2.7, 1 iteration |
| splay | FPGA (Fig. 9), > 100 MB working set there | Octane under Duktape, 1 iteration |
| ffmpeg | pointer-sparse trace case (Figs. 2, 7) | FFmpeg 5.1 (arichardson fork), MPEG-4 encode of 10 lavfi 720p frames |

Their Fig. 2 ran Earley-Boyer under V8 (JIT) on ARMv8; V8 has no CHERI-RISC-V
port, so Earley-Boyer runs under Duktape as on their FPGA.

Sizes (QEMU `-icount shift=0`, purecap, kernel included): MiBench 0.02-0.56 G
instructions, ffmpeg ~2.8 G, earley-boyer ~5.0 G, splay ~7.9 G. All nine run in
both ABIs with identical output (MD5).

## Build (where the CHERI SDK is)

```sh
# sources: ~/hiwi/tagval-src/{duktape-2.7.0,octane,llvm-test-suite,FFmpeg}
#   duktape-2.7.0.tar.xz (GitHub release), github.com/chromium/octane,
#   github.com/CTSRD-CHERI/llvm-test-suite (sparse: MultiSource/Benchmarks/MiBench),
#   github.com/arichardson/FFmpeg
util/cheri/tagval/build_ffmpeg.sh                 # ~/hiwi/tagval-gem5/ffmpeg/<abi>/ffmpeg
util/cheri/tagval/build.py --ffmpeg ~/hiwi/tagval-gem5/ffmpeg
```

`build.py` writes the Olden layout (`builds/<abi>/bin[-stripped]`,
`data/<workload>/` inputs, `workloads.json`), so `olden/run.py` runs it
(`tagval/run_all.sh`; input files travel in each run's payload, so runs boot
CheriBSD themselves, NO_CHECKPOINT=1).

Duktape needed three changes for purecap (both ABIs build the same source):
`DUK_USE_EXEC_REGCONST_OPTIMIZE` off (it needs an 8/16-byte `duk_tval`; 16-byte
pointers make it 32), `duk__resize_valstack` rebases its pointers on the
realloc'd value stack instead of adding the allocations' distance (tag fault),
and 16-byte padding before an object's array part (misaligned capability
store). These are Duktape porting bugs, found with gdb under CHERI-QEMU.

## Run and compare (server)

`util/cheri/validation.sh RESULTS` (stages `tvmain tvtc tvswe`), or directly:

```sh
STAGES=main MAIN_ABIS=plain,purecap util/cheri/holygrail.sh tagval RESULTS
STAGES=tc util/cheri/holygrail.sh tagval RESULTS                  # sizes 4 KiB .. 1 MiB
CHERI_TAG_SWE=1 STAGES=tc TC_CONFIGS=atomic-flat util/cheri/holygrail.sh tagval RESULTS hgswe
util/cheri/tagcache_sweep_collect.py RESULTS/tagval/hg-tc-* RESULTS/tagval/hgswe-tc-* --out tc.csv
util/cheri/tagval/joannou_compare.py tc.csv
```

`joannou_compare.py` sets the sweep against the numbers their text states
(Fig. 2 at 32 KiB, silent-write elimination, FPGA bounds, Fig. 3 locality).
Differences to keep in mind: our granule is 16 bytes (theirs 8 bytes in the
trace study, 32 bytes on the FPGA), so a tag cache of the same size covers 2x
their data; lines are 64 bytes; the hierarchical table's grouping factor is 512.
