#!/usr/bin/env python3
"""Phase boundaries of the Olden builds for CHERI_STATS_AT_PC.

Each program builds its data structure, then computes on it. For every
(ABI, workload) build this writes the guest PCs of three function entries,
each counted once (the first call): the build function, the compute
function and libc's exit(), so that the stats dumps split the region into
startup / build / compute / exit (util/cheri/phase_stats.py --labels
startup,build,compute,exit). Addresses come from the unstripped binaries'
symbol tables (static, non-PIE, so the same in the stripped copies the
runs use); every function must be called, not only defined (bh builds with
uniform_testdata, voronoi computes in build_delaunay).

Usage: util/cheri/olden/phase_pcs.py [--work ~/hiwi/olden-gem5]
         [--sdk ~/cheri/output/sdk] [--abis plain,purecap]
         [--out util/cheri/olden/phase-pcs.json]
Rerun after rebuilding the binaries.
"""

import argparse
import json
import os
import subprocess

PHASES = {  # workload: (build function, compute function)
    "bh": ("uniform_testdata", "stepsystem"),
    "bisort": ("RandTree", "Bisort"),
    "em3d": ("initialize_graph", "compute_nodes"),
    "health": ("alloc_tree", "sim"),
    "mst": ("MakeGraph", "ComputeMst"),
    "perimeter": ("MakeTree", "CountTree"),
    "power": ("build_tree", "Compute_Tree"),
    "treeadd": ("TreeAlloc", "TreeAdd"),
    "tsp": ("build_tree", "tsp"),
    "voronoi": ("get_points", "build_delaunay"),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", default=os.path.expanduser("~/hiwi/olden-gem5"))
    ap.add_argument("--sdk", default=os.path.expanduser("~/cheri/output/sdk"))
    ap.add_argument("--abis", default="plain,purecap")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "phase-pcs.json"))
    a = ap.parse_args()
    nm = os.path.join(a.sdk, "bin", "llvm-nm")
    out = {}
    for abi in a.abis.split(","):
        for wl, (build, compute) in PHASES.items():
            path = os.path.join(a.work, "builds", abi, "bin", wl)
            syms = {}
            for line in subprocess.run([nm, path], capture_output=True,
                                       text=True, check=True).stdout.split(
                                           "\n"):
                p = line.split()
                if len(p) == 3 and p[1] in "Tt":
                    syms.setdefault(p[2], int(p[0], 16))
            pcs = [syms[f] for f in (build, compute, "exit")]
            out[f"{abi}/{wl}"] = {
                "CHERI_STATS_AT_PC": ",".join(f"{pc:#x}:1" for pc in pcs)}
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {a.out} ({len(out)} builds)")


if __name__ == "__main__":
    main()
