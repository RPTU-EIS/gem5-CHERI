#!/usr/bin/env python3
"""Run CoreMark-PRO (purecap vs hybrid) on the gem5 CHERI-RISC-V model.

Each (workload, ABI, config) is one gem5 run, in OUT/<workload>/<abi>-<config>/
(config = CPU[-TAGMODEL], e.g. minor-hierarchical):
the workload runs inside an `m5 workbegin` / `m5 workend` region (the
workbegin switches from the atomic boot CPU to the requested CPU), so its
stats.txt holds one dump for exactly that workload. parse.py turns all runs
into CSV.

Everything that defines the system comes from the environment and is recorded
in OUT/manifest.json, so a run can be repeated as is, or with another kernel:
  CHERI_KERNEL, CHERI_DISK      kernel / disk image (switch config defaults)
  CHERI_TAG_MODEL, CHERI_TAG_CACHE, CHERI_TAG_ASSOC, CHERI_L1D, CHERI_L1I,
  CHERI_L2                      see cheri-riscv-cheribsd-switch.py

With --checkpoint BASE the boot and the unpacking of the binaries happen
once per memory layout: BASE-notag (no tag model) and BASE-tagged (tag
table reserved; used by the passthrough/flat/hierarchical configs) are
created on first use (CheriBSD booted, both ABIs' binaries in /root/cm/, then
`m5 checkpoint`), and every run restores the matching one and only runs the
workload. Each records the kernel, disk and binary hashes; a mismatching one
is refused.

Usage:
  util/cheri/coremark/run.py --out m5out/coremark/minor-base \\
      --configs atomic,minor,minor-passthrough,minor-flat,minor-hierarchical \\
      [--abis purecap,hybrid,plain] [--iterations 1] \\
      [--workloads core,zip-test] [--jobs 4] [--checkpoint DIR]
"""

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time

