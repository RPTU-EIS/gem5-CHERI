#!/usr/bin/env python3
"""Classify the cheribsdtest runs of run.py.

Reads OUT/<variant>-<config>/console.log. Every listed test gets one status:
PASS, FAIL, XFAIL (expected failure, annotated in cheribsdtest), XPASS
(passed although expected to fail), SKIP (the test's own skip check),
TIMEOUT (killed by timeout(1)), CRASH (no result line, e.g. the test
runner itself died), INCOMPLETE (started, but the run ended first) or
NOTRUN (listed, never started). Writes OUT/results.csv (one row per test
and run) and OUT/summary.csv (counts per run), and prints both.

--ref compares with another results.csv (e.g. the same suites on QEMU):
tests whose status differs per (variant, test).

Usage: util/cheri/cheribsdtest/parse.py OUT [--ref REF/results.csv]
"""

import argparse
import csv
import glob
import os
import re
import sys

STATUSES = ["PASS", "FAIL", "XFAIL", "XPASS", "SKIP", "TIMEOUT", "CRASH",
            "INCOMPLETE", "NOTRUN"]
RESULT = re.compile(r"^(PASS|FAIL|XFAIL|XPASS|SKIP): ([a-z][a-z0-9_]*)(.*)$")
TIMEOUT_RCS = {"124", "137"}


def parse_log(path):
    """{test: (status, detail)} in list order, and whether the run ended."""
    listed, res, current, ended = [], {}, None, False
    with open(path, errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\r\n").rstrip("\r")
            if line.startswith("=== CBT-LIST "):
                listed.append(line.split()[2])
            elif line.startswith("=== CBT-TEST "):
                current = line.split()[2]
                res[current] = ("INCOMPLETE", "")
            elif line.startswith("=== CBT-RC "):
                _, _, t, rc = line.split()[:4]
                if res.get(t, ("INCOMPLETE",))[0] == "INCOMPLETE":
                    res[t] = ("TIMEOUT" if rc in TIMEOUT_RCS else "CRASH",
                              f"rc={rc}")
                current = None
            elif line.startswith("=== CM-END"):
                ended = True
            else:
                m = RESULT.match(line)
                if m and m.group(2) == current:
                    res[current] = (m.group(1), m.group(3).lstrip(": ").strip())
    for t in listed:
        res.setdefault(t, ("NOTRUN", ""))
    order = listed + [t for t in res if t not in listed]
    return {t: res[t] for t in order}, ended


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("--ref", help="results.csv to compare with")
    args = ap.parse_args()

    rows, summary = [], []
    for log in sorted(glob.glob(os.path.join(args.out, "*", "console.log"))):
        run = os.path.basename(os.path.dirname(log))
        variant, config = run, ""
        for cpu in ("-atomic", "-timing", "-minor", "-o3", "-qemu"):
            if cpu in run:
                i = run.index(cpu)
                variant, config = run[:i], run[i + 1:]
        res, ended = parse_log(log)
        counts = {s: 0 for s in STATUSES}
        for t, (st, detail) in res.items():
            counts[st] += 1
            rows.append({"variant": variant, "config": config, "test": t,
                         "status": st, "detail": detail})
        summary.append(dict(variant=variant, config=config, tests=len(res),
                            finished="yes" if ended else "no", **counts))
    if not rows:
        sys.exit(f"no */console.log with results under {args.out}")

    with open(os.path.join(args.out, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, ["variant", "config", "test", "status",
                               "detail"])
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(args.out, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, ["variant", "config", "tests", "finished"]
                           + STATUSES)
        w.writeheader()
        w.writerows(summary)

    hdr = f"{'variant':20s} {'config':18s} {'tests':>5s} " + " ".join(
        f"{s[:6]:>6s}" for s in STATUSES) + "  done"
    print(hdr)
    for s in summary:
        print(f"{s['variant']:20s} {s['config']:18s} {s['tests']:5d} "
              + " ".join(f"{s[k]:6d}" for k in STATUSES)
              + f"  {s['finished']}")
    bad = [r for r in rows if r["status"] in
           ("FAIL", "XPASS", "TIMEOUT", "CRASH")]
    if bad:
        print("\nunexpected results:")
        for r in bad:
            print(f"  {r['variant']}-{r['config']}: {r['status']} "
                  f"{r['test']}: {r['detail']}")

    if args.ref:
        with open(args.ref) as f:
            ref = {(r["variant"], r["test"]): r["status"]
                   for r in csv.DictReader(f)}
        # compare finished tests only; unfinished ones are counted
        done = [r for r in rows if (r["variant"], r["test"]) in ref
                and r["status"] not in ("INCOMPLETE", "NOTRUN")]
        diff = [r for r in done
                if ref[(r["variant"], r["test"])] != r["status"]]
        missing = {k for k in ref} - {(r["variant"], r["test"]) for r in rows}
        unfinished = sum(r["status"] in ("INCOMPLETE", "NOTRUN")
                         for r in rows)
        print(f"\nvs {args.ref}: {len(done)} finished test(s) compared, "
              f"{len(done) - len(diff)} agree, {len(diff)} differ"
              + (f", {unfinished} unfinished" if unfinished else ""))
        for r in diff:
            print(f"  {r['variant']}-{r['config']} {r['test']}: "
                  f"{r['status']} (ref {ref[(r['variant'], r['test'])]})")
        if missing:
            print(f"  {len(missing)} ref test(s) not in these runs")


if __name__ == "__main__":
    main()
