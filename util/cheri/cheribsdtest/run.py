#!/usr/bin/env python3
"""Run CheriBSD's cheribsdtest suites on the gem5 CHERI-RISC-V model.

cheribsdtest is CheriBSD's regression suite for CHERI semantics (bounds,
permissions, sealing, sentries, signals, revocation, ...). Its binaries are
part of the disk image (/bin/cheribsdtest-<variant>), so a run only needs a
job script. One gem5 run per (variant, config) in OUT/<variant>-<config>/
(config = CPU[-TAGMODEL]); each boots CheriBSD on the atomic CPU and switches
to CPU at the region (`m5 workbegin`), which covers all tests.

cheribsdtest's own `-a` waits for every test child without a timeout, so one
hung test would stop the run. The job therefore lists the tests (`-l`) and
starts each one separately under timeout(1) (guest seconds), printing a
marker before and after it: a run killed by the host timeout still has the
results of every test it finished. parse.py reads console.log.

The kernel, disk and virtio settings default to the 2026 setup of
holygrail.sh (CHERI_KERNEL, CHERI_DISK, CHERI_VIRTIO_SEG_MAX override them).

Usage:
  util/cheri/cheribsdtest/run.py --out RESULTS/cheribsdtest/<tag> \\
      [--variants purecap,hybrid] [--configs atomic,minor,o3] [--jobs 4]
      [--test-timeout 60] [--timeout 180000] [--tests t1,t2]
"""

import argparse
import concurrent.futures as cf
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "cm_run", os.path.join(HERE, "..", "coremark", "run.py")
)
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)  # shared gem5 helpers
GEM5 = cm.GEM5

VARIANTS = [
    "purecap",
    "purecap-dynamic",
    "purecap-mt",
    "purecap-dynamic-mt",
    "hybrid",
    "hybrid-dynamic",
    "hybrid-mt",
    "hybrid-dynamic-mt",
]
SYSTEM_DEFAULTS = {
    "CHERI_KERNEL": os.path.join(GEM5, "tests", "kernel-2026-nodebug"),
    "CHERI_DISK": os.path.join(
        GEM5, "tests", "cheribsd-2026-riscv64-purecap.img"),
    "CHERI_VIRTIO_SEG_MAX": "126",
}


def job(variant, test_timeout, tests):
    """Guest script: list the tests, then run each under timeout(1)."""
    exe = f"/bin/cheribsdtest-{variant}"
    # /tmp on tmpfs as in CheriBSD's test setup (tmpfs_rw_nocaps skips
    # otherwise); the gem5 boot flow does not mount one
    lines = ["#!/bin/sh",
             "mount -p | awk '$2 == \"/tmp\" && $3 == \"tmpfs\"' | grep -q . "
             "|| mount -t tmpfs tmpfs /tmp",
             "cd /tmp"]
    lines += cm.guest_prelude("off")
    lines += [
        f"[ -x {exe} ] || {{ echo '=== CBT-MISSING {exe}'; "
        f"echo '=== CM-END {variant} status=127'; exit 0; }}",
    ]
    if tests:
        lines.append("printf '%s\\n' " + " ".join(tests) + " > /tmp/cbt.lst")
    else:
        lines.append(f"{exe} -l < /dev/null | grep -E '^[a-z][a-z0-9_]*$' "
                     "> /tmp/cbt.lst")
    lines += [
        "sed 's/^/=== CBT-LIST /' /tmp/cbt.lst",
        'echo "=== CBT-NTESTS $(wc -l < /tmp/cbt.lst)"',
        f'echo "=== CM-BEGIN {variant}"',
        "/sbin/m5 workbegin",
        "while read t; do",
        '  echo "=== CBT-TEST $t"',
        f'  timeout -s KILL {test_timeout} {exe} "$t" < /dev/null 2>&1',
        '  echo "=== CBT-RC $t $?"',
        "done < /tmp/cbt.lst",
        "/sbin/m5 workend",
        f'echo "=== CM-END {variant} status=0"',
    ]
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="results directory")
    ap.add_argument("--variants", default="purecap,hybrid",
                    help=f"comma list of {','.join(VARIANTS)} (or 'all')")
    ap.add_argument("--configs", default="atomic",
                    help="comma list of CPU[-TAGMODEL]")
    ap.add_argument("--tests", default=None,
                    help="comma list of test names (default: every test the "
                    "variant lists)")
    ap.add_argument("--test-timeout", type=int, default=60,
                    help="guest seconds per test before it is killed")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument(
        "--timeout",
        type=int,
        default=50 * 3600,
        help="host seconds per gem5 run before it is killed (default 50 h)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    variants = (VARIANTS if args.variants == "all"
                else args.variants.split(","))
    for v in variants:
        if v not in VARIANTS:
            sys.exit(f"unknown variant {v} ({', '.join(VARIANTS)})")
    cfg = {}
    for c in args.configs.split(","):
        cpu, _, tag = c.partition("-")
        tag = tag or "none"
        if cpu not in ("atomic", "timing", "minor", "o3") or tag not in (
            "none",
            "passthrough",
            "nocache",
            "flat",
            "hierarchical",
        ):
            sys.exit(f"bad config {c}")
        cfg[c] = (cpu, tag)
    tests = args.tests.split(",") if args.tests else None

    env = dict(os.environ)
    for k, v in SYSTEM_DEFAULTS.items():
        env.setdefault(k, v)
    for k in ("CHERI_KERNEL", "CHERI_DISK"):
        if not os.path.exists(env[k]):
            sys.exit(f"missing {k}={env[k]}")
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    knobs = {k: env[k] for k in cm.ENV_KNOBS + ["CHERI_MISALIGNED"]
             if k in env}
    gem5_rev = subprocess.run(
        ["git", "-C", GEM5, "describe", "--always", "--dirty"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "suite": "cheribsdtest",
        "gem5_rev": gem5_rev,
        "gem5_bin": cm.GEM5_BIN,
        "config": cm.CONFIG,
        "variants": variants,
        "configs": {c: {"cpu": a, "tag_model": t} for c, (a, t) in cfg.items()},
        "layout": "OUT/<variant>-<config>/",
        "tests": tests,
        "test_timeout_guest_seconds": args.test_timeout,
        "timeout_host_seconds": args.timeout,
        "env_knobs": knobs,
        "system_files": {
            "CHERI_KERNEL": {"path": os.path.abspath(env["CHERI_KERNEL"]),
                             "sha256": cm.sha256(env["CHERI_KERNEL"])},
            "CHERI_DISK": {"path": os.path.abspath(env["CHERI_DISK"])},
        },
        "command": " ".join(sys.argv),
    }
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"manifest: {os.path.join(out, 'manifest.json')}")

    scripts = {}
    for v in variants:
        path = os.path.join(out, f"job-{v}.sh")
        with open(path, "w") as f:
            f.write("\n".join(job(v, args.test_timeout, tests)) + "\n")
        scripts[v] = path
    if args.dry_run:
        return

    runs = [(v, c) for v in variants for c in cfg]
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(cm.run_one, os.path.join(out, f"{v}-{c}"),
                            cfg[c][0], cfg[c][1], scripts[v], args.timeout,
                            env)
                for v, c in runs]
        for fut in cf.as_completed(futs):
            outdir, rc, secs = fut.result()
            print(f"{os.path.relpath(outdir, out)}: driver exit {rc}, "
                  f"{secs / 3600:.1f} h", flush=True)
    print(f"next: util/cheri/cheribsdtest/parse.py {out}")


if __name__ == "__main__":
    main()
