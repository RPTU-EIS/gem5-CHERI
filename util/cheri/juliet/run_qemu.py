#!/usr/bin/env python3
"""Reference run of Juliet on CHERI-QEMU, for comparison with gem5.

Runs build.py's binaries on the kernel and disk image gem5 uses (-snapshot:
the image is not modified), with gem5's 3 GiB, the same inputs and one boot
per (CWE, ABI, shard), so a shard starts from the same state as a gem5 run
restored from its checkpoint. /tmp is on the root file system, as on gem5: its
block size sets stdio's buffer size, which changes what some bad tests read from
leftover registers (a tmpfs makes 95 plain CWE134 tests differ). Results are in
the same layout, with config "qemu": parse.py reads OUT like a gem5 run,
compare.py sets the two side by side.

QEMU runs with -icount shift=0,sleep=off: one instruction per guest
nanosecond, and idle time is skipped, so tests waiting on a socket cost no
host time. gem5's atomic CPU runs about 2e9 instructions per guest second, so
the default --test-timeout of 2 gives a CPU-bound test about the instructions
that gem5's 1 s does. A test that spins until its timeout takes seconds here
and hours on gem5, so this also finishes the shards gem5's time limit stopped.

Usage:
  util/cheri/juliet/run_qemu.py --out RESULTS/juliet/qemu \\
      [--abis purecap,plain] [--cwes 121,122] [--jobs 6] [--test-timeout 2]
Environment: CHERI_KERNEL, CHERI_DISK, QEMU, QEMU_BIOS as util/cheri/qemu_job.py
"""

import argparse
import concurrent.futures as cf
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


jl = load("jl_run", os.path.join(HERE, "run.py"))
qj = load("qemu_job", os.path.join(HERE, "..", "qemu_job.py"))

MEMORY_MB = 3072  # as gem5's DualChannelDDR4_2400(size="3GB")
ICOUNT = "shift=0,sleep=off"
# CWE680's tests fill several GiB, so limit how many of them run at once.
FILLS_MEMORY = {680}
MAX_FILLING = 2


def run_shard(out, builds, cwe, abi, name, prog, runs, exes, test_timeout,
              timeout, filling):
    jdir = os.path.join(out, f"CWE{cwe}", "jobs")
    os.makedirs(jdir, exist_ok=True)
    members = jl.shard_members(os.path.join(jdir, f"{abi}-{name}.sh"), builds,
                               cwe, prog, runs, exes)
    script = [
        "cd /tmp && rm -rf /tmp/jl && mv /tmp/payload /tmp/jl",
        "mkdir -p /tmp/jl/work && cd /tmp/jl/work",
    ]
    script += jl.guest_setup(cwe, len(runs))
    script += jl.guest_tests(prog, exes, runs, test_timeout, 0)
    script.append('echo "=== JL-END status=$st"')
    outdir = os.path.join(out, f"CWE{cwe}", f"{abi}-qemu", name)
    os.makedirs(outdir, exist_ok=True)
    log = os.path.join(outdir, "console.log")
    if cwe in FILLS_MEMORY:
        with filling:
            secs = qj.run_job(script, log, members, ICOUNT, MEMORY_MB, timeout,
                              tmp_on_root=True)
    else:
        secs = qj.run_job(script, log, members, ICOUNT, MEMORY_MB, timeout,
                          tmp_on_root=True)
    return outdir, len(runs), secs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--builds",
                    default=os.path.expanduser("~/hiwi/juliet-gem5/out"))
    ap.add_argument("--abis", default="purecap,plain")
    ap.add_argument("--cwes", default=None, help="comma list (default: all)")
    ap.add_argument("--test-timeout", type=int, default=2,
                    help="guest seconds per test")
    ap.add_argument("--timeout", type=int, default=4 * 3600,
                    help="host seconds per QEMU run")
    ap.add_argument("--jobs", type=int, default=6)
    args = ap.parse_args()

    builds = os.path.abspath(args.builds)
    abis = args.abis.split(",")
    if args.cwes:
        cwes = [int(c.removeprefix("CWE")) for c in args.cwes.split(",")]
    else:
        cwes = sorted(int(d[3:]) for d in os.listdir(
            os.path.join(builds, abis[0])) if d.startswith("CWE"))
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    env = {k: os.environ.get(k, v) for k, v in qj.DEFAULTS.items()}
    with open(env["CHERI_KERNEL"], "rb") as f:
        kernel_sha = hashlib.sha256(f.read()).hexdigest()
    qemu_ver = subprocess.run([env["QEMU"], "--version"], capture_output=True,
                              text=True).stdout.split("\n")[0]
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump({
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "suite": "juliet", "simulator": qemu_ver, "qemu": env["QEMU"],
            "firmware": env["QEMU_BIOS"], "kernel": env["CHERI_KERNEL"],
            "kernel_sha256": kernel_sha, "disk": env["CHERI_DISK"],
            "builds": builds, "abis": abis, "cwes": cwes,
            "memory_mb": MEMORY_MB, "icount": ICOUNT, "tmp": "root file system",
            "test_timeout_guest_seconds": args.test_timeout,
            "layout": "OUT/CWE<n>/<abi>-qemu/<shard>/",
            "command": " ".join(sys.argv),
        }, f, indent=2)

    jobs = [(cwe, abi, *sh) for cwe in cwes for abi in abis
            for sh in jl.load_shards(builds, abi, cwe, 0)]
    # Largest shards first, so the tail of the run is short.
    jobs.sort(key=lambda j: -len(j[4]))
    print(f"{len(jobs)} QEMU runs, {sum(len(j[4]) for j in jobs)} test "
          "executions", flush=True)
    filling = threading.Semaphore(MAX_FILLING)
    failed = []
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(run_shard, out, builds, *j, args.test_timeout,
                            args.timeout, filling) for j in jobs]
        for fut in cf.as_completed(futs):
            outdir, want, secs = fut.result()
            status, got = jl.shard_status(outdir)
            rel = os.path.relpath(outdir, out)
            if status != "0" or got != want:
                failed.append(rel)
            print(f"{rel}: shard status {status}, {got}/{want} tests reported"
                  f", {secs / 60:.1f} min", flush=True)
    if failed:
        print(f"\nWARNING: {len(failed)} shard(s) incomplete:\n  "
              + "\n  ".join(sorted(failed)), flush=True)
    print(f"next: util/cheri/juliet/parse.py {out}")


if __name__ == "__main__":
    main()
