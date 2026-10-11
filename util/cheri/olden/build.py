#!/usr/bin/env python3
"""Build the Olden benchmarks (LLVM test-suite version) for CheriBSD
RISC-V, purecap and hybrid, plus native reference outputs.

Olden is the standard pointer-intensive suite (trees, lists, graphs built
from malloc'd nodes), so it shows what capability-sized pointers cost.

Both ABIs use the same CHERI LLVM and flags (-O2 -static, -DTORONTO: the
sequential version), only --config differs, as for CoreMark-PRO. patches/
holds the source changes purecap needs (see README.md). Each benchmark is
also built for the host and run with the same arguments; parse.py compares
the guest output with that reference (numbers with a tolerance, since
RISC-V and x86 may round differently) and purecap's with hybrid's (exactly).

Three ABIs: purecap, hybrid (the same code built for a CHERI system) and
plain (RV64 without CHERI: -march=rv64imafdc, plus 8-byte-word
memcpy/memmove instead of the hybrid libc's tag-preserving ones; the
baseline of a core without CHERI).

Usage: util/cheri/olden/build.py [--src DIR] [--work DIR] [--sdk DIR]
         [--abis purecap,hybrid,plain]   (others already built are kept)
  --src   llvm-test-suite/MultiSource/Benchmarks/Olden
          (default ~/hiwi/llvm-test-suite/MultiSource/Benchmarks/Olden;
          left untouched, a patched copy is built)
  --work  default ~/hiwi/olden-gem5
Output: WORK/builds/<abi>/bin/<bench>, WORK/builds/<abi>/bin-stripped/,
        WORK/ref/<bench>.out, WORK/workloads.json (arguments, flags,
        reference exit codes)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = {
    "purecap": "cheribsd-riscv64-purecap.cfg",
    "hybrid": "cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg",
    # plain RV64: the hybrid sysroot, compiled without the CHERI extension,
    # with 8-byte-word memcpy/memmove (util/cheri/common/memcpy64.c)
    "plain": "cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg",
}
ABI_FLAGS = {"purecap": [], "hybrid": [], "plain": ["-march=rv64imafdc"]}
# Arguments sized for detailed simulation: the test suite's
# SMALL_PROBLEM_SIZE inputs (bisort and mst, which have none, scaled down);
# ~50-300 M instructions each, data sets still far larger than the caches
# (e.g. treeadd 20 levels = 1 M nodes, 24 MB hybrid / 48 MB purecap).
WORKLOADS = {
    "bh": {"args": "2000 5", "cflags": ["-fcommon", "-Wno-implicit-int"]},
    "bisort": {"args": "100000", "cflags": []},
    "em3d": {"args": "256 250 35", "cflags": []},
    "health": {"args": "8 15 1", "cflags": []},
    "mst": {"args": "1000", "cflags": []},
    "perimeter": {"args": "9", "cflags": []},
    # power's size is fixed at compile time
    "power": {"args": "", "cflags": ["-DSMALL_PROBLEM_SIZE"]},
    "treeadd": {"args": "20", "cflags": []},
    "tsp": {"args": "102400", "cflags": []},
    "voronoi": {"args": "10000 20 32 7", "cflags": []},
}
COMMON = ["-O2", "-DTORONTO", "-w"]


def run(cmd, **kw):
    p = subprocess.run(cmd, **kw)
    if p.returncode != 0:
        sys.exit(f"failed: {' '.join(cmd)}")
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=os.path.expanduser(
        "~/hiwi/llvm-test-suite/MultiSource/Benchmarks/Olden"))
    ap.add_argument("--work", default=os.path.expanduser("~/hiwi/olden-gem5"))
    ap.add_argument("--sdk", default=os.environ.get(
        "CHERI_SDK", os.path.expanduser("~/cheri/output/sdk")))
    ap.add_argument("--host-cc", default=shutil.which("clang") or "cc")
    ap.add_argument("--abis", default="purecap,hybrid,plain")
    args = ap.parse_args()
    abis = args.abis.split(",")

    work = os.path.abspath(args.work)
    src = os.path.join(work, "src")
    shutil.rmtree(src, ignore_errors=True)
    shutil.copytree(args.src, src)
    for p in sorted(os.listdir(os.path.join(HERE, "patches"))):
        with open(os.path.join(HERE, "patches", p)) as f:
            run(["patch", "-d", src, "-p1", "--forward", "--silent"], stdin=f)

    cc = os.path.join(args.sdk, "bin", "clang")
    strip = os.path.join(args.sdk, "bin", "llvm-strip")
    memcpy64 = os.path.join(work, "memcpy64.o")
    if "plain" in abis:
        run([cc, "--config", CFG["plain"]] + ABI_FLAGS["plain"] +
            ["-O2", "-fno-builtin", "-c", "-o", memcpy64,
             os.path.join(HERE, "..", "common", "memcpy64.c")])
    info = {}
    for b, w in WORKLOADS.items():
        sources = sorted(os.path.join(src, b, f)
                         for f in os.listdir(os.path.join(src, b))
                         if f.endswith(".c"))
        flags = COMMON + w["cflags"]
        for abi in abis:
            cfg = CFG[abi]
            bindir = os.path.join(work, "builds", abi, "bin")
            sdir = os.path.join(work, "builds", abi, "bin-stripped")
            os.makedirs(bindir, exist_ok=True)
            os.makedirs(sdir, exist_ok=True)
            exe = os.path.join(bindir, b)
            extra = [memcpy64] if abi == "plain" else []
            run([cc, "--config", cfg, "-static"] + ABI_FLAGS[abi] + flags +
                sources + extra + ["-o", exe, "-lm"])
            run([strip, "-o", os.path.join(sdir, b), exe])
        # native reference output, same sources and arguments
        ndir = os.path.join(work, "native")
        rdir = os.path.join(work, "ref")
        os.makedirs(ndir, exist_ok=True)
        os.makedirs(rdir, exist_ok=True)
        nexe = os.path.join(ndir, b)
        run([args.host_cc] + flags + sources + ["-o", nexe, "-lm"])
        with open(os.path.join(rdir, b + ".out"), "w") as f:
            rc = subprocess.run([nexe] + w["args"].split(), stdout=f,
                                stderr=subprocess.STDOUT).returncode
        info[b] = dict(w, ref=os.path.join("ref", b + ".out"), ref_exit=rc,
                       sources=[os.path.relpath(s, src) for s in sources],
                       common_cflags=COMMON)
        print(f"{b}: built ({', '.join(abis)}), native exit {rc}",
              flush=True)
    built = sorted(a for a in CFG
                   if os.path.isdir(os.path.join(work, "builds", a, "bin")))
    with open(os.path.join(work, "workloads.json"), "w") as f:
        json.dump({"src": os.path.abspath(args.src), "sdk": args.sdk,
                   "abis": built, "abi_flags": ABI_FLAGS,
                   "patches": sorted(os.listdir(os.path.join(HERE,
                                                             "patches"))),
                   "workloads": info}, f, indent=2)
    print(f"built: {work}/builds (arguments: {work}/workloads.json)")


if __name__ == "__main__":
    main()
