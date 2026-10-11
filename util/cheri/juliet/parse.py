#!/usr/bin/env python3
"""Summarise a Juliet run (run.py output) per CWE, ABI and config.

Each test's console line ("JL <cwe> <good|bad> <test> exit N|signal N|
timeout") is classified:

  ok         exit 0
  sigprot    killed by SIGPROT (34): a CHERI capability fault
  segv, bus, abort, ill, signal-N
             killed by another signal (abort: e.g. allocator detecting a
             double free, or the stack protector)
  exit-N     exited non-zero
  timeout    killed by the guest-time timeout (e.g. waits on a socket)
  missing    no result (gem5 run died or shard incomplete)

For a bad test, a signal is a detection; exit 0 is undetected. For a good
test anything but ok is a false positive (or an environment problem:
timeouts on socket tests also happen in good tests).

Writes OUT/results.csv (one row per test execution), OUT/summary.csv (counts
per abi/config/cwe/kind/outcome) and OUT/detection.csv (per abi/config/cwe:
bad tests detected by SIGPROT / other signal / undetected, good tests ok),
and prints the detection table.

Usage: util/cheri/juliet/parse.py OUT
"""

import collections
import csv
import os
import re
import sys

SIGNALS = {34: "sigprot", 11: "segv", 10: "bus", 6: "abort", 4: "ill"}
RUN_DIR = re.compile(r"CWE(\d+)/(\w+?)-([\w-]+)/([sx]\d+)$")


def classify(how, val):
    if how == "timeout":
        return "timeout"
    if how == "signal":
        return SIGNALS.get(int(val), f"signal-{val}")
    return "ok" if int(val) == 0 else f"exit-{val}"


def expected(out, cwe, abi, shard):
    """(kind, test-kind) runs a shard was given (run.py's .tests file)."""
    path = os.path.join(out, f"CWE{cwe}", "jobs", f"{abi}-{shard}.tests")
    try:
        with open(path) as f:
            return [tuple(line.split()) for line in f if line.strip()]
    except OSError:
        return []


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = os.path.abspath(sys.argv[1])
    rows = []
    for root, dirs, files in os.walk(out):
        m = RUN_DIR.search(os.path.relpath(root, out))
        if not m or "console.log" not in files:
            continue
        cwe, abi, config, shard = m.groups()
        got = {}
        with open(os.path.join(root, "console.log"), errors="replace") as f:
            for line in f:
                p = line.split()
                if len(p) >= 5 and p[0] == "JL":
                    got[(p[2], p[3])] = (p[4], p[5] if len(p) > 5 else "")
        for kind, test in expected(out, cwe, abi, shard) or sorted(got):
            how, val = got.get((kind, test), ("missing", ""))
            rows.append(
                {
                    "abi": abi,
                    "config": config,
                    "cwe": int(cwe),
                    "kind": kind,
                    "test": test.rsplit("-", 1)[0],
                    "outcome": "missing"
                    if how == "missing"
                    else classify(how, val),
                    "raw": f"{how} {val}".strip(),
                    "run_dir": os.path.relpath(root, out),
                }
            )
    if not rows:
        sys.exit(f"no Juliet results under {out}")
    rows.sort(key=lambda r: (r["abi"], r["config"], r["cwe"], r["kind"],
                             r["test"]))
    with open(os.path.join(out, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    counts = collections.Counter(
        (r["abi"], r["config"], r["cwe"], r["kind"], r["outcome"])
        for r in rows
    )
    with open(os.path.join(out, "summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["abi", "config", "cwe", "kind", "outcome", "count"])
        for k in sorted(counts):
            w.writerow(list(k) + [counts[k]])

    groups = sorted({(r["abi"], r["config"], r["cwe"]) for r in rows})
    det = []
    for abi, config, cwe in groups:
        sel = [r for r in rows
               if (r["abi"], r["config"], r["cwe"]) == (abi, config, cwe)]
        bad = [r["outcome"] for r in sel if r["kind"] == "bad"]
        good = [r["outcome"] for r in sel if r["kind"] == "good"]
        nb = len(bad) - bad.count("missing") - bad.count("timeout")
        det.append(
            {
                "abi": abi,
                "config": config,
                "cwe": cwe,
                "bad_tests": len(bad),
                "bad_sigprot": bad.count("sigprot"),
                "bad_other_signal": sum(
                    o in ("segv", "bus", "abort", "ill")
                    or o.startswith("signal-") for o in bad
                ),
                "bad_undetected": bad.count("ok"),
                "bad_exit_nonzero": sum(o.startswith("exit-") for o in bad),
                "bad_timeout": bad.count("timeout"),
                "bad_missing": bad.count("missing"),
                "bad_sigprot_pct": round(100 * bad.count("sigprot") / nb, 1)
                if nb else None,
                "good_tests": len(good),
                "good_ok": good.count("ok"),
                "good_false_positive": sum(
                    o not in ("ok", "timeout", "missing") for o in good
                ),
                "good_timeout": good.count("timeout"),
                "good_missing": good.count("missing"),
            }
        )
    with open(os.path.join(out, "detection.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, list(det[0]))
        w.writeheader()
        w.writerows(det)

    hdr = (f"{'abi':8} {'config':10} {'cwe':>6} {'bad':>6} {'SIGPROT':>8} "
           f"{'other':>6} {'undet':>6} {'exit!0':>6} {'tmo':>5} {'miss':>5}"
           f" | {'good':>6} {'FP':>4} {'tmo':>5} {'miss':>5}")
    print(hdr)
    print("-" * len(hdr))
    for d in det:
        print(f"{d['abi']:8} {d['config']:10} {d['cwe']:>6} "
              f"{d['bad_tests']:>6} {d['bad_sigprot']:>8} "
              f"{d['bad_other_signal']:>6} {d['bad_undetected']:>6} "
              f"{d['bad_exit_nonzero']:>6} {d['bad_timeout']:>5} "
              f"{d['bad_missing']:>5} | {d['good_tests']:>6} "
              f"{d['good_false_positive']:>4} {d['good_timeout']:>5} "
              f"{d['good_missing']:>5}")
    missing = sum(r["outcome"] == "missing" for r in rows)
    if missing:
        print(f"\nWARNING: {missing} test(s) have no result (incomplete "
              "shards; see run.py's warnings)")
    print(f"\nwrote {out}/results.csv, summary.csv, detection.csv")


if __name__ == "__main__":
    main()
