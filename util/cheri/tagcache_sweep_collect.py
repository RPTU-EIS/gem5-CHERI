#!/usr/bin/env python3
"""Collect a tagcache_sweep.sh run into one CSV.

For every point directory (each with the all_stats.csv of the suite's
parse.py), every run with a tag model gets the DRAM traffic overhead as
Joannou et al. define it: tag-table transactions per data transaction at
the tag controller, (tagReads + tagWrites) / (dataReads + dataWrites),
plus the leaf hit rate and the share of lookups the root level elided.
The tag-cache size comes from the run's CHERI_TAG_CACHE (manifest.json).

Usage: util/cheri/tagcache_sweep_collect.py POINT_DIR... [--out CSV]
  e.g. RESULTS/olden/tc-* RESULTS/coremark/tc-*
"""

import argparse
import csv
import json
import os
import re
import sys

STAT = "board.memory.tag_controller."
UNITS = {"B": 1, "KiB": 1 << 10, "MiB": 1 << 20, "kB": 1000, "MB": 10**6}


def size_bytes(s):
    m = re.fullmatch(r"(\d+)\s*([A-Za-z]*)", s.strip())
    if not m or m.group(2) not in UNITS:
        sys.exit(f"cannot parse size {s!r}")
    return int(m.group(1)) * UNITS[m.group(2) or "B"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("points", nargs="+")
    ap.add_argument("--out", default="tagcache_sweep.csv")
    args = ap.parse_args()

    rows = []
    for d in args.points:
        with open(os.path.join(d, "manifest.json")) as f:
            man = json.load(f)
        knobs = man.get("env_knobs", {})
        size = knobs.get("CHERI_TAG_CACHE", "32KiB")
        swe = knobs.get("CHERI_TAG_SWE", "0") == "1"
        suite = man.get("suite", os.path.basename(os.path.dirname(
            os.path.abspath(d))))
        with open(os.path.join(d, "all_stats.csv")) as f:
            for r in csv.DictReader(f):
                if r.get("tag_model") in (None, "", "none", "passthrough"):
                    continue

                def v(name):
                    x = r.get(STAT + name, "")
                    return float(x) if x not in ("", "nan") else 0.0

                data = v("dataReads") + v("dataWrites")
                lookups = v("leafHits") + v("leafMisses")
                evictions = v("leafEvictions")
                if data == 0:
                    continue
                rows.append({
                    "suite": suite,
                    "workload": r["workload"],
                    "abi": r["abi"],
                    "cpu": r["cpu"],
                    "tag_model": r["tag_model"],
                    "silent_write_elim": int(swe),
                    "tag_cache": size,
                    "tag_cache_bytes": size_bytes(size),
                    "data_transactions": int(data),
                    "tag_reads": int(v("tagReads")),
                    "tag_writes": int(v("tagWrites")),
                    "dram_overhead":
                        (v("tagReads") + v("tagWrites")) / data,
                    "leaf_hit_rate":
                        v("leafHits") / lookups if lookups else "",
                    # Joannou et al. Fig. 3: hits on tags the line had
                    # not served yet (spatial) vs served before (temporal)
                    "leaf_spatial_hit_share":
                        v("leafSpatialHits") / lookups if lookups else "",
                    "leaf_temporal_hit_share":
                        v("leafTemporalHits") / lookups if lookups else "",
                    "zero_elided_share":
                        v("zeroElided") / lookups if lookups else "",
                    # their silent-write elimination: dirty share of
                    # evicted leaf lines
                    "leaf_dirty_eviction_share":
                        v("leafDirtyEvictions") / evictions
                        if evictions else "",
                    "silent_writes": int(v("silentWrites")),
                    "point_dir": os.path.abspath(d),
                })
    if not rows:
        sys.exit("no runs with a tag model found")
    rows.sort(key=lambda r: (r["suite"], r["workload"], r["abi"],
                             r["silent_write_elim"],
                             r["tag_model"], r["tag_cache_bytes"]))
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {args.out} ({len(rows)} runs)")


if __name__ == "__main__":
    main()
