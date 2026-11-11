#!/usr/bin/env python3
"""Compare two Juliet results.csv test by test (e.g. gem5 with CHERI-QEMU).

A test execution agrees if both runs classified it the same way (parse.py's
outcome: ok, sigprot, segv, abort, timeout, exit-N, ...). One with no result
on one side (missing: a gem5 shard stopped by its time limit) is not compared.
Differences are split by whether the test can legitimately differ between runs:
  random   its path or input depends on rand(), seeded from the guest's clock:
           flow variant _12 (globalReturnsTrueOrFalse) and the _rand sources
  other    everything else
Writes OUT/compare.csv (one row per differing or uncompared test) and
OUT/compare_summary.csv (counts per ABI and CWE), prints the summary, and with
--latex prints the rows of the paper's table: the share of bad versions stopped
on both simulators, over the tests that reach their bug deterministically (not
random, and not the _socket sources, which have no network peer here).

Usage: util/cheri/juliet/compare.py GEM5/results.csv QEMU/results.csv
           [--abis purecap,plain] [--out DIR] [--latex]
"""

import argparse
import collections
import csv
import os
import re


def is_random(test):
    return bool(re.search(r"_12[a-z]?$", test)) or "_rand" in test


def needs_peer(test):
    return "_socket" in test


def stopped(outcome, abi):
    """A capability fault on purecap, any crash on an unprotected ABI."""
    if abi == "purecap":
        return outcome == "sigprot"
    return (outcome in ("sigprot", "segv", "bus", "abort", "ill")
            or outcome.startswith("signal-"))


def percent(part, whole):
    """Rounded, but 100 only if it really is all of them."""
    return str(min(round(100 * part / whole), 100 if part == whole else 99))


def stop_share(res, abi, cwe):
    """(stopped, counted) bad versions; timeouts and missing not counted."""
    got = [v for k, v in res.items()
           if k[:3] == (abi, cwe, "bad") and v not in ("timeout", "missing")
           and not is_random(k[3]) and not needs_peer(k[3])]
    return sum(stopped(v, abi) for v in got), len(got)


def load(path, abis):
    with open(path) as f:
        return {(r["abi"], int(r["cwe"]), r["kind"], r["test"]): r["outcome"]
                for r in csv.DictReader(f) if r["abi"] in abis}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gem5")
    ap.add_argument("qemu")
    ap.add_argument("--abis", default="purecap,plain")
    ap.add_argument("--out", default=None, help="default: next to QEMU's CSV")
    ap.add_argument("--latex", action="store_true")
    args = ap.parse_args()
    abis = args.abis.split(",")
    a, b = load(args.gem5, abis), load(args.qemu, abis)
    out = args.out or os.path.dirname(os.path.abspath(args.qemu))

    keys = sorted(set(a) | set(b))
    count = collections.Counter()
    rows = []
    for k in keys:
        ga, qe = a.get(k, "missing"), b.get(k, "missing")
        if "missing" in (ga, qe):
            cmp = "uncompared"
        elif ga == qe:
            cmp = "agree"
        else:
            cmp = "differ-random" if is_random(k[3]) else "differ-other"
        count[(k[0], k[1], cmp)] += 1
        if cmp != "agree":
            rows.append({"abi": k[0], "cwe": k[1], "kind": k[2], "test": k[3],
                         "gem5": ga, "qemu": qe, "result": cmp})
    with open(os.path.join(out, "compare.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, ["abi", "cwe", "kind", "test", "gem5", "qemu",
                               "result"])
        w.writeheader()
        w.writerows(rows)

    kinds = ("agree", "differ-random", "differ-other", "uncompared")
    print(f"{'abi':8} {'cwe':>4} {'agree':>7} {'random':>7} {'other':>7} "
          f"{'uncompared':>11}")
    with open(os.path.join(out, "compare_summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["abi", "cwe"] + list(kinds))
        for abi in abis:
            total = [0, 0, 0, 0]
            for cwe in sorted({k[1] for k in keys if k[0] == abi}):
                c = [count[(abi, cwe, x)] for x in kinds]
                w.writerow([abi, cwe] + c)
                print(f"{abi:8} {cwe:>4} {c[0]:>7} {c[1]:>7} {c[2]:>7} "
                      f"{c[3]:>11}")
                total = [x + y for x, y in zip(total, c)]
            print(f"{abi:8} {'all':>4} {total[0]:>7} {total[1]:>7} "
                  f"{total[2]:>7} {total[3]:>11}")
    print(f"\nwrote {out}/compare.csv, compare_summary.csv")

    if args.latex:
        print("\n% CWE & gem5 plain & QEMU plain & gem5 purecap & QEMU purecap "
              "(not counted: tests)")
        cwes = sorted({k[1] for k in keys})
        tot = collections.defaultdict(lambda: [0, 0])
        for cwe in cwes:
            cells = []
            for name, res, abi in (("gp", a, "plain"), ("qp", b, "plain"),
                                   ("gc", a, "purecap"), ("qc", b, "purecap")):
                s_, n = stop_share(res, abi, cwe)
                cells.append(percent(s_, n) if n else "--")
                if cwe != 680:
                    tot[name][0] += s_
                    tot[name][1] += n
            print(f"{cwe} & " + " & ".join(cells) + " \\\\")
        print("Total (without 680) & " + " & ".join(
            percent(*v) for v in tot.values()) + " \\\\")
        print("% counted:", {k: v for k, v in tot.items()})


if __name__ == "__main__":
    main()
