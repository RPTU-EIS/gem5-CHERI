#!/usr/bin/env python3
"""Function-level profile of a run made with CHERI_PC_PROFILE=1.

The PcProfile probe writes pcprof-<n>.csv (mode,pc,insts,cycles since the
workbegin reset) at every statistics dump. This resolves the PCs to
functions: supervisor-mode PCs with the kernel's symbol table, user-mode
PCs with the (unstripped) program binary; user PCs outside the program
(other processes, e.g. the shell) count as "[other user]". With
CHERI_STATS_AT_PC phase dumps, phases are differences of consecutive
dumps, as in util/cheri/phase_stats.py.

Usage: util/cheri/pc_profile.py RUN_DIR [RUN_DIR] --binary ELF [--binary ELF]
         [--kernel tests/kernel] [--labels startup,build,compute,exit]
         [--phase PHASE] [--top 25] [--out profile.csv]
One RUN_DIR: its top functions by cycles. Two: the second minus the first
per function (e.g. purecap - plain; --binary in the same order), sorted by
the difference. --phase restricts to one phase (default: whole region).
"""

import argparse
import bisect
import csv
import os
import re
import subprocess
import sys

NM = os.path.expanduser("~/cheri/output/sdk/bin/llvm-nm")
MODES = {0: "user", 1: "kernel", 3: "machine"}


def symbols(elf):
    starts, names = [], []
    out = subprocess.run([NM, "-n", "--defined-only", elf],
                         capture_output=True, text=True, check=True).stdout
    for line in out.split("\n"):
        p = line.split()
        if len(p) == 3 and p[1] in "TtWw":
            starts.append(int(p[0], 16))
            names.append(p[2])
    return starts, names


def lookup(table, pc):
    starts, names = table
    i = bisect.bisect_right(starts, pc) - 1
    return names[i] if i >= 0 else None


def load_dumps(run, nphases):
    files = sorted((f for f in os.listdir(run)
                    if re.fullmatch(r"pcprof-\d+\.csv", f)),
                   key=lambda f: int(f[7:-4]))
    if len(files) < nphases:
        sys.exit(f"{run}: {len(files)} profile dumps, need {nphases}")
    dumps = []
    for f in files[:nphases]:
        d = {}
        with open(os.path.join(run, f)) as fh:
            for r in csv.DictReader(fh):
                d[(int(r["mode"]), int(r["pc"], 16))] = (
                    int(r["insts"]), int(r["cycles"]))
        dumps.append(d)
    return dumps


def profile(run, binary, kernel, labels, phase):
    con = open(os.path.join(run, "console.log"), errors="replace").read()
    n_pc = con.count("[pc-stats] dump")
    names = labels if labels and len(labels) == n_pc + 1 else \
        [f"phase{i}" for i in range(n_pc + 1)]
    dumps = load_dumps(run, n_pc + 1)
    if phase and phase != "total":
        i = names.index(phase)
        cur, prev = dumps[i], dumps[i - 1] if i else {}
    else:
        cur, prev = dumps[-1], {}
    user = symbols(binary)
    lo = user[0][0] if user[0] else 0
    hi = max(user[0]) + 0x10000 if user[0] else 0
    out = {}
    for key, (ins, cyc) in cur.items():
        pi, pc_ = prev.get(key, (0, 0))
        ins, cyc = ins - pi, cyc - pc_
        if not ins and not cyc:
            continue
        mode, pc = key
        if mode == 0:
            fn = lookup(user, pc) if lo <= pc < hi else "[other user]"
        else:
            fn = lookup(kernel, pc)
        k = (MODES.get(mode, str(mode)), fn or "[unknown]")
        a, b = out.get(k, (0, 0))
        out[k] = (a + ins, b + cyc)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--binary", action="append", required=True)
    ap.add_argument("--kernel", default="tests/kernel")
    ap.add_argument("--labels", default="startup,build,compute,exit")
    ap.add_argument("--phase", default="total")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out")
    a = ap.parse_args()
    if len(a.binary) != len(a.runs):
        sys.exit("give one --binary per RUN_DIR")
    kernel = symbols(a.kernel)
    labels = a.labels.split(",")
    profs = [profile(r, b, kernel, labels, a.phase)
             for r, b in zip(a.runs, a.binary)]
    rows = []
    if len(profs) == 1:
        p = profs[0]
        tot = sum(c for _, c in p.values())
        for (mode, fn), (ins, cyc) in p.items():
            rows.append({"mode": mode, "function": fn, "insts": ins,
                         "cycles": cyc, "share_pct": 100.0 * cyc / tot})
        rows.sort(key=lambda r: -r["cycles"])
        print(f"{a.runs[0]} ({a.phase}): {tot:,} cycles")
        print(f"{'mode':7}{'function':36}{'cycles':>14}{'share':>8}"
              f"{'insts':>14}")
        for r in rows[:a.top]:
            print(f"{r['mode']:7}{r['function'][:35]:36}{r['cycles']:14,}"
                  f"{r['share_pct']:7.1f}%{r['insts']:14,}")
    else:
        p0, p1 = profs[0], profs[1]
        base = sum(c for _, c in p0.values())
        gap = sum(c for _, c in p1.values()) - base
        for k in set(p0) | set(p1):
            i0, c0 = p0.get(k, (0, 0))
            i1, c1 = p1.get(k, (0, 0))
            rows.append({"mode": k[0], "function": k[1], "cycles_a": c0,
                         "cycles_b": c1, "d_cycles": c1 - c0,
                         "d_insts": i1 - i0,
                         "share_of_gap_pct": 100.0 * (c1 - c0) / gap
                         if gap else 0.0})
        rows.sort(key=lambda r: -r["d_cycles"])
        print(f"{a.runs[1]} minus {a.runs[0]} ({a.phase}): "
              f"{gap:+,} cycles ({100.0 * gap / base:+.1f}%)")
        print(f"{'mode':7}{'function':36}{'d cycles':>14}{'of gap':>8}"
              f"{'d insts':>14}{'cycles a':>14}{'cycles b':>14}")
        for r in rows[:a.top]:
            print(f"{r['mode']:7}{r['function'][:35]:36}"
                  f"{r['d_cycles']:+14,}{r['share_of_gap_pct']:7.1f}%"
                  f"{r['d_insts']:+14,}{r['cycles_a']:14,}"
                  f"{r['cycles_b']:14,}")
    if a.out:
        with open(a.out, "w", newline="") as f:
            w = csv.DictWriter(f, list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
