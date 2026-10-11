#!/usr/bin/env python3
"""Run Olden (purecap vs hybrid) on the gem5 CHERI-RISC-V model.

Same scheme as util/cheri/coremark/run.py, whose helpers it uses: one gem5
run per (workload, ABI, config) in OUT/<workload>/<abi>-<config>/ (config =
CPU[-TAGMODEL]), restored from a checkpoint of booted CheriBSD that already
holds both ABIs' binaries (BASE-notag, and BASE-tagged for tag-model
configs; created on first use and refused if kernel, disk or binaries
changed). The benchmark runs inside one m5 workbegin/workend region, so
stats.txt covers exactly that program; its output goes to a file and is
printed after the region (or, above 32 KiB, its MD5 and line count) so
parse.py can check it.

The kernel's WITNESS lock-order checking is switched off before the region
(--witness on keeps it): it inflates kernel time (page faults are frequent
in these allocation-heavy programs) and is not part of a production system.

Usage:
  util/cheri/olden/run.py --out m5out/olden/<name> \\
      --checkpoint m5out/olden/ckpt \\
      [--configs atomic,minor,minor-passthrough,minor-flat,minor-hierarchical]
      [--abis purecap,hybrid] [--workloads treeadd,mst] [--jobs 4]
      [--wl-args NAME=ARGS ...]
"""

import argparse
import concurrent.futures as cf
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "cm_run", os.path.join(HERE, "..", "coremark", "run.py")
)
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)  # shared gem5/checkpoint helpers
GEM5 = cm.GEM5
OUTPUT_INLINE_MAX = 32 * 1024


