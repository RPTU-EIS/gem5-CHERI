#!/usr/bin/env python3
"""Collect CoreMark-PRO results from run.py output into CSV files.

For every <abi>-<cpu>/ run directory under OUT (OUT/<workload>/<abi>-<cpu>/,
or the older OUT/<abi>-<cpu>/ with several workloads) it pairs each
workload's region in console.log (=== CM-BEGIN/END, CoreMark-PRO's own
"-- name:key=value" report) with the stats.txt dump taken at that region's
`m5 workend`.

Writes
  OUT/results.csv            one row per (abi, cpu, workload)
  OUT/comparison.csv         ratios per (config, workload) for every ABI
                             pair present: purecap/plain, hybrid/plain,
                             purecap/hybrid (plain: RV64 without CHERI)
  OUT/<workload>/summary.csv that workload's rows (per-workload layout)
  OUT/all_stats.csv          every gem5 statistic of every run, one row per
                             (abi, config, workload)
  OUT/tag_costs.csv          each tag model vs passthrough (same CPU, ABI,
                             workload): cycles and DRAM ratios, tag stats
results.csv also has wall-clock times (run_info.json written by run.py,
checkpoint boot cost from the manifest) and every key CoreMark-PRO printed
(cm_*).
and prints the comparison with geometric means.

Usage: util/cheri/coremark/parse.py OUT [MORE_OUT ...] [--into DIR]
  Several result directories are merged; for the same (abi, cpu, workload)
  the later directory wins (e.g. a rerun of one workload). CSVs go to
  --into (default: the first OUT).
"""

import argparse
import csv
import json
import math
import os
import re
import sys

CORE = r"board\.processor\.(?:cores|start|switch)\.core\."


def stat_dumps(path):
    """List of {name: value} dicts, one per stats dump."""
    dumps, cur = [], None
    with open(path) as f:
        for line in f:
            if line.startswith("---------- Begin Simulation Statistics"):
                cur = {}
            elif line.startswith("---------- End Simulation Statistics"):
                dumps.append(cur)
                cur = None
            elif cur is not None:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        cur[parts[0]] = float(parts[1])
                    except ValueError:
                        pass
    return dumps


def total(d, pattern):
    rx = re.compile(pattern)
    return sum(v for k, v in d.items() if rx.fullmatch(k))


CACHES = r"board\.cache_hierarchy\.(l1d-cache-\d+|l1i-cache-\d+|l2-cache-\d+|dptw_caches|iptw_caches)"
CACHE_NAMES = {
    "l1d": r"l1d-cache-\d+",
    "l1i": r"l1i-cache-\d+",
    "l2": r"l2-cache-\d+",
    "dptw": r"dptw_caches",
    "iptw": r"iptw_caches",
}
INST_TYPES = [
    "IntAlu",
    "IntMult",
    "IntDiv",
    "FloatAdd",
    "FloatCmp",
    "FloatCvt",
    "FloatMult",
    "FloatMultAcc",
    "FloatDiv",
    "FloatMisc",
    "FloatSqrt",
    "MemRead",
    "MemWrite",
    "FloatMemRead",
    "FloatMemWrite",
    "No_OpClass",
]


