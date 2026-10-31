#!/usr/bin/env python3
"""Reference run of cheribsdtest on CHERI-QEMU, for comparison with gem5.

Boots the same kernel and disk image in QEMU (riscv64xcheri, cheribuild's
BBL firmware, -snapshot: the image is not modified) in single-user mode,
types run.py's job (without the m5 operations) into the console and keeps
the console in OUT/<variant>-qemu/console.log, which parse.py reads like a
gem5 run. Pass parse.py --ref OUT/results.csv when parsing the gem5 runs.

Usage:
  util/cheri/cheribsdtest/run_qemu.py --out RESULTS/cheribsdtest/qemu \\
      [--variants purecap,hybrid | all] [--jobs 2] [--test-timeout 60]
Environment: CHERI_KERNEL, CHERI_DISK as run.py; QEMU (default
  ~/cheri/build/qemu-build/qemu-system-riscv64xcheri), QEMU_BIOS (default
  ~/cheri/output/sdk/share/qemu/bbl-riscv64cheri-virt-fw_jump.bin)
"""

import argparse
import concurrent.futures as cf
import importlib.util
import os
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "cbt_run", os.path.join(HERE, "run.py"))
cbt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cbt)

# only the start: kernel messages can land inside the rest of the prompt
SHELL_PROMPT_Q = b"Enter full pathname of shell"
DONE = b"=== QEMU-JOB-DONE"


def run_variant(out, variant, test_timeout, timeout, env):
    outdir = os.path.join(out, f"{variant}-qemu")
    os.makedirs(outdir, exist_ok=True)
    job = [ln for ln in cbt.job(variant, test_timeout, None)[1:]
           if "/sbin/m5" not in ln]
    # sstc off: the BBL firmware does not enable S-mode stimecmp, so the
    # kernel must use the SBI timer (as on gem5)
    cmd = [env["QEMU"], "-M", "virt", "-cpu", "rv64,sstc=off",
           "-m", "2048", "-nographic",
           "-bios", env["QEMU_BIOS"], "-kernel", env["CHERI_KERNEL"],
           "-append", "-s", "-snapshot",
           "-drive", f"if=none,file={env['CHERI_DISK']},id=drv,format=raw",
           "-device", "virtio-blk-device,drive=drv"]
    with open(os.path.join(outdir, "command.txt"), "w") as f:
        f.write(" ".join(cmd) + "\n")
    log = open(os.path.join(outdir, "console.log"), "wb")
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, bufsize=0)
    buf, stage, t0 = b"", 0, time.time()

    def send(text):
        p.stdin.write(text.encode())
        p.stdin.flush()

    try:
        while time.time() - t0 < timeout and p.poll() is None:
            r, _, _ = select.select([p.stdout], [], [], 1.0)
            if not r:
                continue
            chunk = os.read(p.stdout.fileno(), 65536)
            if not chunk:
                break
            log.write(chunk)
            log.flush()
            buf = (buf + chunk)[-8192:]
            if stage == 0 and SHELL_PROMPT_Q in buf:
                time.sleep(0.5)
                send("\n")
                stage, buf = 1, b""
            elif stage == 1 and buf.endswith(b"# "):
                # write the job to a tmpfs and run it
                send("mount -t tmpfs tmpfs /tmp\n")
                time.sleep(1)
                send("cat > /tmp/job.sh <<'CBT_EOF'\n")
                for ln in job:
                    send(ln + "\n")
                    time.sleep(0.05)
                send("CBT_EOF\n")
                time.sleep(1)
                send("sh /tmp/job.sh; echo '=== QEMU-JOB-DONE'\n")
                stage, buf = 2, b""
            elif stage == 2 and b"\n" + DONE in buf.replace(b"\r", b""):
                break  # the marker at a line start: not the echoed command
    finally:
        if p.poll() is None:
            p.kill()
        p.wait()
        log.close()
    return outdir, time.time() - t0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--variants", default="purecap,hybrid")
    ap.add_argument("--test-timeout", type=int, default=60)
    ap.add_argument("--timeout", type=int, default=6 * 3600,
                    help="host seconds per QEMU run")
    ap.add_argument("--jobs", type=int, default=2)
    args = ap.parse_args()
    variants = (cbt.VARIANTS if args.variants == "all"
                else args.variants.split(","))
    env = dict(os.environ)
    for k, v in cbt.SYSTEM_DEFAULTS.items():
        env.setdefault(k, v)
    env.setdefault("QEMU", os.path.expanduser(
        "~/cheri/build/qemu-build/qemu-system-riscv64xcheri"))
    env.setdefault("QEMU_BIOS", os.path.expanduser(
        "~/cheri/output/sdk/share/qemu/bbl-riscv64cheri-virt-fw_jump.bin"))
    for k in ("QEMU", "QEMU_BIOS", "CHERI_KERNEL", "CHERI_DISK"):
        if not os.path.exists(env[k]):
            sys.exit(f"missing {k}={env[k]}")
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(run_variant, out, v, args.test_timeout,
                            args.timeout, env) for v in variants]
        for fut in cf.as_completed(futs):
            outdir, secs = fut.result()
            print(f"{os.path.basename(outdir)}: {secs / 60:.1f} min",
                  flush=True)
    print(f"next: util/cheri/cheribsdtest/parse.py {out}")


if __name__ == "__main__":
    main()
