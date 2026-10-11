#!/usr/bin/env python3
"""Run the Juliet C/C++ test suite (purecap vs hybrid) on gem5 CHERI-RISC-V.

Uses build.py's output: per ABI and CWE, static multi-call binaries of up to
250 tests (sNN) and the few tests built as separate executables (run in
groups, xNN). One gem5 run per (CWE, ABI, config, shard), in
OUT/CWE<n>/<abi>-<config>/<shard>/: it restores a booted CheriBSD
checkpoint, unpacks the shard, and inside one m5 workbegin/workend region
runs every test's good and then bad variant in its own forked process
(stdin from the CWE's input file, as cheribuild sets it up; a guest-time
timeout). One console line per run, "JL <cwe> <good|bad> <test>-<variant>
exit N|signal N|timeout"; parse.py classifies them.

The checkpoint holds no test binaries (BASE-notag, plus BASE-tagged for
tag-model configs), so one is shared by every shard and every build; it
records the kernel and disk it was made with and is refused if they changed.

Usage:
  util/cheri/juliet/run.py --out m5out/juliet/<name> \\
      --checkpoint m5out/juliet/ckpt [--configs atomic] \\
      [--abis purecap,hybrid] [--cwes 121,122] [--test-timeout 1] \\
      [--misaligned emulate|trap] [--jobs 8] [--limit N]
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
PAYLOAD_VERSION = 1

# stdin contents per CWE, as cheribuild's juliet-cwe-* targets set up
# /tmp/in.txt (sizes/indices read with fgets/fscanf); others get empty input.
INPUTS = {
    121: "500\n",
    122: "500\n",
    124: "-500\n",
    126: "500\n",
    127: "-500\n",
    134: "Format string: %s %d %s\n",
}


SEP_CHUNK = 40  # separate executables (~0.9 MB each) per gem5 run


def load_shards(builds, abi, cwe, limit):
    """[(name, multi-call binary or None, [(kind, test)], [separate exe
    paths])] for one ABI and CWE, from build.py's shards.json."""
    base = os.path.join(builds, abi, f"CWE{cwe}")
    try:
        with open(os.path.join(base, "shards.json")) as f:
            info = json.load(f)
    except OSError:
        return []
    out, left = [], limit or 1 << 30
    for sh in info["shards"]:
        tests = sh["tests"][:left]
        left -= len(tests)
        if not tests:
            break
        runs = [(k, t) for k in ("good", "bad") for t in tests
                if t in sh[k]]
        # With --limit the binary runs the first N of each variant (its
        # table is in this order).
        out.append((sh["shard"], os.path.join(base, sh["shard"]), runs, []))
    seps = sorted(info.get("separate", {}).items())
    if limit:
        seps = seps[: max(0, left)]
    for i in range(0, len(seps), SEP_CHUNK):
        runs, exes = [], []
        for t, kinds in seps[i : i + SEP_CHUNK]:
            for k in kinds:
                runs.append((k, t))
                exes.append(os.path.join(base, "sep", f"{t}-{k}"))
        out.append((f"x{i // SEP_CHUNK:02d}", None, runs, exes))
    return out


def make_job(path, builds, cwe, prog, runs, exes, test_timeout, limit):
    """Guest script for one shard: unpack, run the multi-call binary (all
    good then all bad tests) and/or the separate executables via jrun."""
    work = path + ".d"
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "in.txt"), "w") as f:
        f.write(INPUTS.get(cwe, ""))
    with open(path[:-3] + ".tests", "w") as f:
        f.write("".join(f"{k} {t}-{k}\n" for k, t in runs))
    members = [(os.path.join(work, "in.txt"), "in.txt")]
    if prog:
        members.append((prog, "prog"))
    if exes:
        with open(os.path.join(work, "list.txt"), "w") as f:
            for e in exes:
                kind = e.rsplit("-", 1)[1]
                f.write(f"CWE{cwe} {kind} /tmp/jl/sep/{os.path.basename(e)}\n")
        members += [(os.path.join(builds, "jrun"), "jrun"),
                    (os.path.join(work, "list.txt"), "list.txt")]
        members += [(e, "sep/" + os.path.basename(e)) for e in exes]
    tgz = path + ".tgz"
    cm.bundle(tgz, members)
    cmds = []
    if prog:
        # with --limit, stop after the expected number of results
        cmds.append(f"/tmp/jl/prog {test_timeout} /tmp/jl/in.txt"
                    + (f" all {len({t for _, t in runs})}" if limit else ""))
    if exes:
        cmds.append(f"/tmp/jl/jrun {test_timeout} /tmp/jl/in.txt "
                    "/tmp/jl/list.txt")
    lines = [
        "#!/bin/sh",
        # Lock-order checking (the kernel is built with WITNESS) costs ~25%
        # of a test's simulated time and does not affect CHERI behaviour.
        "sysctl debug.witness.watch=0 >/dev/null 2>&1",
        "rm -rf /tmp/jl && mkdir -p /tmp/jl/work && cd /tmp/jl/work",
        'tail -c +@PAYLOAD_OFFSET@ "$0" | tar xzf - -C /tmp/jl || '
        '{ echo "=== JL-UNPACK-FAILED"; exit 1; }',
        # CWE134 (format strings) reads these, as in cheribuild
        "export ADD='%s%d%s'",
        "cp /tmp/jl/in.txt /tmp/in.txt",
        "printf '%s\\n' 'Format string: %s %d %s' > /tmp/file.txt",
        f'echo "=== JL-BEGIN CWE{cwe} {len(runs)}"',
        "/sbin/m5 workbegin",
        "st=0",
    ]
    lines += [c + " || st=$?" for c in cmds]
    lines += ["/sbin/m5 workend", 'echo "=== JL-END status=$st"']
    cm.write_payload_script(path, lines, tgz)
    return len(runs)


