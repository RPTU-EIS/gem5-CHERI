#!/usr/bin/env python3
"""Tabulate the baseline check (run.sh): per kernel and CPU model, each
build's committed instructions, cycles and checksum, relative to the
reference build (default stock). Writes OUT/baseline.csv.

Usage: util/cheri/baseline/compare.py OUT [--ref stock]
"""

import argparse
import csv
import os
import re

STATS = {
    "insts": re.compile(r"^simInsts\s+(\d+)"),
    "cycles": re.compile(r"^board\.processor\.cores\.core\.numCycles\s+(\d+)"),
    "ticks": re.compile(r"^simTicks\s+(\d+)"),
    "host_s": re.compile(r"^hostSeconds\s+([\d.]+)"),
}


def read_run(d):
    r = {}
    try:
        with open(os.path.join(d, "stats.txt")) as f:
            for line in f:
                for k, rx in STATS.items():
                    m = rx.match(line)
                    if m:
                        r[k] = float(m.group(1))
    except OSError:
        pass
    try:
        with open(os.path.join(d, "run.log"), errors="replace") as f:
            m = re.search(r"checksum=([0-9a-f]+)", f.read())
            r["checksum"] = m.group(1) if m else "none"
    except OSError:
        r["checksum"] = "none"
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("--ref", default="stock")
    args = ap.parse_args()
    builds = sorted(os.listdir(args.out))
    builds = [b for b in builds if os.path.isdir(os.path.join(args.out, b))]
    rows = []
    for b in builds:
        for cpu in sorted(os.listdir(os.path.join(args.out, b))):
            for k in sorted(os.listdir(os.path.join(args.out, b, cpu))):
                r = read_run(os.path.join(args.out, b, cpu, k))
                rows.append(dict(build=b, cpu=cpu, kernel=k, **r))
    ref = {(r["cpu"], r["kernel"]): r for r in rows if r["build"] == args.ref}
    for r in rows:
        f = ref.get((r["cpu"], r["kernel"]), {})
        for k in ("insts", "cycles"):
            if k in r and f.get(k):
                r[k + "_vs_ref"] = r[k] / f[k]
        r["checksum_vs_ref"] = ("same" if f.get("checksum") == r["checksum"]
                                else "differs")
    cols = ["build", "cpu", "kernel", "insts", "cycles", "ticks", "host_s",
            "checksum", "insts_vs_ref", "cycles_vs_ref", "checksum_vs_ref"]
    with open(os.path.join(args.out, "baseline.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{'cpu':7s} {'kernel':9s} " + " ".join(
        f"{b + ' insts/cyc':>22s}" for b in builds if b != args.ref))
    for cpu in ("atomic", "timing", "minor", "o3"):
        for k in sorted({r["kernel"] for r in rows}):
            cells = []
            for b in builds:
                if b == args.ref:
                    continue
                r = next((x for x in rows if x["build"] == b and
                          x["cpu"] == cpu and x["kernel"] == k), None)
                if not r or "insts_vs_ref" not in r:
                    cells.append(f"{'-':>22s}")
                    continue
                flag = "" if r["checksum_vs_ref"] == "same" else " !sum"
                cells.append(f"{r['insts_vs_ref']:9.6f}/"
                             f"{r.get('cycles_vs_ref', 0):9.6f}{flag:>3s}")
            if any(c.strip() != "-" for c in cells):
                print(f"{cpu:7s} {k:9s} " + " ".join(cells))
    print(f"(ratios vs {args.ref}; wrote {args.out}/baseline.csv)")


if __name__ == "__main__":
    main()