def region(wl, exe, args, witness):
    """Guest commands for one workload (restored guest, binaries in
    /root/cm/<abi>/)."""
    lines = ["#!/bin/sh", "cd /tmp"]
    if not witness:
        lines.append("sysctl debug.witness.watch=0 >/dev/null 2>&1")
    lines += [
        f'echo "=== CM-BEGIN {wl}"',
        "/sbin/m5 workbegin",
        f"{exe} {args} > /tmp/ol_out.txt 2>&1",
        "st=$?",
        "/sbin/m5 workend",
        f'echo "=== CM-END {wl} status=$st"',
        f'echo "=== OL-MD5 {wl} $(md5 -q /tmp/ol_out.txt) '
        '$(wc -l < /tmp/ol_out.txt) $(wc -c < /tmp/ol_out.txt)"',
        f"if [ $(wc -c < /tmp/ol_out.txt) -le {OUTPUT_INLINE_MAX} ]; then",
        f'  echo "=== OL-OUT-BEGIN {wl}"',
        "  cat /tmp/ol_out.txt",
        f'  echo "=== OL-OUT-END {wl}"',
        "fi",
    ]
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="results directory")
    ap.add_argument(
        "--work",
        default=os.path.expanduser("~/hiwi/olden-gem5"),
        help="build.py work dir (builds/, workloads.json)",
    )
    ap.add_argument("--abis", default=None,
                    help="default: every ABI built (purecap,hybrid,plain)")
    ap.add_argument(
        "--configs",
        default="atomic,minor,minor-passthrough,minor-flat,minor-hierarchical",
        help="comma list of CPU[-TAGMODEL]",
    )
    ap.add_argument("--workloads", default=None, help="default: all built")
    ap.add_argument(
        "--wl-args",
        action="append",
        default=[],
        help="NAME=ARGS: other arguments for one workload (the output "
        "check against the native reference then does not apply)",
    )
    ap.add_argument("--witness", choices=("off", "on"), default="off")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument(
        "--timeout",
        type=int,
        default=48 * 3600,
        help="host seconds per gem5 run before it is killed (default 48 h; "
        "long workloads on Minor take many hours on a loaded machine)",
    )
    ap.add_argument("--sdk", default=os.path.expanduser("~/cheri/output/sdk"))
    ap.add_argument("--checkpoint", required=True, help="checkpoint base")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    work = os.path.abspath(args.work)
    with open(os.path.join(work, "workloads.json")) as f:
        built = json.load(f)
    wls = built["workloads"]
    workloads = args.workloads.split(",") if args.workloads else list(wls)
    for wl in workloads:
        if wl not in wls:
            sys.exit(f"unknown workload {wl} (built: {', '.join(wls)})")
    wl_args = {wl: wls[wl]["args"] for wl in workloads}
    changed = {}
    for spec in args.wl_args:
        name, _, a = spec.partition("=")
        if name not in wl_args:
            sys.exit(f"--wl-args: unknown workload {name}")
        wl_args[name] = changed[name] = a

    cfg = {}
    for c in args.configs.split(","):
        cpu, _, tag = c.partition("-")
        tag = tag or "none"
        if cpu not in ("atomic", "timing", "minor", "o3") or tag not in (
            "none",
            "passthrough",
            "flat",
            "hierarchical",
        ):
            sys.exit(f"bad config {c}")
        cfg[c] = (cpu, tag)

    out = os.path.abspath(args.out)
    os.makedirs(os.path.join(out, "bin"), exist_ok=True)
    env = dict(os.environ)
    abis = (args.abis.split(",") if args.abis
            else built.get("abis", ["purecap", "hybrid"]))
    binaries, bins_by_abi = {}, {}
    for abi in abis:
        bins = []
        for wl in workloads:
            src = os.path.join(work, "builds", abi, "bin", wl)
            dst = os.path.join(out, "bin", f"{abi}-{wl}")
            cm.strip(args.sdk, src, dst)
            bins.append((wl, dst))
            binaries[f"{abi}/{wl}"] = {"path": src, "sha256": cm.sha256(src)}
        bins_by_abi[abi] = bins

    knobs = {k: env[k] for k in cm.ENV_KNOBS + ["CHERI_MISALIGNED"]
             if k in env}
    system_files = {}
    for k in ("CHERI_KERNEL", "CHERI_DISK"):
        p = knobs.get(k) or os.path.join(
            GEM5,
            "tests",
            "kernel" if k == "CHERI_KERNEL" else "cheribsd-riscv64-purecap.img",
        )
        system_files[k] = {"path": os.path.abspath(p)}
        if k == "CHERI_KERNEL" and os.path.exists(p):
            system_files[k]["sha256"] = cm.sha256(p)
    gem5_rev = subprocess.run(
        ["git", "-C", GEM5, "describe", "--always", "--dirty"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "suite": "olden",
        "gem5_rev": gem5_rev,
        "config": cm.CONFIG,
        "abis": abis,
        "configs": {c: {"cpu": a, "tag_model": t} for c, (a, t) in cfg.items()},
        "layout": "OUT/<workload>/<abi>-<config>/",
        "workloads": workloads,
        "workload_args": wl_args,
        "args_changed_from_build": changed,
        "build": {k: v for k, v in built.items() if k != "workloads"},
        "build_workloads": {wl: wls[wl] for wl in workloads},
        "work": work,
        "guest_witness": args.witness,
        "env_knobs": knobs,
        "system_files": system_files,
        "binaries": binaries,
        "command": " ".join(sys.argv),
    }
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"manifest: {os.path.join(out, 'manifest.json')}")
    if args.dry_run:
        return

    ckpts = {}
    base = os.path.abspath(args.checkpoint)
    for tagged in sorted({tag != "none" for _, tag in cfg.values()}):
        ckpt = base + ("-tagged" if tagged else "-notag")
        cm.ensure_checkpoint(ckpt, tagged, system_files, binaries,
                             bins_by_abi, out, env, args.timeout)
        ckpts[tagged] = ckpt
    manifest["checkpoints"] = {}
    for tagged, ckpt in ckpts.items():
        try:
            with open(os.path.join(ckpt, "ckpt_info.json")) as f:
                info = json.load(f)
        except OSError:
            info = {"checkpoint_tick": cm.checkpoint_tick(ckpt)}
        manifest["checkpoints"]["tagged" if tagged else "notag"] = dict(
            info, path=ckpt)
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    scripts = {}
    for wl in workloads:
        os.makedirs(os.path.join(out, wl), exist_ok=True)
        for abi in abis:
            path = os.path.join(out, wl, f"job-{abi}.sh")
            with open(path, "w") as f:
                f.write("\n".join(region(
                    wl, f"/root/cm/{abi}/cm_{wl}.exe", wl_args[wl],
                    args.witness == "on")) + "\n")
            scripts[(wl, abi)] = path

    jobs = [(wl, abi, c) for wl in workloads for abi in abis for c in cfg]
    failed = []
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = []
        for wl, abi, c in jobs:
            cpu, tag = cfg[c]
            futs.append(pool.submit(
                cm.run_restored,
                os.path.join(out, wl, f"{abi}-{c}"),
                cpu,
                tag,
                scripts[(wl, abi)],
                ckpts[tag != "none"],
                args.timeout,
                env,
            ))
        for fut in cf.as_completed(futs):
            outdir, rc, secs = fut.result()
            status = cm.workload_status(outdir)
            if status != "0":
                failed.append(os.path.relpath(outdir, out))
            print(f"{os.path.relpath(outdir, out)}: gem5 exit {rc}, "
                  f"workload exit {status}, {secs / 60:.1f} min", flush=True)
    if failed:
        print(f"\nWARNING: {len(failed)} run(s) did not exit 0 (see their "
              "console.log):\n  " + "\n  ".join(sorted(failed)), flush=True)
    print(f"next: util/cheri/olden/parse.py {out}")


if __name__ == "__main__":
    main()