def ensure_checkpoint(ckpt, tagged, system_files, out, env, timeout):
    """Booted CheriBSD that, after a restore, runs `m5 readfile`."""
    fingerprint = {
        "system_files": system_files,
        "tag_reservation": tagged,
        "payload_version": PAYLOAD_VERSION,
    }
    fp_path = os.path.join(ckpt, "jl_fingerprint.json")
    if os.path.exists(os.path.join(ckpt, "m5.cpt")):
        with open(fp_path) as f:
            if json.load(f) != fingerprint:
                sys.exit(
                    f"checkpoint {ckpt} was made with another kernel/disk/"
                    "layout; use a new --checkpoint"
                )
        print(f"restoring {ckpt}")
        return
    name = os.path.basename(ckpt)
    print(f"creating checkpoint {ckpt} (boot)", flush=True)
    os.makedirs(ckpt, exist_ok=True)
    with open(fp_path, "w") as f:
        json.dump(fingerprint, f, indent=2)
    prep = os.path.join(out, f"runner-{name}.sh")
    with open(prep, "w") as f:
        f.write(
            "\n".join(
                [
                    "#!/bin/sh",
                    "cd /tmp",
                    "sync",
                    "/sbin/m5 checkpoint",
                    "/sbin/m5 readfile > /tmp/jl_job.sh",
                    "sh /tmp/jl_job.sh",
                    "/sbin/m5 exit",
                    "",
                ]
            )
        )
    penv = dict(
        env,
        CHERI_CKPT_OUT=ckpt,
        CHERI_SWITCH_CPU="atomic",
        CHERI_TAG_MODEL="passthrough" if tagged else "none",
    )
    t0 = time.time()
    rc = subprocess.run(
        [
            sys.executable,
            cm.DRIVER,
            "--outdir",
            os.path.join(out, name),
            "--binary",
            prep,
            "--config",
            cm.CONFIG,
            "--timeout",
            str(timeout),
        ],
        cwd=GEM5,
        env=penv,
    ).returncode
    t1 = time.time()
    if not os.path.exists(os.path.join(ckpt, "m5.cpt")):
        sys.exit(f"checkpoint creation failed (driver exit {rc})")
    tick = cm.checkpoint_tick(ckpt)
    with open(os.path.join(ckpt, "ckpt_info.json"), "w") as f:
        json.dump(
            {
                "created": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(t0)
                ),
                "tag_reservation": tagged,
                "boot_wall_seconds": round(t1 - t0, 3),
                "checkpoint_tick": tick,
                "boot_sim_seconds": tick / 1e12 if tick else None,
                "console": os.path.join(out, name, "console.log"),
            },
            f,
            indent=2,
        )


