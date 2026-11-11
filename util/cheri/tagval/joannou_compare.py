#!/usr/bin/env python3
"""Compare the tag-cache results with Joannou et al., "Efficient Tagged
Memory" (ICCD 2017), using only numbers their text states:

  Fig. 2 (trace study, small system: 1 core, 256 KiB LLC, 8-way tag cache,
    64-byte lines, 1 tag bit per 8 bytes): at a 32 KiB tag cache,
    Earley-Boyer 4.91 % and FFMPEG 1.31 % DRAM traffic overhead; 32 KiB is
    the size they need for < 5 % on the small system.
  Silent-write elimination: dirty tag lines 80 % -> 4 % (FFMPEG),
    60 % -> ~30 % (Earley-Boyer).
  FPGA (Fig. 9; CHERI-MIPS, 32 KiB 4-way tag cache, 128-byte lines, 1 bit
    per 32 bytes): uncompressed < 3 % for programs whose data fits the tag
    cache's reach, Splay < 8 %; with the hierarchical table MiBench ~0.
  Fig. 3: spatial locality at page scale is why the tag cache hits.

Our tag granule is 16 bytes (1 bit per 16 B, so a tag cache covers 2x the
data of theirs at the same size), lines are 64 bytes, and the hierarchical
table's grouping factor is 512 (their line-group principle).

Input: tagcache_sweep_collect.py's CSV (atomic sweep of tagval, with and
without CHERI_TAG_SWE). Usage: joannou_compare.py SWEEP.csv [--abi purecap] [--cpu atomic]
"""

import argparse
import csv
from collections import defaultdict

KIB = 1024
REF_FIG2_32K = {"earley-boyer": 4.91, "ffmpeg": 1.31}
REF_DIRTY = {"ffmpeg": (80, 4), "earley-boyer": (60, 30)}
MIBENCH = ("qsort", "jpeg", "dijkstra", "sha", "crc32", "fft")


def pct(x):
    return f"{100 * float(x):6.2f}%" if x not in ("", None) else "     -"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv")
    ap.add_argument("--abi", default="purecap")
    ap.add_argument("--cpu", default="atomic",
                    help="CPU of the runs to use (the sweep's: atomic)")
    args = ap.parse_args()
    rows = [r for r in csv.DictReader(open(args.csv))
            if r["suite"] == "tagval" and r["cpu"] == args.cpu]
    by = defaultdict(dict)  # (wl, abi, model, swe) -> {size: row}
    for r in rows:
        by[(r["workload"], r["abi"], r["tag_model"],
            r["silent_write_elim"])][int(r["tag_cache_bytes"])] = r
    wls = sorted({r["workload"] for r in rows})
    sizes = sorted({int(r["tag_cache_bytes"]) for r in rows})
    a = args.abi

    print(f"== Fig. 2: DRAM traffic overhead vs leaf tag-cache size "
          f"(flat, {a}, no SWE)")
    print(f"{'workload':14s}" + "".join(f"{s // KIB:>8d}K" for s in sizes)
          + "   <5% at   Joannou@32K")
    for wl in wls:
        pts = by.get((wl, a, "flat", "0"), {})
        under = next((f"{s // KIB}K" for s in sizes if s in pts and
                      float(pts[s]["dram_overhead"]) < 0.05), "-")
        ref = REF_FIG2_32K.get(wl)
        print(f"{wl:14s}" + "".join(pct(pts[s]["dram_overhead"])
                                    if s in pts else "      - "
                                    for s in sizes)
              + f"   {under:>6s}   " + (f"{ref:.2f}%" if ref else ""))

    print(f"\n== Figs. 7/9: flat vs hierarchical at 32 KiB ({a} and plain; "
          "Joannou FPGA: uncompressed < 3 %, Splay < 8 %, MiBench "
          "compressed ~0)")
    for wl in wls:
        cells = []
        for abi in (a, "plain"):
            for model in ("flat", "hierarchical"):
                r = by.get((wl, abi, model, "0"), {}).get(32 * KIB)
                cells.append(pct(r["dram_overhead"]) if r else "     -")
        print(f"{wl:14s} {a}: flat {cells[0]} hier {cells[1]}   "
              f"plain: flat {cells[2]} hier {cells[3]}")

    print(f"\n== Silent-write elimination: dirty share of evicted leaf "
          f"lines (flat, {a}, 32 KiB)")
    for wl in wls:
        off = by.get((wl, a, "flat", "0"), {}).get(32 * KIB)
        on = by.get((wl, a, "flat", "1"), {}).get(32 * KIB)
        ref = REF_DIRTY.get(wl)
        print(f"{wl:14s} off {pct(off['leaf_dirty_eviction_share']) if off else '     -'}"
              f"  on {pct(on['leaf_dirty_eviction_share']) if on else '     -'}"
              f"  overhead off {pct(off['dram_overhead']) if off else '     -'}"
              f" on {pct(on['dram_overhead']) if on else '     -'}"
              + (f"   Joannou {ref[0]}% -> {ref[1]}%" if ref else ""))

    print(f"\n== Fig. 3: spatial vs temporal leaf hits (flat, {a}, 256 KiB)")
    for wl in wls:
        r = by.get((wl, a, "flat", "0"), {}).get(256 * KIB)
        if r:
            print(f"{wl:14s} spatial {pct(r['leaf_spatial_hit_share'])} "
                  f"temporal {pct(r['leaf_temporal_hit_share'])} "
                  f"miss {pct(1 - float(r['leaf_hit_rate']))}")


if __name__ == "__main__":
    main()