def metrics(d):
    """Named metrics from one stats dump (sums over cores/caches/channels).
    Everything else is in all_stats.csv."""
    nan = float("nan")
    m = {
        # simulated and host time of the region
        "sim_seconds": d.get("simSeconds", nan),
        "sim_ticks": d.get("simTicks", nan),
        "final_tick": d.get("finalTick", nan),
        "host_seconds": d.get("hostSeconds", nan),
        "host_inst_rate": d.get("hostInstRate", nan),
        "host_tick_rate": d.get("hostTickRate", nan),
        "host_memory_bytes": d.get("hostMemory", nan),
        # core
        "insts": total(d, CORE + r"commitStats0\.numInsts"),
        "ops": total(d, CORE + r"commitStats0\.numOps"),
        "cycles": total(d, CORE + r"numCycles"),
        "idle_cycles": total(d, CORE + r"idleCycles"),
        "loads": total(
            d, CORE + r"commitStats0\.committedInstType::(Float)?MemRead"
        ),
        "stores": total(
            d, CORE + r"commitStats0\.committedInstType::(Float)?MemWrite"
        ),
        "branches": total(d, CORE + r"branchPred\.committed_0::total"),
        "branch_lookups": total(d, CORE + r"branchPred\.lookups_0::total"),
        "branch_mispredicts": total(
            d, CORE + r"branchPred\.mispredicted_0::total"
        ),
        "btb_hits": total(d, CORE + r"branchPred\.BTBHits"),
        "btb_lookups": total(d, CORE + r"branchPred\.BTBLookups"),
        # TLBs / page-table walks
        "dtlb_misses": total(d, CORE + r"mmu\.dtb\.(read|write)Misses"),
        "itlb_misses": total(d, CORE + r"mmu\.itb\.(read|write)Misses"),
        "dtlb_accesses": total(d, CORE + r"mmu\.dtb\.(read|write)Accesses"),
        "itlb_accesses": total(d, CORE + r"mmu\.itb\.(read|write)Accesses"),
        # memory
        "dram_bytes_read": total(
            d, r"board\.memory\..*\.dram\.bytesRead::total"
        ),
        "dram_bytes_written": total(
            d, r"board\.memory\..*\.dram\.bytesWritten::total"
        ),
        "dram_read_reqs": total(d, r"board\.memory\..*mem_ctrl\d*\.readReqs"),
        "dram_write_reqs": total(
            d, r"board\.memory\..*mem_ctrl\d*\.writeReqs"
        ),
        "dram_row_hits_read": total(
            d, r"board\.memory\..*\.dram\.readRowHits"
        ),
        "dram_row_hits_write": total(
            d, r"board\.memory\..*\.dram\.writeRowHits"
        ),
        # CHERI tag-storage model (0 if CHERI_TAG_MODEL=none)
        "tag_reads": total(d, r".*tag_controller\.tagReads"),
        "tag_writes": total(d, r".*tag_controller\.tagWrites"),
        "tag_leaf_hits": total(d, r".*tag_controller\.leafHits"),
        "tag_leaf_misses": total(d, r".*tag_controller\.leafMisses"),
        "tag_zero_elided": total(d, r".*tag_controller\.zeroElided"),
        "tag_delayed_reads": total(d, r".*tag_controller\.delayedReads"),
        "tag_delay_ticks": total(d, r".*tag_controller\.delayTicks"),
    }
    for t in INST_TYPES:
        m["inst_" + t] = total(
            d, CORE + r"commitStats0\.committedInstType::" + t
        )
    for name, rx in CACHE_NAMES.items():
        base = r"board\.cache_hierarchy\." + rx + r"\."
        m[name + "_accesses"] = total(d, base + r"demandAccesses::total")
        m[name + "_misses"] = total(d, base + r"demandMisses::total")
        m[name + "_hits"] = total(d, base + r"demandHits::total")
        m[name + "_writebacks"] = total(d, base + r"writebacks::total")
        m[name + "_miss_latency_ticks"] = total(
            d, base + r"demandMissLatency::total"
        )
    m["ipc"] = m["insts"] / m["cycles"] if m["cycles"] else nan
    k = m["insts"] / 1000.0 if m["insts"] else nan
    for name in CACHE_NAMES:
        m[name + "_mpki"] = m[name + "_misses"] / k
        m[name + "_miss_rate"] = (
            m[name + "_misses"] / m[name + "_accesses"]
            if m[name + "_accesses"]
            else nan
        )
    m["branch_mpki"] = m["branch_mispredicts"] / k
    m["dram_bytes_per_kinst"] = (
        m["dram_bytes_read"] + m["dram_bytes_written"]
    ) / k
    m["region_start_sim_seconds"] = (m["final_tick"] - m["sim_ticks"]) / 1e12
    return m