def shard_status(outdir):
    """(guest status of the shard, number of JL result lines)."""
    status, n = "?", 0
    try:
        with open(os.path.join(outdir, "console.log"), errors="replace") as f:
            for line in f:
                if line.startswith("JL "):
                    n += 1
                elif line.startswith("=== JL-END"):
                    status = line.rsplit("status=", 1)[-1].strip()
                elif line.startswith("=== JL-UNPACK-FAILED"):
                    status = "unpack-failed"
    except OSError:
        pass
    return status, n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="results directory")
    ap.add_argument(
        "--builds",
        default=os.path.expanduser("~/hiwi/juliet-gem5/out"),
        help="out/ dir from build.py",
    )
    ap.add_argument("--abis", default=None,
                    help="default: every ABI built (purecap,hybrid,plain)")
    ap.add_argument(
        "--configs",
        default="atomic",
        help="comma list of CPU[-TAGMODEL] (default atomic: the outcome "
        "of a test does not depend on the timing model)",
    )
    ap.add_argument(
        "--cwes", default=None, help="comma list (default: all built)"
    )
    ap.add_argument(
        "--limit", type=int, default=0, help="first N tests per CWE (pilot)"
    )
    ap.add_argument(
        "--test-timeout",
        type=int,
        default=1,
        help="guest seconds per test (tests that wait on a socket time out)",
    )
    ap.add_argument(
        "--misaligned",
        choices=("emulate", "trap"),
        default="emulate",
        help="misaligned data accesses: complete (default; as on QEMU and "
        "on hardware with firmware emulation, where Juliet results are "
        "usually reported) or trap (gem5's default: SIGBUS in the guest)",
    )
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=12 * 3600)
    ap.add_argument("--checkpoint", required=True, help="checkpoint base")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    builds = os.path.abspath(args.builds)
    if not os.path.exists(os.path.join(builds, "jrun")):
        sys.exit(f"{builds}/jrun missing: run util/cheri/juliet/build.py")
    abis = (args.abis.split(",") if args.abis else
            [a for a in ("purecap", "hybrid", "plain")
             if os.path.isdir(os.path.join(builds, a))])
    if args.cwes:
        cwes = [int(c.removeprefix("CWE")) for c in args.cwes.split(",")]
    else:
        cwes = sorted(
            {
                int(d[3:])
                for abi in abis
                if os.path.isdir(os.path.join(builds, abi))
                for d in os.listdir(os.path.join(builds, abi))
                if d.startswith("CWE")
            }
        )
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
    os.makedirs(out, exist_ok=True)
    env = dict(os.environ)
    env["CHERI_MISALIGNED"] = "1" if args.misaligned == "emulate" else "0"
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

    # Guest scripts, one per (CWE, ABI, shard); shared by all configs.
    jobs, plan = [], {}
    for cwe in cwes:
        for abi in abis:
            for name, prog, runs, exes in load_shards(
                builds, abi, cwe, args.limit
            ):
                jdir = os.path.join(out, f"CWE{cwe}", "jobs")
                os.makedirs(jdir, exist_ok=True)
                script = os.path.join(jdir, f"{abi}-{name}.sh")
                n = make_job(
                    script, builds, cwe, prog, runs, exes,
                    args.test_timeout, args.limit,
                )
                plan[f"CWE{cwe}/{abi}/{name}"] = {
                    "runs": n,
                    "multi_call": prog is not None,
                    "separate_executables": len(exes),
                }
                for c in cfg:
                    jobs.append((cwe, abi, c, name, script, n))
    gem5_rev = subprocess.run(
        ["git", "-C", GEM5, "describe", "--always", "--dirty"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    build_summary = os.path.join(os.path.dirname(builds), "build-summary.json")
    manifest = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gem5_rev": gem5_rev,
        "config": cm.CONFIG,
        "builds": builds,
        "build_summary": json.load(open(build_summary))
        if os.path.exists(build_summary)
        else None,
        "abis": abis,
        "configs": {c: {"cpu": a, "tag_model": t} for c, (a, t) in cfg.items()},
        "cwes": cwes,
        "test_timeout_guest_seconds": args.test_timeout,
        "misaligned_accesses": args.misaligned,
        "guest_witness": "disabled at run time (debug.witness.watch=0)",
        "inputs": {f"CWE{k}": v for k, v in INPUTS.items() if k in cwes},
        "layout": "OUT/CWE<n>/<abi>-<config>/<shard>/ (sNN: multi-call "
        "binary, xNN: separate executables)",
        "shards": plan,
        "env_knobs": knobs,
        "system_files": system_files,
        "command": " ".join(sys.argv),
    }
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    total = sum(n for *_, n in jobs)
    print(
        f"{len(jobs)} gem5 runs, {total} test executions; manifest: "
        f"{os.path.join(out, 'manifest.json')}"
    )
    if args.dry_run:
        return

    ckpts = {}
    base = os.path.abspath(args.checkpoint)
    for tagged in sorted({tag != "none" for _, tag in cfg.values()}):
        ckpt = base + ("-tagged" if tagged else "-notag")
        ensure_checkpoint(ckpt, tagged, system_files, out, env, args.timeout)
        ckpts[tagged] = ckpt

    # Largest shards first, so the tail of the run is short.
    jobs.sort(key=lambda j: -j[5])
    failed = []
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = {}
        for cwe, abi, c, idx, script, n in jobs:
            cpu, tag = cfg[c]
            outdir = os.path.join(out, f"CWE{cwe}", f"{abi}-{c}", idx)
            fut = pool.submit(
                cm.run_restored,
                outdir,
                cpu,
                tag,
                script,
                ckpts[tag != "none"],
                args.timeout,
                env,
            )
            futs[fut] = n
        for fut in cf.as_completed(futs):
            outdir, rc, secs = fut.result()
            status, got = shard_status(outdir)
            rel = os.path.relpath(outdir, out)
            if status != "0" or got != futs[fut]:
                failed.append(rel)
            print(
                f"{rel}: gem5 exit {rc}, shard status {status}, "
                f"{got}/{futs[fut]} tests reported, {secs / 60:.1f} min",
                flush=True,
            )
    if failed:
        print(
            f"\nWARNING: {len(failed)} shard(s) incomplete (see their "
            "console.log):\n  " + "\n  ".join(sorted(failed)),
            flush=True,
        )
    print(f"next: util/cheri/juliet/parse.py {out}")


if __name__ == "__main__":
    main()
