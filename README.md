# gem5-CHERI: A CHERI-RISC-V implementation in gem5

A model of a [CHERI](https://www.cl.cam.ac.uk/research/security/ctsrd/cheri/)
RISC-V processor in the [gem5](https://www.gem5.org) simulator. It boots a
pure-capability CheriBSD kernel and runs CheriBSD programs, both purecap
(every pointer is a capability) and plain RV64, on gem5's Atomic, Timing,
Minor and O3 CPU models. The tree is based on gem5 v24.0 and adds a new ISA,
`RISCV_CHERI`; the plain `RISCV` ISA behaves as in upstream gem5.

## What is modelled

* **ISA:** CHERI-RISC-V ISAv9 with 128-bit compressed capabilities (CC128),
  capability and integer encoding modes, capability loads, stores and atomics
  (`LR.C`, `SC.C`, `AMOSWAP.C`), and CHERI exceptions. The register file is
  merged: each integer register is the address field of a capability register.
* **Virtual memory:** Sv39 with the CHERI page-table bits (CW, CR, CRM, CD,
  CRG), including the load barrier that CheriBSD's revocation uses.
* **Tags:** one tag per 16-byte granule, kept in a functional tag table, so
  every CPU model and cache sees the same tags. An optional tag controller
  models the timing of a tag table in DRAM behind flat or hierarchical tag
  caches.
* **CPUs:** all four CPU models execute capability instructions. The main
  config boots on Atomic and switches to the detailed model for the program.
* **Platform:** one core with CLINT, PLIC, UART and a VirtIO disk. SBI calls
  are handled by the simulator, so no OpenSBI or BBL firmware is needed.
* **Statistics:** gem5's statistics, plus optional per-privilege-mode
  instruction and cycle counts and per-PC and per-mnemonic profiles.

## Validation

* **cheribsdtest** (CheriBSD's CHERI regression suite): on Atomic, gem5 gives
  the same result as CHERI-QEMU on all 2,088 tests of its eight variants.
  Minor and O3 agree on all 313 purecap tests.
* **Juliet** memory-safety test cases: on purecap, gem5 and CHERI-QEMU agree
  on all 25,180 executions whose outcome does not depend on the guest clock
  or `rand()`, with no false positives.
* **Plain RV64:** the same programs give identical committed instructions
  and cycles on upstream gem5 v24.0 and on this tree, on Atomic, Minor and O3.

The scripts are in [util/cheri/cheribsdtest](util/cheri/cheribsdtest),
[util/cheri/juliet](util/cheri/juliet) and
[util/cheri/baseline](util/cheri/baseline).

## Requirements

* A Linux x86-64 host. Tested on Ubuntu 24.04 with GCC 13.3, SCons 4.5 and
  Python 3.12.
* gem5's build dependencies, for example on Ubuntu:

  ```sh
  sudo apt install build-essential scons python3-dev zlib1g-dev m4 \
      libprotobuf-dev protobuf-compiler libgoogle-perftools-dev
  ```

  See [gem5's build documentation](https://www.gem5.org/documentation/general_docs/building)
  for the full list.
* For CHERI programs (full system): [cheribuild](https://github.com/CTSRD-CHERI/cheribuild)
  and its host packages, to build the CHERI LLVM toolchain, CheriBSD and its
  disk image. This takes about 50 GB of disk and a few hours the first time.

A full-system run uses about 400 MB of host memory.

## 1. Build gem5

```sh
scons build/RISCV_CHERI/gem5.opt -j$(nproc)
```

If a conda or virtualenv Python comes first in `PATH`, add
`PYTHON_CONFIG=/usr/bin/python3-config` so that gem5 links the system Python.

## 2. Quick check in SE mode (no CheriBSD needed)

SE mode runs plain RV64 programs; [util/cheri/examples/bin/se](util/cheri/examples/bin/se)
has two freestanding ones.

```sh
for cpu in atomic minor o3; do
    build/RISCV_CHERI/gem5.opt --outdir m5out/se-$cpu util/cheri/baseline/se.py \
        --isa riscv_cheri --cpu $cpu --binary util/cheri/examples/bin/se/ptrchase
done
```

Each run prints `checksum=0000001ffff80000` and commits 14.4 million
instructions. On a laptop, Atomic takes about 20 s, Minor 1.5 min and O3
6 min.

## 3. Build CheriBSD and its disk image

From the gem5 directory:

```sh
git clone https://github.com/CTSRD-CHERI/cheribuild.git ~/cheribuild
~/cheribuild/cheribuild.py cheribsd-riscv64-purecap -d \
    --cheribsd-riscv64-purecap/kernel-config CHERI-PURECAP-QEMU-NODEBUG
util/cheri/guest/build_m5.sh
~/cheribuild/cheribuild.py disk-image-riscv64-purecap
util/cheri/kernel_for_gem5.py \
    ~/cheri/output/rootfs-riscv64-purecap/boot/kernel/kernel.full \
    tests/kernel-cheribsd

export CHERI_KERNEL=$PWD/tests/kernel-cheribsd
export CHERI_DISK=$HOME/cheri/output/cheribsd-riscv64-purecap.img
```

* The first cheribuild command builds the CHERI LLVM toolchain (the SDK) and
  CheriBSD, with sources in `~/cheri` and outputs in `~/cheri/output`.
* `build_m5.sh` builds gem5's `m5` utility for CheriBSD and installs it with
  [m5_init.sh](util/cheri/guest/m5_init.sh) in `~/cheri/extra-files`, which
  the disk image includes. The guest runs `/etc/m5_init.sh` at boot: it runs
  the file given as `CHERI_READFILE`, then ends the simulation.
* `kernel_for_gem5.py` removes the kernel's dummy program interpreter, which
  gem5's ELF loader would otherwise try to open.

Tested with cheribuild `8a9803f5`, CheriBSD `88f39900c32` (2026-07-20) and
CHERI LLVM `7e122876ee01`. To build exactly these, clone CheriBSD and
llvm-project from [CTSRD-CHERI](https://github.com/CTSRD-CHERI) into
`~/cheri/cheribsd` and `~/cheri/llvm-project`, check out those commits, and
pass `--skip-update` to cheribuild.

## 4. Run the examples on Atomic, Minor and O3

```sh
util/cheri/examples/run.sh atomic
util/cheri/examples/run.sh minor
util/cheri/examples/run.sh o3
```

Each run boots CheriBSD on Atomic, switches to the given CPU at the first
`m5 workbegin` and runs the six programs in
[util/cheri/examples/bin](util/cheri/examples/bin), each built as purecap
and as plain RV64:

| Program | What it shows |
|---|---|
| `hello` | the ABI and the capability of a stack buffer |
| `bounds` | a write one byte past a 16-byte heap buffer: purecap stops it with `SIGPROT`, plain RV64 does not notice |
| `list` | pointer chasing through a 16,384-node linked list: purecap nodes are twice as large |

`run.sh` prints the programs' output, the same on every CPU (the address
in `hello-plain` changes from run to run, and kernel messages may appear in
between):

```
=== hello-purecap
hello: purecap, pointers are 16-byte capabilities
hello: &buf = 0x3fffdffe20 [rwRW,0x3fffdffe20-0x3fffdffe40]
=== hello-purecap exit 0
=== bounds-purecap
bounds: SIGPROT, the out-of-bounds write was stopped
=== bounds-purecap exit 0
=== list-purecap
list: 16384 nodes of 32 bytes, 8 walks, sum 1073676288
=== list-purecap exit 0
=== hello-plain
hello: plain RV64, pointers are 8-byte integers
hello: &buf = 0x800a1a38
=== hello-plain exit 0
=== bounds-plain
bounds: wrote buf[16], the out-of-bounds write went undetected
=== bounds-plain exit 0
=== list-plain
list: 16384 nodes of 16 bytes, 8 walks, sum 1073676288
=== list-plain exit 0
```

The results are in `m5out/examples/<cpu>/`. `console.log` is the full
console. `stats.txt` holds one statistics dump for the boot, one per program
in the order above, and a last one up to the end of the simulation; the
program's core is `board.processor.switch.core` (for example `numCycles`
and `commitStats0.numInsts`). On O3, `list-purecap` takes 3.1× the cycles of
`list-plain` (23.0 million against 7.4 million, including process start-up):
its nodes are twice as large, so its list (512 kB) is twice the size of the
L2.

The boot dominates the run time: about 780 million instructions on Atomic,
up to the first program. With the three runs in parallel on a laptop, each
took about 23 minutes; the programs then take a few seconds each, up to half
a minute on O3.

To run only some programs, name them:
`util/cheri/examples/run.sh o3 util/cheri/examples/bin/list-*`.
[util/cheri/examples/build.sh](util/cheri/examples/build.sh) rebuilds the
binaries from [util/cheri/examples/src](util/cheri/examples/src).

## 5. Run your own programs

Build a static CheriBSD binary with the SDK and pass it to `run.sh`:

```sh
~/cheri/output/sdk/bin/clang --config cheribsd-riscv64-purecap.cfg \
    -O2 -static -o prog prog.c                    # purecap
~/cheri/output/sdk/bin/clang --config cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg \
    -march=rv64imafdc -O2 -static -o prog prog.c  # plain RV64
util/cheri/examples/run.sh o3 ./prog
```

`run.sh` wraps
[cheri-riscv-cheribsd-switch.py](configs/example/gem5_library/cheri-riscv-cheribsd-switch.py),
which you can also run directly with any guest shell script as
`CHERI_READFILE`. Statistics are reset at every `m5 workbegin` and dumped at
every `m5 workend`. [util/cheri/mkrunner.sh](util/cheri/mkrunner.sh) bundles
binaries and their arguments into such a script. The config reads these
environment variables; its header lists all of them:

| Variable | Meaning (default) |
|---|---|
| `CHERI_SWITCH_CPU` | CPU after the first `m5 workbegin`: `atomic`, `timing`, `minor`, `o3` (`timing`) |
| `CHERI_KERNEL`, `CHERI_DISK` | kernel and disk image |
| `CHERI_READFILE` | script the guest runs after booting |
| `CHERI_VIRTIO_SEG_MAX` | VirtIO disk segments; the CheriBSD above needs `126` (`run.sh` sets it) |
| `CHERI_TAG_MODEL` | tag timing: `none`, `passthrough`, `flat`, `hierarchical`, `nocache` (`none`) |
| `CHERI_L1D`, `CHERI_L1I`, `CHERI_L2` | cache sizes (`16kB`, `16kB`, `256kB`) |
| `CHERI_L1D_PF`, `CHERI_L2_PF` | prefetchers, e.g. `none`, `stride`, `tagged`, `ampm` (`stride`) |
| `CHERI_CKPT_OUT`, `CHERI_CKPT_IN` | save a checkpoint at `m5 checkpoint`, or start from one instead of booting |
| `CHERI_PRIV_STATS`, `CHERI_PC_PROFILE`, `CHERI_INST_PROFILE` | `1` adds per-privilege-mode statistics, a per-PC profile, a per-mnemonic profile |

The modelled system is one core at 3 GHz, 16 kB L1 instruction and data
caches, a 256 kB L2 and 3 GB of dual-channel DDR4-2400.

The benchmark suites used with this model (CoreMark-PRO, Olden, Juliet,
cheribsdtest and a tag-traffic study) are in [util/cheri](util/cheri), each
with a README.

## Repository layout

| Path | Contents |
|---|---|
| [src/arch/riscv_cheri](src/arch/riscv_cheri) | the `RISCV_CHERI` ISA: decoder, capability instructions and checks, MMU, faults, SBI |
| [src/arch/generic/cap_reg.hh](src/arch/generic/cap_reg.hh) | the capability register type |
| [src/mem/cheri_tag_table.hh](src/mem/cheri_tag_table.hh), [src/mem/cheri_tag_controller.hh](src/mem/cheri_tag_controller.hh) | the tag table and the tag timing model |
| [src/cpu](src/cpu) | CHERI support in the simple, Minor and O3 CPUs |
| [src/dev/riscv_cheri](src/dev/riscv_cheri) | CLINT and PLIC |
| [src/python/gem5/components](src/python/gem5/components) | `RiscvCheriBoard` and `CheriTaggedMemory` |
| [configs/example/gem5_library](configs/example/gem5_library) | `cheri-riscv-cheribsd-switch.py`; the other `cheri-riscv-cheribsd-*.py` configs are debugging aids with hard-coded paths |
| [util/cheri](util/cheri) | guest setup, examples, benchmark and validation suites |
| [tests/test_framework](tests/test_framework) | a small assembler for bare-metal CHERI test programs |

## Limitations

* One core.
* Only the `RISCV_CHERI` and `RISCV` builds are maintained. The other ISAs
  need an empty capability register class, as `src/arch/riscv/isa.cc` has,
  before they work.
* SE mode runs plain RV64 programs only, since gem5's SE mode emulates Linux
  system calls and CheriBSD programs use FreeBSD's.
* There is no boot loader: gem5 loads the kernel directly and patches one
  instruction in its `_start` so that the device-tree pointer is kept.
* Tested with the CheriBSD version above; other versions may need a
  different `CHERI_VIRTIO_SEG_MAX`.

## gem5

This tree is a fork of gem5. For gem5 itself see <https://www.gem5.org>, its
[documentation](https://www.gem5.org/documentation) and
[source](https://github.com/gem5/gem5). The license is gem5's; see
[LICENSE](LICENSE) and [COPYING](COPYING).
