#!/usr/bin/env python3
"""Boot CheriBSD (single-user) in gem5 and run a test binary non-interactively.

The SBI console reads gem5's stdin, so we drive the shell by watching gem5's
stdout for prompts and writing keystrokes to its stdin.  The test binary is
delivered with `m5 readfile` (the config's `readfile=`).

Usage:
  util/cheri/run_cheribsd_test.py --outdir m5out/t1 --binary path/to/prog \
      [--config configs/example/gem5_library/cheri-riscv-cheribsd-run.py] \
      [--timeout 3600] [--extra-cmd 'echo hi']
"""

import argparse
import os
import re
import select
import subprocess
import sys
import time

SHELL_PROMPT_Q = b"Enter full pathname of shell or RETURN for /bin/sh:"
ROOT_PROMPT = re.compile(rb"(^|\n)# $")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gem5", default="build/RISCV_CHERI/gem5.opt")
    ap.add_argument(
        "--config",
        default="configs/example/gem5_library/cheri-riscv-cheribsd-run.py",
    )
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--args", default="", help="arguments for the binary")
    ap.add_argument("--debug-flags", default=None)
    ap.add_argument("--debug-start", default=None)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    cmd = [args.gem5, "--outdir", args.outdir]
    if args.debug_flags:
        cmd += [
            "--debug-flags",
            args.debug_flags,
            "--debug-file",
            "trace.out.gz",
        ]
    if args.debug_start:
        cmd += ["--debug-start", args.debug_start]
    cmd += [args.config]
    env = dict(os.environ)
    env["CHERI_READFILE"] = os.path.abspath(args.binary)

    log = open(os.path.join(args.outdir, "console.log"), "wb")
    p = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        bufsize=0,
    )

    # Commands to type once the root shell is up.  The root fs may be
    # read-only, so run the binary from a tmpfs.
    script = [
        b"mount -t tmpfs tmpfs /tmp\n",
        b"cd /tmp && /sbin/m5 readfile > t && chmod +x t && echo READY\n",
        ("./t %s; echo EXIT_STATUS=$?\n" % args.args).encode(),
        b"/sbin/m5 exit\n",
    ]

    buf = b""
    stage = 0
    sent = 0
    start = time.time()
    last_send = 0.0
    try:
        while True:
            if time.time() - start > args.timeout:
                print("\n[driver] TIMEOUT", flush=True)
                break
            r, _, _ = select.select([p.stdout], [], [], 1.0)
            if r:
                chunk = os.read(p.stdout.fileno(), 65536)
                if not chunk:
                    break
                log.write(chunk)
                log.flush()
                sys.stdout.buffer.write(chunk)
                sys.stdout.flush()
                buf = (buf + chunk)[-8192:]
            if p.poll() is not None:
                break
            if stage == 0 and SHELL_PROMPT_Q in buf:
                time.sleep(0.5)
                p.stdin.write(b"\n")
                p.stdin.flush()
                stage = 1
                buf = b""
                last_send = time.time()
            elif stage == 1 and sent < len(script):
                if ROOT_PROMPT.search(buf) and time.time() - last_send > 1:
                    p.stdin.write(script[sent])
                    p.stdin.flush()
                    sent += 1
                    buf = b""
                    last_send = time.time()
    finally:
        if p.poll() is None:
            p.kill()
        p.wait()
        log.close()
    print(
        "\n[driver] gem5 exited rc=%s after %.0fs"
        % (p.returncode, time.time() - start),
        flush=True,
    )


if __name__ == "__main__":
    main()
