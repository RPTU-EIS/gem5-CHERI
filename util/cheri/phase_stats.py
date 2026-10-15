#!/usr/bin/env python3
"""Split one region's statistics into phases and privilege modes.

For runs made with CHERI_STATS_AT_PC (cumulative stats dumps when the
detailed CPU commits given PCs) and CHERI_PRIV_STATS=1 (instructions and
cycles per privilege mode). Each RUN_DIR is one <abi>-<config> directory
(console.log + stats.txt) holding a single workbegin/workend region: its
dumps are the PC dumps, in the order console.log reports them, then the
workend dump (gem5's final dump at exit is ignored). Phase i is the difference between consecutive dumps (phase 0
starts at the workbegin reset), so the phases add up to the region exactly.

Usage: util/cheri/phase_stats.py RUN_DIR [RUN_DIR ...]
         [--labels startup,alloc,traverse,exit] [--out phases.csv]
Prints per run and phase the main counters, split by user/supervisor/
machine mode, and for two or more runs each run minus the first (e.g.
purecap - plain) per phase and mode. Writes every value to --out.
"""

import argparse
import csv
import importlib.util
import os
import re
import sys

_spec = importlib.util.spec_from_file_location(
    "cm_parse",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "coremark",
                 "parse.py"))
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)

MODES = ["user", "supervisor", "machine"]
# counters that add up over phases (metrics() names)
FIELDS = ["insts", "cycles", "idle_cycles", "loads", "stores",
          "inst_IntAlu", "inst_No_OpClass", "l1d_accesses", "l1d_misses",
          "l2_misses", "dram_bytes_read", "dram_bytes_written",
          "dtlb_accesses", "dtlb_misses", "dptw_accesses", "dptw_misses",
          "sim_ticks"]
SHOW = ["insts", "cycles", "idle_cycles", "l1d_misses", "l2_misses",
        "dram_bytes", "dtlb_misses", "dptw_accesses"]


def counters(d):
    m = cm.metrics(d)
    out = {f: m[f] for f in FIELDS}
    out["dram_bytes"] = m["dram_bytes_read"] + m["dram_bytes_written"]
    for mode in MODES:
        for what in ("insts", "cycles"):
            out[f"{mode}_{what}"] = cm.total(
                d, cm.CORE + rf"priv_tracker\.{what}::{mode}")
    return out


def phases(run, labels):
    con = open(os.path.join(run, "console.log"), errors="replace").read()
    pcs = re.findall(r"\[pc-stats\] dump \d+: pc=(0x[0-9a-f]+) count=(\d+)",
                     con)
    dumps = [counters(d) for d in
             cm.stat_dumps(os.path.join(run, "stats.txt"))]
    # gem5 dumps once more at exit (after the workend): ignore that one
    if len(dumps) < len(pcs) + 1:
        sys.exit(f"{run}: {len(dumps)} stats dumps for {len(pcs)} PC dumps "
                 "+ 1 workend (expected one region)")
    dumps = dumps[:len(pcs) + 1]
    names = labels or [f"phase{i}" for i in range(len(dumps))]
    if len(names) != len(dumps):
        sys.exit(f"{run}: {len(dumps)} phases, {len(names)} labels")
    prev = {k: 0.0 for k in dumps[0]}
    rows = []
    for i, (name, d) in enumerate(zip(names, dumps)):
        row = {k: d[k] - prev[k] for k in d}
        row.update(run=os.path.basename(os.path.normpath(run)), phase=name,
                   ends_at=f"{pcs[i][0]}:{pcs[i][1]}" if i < len(pcs)
                   else "workend")
        rows.append(row)
        prev = d
    tot = {k: dumps[-1][k] for k in dumps[-1]}
    tot.update(run=rows[0]["run"], phase="total", ends_at="workend")
    rows.append(tot)
    return rows


def fmt(v):
    return f"{v / 1e6:10.2f}M"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--labels", default="")
    ap.add_argument("--out", default="phases.csv")
    a = ap.parse_args()
    labels = [x for x in a.labels.split(",") if x]
    allrows = [phases(r, labels) for r in a.runs]

    for rows in allrows:
        print(f"\n== {rows[0]['run']}")
        print(f"{'phase':10}" + "".join(f"{s[:11]:>12}" for s in SHOW)
              + "".join(f"{m[:4] + ' ins':>12}{m[:4] + ' cyc':>12}"
                        for m in MODES))
        for r in rows:
            print(f"{r['phase']:10}" + "".join(fmt(r[s]) for s in SHOW)
                  + "".join(fmt(r[f"{m}_insts"]) + fmt(r[f"{m}_cycles"])
                            for m in MODES))
        t = rows[-1]
        attributed = sum(t[f"{m}_cycles"] for m in MODES)
        print(f"   cycles by mode add up to {attributed:.0f} of "
              f"{t['cycles']:.0f} cycles")

    base = allrows[0]
    for rows in allrows[1:]:
        print(f"\n== {rows[0]['run']} minus {base[0]['run']} "
              "(share of the total difference)")
        dtot = rows[-1]["cycles"] - base[-1]["cycles"]
        print(f"{'phase':10}{'d insts':>12}{'d cycles':>12}{'share':>8}"
              + "".join(f"{'d ' + m[:4] + ' cyc':>14}" for m in MODES))
        for r, b in zip(rows, base):
            dc = r["cycles"] - b["cycles"]
            print(f"{r['phase']:10}{fmt(r['insts'] - b['insts'])}"
                  f"{fmt(dc)}{100 * dc / dtot if dtot else 0:7.1f}%"
                  + "".join(f"{fmt(r[f'{m}_cycles'] - b[f'{m}_cycles'])}  "
                            for m in MODES))

    flat = [r for rows in allrows for r in rows]
    cols = ["run", "phase", "ends_at"] + [k for k in flat[0]
                                          if k not in ("run", "phase",
                                                       "ends_at")]
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(flat)
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