GEM5 = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
DRIVER = os.path.join(GEM5, "util", "cheri", "run_cheribsd_test.py")
CONFIG = os.path.join(
    GEM5,
    "configs",
    "example",
    "gem5_library",
    "cheri-riscv-cheribsd-switch.py",
)
WORKLOADS = [
    "core",
    "cjpeg-rose7-preset",
    "linear_alg-mid-100x100-sp",
    "loops-all-mid-10k-sp",
    "nnet_test",
    "parser-125k",
    "radix2-big-64k",
    "sha-test",
    "zip-test",
]
PAYLOAD_VERSION = 2
ENV_KNOBS = [
    "CHERI_KERNEL",
    "CHERI_DISK",
    "CHERI_TAG_MODEL",
    "CHERI_TAG_CACHE",
    "CHERI_TAG_ASSOC",
    "CHERI_L1D",
    "CHERI_L1I",
    "CHERI_L2",
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def strip(sdk, src, dst):
    """Copy a binary for the guest without debug info (~10x smaller
    payload, much faster to unpack in the guest). Uses a pre-stripped copy
    from build.sh (bin-stripped/ next to bin/) if present, else the CHERI
    SDK's llvm-strip, else any llvm-strip on PATH, else copies it unstripped
    (works, but unpacking in the guest takes hours)."""
    pre = os.path.join(
        os.path.dirname(os.path.dirname(src)),
        "bin-stripped",
        os.path.basename(src),
    )
    tool = os.path.join(sdk, "bin", "llvm-strip")
    if not os.path.exists(tool):
        tool = shutil.which("llvm-strip")
    if os.path.exists(pre):
        shutil.copyfile(pre, dst)
    elif tool:
        subprocess.run([tool, "-o", dst, src], check=True)
    else:
        print(
            f"warning: no stripped copy or llvm-strip for {src}; shipping "
            "it unstripped (slow guest unpack). Run build.sh where the SDK "
            "exists and copy builds/ including bin-stripped/.",
            file=sys.stderr,
        )
        shutil.copyfile(src, dst)
    os.chmod(dst, 0o755)


def write_payload_script(path, lines, tgz):
    """Shell script followed by a raw gzip'd tar. The guest's m5_init.sh
    saves the readfile to a file and runs it, so the script extracts its own
    tail ("$0"); the shell never parses past `exit`. Unlike base64 this needs
    no slow in-guest decoding. `lines` may use @PAYLOAD_OFFSET@."""
    with open(tgz, "rb") as f:
        payload = f.read()
    marker = "@PAYLOAD_OFFSET@"
    text = "\n".join(lines + ["exit 0", ""])
    # The offset is part of the header it skips: iterate to a fixed point
    # (FreeBSD tail rejects zero-padded offsets).
    offset = len(text.encode()) + 1  # tail -c +N is 1-based
    while True:
        head = text.replace(marker, str(offset))
        if len(head.encode()) + 1 == offset:
            break
        offset = len(head.encode()) + 1
    with open(path, "wb") as f:
        f.write(head.encode())
        f.write(payload)


def bundle(tgz, members):
    """members: [(path on host, name in archive)]. Files are stored as
    executable whatever their mode on the host (a plain copy of a binary may
    lack the execute bit, and the guest then refuses to run it)."""

    def executable(ti):
        ti.mode = 0o755
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = "root"
        return ti

    with tarfile.open(tgz, "w:gz") as tar:
        for src, name in members:
            tar.add(src, arcname=name, filter=executable)


def make_runner(path, bins, iterations, extra_args, wl_args):
    """Guest script: unpack the binaries, then one region per workload."""
    tgz = path + ".tgz"
    bundle(tgz, [(exe, f"cm_{wl}.exe") for wl, exe in bins])
    lines = [
        "#!/bin/sh",
        "cd /tmp",
        'tail -c +@PAYLOAD_OFFSET@ "$0" | tar xzf - -C /tmp || '
        '{ echo "=== CM-UNPACK-FAILED"; exit 1; }',
        "chmod +x /tmp/cm_*.exe",
    ]
    lines += regions(
        [wl for wl, _ in bins], iterations, extra_args, "/tmp", wl_args
    )
    lines += ["rm -f /tmp/cm_*.exe"]
    write_payload_script(path, lines, tgz)


def regions(bins, iterations, extra_args, exe_dir, wl_args):
    out = []
    for wl in bins:
        cmd = (
            f"{exe_dir}/cm_{wl}.exe -v0 -c1 -w1 -i{iterations[wl]} "
            f"{wl_args.get(wl, '')} {extra_args}"
        )
        out += [
            f'echo "=== CM-BEGIN {wl}"',
            "/sbin/m5 workbegin",
            cmd.strip(),
            f'echo "=== CM-END {wl} status=$?"',
            "/sbin/m5 workend",
        ]
    return out


def make_ckpt_runner(path, bins_by_abi):
    """Checkpoint creation: unpack every ABI's binaries to /root/cm/<abi>,
    checkpoint, then (after a restore) run whatever `m5 readfile` returns."""
    tgz = path + ".tgz"
    bundle(
        tgz,
        [
            (exe, f"{abi}/cm_{wl}.exe")
            for abi, bins in bins_by_abi.items()
            for wl, exe in bins
        ],
    )
    lines = [
        "#!/bin/sh",
        "cd /tmp",
        "mkdir -p /root/cm",
        'tail -c +@PAYLOAD_OFFSET@ "$0" | tar xzf - -C /root/cm || '
        '{ echo "=== CM-UNPACK-FAILED"; exit 1; }',
        "chmod +x /root/cm/*/cm_*.exe",
        "ls -l /root/cm/*",
        "sync",
        "/sbin/m5 checkpoint",
        "/sbin/m5 readfile > /tmp/cm_job.sh",
        "sh /tmp/cm_job.sh",
        "/sbin/m5 exit",
    ]
    write_payload_script(path, lines, tgz)


def workload_status(outdir):
    """Exit status the guest reported for the workload ("?" if none)."""
    status = "?"
    try:
        with open(os.path.join(outdir, "console.log"), errors="replace") as f:
            for line in f:
                if line.startswith("=== CM-END"):
                    status = line.rsplit("status=", 1)[-1].strip()
    except OSError:
        pass
    return status


def write_run_info(outdir, info):
    with open(os.path.join(outdir, "run_info.json"), "w") as f:
        json.dump(info, f, indent=2)


def checkpoint_tick(ckpt):
    """Simulated tick at which the checkpoint was taken (end of boot)."""
    try:
        with open(os.path.join(ckpt, "m5.cpt")) as f:
            for line in f:
                if line.startswith("curTick="):
                    return int(line.split("=")[1])
    except OSError:
        pass
    return None


def run_restored(outdir, cpu, tag, job, ckpt, timeout, env):
    """Restore the checkpoint and run `job` (no boot, no shell driving)."""
    os.makedirs(outdir, exist_ok=True)
    env = dict(
        env,
        CHERI_SWITCH_CPU=cpu,
        CHERI_TAG_MODEL=tag,
        CHERI_CKPT_IN=ckpt,
        CHERI_READFILE=job,
    )
    env.pop("CHERI_CKPT_OUT", None)
    cmd = [
        os.path.join(GEM5, "build/RISCV_CHERI/gem5.opt"),
        "--outdir",
        outdir,
        CONFIG,
    ]
    t0 = time.time()
    with open(os.path.join(outdir, "console.log"), "w") as log:
        try:
            rc = subprocess.run(
                cmd,
                cwd=GEM5,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            ).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    t1 = time.time()
    write_run_info(
        outdir,
        {
            "mode": "checkpoint-restore",
            "cpu": cpu,
            "tag_model": tag,
            "checkpoint": ckpt,
            "start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)),
            "end": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t1)),
            "wall_seconds": round(t1 - t0, 3),
            "exit_code": rc,
            "command": cmd,
            "env_knobs": {
                k: env[k] for k in ENV_KNOBS + ["CHERI_SWITCH_CPU"] if k in env
            },
        },
    )
    return outdir, rc, t1 - t0


