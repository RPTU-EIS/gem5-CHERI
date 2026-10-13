#!/usr/bin/env python3
"""Collect Olden results (run.py output) into CSV files.

Checks every run's program output, then uses util/cheri/coremark/parse.py
for the gem5 statistics, so the CSVs (results.csv, comparison.csv,
all_stats.csv, tag_costs.csv, <workload>/summary.csv) have the same columns
as CoreMark-PRO's and util/cheri/coremark/plot.py plots them.

Output checks (columns in results.csv, and OUT/validation.csv):
  output_vs_native   same: identical to the native (host) run with the same
                     arguments (MD5); close: equal up to a relative 1e-3 in
                     every number (FP results may round differently on x86);
                     differs; n/a (arguments changed, or no output)
  output_vs_plain,   identical to the plain RV64 / hybrid run of the same
  output_vs_hybrid   config (same compiler, so must match exactly)
A run whose output differs counts as an error (errors=1), like a CoreMark-PRO
CRC error.

Usage: util/cheri/olden/parse.py OUT [MORE_OUT ...] [--into DIR]
"""

import csv
import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "cm_parse", os.path.join(HERE, "..", "coremark", "parse.py")
)
cmp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cmp)
NUM = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")


def guest_output(console):
    """{workload: (md5, lines, bytes, text or None)} from a console.log."""
    res, cur, buf = {}, None, []
    with open(console, errors="replace") as f:
        for line in f:
            line = line.replace("\r", "")
            m = re.match(r"=== OL-MD5 (\S+) (\S+)\s+(\d+)\s+(\d+)", line)
            if m:
                res[m.group(1)] = [m.group(2), int(m.group(3)),
                                   int(m.group(4)), None]
                continue
            m = re.match(r"=== OL-OUT-BEGIN (\S+)", line)
            if m:
                cur, buf = m.group(1), []
                continue
            if cur and line.startswith(f"=== OL-OUT-END {cur}"):
                if cur in res:
                    res[cur][3] = "".join(buf)
                cur = None
                continue
            if cur is not None:
                buf.append(line)
    return {k: tuple(v) for k, v in res.items()}


def close(a, b, rel=1e-3, absolute=1e-9):
    """Same text apart from numbers, which agree within a tolerance."""
    if NUM.sub("#", a).split() != NUM.sub("#", b).split():
        return False
    for x, y in zip(NUM.findall(a), NUM.findall(b)):
        x, y = float(x), float(y)
        if abs(x - y) > max(absolute, rel * max(abs(x), abs(y))):
            return False
    return True


def checks(out):
    """{(abi, config, workload): {...}} for every run under out."""
    with open(os.path.join(out, "manifest.json")) as f:
        man = json.load(f)
    work = man.get("work", "")
    changed = man.get("args_changed_from_build", {})
    runs = {}
    for d, _, files in sorted(os.walk(out)):
        m = re.fullmatch(r"(purecap|hybrid|plain)-([A-Za-z0-9_-]+)",
                         os.path.basename(d))
        if not m or "console.log" not in files:
            continue
        for wl, o in guest_output(os.path.join(d, "console.log")).items():
            runs[(m.group(1), m.group(2), wl)] = o
    res = {}
    for (abi, config, wl), (md5, lines, size, text) in runs.items():
        r = {"output_md5": md5, "output_bytes": size}
        ref = os.path.join(work, "ref", wl + ".out")
        if wl in changed or not os.path.exists(ref):
            r["output_vs_native"] = "n/a"
        else:
            data = open(ref, "rb").read()
            if hashlib.md5(data).hexdigest() == md5:
                r["output_vs_native"] = "same"
            elif text is not None and close(text, data.decode(errors="replace")):
                r["output_vs_native"] = "close"
            else:
                r["output_vs_native"] = "differs"
        # same compiler and ISA family: must match the other ABIs exactly
        for other in ("plain", "hybrid"):
            if other == abi or (abi == "hybrid" and other == "hybrid"):
                continue
            o = runs.get((other, config, wl))
            if o is not None:
                r["output_vs_" + other] = ("same" if o[0] == md5
                                           else "differs")
        res[(abi, config, wl)] = r
    return res


def main():
    argv = sys.argv[1:]
    into = argv[argv.index("--into") + 1] if "--into" in argv else None
    dirs = [a for a in argv if not a.startswith("--") and a != into]
    if not dirs:
        sys.exit(__doc__)
    allchecks = {}
    for d in dirs:
        allchecks.update(checks(d))

    orig = cmp.collect

    def collect(out, all_stats):
        rows = orig(out, all_stats)
        for row in rows:
            c = allchecks.get((row["abi"], row["config"], row["workload"]),
                              {"output_vs_native": "n/a"})
            row.update(c)
            bad = "differs" in (c.get("output_vs_native"),
                                c.get("output_vs_plain"),
                                c.get("output_vs_hybrid"))
            row["errors"] = int(bad)
        return rows

    cmp.collect = collect
    cmp.main()  # reads sys.argv (dirs, --into)

    out = dirs[0]
    i = sys.argv.index("--into") if "--into" in sys.argv else -1
    if i >= 0:
        out = sys.argv[i + 1]
    rows = [dict(abi=k[0], config=k[1], workload=k[2], **v)
            for k, v in sorted(allchecks.items())]
    with open(os.path.join(out, "validation.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, ["abi", "config", "workload", "output_md5",
                               "output_bytes", "output_vs_native",
                               "output_vs_plain", "output_vs_hybrid"],
                           restval="")
        w.writeheader()
        w.writerows(rows)
    bad = [r for r in rows if "differs" in (r.get("output_vs_native"),
                                            r.get("output_vs_plain"),
                                            r.get("output_vs_hybrid"))]
    print(f"\noutput checks: {len(rows) - len(bad)}/{len(rows)} ok "
          f"(validation.csv)")
    for r in bad:
        print(f"  OUTPUT MISMATCH {r['workload']} {r['abi']}-{r['config']}: "
              f"native {r['output_vs_native']}, plain "
              f"{r.get('output_vs_plain', '-')}, hybrid "
              f"{r.get('output_vs_hybrid', '-')}")


if __name__ == "__main__":
    main()
