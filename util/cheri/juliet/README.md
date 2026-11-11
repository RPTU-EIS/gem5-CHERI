# Juliet C/C++ test suite on gem5 CHERI-RISC-V (purecap vs hybrid vs plain RV64)

Security evaluation with NIST's Juliet 1.3 test suite
([arichardson/juliet-test-suite-c](https://github.com/arichardson/juliet-test-suite-c),
the version cheribuild uses). Every test case has a *bad* variant (contains
the CWE's bug) and a *good* variant (same code, bug fixed). Under CheriBSD on
the gem5 model, a purecap bad test should be stopped by a capability fault
(SIGPROT); the hybrid build (integer pointers on a CHERI system) and the
plain RV64 build (no CHERI instructions; a core without CHERI) are the
unprotected baselines; good tests must pass under every ABI (no false
positives). `build.py --abis plain` adds plain to an existing build. It also exercises the
model's CHERI checks on ~13k distinct programs per ABI.

## 1. Build (on a machine with the CHERI SDK)

```sh
git clone https://github.com/arichardson/juliet-test-suite-c ~/hiwi/juliet-test-suite-c
util/cheri/juliet/build.py [--src SRC] [--work WORK] [--cwes 121,122,...] \
    [--shard-size 250] [--jobs N]
#   SRC   default ~/hiwi/juliet-test-suite-c  (left untouched)
#   WORK  default ~/hiwi/juliet-gem5
```

* Default CWEs: cheribuild's memory-safety set, 121 122 124 126 127 134 188
  415 416 587 588 680 685 843 (stack/heap overflow, buffer underwrite,
  over-/under-read, format string, memory-layout reliance, double free, use
  after free, fixed address, non-structure pointer, integer overflow to
  buffer overflow, wrong argument count, type confusion), 13,395 tests. Any
  other CWE works too.
* Same compilation as cheribuild's `juliet-cwe-*` targets: `-O0 -g` (the
  bugs are undefined behaviour that optimisation removes), Windows-only tests
  excluded, CWE188 purecap with `-cheri-bounds=subobject-safe`. Both ABIs use
  the same CHERI LLVM and flags; only `--config` differs
  (`cheribsd-riscv64-purecap.cfg`,
  `cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg`). Warnings are silenced
  (`-w`): the tests contain what they warn about.
* **What differs from cheribuild: how tests are started.** cheribuild runs
  one executable per test and variant (the test's own `main()`). Under
  simulation creating a process dominates (a dynamically linked exec costs
  more than most tests), so each test's `good()`/`bad()` entry points are
  compiled once and linked into **static multi-call binaries** of up to 250
  tests (`sNN`). The binary forks once per test and variant and, in the
  child, does what the test's `main()` does (`srand(time(NULL))`, then the
  entry point), with stdin from the CWE's input file, stdout/stderr to
  `/dev/null`, no core dumps and a SIGALRM timeout. The test code is
  identical; a fault ends only that child. Tests that cannot share a binary
  (class-based C++ tests, whose good and bad files each define `main` and the
  same class; or any whose objects clash when linked together) are built as
  separate static executables per variant, with the suite's
  `INCLUDEMAIN`/`OMITGOOD`/`OMITBAD`, and started by `jrun` (`xNN` shards).
* **Static linking** also makes the binaries independent of the disk
  image's libraries: dynamically linked binaries from the current SDK fail
  on the 2024 image (every purecap test, good ones included, gets SIGPROT).
* Output: `WORK/out/<abi>/CWE<n>/{sNN, sep/, shards.json}`, `WORK/out/jrun`,
  `WORK/build-summary.{json,txt}` (tests found / built / multi-call /
  separate / failed per ABI and CWE). About 1.0-1.4 MB per 250-test shard.

## 2. Run

```sh
util/cheri/juliet/run.py --out RESULTS/juliet/<tag> \
    --checkpoint RESULTS/checkpoints/juliet-k<kernel> \
    [--configs atomic] [--abis purecap,hybrid] [--cwes 121,122] \
    [--test-timeout 1] [--misaligned emulate|trap] [--jobs 16] [--limit N]
```

* One gem5 run per (CWE, ABI, config, shard) in
  `OUT/CWE<n>/<abi>-<config>/<shard>/` (`console.log`, `stats.txt`, ...);
  guest scripts and the expected test list per shard in `OUT/CWE<n>/jobs/`.
* Each run restores a checkpoint of booted CheriBSD (`BASE-notag`, plus
  `BASE-tagged` for tag-model configs; created on first use, ~20 min; it
  holds no test binaries, so it is reused across builds and CWEs), unpacks
  its shard and runs all good, then all bad variants inside one
  `m5 workbegin`/`workend` region (so `stats.txt` covers exactly the tests).
* Inputs as cheribuild: stdin `500` for CWE121/122/126, `-500` for 124/127,
  a format string for 134 (plus `ADD=%s%d%s` and `/tmp/file.txt`), empty
  otherwise.
* `--misaligned emulate` (default) makes misaligned data accesses to DRAM
  complete, as on QEMU (where CHERI Juliet results are usually reported) and
  on hardware whose firmware emulates them. gem5's default (`trap`) raises
  address-misaligned exceptions, which CheriBSD turns into SIGBUS, so the
  hybrid baseline would "detect" e.g. most type-confusion tests. Capability
  accesses must be 16-byte aligned either way (checked before the PMA).
  This is the `CHERI_MISALIGNED` knob of `cheri-riscv-cheribsd-switch.py`.
* The guest kernel is built with WITNESS (lock-order checking); each job
  turns it off (`sysctl debug.witness.watch=0`), saving ~25% of simulated
  time. It does not affect CHERI behaviour.
* `--configs` defaults to `atomic`: whether a test traps does not depend on
  the timing model. `minor`, `minor-hierarchical`, ... also work (e.g. to
  check that tags survive the tag-storage model).
* `--limit N`: only the first N tests per CWE (pilot).
* Cost (Atomic): ~3-4 host seconds per test run (fork, test, exit), plus
  ~6 min per shard (restore + unpack). The default set is ~53,600 runs
  (13,395 tests x 2 variants x 2 ABIs) in ~110 shards: ~60-65 host hours,
  e.g. ~4 h with `--jobs 16`.

## 3. Analyse

```sh
util/cheri/juliet/parse.py RESULTS/juliet/<tag>
```

Classifies every run: `ok` (exit 0), `sigprot` (SIGPROT, a CHERI fault),
`segv`, `bus`, `abort` (e.g. allocator detecting a double free), `ill`,
`signal-N`, `exit-N`, `timeout` (e.g. waits for a socket connection; both
ABIs), `missing` (shard incomplete). Writes `results.csv` (one row per run),
`summary.csv` (counts) and `detection.csv` (per ABI/config/CWE: bad tests
stopped by SIGPROT, by another signal, undetected; good tests ok / false
positive), and prints the detection table.

Expected, from the pilot: purecap stops spatial bugs (CWE843 type
confusion: 58/60 SIGPROT); use after free (CWE416) is not detected in
either ABI, since CheriBSD's revocation only invalidates capabilities to
freed memory after a revocation pass, not on `free()`.

## Reference on CHERI-QEMU

```sh
util/cheri/juliet/run_qemu.py --out RESULTS/juliet/qemu [--abis purecap,plain] [--jobs 6]
util/cheri/juliet/parse.py RESULTS/juliet/qemu
util/cheri/juliet/compare.py GEM5/results.csv RESULTS/juliet/qemu/results.csv --latex
```

Same binaries, kernel, disk, memory size and inputs as gem5, one boot per
shard, config `qemu` in the same layout. `-icount shift=0,sleep=off` with a 2 s
test timeout gives a CPU-bound test about the instructions of gem5's 1 s, and a
test that spins to its timeout takes seconds instead of hours, so all shards
finish (about 25 min on 6 host cores). `/tmp` is on the root file system as on
gem5: some bad tests depend on stdio's buffer size, which follows the block size.

Result (2026-11-04, plain and purecap, two QEMU runs): no false positive on either
simulator and all good versions agree. On purecap, gem5 and QEMU agree on all 25,180
comparable executions that do not depend on `rand()`; the other differences are tests
seeded from the guest clock (flow variant `_12`, `_rand` sources), and the two QEMU
runs differ from each other on such tests too. On plain, one QEMU run matches gem5 on all
24,498 such executions; the other differs on 99, all in two shards whose outcome changes
between QEMU boots.

## Everything in one place (e.g. on a server)

```sh
JOBS=16 util/cheri/juliet/run_all.sh ~/cheri-results [TAG]
```

keeps the checkpoint in `RESULTS/checkpoints/juliet-k<kernel hash>-*` and
the run in `RESULTS/juliet/<TAG>/`. Needs on the server: this gem5 tree
built, the disk image, and `WORK/out/` copied from the build machine
(`BUILDS=` points at it). No SDK, cheribuild or CMake needed there.