def run_one(outdir, cpu, tag, runner, timeout, env):
    """Boot CheriBSD and run `runner` (no checkpoint)."""
    os.makedirs(outdir, exist_ok=True)
    env = dict(env, CHERI_SWITCH_CPU=cpu, CHERI_TAG_MODEL=tag)
    cmd = [
        sys.executable,
        DRIVER,
        "--outdir",
        outdir,
        "--binary",
        runner,
        "--config",
        CONFIG,
        "--timeout",
        str(timeout),
    ]
    t0 = time.time()
    with open(os.path.join(outdir, "driver.log"), "w") as log:
        rc = subprocess.run(
            cmd, cwd=GEM5, env=env, stdout=log, stderr=subprocess.STDOUT
        ).returncode
    t1 = time.time()
    write_run_info(
        outdir,
        {
            "mode": "boot",
            "cpu": cpu,
            "tag_model": tag,
            "start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)),
            "end": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t1)),
            "wall_seconds": round(t1 - t0, 3),
            "exit_code": rc,
            "command": cmd,
            "env_knobs": {
                k: env[k] for k in ENV_KNOBS + ["CHERI_SWITCH_CPU"] if k in env
            },
        },
    )
    return outdir, rc, t1 - t0


def ensure_checkpoint(
    ckpt, tagged, system_files, binaries, bins_by_abi, out, env, timeout
):
    """Create ckpt (boot + unpack all binaries) unless it exists and
    matches; refuse a checkpoint made with other files."""
    fingerprint = {
        "system_files": system_files,
        "binaries": {k: v["sha256"] for k, v in binaries.items()},
        "tag_reservation": tagged,
        # bump PAYLOAD_VERSION when the guest payload changes, so older
        # checkpoints are refused (v1 could ship binaries without +x)
        "payload_version": PAYLOAD_VERSION,
    }
    fp_path = os.path.join(ckpt, "cm_fingerprint.json")
    if os.path.exists(os.path.join(ckpt, "m5.cpt")):
        with open(fp_path) as f:
            saved = json.load(f)
        if (
            saved["system_files"] != fingerprint["system_files"]
            or saved.get("tag_reservation", False) != tagged
            or saved.get("payload_version", 1) != PAYLOAD_VERSION
            or any(
                saved["binaries"].get(k) != v
                for k, v in fingerprint["binaries"].items()
            )
        ):
            sys.exit(
                f"checkpoint {ckpt} was made with another "
                "kernel/disk/binaries/layout; use a new --checkpoint"
            )
        print(f"restoring {ckpt}")
        return
    name = os.path.basename(ckpt)
    print(f"creating checkpoint {ckpt} (boot + unpack)", flush=True)
    os.makedirs(ckpt, exist_ok=True)
    with open(fp_path, "w") as f:
        json.dump(fingerprint, f, indent=2)
    prep = os.path.join(out, f"runner-{name}.sh")
    make_ckpt_runner(prep, bins_by_abi)
    penv = dict(
        env,
        CHERI_CKPT_OUT=ckpt,
        CHERI_SWITCH_CPU="atomic",
        CHERI_TAG_MODEL="passthrough" if tagged else "none",
    )
    t0 = time.time()
    prc = subprocess.run(
        [
            sys.executable,
            DRIVER,
            "--outdir",
            os.path.join(out, name),
            "--binary",
            prep,
            "--config",
            CONFIG,
            "--timeout",
            str(timeout),
        ],
        cwd=GEM5,
        env=penv,
    ).returncode
    t1 = time.time()
    if not os.path.exists(os.path.join(ckpt, "m5.cpt")):
        sys.exit(f"checkpoint creation failed (driver exit {prc})")
    tick = checkpoint_tick(ckpt)
    with open(os.path.join(ckpt, "ckpt_info.json"), "w") as f:
        json.dump(
            {
                "created": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(t0)
                ),
                "tag_reservation": tagged,
                "boot_and_unpack_wall_seconds": round(t1 - t0, 3),
                "checkpoint_tick": tick,
                "boot_and_unpack_sim_seconds": tick / 1e12 if tick else None,
                "console": os.path.join(out, name, "console.log"),
            },
            f,
            indent=2,
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="results directory")
    ap.add_argument(
        "--builds",
        default=os.path.expanduser("~/hiwi/coremark-pro-gem5/builds"),
        help="CoreMark-PRO builds/ dir from build.sh",
    )
    ap.add_argument("--abis", default="purecap,hybrid,plain")
    ap.add_argument(
        "--configs",
        default=None,
        help="comma list of CPU[-TAGMODEL], e.g. atomic,minor,"
        "minor-passthrough,minor-flat,minor-hierarchical (tag model none "
        "if omitted); run dirs are <abi>-<config>",
    )
    ap.add_argument(
        "--cpus",
        default="atomic,minor",
        help="old spelling of --configs without tag models",
    )
    ap.add_argument("--workloads", default=",".join(WORKLOADS))
    ap.add_argument(
        "--iterations",
        default="1",
        help="iterations for all workloads (N) or per workload "
        "(name=N,name=N,...; others default to 1)",
    )
    ap.add_argument(
        "--extra-args", default="", help="more flags for every workload"
    )
    ap.add_argument(
        "--wl-args",
        action="append",
        default=[],
        help="flags for one workload, NAME=FLAGS (repeatable), e.g. "
        "core=-D=-I1 (core's 1000-iteration preset)",
    )
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument(
        "--timeout",
        type=int,
        default=48 * 3600,
        help="host seconds per gem5 run before it is killed (default 48 h; "
        "long workloads on Minor take many hours on a loaded machine)",
    )
    ap.add_argument("--sdk", default=os.path.expanduser("~/cheri/output/sdk"))
    ap.add_argument(
        "--checkpoint",
        help="checkpoint dir to restore (created on first use)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    workloads = args.workloads.split(",")
    for wl in workloads:
        if wl not in WORKLOADS:
            sys.exit(f"unknown workload {wl}")
    if "=" in args.iterations:
        iterations = {wl: 1 for wl in workloads}
        for kv in args.iterations.split(","):
            k, v = kv.split("=")
            iterations[k] = int(v)
    else:
        iterations = {wl: int(args.iterations) for wl in workloads}

    wl_args = {}
    for spec in args.wl_args:
        name, _, flags = spec.partition("=")
        if name not in WORKLOADS:
            sys.exit(f"--wl-args: unknown workload {name}")
        wl_args[name] = flags

    out = os.path.abspath(args.out)
    os.makedirs(os.path.join(out, "bin"), exist_ok=True)
    env = dict(os.environ)
    abis = args.abis.split(",")
    configs = (args.configs or args.cpus).split(",")
    cfg = {}
    for c in configs:
        cpu, _, tag = c.partition("-")
        tag = tag or "none"
        if cpu not in ("atomic", "timing", "minor", "o3") or tag not in (
            "none",
            "passthrough",
            "flat",
            "hierarchical",
        ):
            sys.exit(
                f"bad config {c}: CPU[-none|passthrough|flat|" "hierarchical]"
            )
        cfg[c] = (cpu, tag)
    binaries, bins_by_abi = {}, {}
    for abi in abis:
        bindir = os.path.join(
            args.builds, f"cheribsd-{abi}", f"clang-cheribsd-{abi}", "bin"
        )
        bins = []
        for wl in workloads:
            src = os.path.join(bindir, f"{wl}.exe")
            dst = os.path.join(out, "bin", f"{abi}-{wl}.exe")
            strip(args.sdk, src, dst)
            bins.append((wl, dst))
            binaries[f"{abi}/{wl}"] = {"path": src, "sha256": sha256(src)}
        bins_by_abi[abi] = bins

    gem5_rev = subprocess.run(
        ["git", "-C", GEM5, "describe", "--always", "--dirty"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    knobs = {k: env[k] for k in ENV_KNOBS if k in env}
    system_files = {}
    for k in ("CHERI_KERNEL", "CHERI_DISK"):
        p = knobs.get(k) or os.path.join(
            GEM5,
            "tests",
            "kernel"
            if k == "CHERI_KERNEL"
            else "cheribsd-riscv64-purecap.img",
        )
        system_files[k] = {"path": os.path.abspath(p)}
        if k == "CHERI_KERNEL" and os.path.exists(p):
            system_files[k]["sha256"] = sha256(p)
    manifest = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gem5_rev": gem5_rev,
        "gem5_binary": os.path.join(GEM5, "build/RISCV_CHERI/gem5.opt"),
        "config": CONFIG,
        "abis": abis,
        "configs": {
            c: {"cpu": cpu, "tag_model": tag} for c, (cpu, tag) in cfg.items()
        },
        "layout": "OUT/<workload>/<abi>-<cpu>/",
        "workloads": workloads,
        "iterations": iterations,
        "workload_args": f"-v0 -c1 -w1 {args.extra_args}".strip(),
        "per_workload_args": wl_args,
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

    # Checkpoints: one per memory layout. With a tag model the board reserves
    # the tag table at the top of DRAM in the device tree, so tag-model runs
    # must restore a guest that booted with that reservation (made with the
    # passthrough model; flat/hierarchical have the same layout).
    ckpts = {}
    if args.checkpoint:
        base = os.path.abspath(args.checkpoint)
        for tagged in sorted({tag != "none" for _, tag in cfg.values()}):
            ckpt = base + ("-tagged" if tagged else "-notag")
            ensure_checkpoint(
                ckpt,
                tagged,
                system_files,
                binaries,
                bins_by_abi,
                out,
                env,
                args.timeout,
            )
            ckpts[tagged] = ckpt
        manifest["checkpoints"] = {}
        for tagged, ckpt in ckpts.items():
            try:
                with open(os.path.join(ckpt, "ckpt_info.json")) as f:
                    info = json.load(f)
            except OSError:
                info = {"checkpoint_tick": checkpoint_tick(ckpt)}
            manifest["checkpoints"]["tagged" if tagged else "notag"] = dict(
                info, path=ckpt
            )
        with open(os.path.join(out, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)

    # One gem5 run per (workload, ABI, config), in OUT/<workload>/<abi>-<config>/.
    # With a checkpoint the guest script only runs the workload (binaries
    # are already in /root/cm/<abi>); without, it unpacks that one binary.
    scripts = {}
    for wl in workloads:
        os.makedirs(os.path.join(out, wl), exist_ok=True)
        for abi in abis:
            path = os.path.join(out, wl, f"job-{abi}.sh")
            if args.checkpoint:
                with open(path, "w") as f:
                    f.write(
                        "\n".join(
                            regions(
                                [wl],
                                iterations,
                                args.extra_args,
                                f"/root/cm/{abi}",
                                wl_args,
                            )
                        )
                        + "\n"
                    )
            else:
                exe = dict(bins_by_abi[abi])[wl]
                make_runner(
                    path, [(wl, exe)], iterations, args.extra_args, wl_args
                )
            scripts[(wl, abi)] = path

    jobs = [(wl, abi, c) for wl in workloads for abi in abis for c in configs]
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = []
        for wl, abi, c in jobs:
            cpu, tag = cfg[c]
            outdir = os.path.join(out, wl, f"{abi}-{c}")
            if args.checkpoint:
                futs.append(
                    pool.submit(
                        run_restored,
                        outdir,
                        cpu,
                        tag,
                        scripts[(wl, abi)],
                        ckpts[tag != "none"],
                        args.timeout,
                        env,
                    )
                )
            else:
                futs.append(
                    pool.submit(
                        run_one,
                        outdir,
                        cpu,
                        tag,
                        scripts[(wl, abi)],
                        args.timeout,
                        env,
                    )
                )
        failed = []
        for fut in cf.as_completed(futs):
            outdir, rc, secs = fut.result()
            status = workload_status(outdir)
            if status != "0":
                failed.append(os.path.relpath(outdir, out))
            print(
                f"{os.path.relpath(outdir, out)}: gem5 exit {rc}, "
                f"workload exit {status}, {secs / 60:.1f} min",
                flush=True,
            )
    if failed:
        print(
            f"\nWARNING: {len(failed)} workload run(s) did not exit 0 "
            "(see their console.log):\n  " + "\n  ".join(sorted(failed)),
            flush=True,
        )
    print(f"next: util/cheri/coremark/parse.py {out}")


if __name__ == "__main__":
    main()
