#!/usr/bin/env python3
"""Collect a cache-size sweep (cache_sweep.sh) into one table.

Reads each results directory's results.csv and the cache sizes recorded in
its manifest.json (CHERI_L1D / CHERI_L2; unset = the defaults 16kB / 256kB),
keeps one CPU/tag config (default minor), and writes OUT/cache_sweep.csv:
one row per (L1D, L2, ABI, workload) with cycles, instructions, IPC, misses
and DRAM traffic, plus each ABI's cycles relative to the baseline ABI
(plain if present) at the default cache sizes. Prints, per workload, cycles
of every ABI at every point relative to that baseline, and the measured
points at which purecap is at least as fast as the baseline at the default
sizes. Only simulated points are reported; nothing is interpolated.

Usage: util/cheri/cache_sweep_collect.py DIR [DIR ...] [--config minor]
         [--out DIR]
"""

import argparse
import csv
import json
import os
import re
import sys

DEFAULT = {"CHERI_L1D": "16kB", "CHERI_L2": "256kB"}
FIELDS = ["cycles", "insts", "ipc", "l1d_misses", "l2_misses", "l1d_mpki",
          "l2_mpki", "dram_bytes_read", "dram_bytes_written"]


def size_bytes(s):
    m = re.fullmatch(r"(\d+)\s*([kKmMgG]?)i?[bB]?", s.strip())
    if not m:
        return float("inf")
    return int(m.group(1)) * {"": 1, "k": 1 << 10, "m": 1 << 20,
                              "g": 1 << 30}[m.group(2).lower()]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--config", default="minor")
    ap.add_argument("--out", help="default: the first DIR's parent")
    args = ap.parse_args()

    rows = []
    for d in args.dirs:
        try:
            man = json.load(open(os.path.join(d, "manifest.json")))
            res = list(csv.DictReader(open(os.path.join(d, "results.csv"))))
        except OSError as e:
            print(f"skipping {d}: {e}", file=sys.stderr)
            continue
        knobs = man.get("env_knobs", {})
        l1d = knobs.get("CHERI_L1D", DEFAULT["CHERI_L1D"])
        l2 = knobs.get("CHERI_L2", DEFAULT["CHERI_L2"])
        for r in res:
            if r.get("config") != args.config:
                continue
            ok = str(r.get("status")) == "0" and str(r.get("errors", "0")) \
                in ("0", "")
            rows.append(dict({"l1d": l1d, "l2": l2, "abi": r["abi"],
                              "workload": r["workload"], "valid": int(ok),
                              "dir": d}, **{k: r.get(k, "") for k in FIELDS}))
    if not rows:
        sys.exit("no rows")
    abis = {r["abi"] for r in rows}
    base_abi = "plain" if "plain" in abis else "hybrid"
    key = lambda r: (r["l1d"], r["l2"], r["abi"], r["workload"])
    by = {key(r): r for r in rows}
    for r in rows:
        b = by.get((DEFAULT["CHERI_L1D"], DEFAULT["CHERI_L2"], base_abi,
                    r["workload"]))
        try:
            r[f"cycles_vs_{base_abi}_default"] = (
                float(r["cycles"]) / float(b["cycles"]))
        except (TypeError, ValueError, ZeroDivisionError):
            r[f"cycles_vs_{base_abi}_default"] = ""
    rows.sort(key=lambda r: (r["workload"], size_bytes(r["l1d"]),
                             size_bytes(r["l2"]), r["abi"]))
    out = args.out or os.path.dirname(os.path.abspath(args.dirs[0]))
    path = os.path.join(out, "cache_sweep.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    points = sorted({(r["l1d"], r["l2"]) for r in rows},
                    key=lambda p: (size_bytes(p[0]), size_bytes(p[1])))
    order = [a for a in ("plain", "hybrid", "purecap") if a in abis]
    col = f"cycles_vs_{base_abi}_default"
    print(f"cycles relative to {base_abi} at L1D {DEFAULT['CHERI_L1D']}, "
          f"L2 {DEFAULT['CHERI_L2']} ({args.config}; - = not simulated "
          "or failed)")
    for wl in sorted({r["workload"] for r in rows}):
        print(f"\n{wl}")
        print(f"  {'L1D':>6} {'L2':>6} " +
              " ".join(f"{a:>9}" for a in order))
        for l1d, l2 in points:
            cells = []
            for a in order:
                r = by.get((l1d, l2, a, wl))
                v = r.get(col) if r and r["valid"] else ""
                cells.append(f"{v:9.3f}" if v != "" else f"{'-':>9}")
            print(f"  {l1d:>6} {l2:>6} " + " ".join(cells))
        if "purecap" in abis:
            ok = [f"{l1d}/{l2}" for l1d, l2 in points
                  if (r := by.get((l1d, l2, "purecap", wl))) and r["valid"]
                  and r.get(col) != "" and r[col] <= 1.0]
            print(f"  purecap <= {base_abi}@default at: "
                  f"{', '.join(ok) if ok else 'none of the simulated points'}")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
