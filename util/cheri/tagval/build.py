#!/usr/bin/env python3
"""Build the tag-validation workloads for CheriBSD RISC-V (plain, purecap).

The programs Joannou et al. ("Efficient Tagged Memory", ICCD 2017) used to
characterise tag-table caching, so that gem5-CHERI's tag model can be
compared with theirs on the same software:

  MiBench (their FPGA study, Fig. 9): qsort, jpeg, dijkstra, sha, crc32,
    fft, from CHERI's llvm-test-suite fork with its "large" inputs;
  Octane under Duktape (their FPGA study, Fig. 9; Earley-Boyer is also
    their pointer-heavy trace case, Figs. 2, 3, 7): earley-boyer and
    splay, the JavaScript compiled into a small Duktape driver
    (duk_octane.c), so the binary needs no files;
  FFmpeg (their pointer-sparse trace case, Figs. 2, 7): build_ffmpeg.sh,
    then this script with --ffmpeg adds it.

Same layout as util/cheri/olden/build.py (WORK/builds/<abi>/bin[-stripped],
WORK/workloads.json), so util/cheri/olden/run.py runs them (see
run_all.sh). Input files go to WORK/data/<workload>/ and travel in each
run's payload; the workload runs in that directory. Both ABIs use the same
CHERI LLVM and flags as Olden (-O2 -static); plain is RV64 without CHERI
plus util/cheri/common/memcpy64.c.

Usage: util/cheri/tagval/build.py [--src DIR] [--work DIR] [--sdk DIR]
         [--abis plain,purecap] [--only NAME,...] [--ffmpeg FFMPEG_WORK]
  --src  directory with llvm-test-suite/ (CHERI fork, MiBench sparse
         checkout), octane/ and duktape-2.7.0/ (default ~/hiwi/tagval-src)
  --work default ~/hiwi/tagval-gem5
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = {
    "purecap": "cheribsd-riscv64-purecap.cfg",
    "hybrid": "cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg",
    "plain": "cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg",
}
ABI_FLAGS = {"purecap": [], "hybrid": [], "plain": ["-march=rv64imafdc"]}
COMMON = ["-O2", "-w"]
MIBENCH_DIR = "llvm-test-suite/MultiSource/Benchmarks/MiBench"
# name: (directory, sources or None for every .c, arguments, input files,
#        extra cflags); arguments and inputs as the test suite's CMakeLists
MIBENCH = {
    "qsort": ("automotive-qsort", ["qsort_large.c"], "input_large.dat",
              ["input_large.dat"], []),
    "jpeg": ("consumer-jpeg", None,
             "-dct int -ppm -outfile /dev/null input_large.jpg",
             ["input_large.jpg"], []),
    "dijkstra": ("network-dijkstra", ["dijkstra.c"], "input.dat large",
                 ["input.dat"], []),
    "sha": ("security-sha", ["sha.c", "sha_driver.c"], "input_large.asc",
            ["input_large.asc"], []),
    "crc32": ("telecomm-CRC32", ["crc_32.c"], "large.pcm", ["large.pcm"],
              ["-Wno-implicit-int"]),
    "fft": ("telecomm-FFT", ["fftmisc.c", "fourierf.c", "main.c"],
            "8 32768 -i", [], ["-DFP_ABSTOLERANCE=1e-5"]),
}
# name: (Octane files, iterations); one iteration runs every benchmark of
# the suite once (Earley-Boyer: Earley and Boyer). Under Duktape one
# iteration is already ~4-6 G instructions (QEMU icount); pdfjs (~32 G) and
# gbemu (~21 G) are too long for detailed simulation and left out.
OCTANE = {
    "earley-boyer": (["earley-boyer.js"], 1),
    "splay": (["splay.js"], 1),
}
# (file, old text, new text): see the Duktape step in main()
DUKTAPE_PATCHES = [
    ("duk_config.h", "#define DUK_USE_EXEC_REGCONST_OPTIMIZE\n",
     "#undef DUK_USE_EXEC_REGCONST_OPTIMIZE\n"),
    ("duktape.c",
     "\ttv_prev_alloc_end = (duk_tval *) (void *) ((duk_uint8_t *) "
     "thr->valstack_alloc_end + ptr_diff);\n"
     "\tthr->valstack = new_valstack;\n"
     "\tthr->valstack_bottom = (duk_tval *) (void *) ((duk_uint8_t *) "
     "thr->valstack_bottom + ptr_diff);\n"
     "\tthr->valstack_top = (duk_tval *) (void *) ((duk_uint8_t *) "
     "thr->valstack_top + ptr_diff);\n"
     "\tthr->valstack_end = (duk_tval *) (void *) ((duk_uint8_t *) "
     "thr->valstack_end + ptr_diff);\n",
     "\t(void) ptr_diff;\n"
     "#define DUK__REBASE(p) ((duk_tval *) (void *) ((duk_uint8_t *) "
     "new_valstack + ((duk_uint8_t *) (p) - (duk_uint8_t *) "
     "thr->valstack)))\n"
     "\ttv_prev_alloc_end = DUK__REBASE(thr->valstack_alloc_end);\n"
     "\tthr->valstack_bottom = DUK__REBASE(thr->valstack_bottom);\n"
     "\tthr->valstack_top = DUK__REBASE(thr->valstack_top);\n"
     "\tthr->valstack_end = DUK__REBASE(thr->valstack_end);\n"
     "\tthr->valstack = new_valstack;\n"
     "#undef DUK__REBASE\n"),
    # object layout 2 pads the 1-byte entry flags only to 8 bytes before
    # the array part, whose duk_tvals hold capabilities (misaligned
    # capability store, SIGBUS): pad to 16 in purecap
    ("duktape.c",
     "#elif (DUK_USE_ALIGN_BY == 8)\n"
     "#define DUK_HOBJECT_E_FLAG_PADDING(e_sz) ((8 - (e_sz)) & 0x07)\n",
     "#elif (DUK_USE_ALIGN_BY == 8) && defined(__CHERI_PURE_CAPABILITY__)\n"
     "#define DUK_HOBJECT_E_FLAG_PADDING(e_sz) ((16 - (e_sz)) & 0x0f)\n"
     "#elif (DUK_USE_ALIGN_BY == 8)\n"
     "#define DUK_HOBJECT_E_FLAG_PADDING(e_sz) ((8 - (e_sz)) & 0x07)\n"),
]


def run(cmd, **kw):
    p = subprocess.run(cmd, **kw)
    if p.returncode != 0:
        sys.exit(f"failed: {' '.join(cmd)}")
    return p


def c_array_header(path, name, data):
    """Write data as a C byte array (no host tools needed)."""
    with open(path, "w") as f:
        f.write(f"static const unsigned char {name}[] = {{\n")
        for i in range(0, len(data), 16):
            f.write(",".join(str(b) for b in data[i:i + 16]) + ",\n")
        f.write("};\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=os.path.expanduser("~/hiwi/tagval-src"))
    ap.add_argument("--work", default=os.path.expanduser("~/hiwi/tagval-gem5"))
    ap.add_argument("--sdk", default=os.environ.get(
        "CHERI_SDK", os.path.expanduser("~/cheri/output/sdk")))
    ap.add_argument("--abis", default="plain,purecap")
    ap.add_argument("--only", default=None, help="comma list of workloads")
    ap.add_argument("--ffmpeg", default=None,
                    help="build_ffmpeg.sh work dir: add its ffmpeg binaries")
    args = ap.parse_args()
    abis = args.abis.split(",")
    only = set(args.only.split(",")) if args.only else None
    src, work = os.path.abspath(args.src), os.path.abspath(args.work)
    cc = os.path.join(args.sdk, "bin", "clang")
    strip = os.path.join(args.sdk, "bin", "llvm-strip")
    os.makedirs(work, exist_ok=True)

    info = {}
    wl_json = os.path.join(work, "workloads.json")
    if os.path.exists(wl_json):
        with open(wl_json) as f:
            info = json.load(f).get("workloads", {})

    memcpy64 = os.path.join(work, "memcpy64.o")
    if "plain" in abis:
        run([cc, "--config", CFG["plain"]] + ABI_FLAGS["plain"] +
            ["-O2", "-fno-builtin", "-c", "-o", memcpy64,
             os.path.join(HERE, "..", "common", "memcpy64.c")])

    def link(abi, name, cmd_tail):
        bindir = os.path.join(work, "builds", abi, "bin")
        sdir = os.path.join(work, "builds", abi, "bin-stripped")
        os.makedirs(bindir, exist_ok=True)
        os.makedirs(sdir, exist_ok=True)
        exe = os.path.join(bindir, name)
        extra = [memcpy64] if abi == "plain" else []
        run([cc, "--config", CFG[abi], "-static"] + ABI_FLAGS[abi] +
            cmd_tail + extra + ["-o", exe, "-lm"])
        run([strip, "-o", os.path.join(sdir, name), exe])

    def stage_inputs(name, d, files):
        ddir = os.path.join(work, "data", name)
        os.makedirs(ddir, exist_ok=True)
        for fn in files:
            shutil.copyfile(os.path.join(d, fn), os.path.join(ddir, fn))
        return [os.path.join("data", name, fn) for fn in files]

    for name, (sub, sources, wargs, files, cflags) in MIBENCH.items():
        if only and name not in only:
            continue
        d = os.path.join(src, MIBENCH_DIR, sub)
        srcs = sorted(sources or [f for f in os.listdir(d)
                                  if f.endswith(".c")])
        for abi in abis:
            link(abi, name, COMMON + cflags + [os.path.join(d, s)
                                               for s in srcs])
        info[name] = {"args": wargs, "files": stage_inputs(name, d, files),
                      "family": "mibench", "src": os.path.join(MIBENCH_DIR,
                                                               sub),
                      "sources": srcs, "cflags": COMMON + cflags}
        print(f"{name}: built ({', '.join(abis)})", flush=True)

    # Duktape, patched for purecap (both ABIs build the same source):
    # - config: no DUK_USE_EXEC_REGCONST_OPTIMIZE, which needs an 8- or
    #   16-byte duk_tval; purecap's 16-byte pointers make it 32 (fatal);
    # - duk__resize_valstack moved its pointers to the realloc'd value
    #   stack by adding the distance between the allocations, which keeps
    #   the old allocation's bounds (tag fault); rebase them on the new one;
    # - object property layout: 16-byte padding before the array part.
    gen = os.path.join(work, "gen")
    duk = os.path.join(gen, "duktape-src")
    shutil.rmtree(duk, ignore_errors=True)
    shutil.copytree(os.path.join(src, "duktape-2.7.0", "src"), duk)
    for fn, old, new in DUKTAPE_PATCHES:
        path = os.path.join(duk, fn)
        with open(path) as f:
            text = f.read()
        if text.count(old) != 1:
            sys.exit(f"{path}: patch context not found exactly once")
        with open(path, "w") as f:
            f.write(text.replace(old, new))
    for name, (jsfiles, iters) in OCTANE.items():
        if only and name not in only:
            continue
        hdir = os.path.join(gen, name)
        os.makedirs(hdir, exist_ok=True)
        js = b"".join(open(os.path.join(src, "octane", f), "rb").read()
                      + b"\n" for f in ["base.js"] + jsfiles)
        js += open(os.path.join(HERE, "octane_runner.js"), "rb").read()
        c_array_header(os.path.join(hdir, "octane_js.h"), "octane_js", js)
        for abi in abis:
            link(abi, name, COMMON + ["-I" + duk, "-I" + hdir,
                                      os.path.join(HERE, "duk_octane.c"),
                                      os.path.join(duk, "duktape.c")])
        info[name] = {"args": str(iters), "files": [], "family": "octane",
                      "src": ["octane/base.js"] + ["octane/" + f
                                                   for f in jsfiles],
                      "engine": "duktape-2.7.0 (no "
                      "DUK_USE_EXEC_REGCONST_OPTIMIZE)", "cflags": COMMON}
        print(f"{name}: built ({', '.join(abis)})", flush=True)

    if args.ffmpeg:
        fw = os.path.abspath(args.ffmpeg)
        for abi in abis:
            exe = os.path.join(fw, abi, "ffmpeg")
            if not os.path.exists(exe):
                sys.exit(f"missing {exe} (run build_ffmpeg.sh)")
            for sub, tool in (("bin", None), ("bin-stripped", strip)):
                d = os.path.join(work, "builds", abi, sub)
                os.makedirs(d, exist_ok=True)
                if tool:
                    run([tool, "-o", os.path.join(d, "ffmpeg"), exe])
                else:
                    shutil.copyfile(exe, os.path.join(d, "ffmpeg"))
                os.chmod(os.path.join(d, "ffmpeg"), 0o755)
        # MPEG-4 encoding of a generated test pattern: no input file, and
        # the md5 muxer prints a digest that must match across ABIs
        info["ffmpeg"] = {
            "args": "-nostdin -hide_banner -loglevel error -threads 1 "
                    "-f lavfi -i testsrc=size=1280x720:rate=25:duration=0.4 "
                    "-c:v mpeg4 -q:v 4 -bitexact -f md5 -",
            "files": [], "family": "ffmpeg", "src": fw}
        print(f"ffmpeg: added ({', '.join(abis)})", flush=True)

    built = sorted(a for a in CFG
                   if os.path.isdir(os.path.join(work, "builds", a, "bin")))
    with open(wl_json, "w") as f:
        json.dump({"src": src, "sdk": args.sdk, "abis": built,
                   "abi_flags": ABI_FLAGS, "workloads": info}, f, indent=2)
    print(f"built: {work}/builds (arguments: {wl_json})")


if __name__ == "__main__":
    main()