def console_regions(path):
    """[(workload, exit status, {key: value}), ...] in run order."""
    regions, cur = [], None
    with open(path, errors="replace") as f:
        for line in f:
            line = line.replace("\r", "").rstrip("\n")
            m = re.match(r"=== CM-BEGIN (\S+)", line)
            if m:
                cur = (m.group(1), {})
                continue
            m = re.match(r"=== CM-END (\S+) status=(\d+)", line)
            if m and cur:
                regions.append((cur[0], int(m.group(2)), cur[1]))
                cur = None
                continue
            m = re.match(r"-- ([^:]+):([^=]+)=\s*(\S+)", line)
            if m and cur:
                cur[1][m.group(2)] = m.group(3)
    return regions


def find_manifest(d, top):
    """manifest.json of the experiment a run directory belongs to."""
    d = os.path.abspath(d)
    top = os.path.abspath(top)
    while True:
        f = os.path.join(d, "manifest.json")
        if os.path.isfile(f):
            with open(f) as fh:
                return json.load(fh)
        if d == top or os.path.dirname(d) == d:
            return {}
        d = os.path.dirname(d)


def collect(out, all_stats):
    """Rows of named metrics; every raw stat goes to all_stats (same keys
    plus abi/cpu/workload)."""
    rows = []
    for d, _, files in sorted(os.walk(out)):
        m = re.fullmatch(
            r"(purecap|hybrid|plain)-([A-Za-z0-9_-]+)", os.path.basename(d)
        )
        if not m or "console.log" not in files:
            continue
        abi, config = m.groups()
        cpu, _, tag = config.partition("-")
        tag = tag or "none"
        regions = console_regions(os.path.join(d, "console.log"))
        dumps = (
            stat_dumps(os.path.join(d, "stats.txt"))
            if os.path.isfile(os.path.join(d, "stats.txt"))
            else []
        )
        # CHERI_STATS_AT_PC dumps (cumulative, inside the region) come before
        # the region's workend dump; drop them (single-region runs, as Olden)
        with open(os.path.join(d, "console.log"), errors="replace") as f:
            n_pc = sum(line.startswith("[pc-stats] dump") for line in f)
        if n_pc and len(regions) == 1:
            dumps = dumps[n_pc:]
        info = {}
        if os.path.isfile(os.path.join(d, "run_info.json")):
            with open(os.path.join(d, "run_info.json")) as f:
                info = json.load(f)
        man = find_manifest(d, out)
        ck = dict(
            man.get("checkpoints", {}).get(
                "tagged" if tag != "none" else "notag",
                man.get("checkpoint_info", {}),
            )
        )
        ck_path = ck.get("path") or man.get("checkpoint")
        if not ck.get("checkpoint_tick") and ck_path:
            try:
                with open(os.path.join(ck_path, "m5.cpt")) as f:
                    for line in f:
                        if line.startswith("curTick="):
                            ck["checkpoint_tick"] = int(line.split("=")[1])
                            break
            except OSError:
                pass
        for i, (wl, status, rep) in enumerate(regions):
            row = {
                "abi": abi,
                "config": config,
                "cpu": cpu,
                "tag_model": tag,
                "workload": wl,
                "status": status,
            }
            row["errors"] = int(rep.get("ERRORS", 0))
            row["iterations"] = rep.get("iterations", "")
            row["guest_seconds"] = rep.get("time(secs)", "")
            row["workloads_per_sec"] = rep.get("workloads/sec", "")
            # wall clock (host) times
            row["run_mode"] = info.get("mode", "")
            row["run_start"] = info.get("start", "")
            row["run_end"] = info.get("end", "")
            row["run_wall_seconds"] = info.get("wall_seconds", "")
            row["run_exit_code"] = info.get("exit_code", "")
            row["checkpoint_boot_wall_seconds"] = ck.get(
                "boot_and_unpack_wall_seconds", ""
            )
            row["checkpoint_boot_sim_seconds"] = ck.get(
                "boot_and_unpack_sim_seconds",
                (ck.get("checkpoint_tick") or 0) / 1e12 or "",
            )
            if i < len(dumps):
                row.update(metrics(dumps[i]))
                all_stats.append(
                    dict(
                        {
                            "abi": abi,
                            "config": config,
                            "cpu": cpu,
                            "tag_model": tag,
                            "workload": wl,
                            "run_dir": os.path.relpath(d, out),
                        },
                        **dumps[i],
                    )
                )
            # host time outside the workload region (boot or restore,
            # unpacking, teardown); only meaningful for one-workload runs
            if (
                len(regions) == 1
                and info.get("wall_seconds") is not None
                and row.get("host_seconds") == row.get("host_seconds")
            ):
                row["setup_wall_seconds"] = round(
                    info["wall_seconds"] - row.get("host_seconds", 0), 3
                )
            # everything CoreMark-PRO reported for this workload
            for k, v in rep.items():
                row["cm_" + k] = v
            row["run_dir"] = os.path.relpath(d, out)
            row["source"] = os.path.basename(os.path.normpath(out))
            rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--into")
    args = ap.parse_args()
    out = args.into or args.dirs[0]
    merged, merged_stats = {}, {}
    for d in args.dirs:
        stats = []
        for row in collect(d, stats):
            merged[(row["abi"], row["config"], row["workload"])] = row
        for st in stats:
            merged_stats[(st["abi"], st["config"], st["workload"])] = st
    rows = list(merged.values())
    bad = [r for r in rows if str(r.get("status")) != "0"
           or str(r.get("errors", "0")) not in ("0", "")]
    if bad:
        print(f"WARNING: {len(bad)} of {len(rows)} runs failed (non-zero "
              "workload exit status or CoreMark-PRO CRC errors); their "
              "metrics are not results:", file=sys.stderr)
        for r in bad[:20]:
            print(f"  {r['workload']} {r['abi']}-{r.get('config', r['cpu'])}"
                  f": status={r['status']} errors={r.get('errors')}",
                  file=sys.stderr)
    stat_rows = list(merged_stats.values())
    if not rows:
        sys.exit(f"no results under {args.dirs}")

    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(out, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)
    if stat_rows:
        sfields = list(dict.fromkeys(k for r in stat_rows for k in r))
        with open(os.path.join(out, "all_stats.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, sfields)
            w.writeheader()
            w.writerows(stat_rows)
    for wl in sorted({r["workload"] for r in rows}):
        if os.path.isdir(os.path.join(out, wl)):
            with open(
                os.path.join(out, wl, "summary.csv"), "w", newline=""
            ) as f:
                w = csv.DictWriter(f, fields)
                w.writeheader()
                w.writerows(r for r in rows if r["workload"] == wl)

    # purecap / hybrid ratios
    by = {(r["abi"], r["config"], r["workload"]): r for r in rows}
    ratio_keys = [
        "insts",
        "cycles",
        "loads",
        "stores",
        "l1d_misses",
        "l2_misses",
        "dram_bytes_read",
    ]
    # ABI pairs (numerator, baseline): plain is RV64 compiled without
    # CHERI, the baseline of a core without CHERI; hybrid is legacy code on
    # a CHERI system.
    pairs = [("purecap", "plain"), ("hybrid", "plain"), ("purecap", "hybrid")]
    comp = []
    for num, den in pairs:
        for (abi, config, wl), p in by.items():
            if abi != num or (den, config, wl) not in by:
                continue
            h = by[(den, config, wl)]
            c = {
                "abi": num,
                "baseline": den,
                "config": config,
                "cpu": p["cpu"],
                "tag_model": p["tag_model"],
                "workload": wl,
            }
            for k in ratio_keys:
                try:
                    c[k + "_ratio"] = float(p[k]) / float(h[k])
                except (KeyError, ValueError, ZeroDivisionError):
                    c[k + "_ratio"] = float("nan")
            c["ipc_" + num] = p.get("ipc", float("nan"))
            c["ipc_" + den] = h.get("ipc", float("nan"))
            c["ipc_abi"] = p.get("ipc", float("nan"))
            c["ipc_baseline"] = h.get("ipc", float("nan"))
            c["errors"] = p["errors"] + h["errors"]
            comp.append(c)
    with open(os.path.join(out, "comparison.csv"), "w", newline="") as f:
        w = csv.DictWriter(
            f,
            list(dict.fromkeys(k for c in comp for k in c)) or ["config"],
            restval="",
        )
        w.writeheader()
        w.writerows(comp)

    # cost of tag storage: each tag model vs passthrough (same topology)
    tag = []
    for (abi, config, wl), r in by.items():
        if r["tag_model"] in ("none", "passthrough"):
            continue
        base = by.get((abi, f"{r['cpu']}-passthrough", wl))
        if not base:
            continue
        t = {
            "abi": abi,
            "cpu": r["cpu"],
            "tag_model": r["tag_model"],
            "workload": wl,
        }
        for k in ("cycles", "dram_bytes_read", "dram_bytes_written"):
            try:
                t[k + "_vs_passthrough"] = float(r[k]) / float(base[k])
            except (KeyError, ValueError, ZeroDivisionError):
                t[k + "_vs_passthrough"] = float("nan")
        for k in (
            "tag_reads",
            "tag_writes",
            "tag_leaf_hits",
            "tag_leaf_misses",
            "tag_zero_elided",
            "tag_delayed_reads",
            "tag_delay_ticks",
        ):
            t[k] = r.get(k, "")
        try:
            hits, misses = float(r["tag_leaf_hits"]), float(
                r["tag_leaf_misses"]
            )
            t["tag_leaf_hit_rate"] = hits / (hits + misses)
        except (KeyError, ValueError, ZeroDivisionError):
            t["tag_leaf_hit_rate"] = float("nan")
        tag.append(t)
    if tag:
        with open(os.path.join(out, "tag_costs.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, list(tag[0]))
            w.writeheader()
            w.writerows(tag)

    def gm(xs):
        xs = [x for x in xs if x > 0 and not math.isnan(x)]
        return (
            math.exp(sum(map(math.log, xs)) / len(xs)) if xs else float("nan")
        )

    for (num, den), config in sorted(
        {((c["abi"], c["baseline"]), c["config"]) for c in comp},
        key=lambda k: (pairs.index(k[0]), k[1]),
    ):
        cs = [c for c in comp if c["config"] == config
              and (c["abi"], c["baseline"]) == (num, den)]
        print(f"\n== {config}: {num} / {den}")
        hdr = [
            "workload",
            "insts",
            "cycles",
            "loads",
            "stores",
            "L1D miss",
            "L2 miss",
            "DRAM rd",
            "IPC a/b",
            "err",
        ]
        print(
            "{:<27}{:>7}{:>8}{:>7}{:>8}{:>9}{:>8}{:>8}{:>12}{:>5}".format(*hdr)
        )
        for c in cs:
            print(
                "{:<27}{:>7.3f}{:>8.3f}{:>7.3f}{:>8.3f}{:>9.3f}{:>8.3f}"
                "{:>8.3f}{:>6.2f}/{:<5.2f}{:>5}".format(
                    c["workload"],
                    c["insts_ratio"],
                    c["cycles_ratio"],
                    c["loads_ratio"],
                    c["stores_ratio"],
                    c["l1d_misses_ratio"],
                    c["l2_misses_ratio"],
                    c["dram_bytes_read_ratio"],
                    c["ipc_abi"],
                    c["ipc_baseline"],
                    c["errors"],
                )
            )
        print(
            "{:<27}{:>7.3f}{:>8.3f}{:>7.3f}{:>8.3f}{:>9.3f}{:>8.3f}"
            "{:>8.3f}".format(
                "geomean",
                *(gm([c[k + "_ratio"] for c in cs]) for k in ratio_keys),
            )
        )
    if tag:
        print(
            "\n== tag storage cost vs passthrough (cycles ratio, "
            "leaf hit rate)"
        )
        for t in sorted(
            tag, key=lambda t: (t["tag_model"], t["abi"], t["workload"])
        ):
            print(
                f"  {t['tag_model']:<13}{t['abi']:<9}{t['workload']:<27}"
                f"{t['cycles_vs_passthrough']:7.3f}"
                f"{t['tag_leaf_hit_rate']:8.3f}"
            )
    print(
        f"\nwrote {out}/results.csv, comparison.csv, all_stats.csv"
        + (", tag_costs.csv" if tag else "")
    )


if __name__ == "__main__":
    main()
