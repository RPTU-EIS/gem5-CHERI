#!/usr/bin/env python3
"""Run a shell script in CheriBSD on CHERI-QEMU (fast functional check).

Boots the kernel and disk image (-snapshot: not modified) in single-user
mode, attaches an optional payload as a second virtio disk (a tar file;
the guest unpacks it with `tar xf /dev/vtbd1 -C /tmp/payload`), types the
script into the console, runs it in /tmp/payload and logs the console until
it finishes. With --icount, QEMU runs one instruction per guest nanosecond,
so guest-side `time` gives approximate instruction counts (kernel included).

Usage: util/cheri/qemu_job.py --script JOB.sh --log CONSOLE.log
         [--payload DIR] [--icount] [--timeout 7200]
Environment: CHERI_KERNEL, CHERI_DISK (2026 defaults as cheribsdtest/run.py),
  QEMU, QEMU_BIOS (as cheribsdtest/run_qemu.py)
"""

import argparse
import os
import select
import subprocess
import sys
import tarfile
import tempfile
import time

GEM5 = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULTS = {
    "CHERI_KERNEL": os.path.join(GEM5, "tests", "kernel-2026-nodebug"),
    "CHERI_DISK": os.path.join(GEM5, "tests",
                               "cheribsd-2026-riscv64-purecap.img"),
    "QEMU": os.path.expanduser(
        "~/cheri/build/qemu-build/qemu-system-riscv64xcheri"),
    "QEMU_BIOS": os.path.expanduser(
        "~/cheri/output/sdk/share/qemu/bbl-riscv64cheri-virt-fw_jump.bin"),
}
# only the start: kernel messages can land inside the rest of the prompt
SHELL_PROMPT_Q = b"Enter full pathname of shell"
DONE = b"=== QEMU-JOB-DONE"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--script", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--payload", help="directory to ship as a tar disk")
    ap.add_argument("--icount", action="store_true")
    ap.add_argument("--timeout", type=int, default=7200)
    args = ap.parse_args()
    env = {k: os.environ.get(k, v) for k, v in DEFAULTS.items()}
    for k, v in env.items():
        if not os.path.exists(v):
            sys.exit(f"missing {k}={v}")

    cmd = [env["QEMU"], "-M", "virt", "-cpu", "rv64,sstc=off", "-m", "2048",
           "-nographic", "-bios", env["QEMU_BIOS"],
           "-kernel", env["CHERI_KERNEL"], "-append", "-s", "-snapshot",
           "-drive", f"if=none,file={env['CHERI_DISK']},id=drv,format=raw",
           "-device", "virtio-blk-device,drive=drv"]
    if args.icount:
        cmd += ["-icount", "shift=0"]
    tmp = None
    if args.payload:
        tmp = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
        with tarfile.open(fileobj=tmp, mode="w") as tar:
            tar.add(args.payload, arcname=".")
        tmp.write(b"\0" * (-tmp.tell() % 512))  # whole sectors
        tmp.close()
        cmd += ["-drive", f"if=none,file={tmp.name},id=pl,format=raw",
                "-device", "virtio-blk-device,drive=pl"]
    with open(args.script) as f:
        script = [ln.rstrip("\n") for ln in f]

    log = open(args.log, "wb")
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, bufsize=0)
    buf, stage, t0 = b"", 0, time.time()

    def send(text):
        p.stdin.write(text.encode())
        p.stdin.flush()

    try:
        while time.time() - t0 < args.timeout and p.poll() is None:
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
                send("mount -t tmpfs tmpfs /tmp && mkdir /tmp/payload\n")
                time.sleep(1)
                if args.payload:
                    send("tar xf /dev/vtbd1 -C /tmp/payload\n")
                    time.sleep(2)
                send("cat > /tmp/job.sh <<'QJ_EOF'\n")
                for ln in script:
                    send(ln + "\n")
                    time.sleep(0.05)
                send("QJ_EOF\n")
                time.sleep(1)
                send("cd /tmp/payload && sh /tmp/job.sh; "
                     "echo '=== QEMU-JOB-DONE'\n")
                stage, buf = 2, b""
            elif stage == 2 and b"\n" + DONE in buf.replace(b"\r", b""):
                break
    finally:
        if p.poll() is None:
            p.kill()
        p.wait()
        log.close()
        if tmp:
            os.unlink(tmp.name)
    print(f"{args.log}: {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
