# cheribsdtest on gem5 CHERI-RISC-V

Functional validation with CheriBSD's own CHERI regression suite
(`bin/cheribsdtest` in CheriBSD: bounds, permissions, sealing, sentries,
signals, revocation, ...). The binaries are part of the disk image
(`/bin/cheribsdtest-<variant>`, eight variants: purecap / hybrid, each also
`-dynamic`, `-mt`, `-dynamic-mt`), so nothing is built here.

## Run

```sh
util/cheri/cheribsdtest/run.py --out RESULTS/cheribsdtest/<tag> \
    [--variants purecap,hybrid | all] [--configs atomic,minor,o3] \
    [--jobs 4] [--test-timeout 60] [--timeout 180000] [--tests t1,t2]
```

* One gem5 run per (variant, config) in `OUT/<variant>-<config>/`; each
  boots CheriBSD (atomic) and switches to the config's CPU at the region,
  which covers all tests. Configs are `CPU[-TAGMODEL]` as in the suites.
* Kernel, disk and `CHERI_VIRTIO_SEG_MAX` default to the 2026 setup of
  `holygrail.sh` (`tests/kernel-2026-nodebug`,
  `tests/cheribsd-2026-riscv64-purecap.img`, 126); the environment
  overrides them.
* cheribsdtest's `-a` waits for each test without a timeout, so the job
  lists the tests (`-l`) and starts each one on its own under `timeout(1)`
  (`--test-timeout`, guest seconds), with markers in the console. A run the
  host timeout (`--timeout`, default 50 h) kills keeps every finished test.
* Cost: ~1 h boot, then the tests (purecap lists 313, hybrid 199).

## Reference on CHERI-QEMU

```sh
util/cheri/cheribsdtest/run_qemu.py --out RESULTS/cheribsdtest/qemu --variants all
```

Same kernel and image (`-snapshot`), single-user, the same job without the
m5 operations; needs CHERI-QEMU (`riscv64xcheri`, e.g. `~/cheri/build/qemu-build`)
and cheribuild's BBL (`bbl-baremetal-riscv64-purecap`). Sstc is turned off
(`-cpu rv64,sstc=off`): BBL does not enable S-mode `stimecmp`, so the kernel
uses the SBI timer, as on gem5. ~2-5 min per variant.

Result (2026-10-30): no FAIL in any variant on QEMU (purecap 303 PASS + 10
XFAIL, hybrid 147 + 52, dynamic/mt variants alike); gem5 atomic purecap and
hybrid agree with QEMU on all 512 tests.

## Analyse

```sh
util/cheri/cheribsdtest/parse.py RESULTS/cheribsdtest/<tag> [--ref OTHER/results.csv]
```

Per test: PASS, FAIL, XFAIL (an expected failure annotated in
cheribsdtest, e.g. no bounds on static globals in hybrid), XPASS, SKIP,
TIMEOUT, CRASH, INCOMPLETE, NOTRUN. Writes `results.csv` and `summary.csv`
and lists every FAIL/XPASS/TIMEOUT/CRASH. `--ref` compares with another
`results.csv` (e.g. the same suites on CHERI-QEMU) per (variant, test).
