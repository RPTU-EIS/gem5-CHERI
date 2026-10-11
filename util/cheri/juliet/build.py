#!/usr/bin/env python3
"""Build the Juliet C/C++ test suite for CheriBSD RISC-V (purecap and hybrid)
as static multi-call binaries, for the gem5 CHERI experiments.

Juliet ships one main() per test case (cheribuild builds one executable per
test and variant). Under simulation, creating a process costs far more than
running a test (a dynamically linked exec is ~1 host minute on Atomic), so
here every test's good() and bad() entry points are compiled once (the same
-O0 code as the per-test build, without the test's own main) and linked into
one static binary per shard of tests. The binary forks once per test and
variant and calls the entry point in the child, as the test's main would
(srand(time(NULL)), stdin from the CWE's input file, stdout/stderr to
/dev/null, no core dumps, a SIGALRM timeout), and prints one line per run:

  JL <CWE> <good|bad> <test>-<good|bad> exit N | signal N | timeout

so a fault in one test only ends that child. Static linking also makes the
binaries independent of the disk image's libraries.

Tests that cannot share a binary (class-based C++ tests, whose good and bad
files each define main and the same class) or whose objects clash at link
time are built as separate static executables, one per variant (with the
suite's INCLUDEMAIN/OMITGOOD/OMITBAD), and run by `jrun`.

Usage: util/cheri/juliet/build.py [--src SRC] [--work WORK] [--cwes ...]
         [--shard-size 250] [--jobs N] [--sdk SDK]
Output: WORK/out/<abi>/CWE<n>/s<NN>       multi-call binaries (stripped)
        WORK/out/<abi>/CWE<n>/sep/        separate executables (stripped)
        WORK/out/<abi>/CWE<n>/shards.json tests per shard
        WORK/out/jrun                     launcher for the separate ones
        WORK/build-summary.json/.txt      tests found / built / failed
"""

import argparse
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CWES = [121, 122, 124, 126, 127, 134, 188, 415, 416, 587, 588, 680,
                685, 843]
CFG = {
    "purecap": "cheribsd-riscv64-purecap.cfg",
    "hybrid": "cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg",
}
TEST_RE = re.compile(r"^(CWE\d+_.+__.+_\d\d)")
DISPATCH = r'''
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

@DECLS@

struct jl_test { const char *name; void (*good)(void); void (*bad)(void); };
static const struct jl_test jl_tests[] = {
@TABLE@
};

/* Usage: PROG TIMEOUT_SECONDS INPUT [good|bad|all [N]]
   (default all; N: only the first N tests of each variant) */
int main(int argc, char **argv)
{
    static const char *kinds[] = { "good", "bad" };
    unsigned timeout = argc > 1 ? (unsigned)strtoul(argv[1], NULL, 10) : 1;
    const char *input = argc > 2 ? argv[2] : "/dev/null";
    size_t limit = argc > 4 ? (size_t)strtoul(argv[4], NULL, 10) : 0;
    int ran = 0;

    setvbuf(stdout, NULL, _IOLBF, 0);
    for (int k = 0; k < 2; k++) {
        if (argc > 3 && strcmp(argv[3], "all") != 0 &&
            strcmp(argv[3], kinds[k]) != 0)
            continue;
        for (size_t i = 0; i < sizeof(jl_tests) / sizeof(jl_tests[0]) &&
            (limit == 0 || i < limit); i++) {
            void (*fn)(void) = k == 0 ? jl_tests[i].good : jl_tests[i].bad;
            int status;
            pid_t pid;

            if (fn == NULL)
                continue;
            fflush(stdout);
            pid = fork();
            if (pid < 0) {
                perror("fork");
                return 1;
            }
            if (pid == 0) {
                struct rlimit nocore = { 0, 0 };
                int in = open(input, O_RDONLY);
                int null = open("/dev/null", O_WRONLY);

                setrlimit(RLIMIT_CORE, &nocore);
                if (in >= 0)
                    dup2(in, 0);
                if (null >= 0) {
                    dup2(null, 1);
                    dup2(null, 2);
                }
                alarm(timeout);
                srand((unsigned)time(NULL));
                fn();
                exit(0);
            }
            while (waitpid(pid, &status, 0) < 0)
                ;
            printf("JL @CWE@ %s %s-%s ", kinds[k], jl_tests[i].name, kinds[k]);
            if (WIFSIGNALED(status) && WTERMSIG(status) == SIGALRM)
                printf("timeout\n");
            else if (WIFSIGNALED(status))
                printf("signal %d\n", WTERMSIG(status));
            else
                printf("exit %d\n", WEXITSTATUS(status));
            ran++;
        }
    }
    printf("JL-DONE %d\n", ran);
    return 0;
}
'''


def run(cmd, log):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True)
    if p.returncode != 0:
        log.append(" ".join(cmd) + "\n" + p.stdout)
    return p.returncode == 0


def scan(cwe_dir):
    """{test: {"sources": [...], "class": bool, "main": path}} with
    Windows-only sources left out (as the suite's CMakeLists.txt)."""
    tests = {}
    for root, _, files in os.walk(cwe_dir):
        for f in files:
            if not re.match(r"^CWE.*\.(c|cpp)$", f):
                continue
            if "w32" in f or "wchar_t" in f:
                continue
            m = TEST_RE.match(f)
            if not m:
                continue
            t = tests.setdefault(m.group(1), {"sources": [], "class": False})
            t["sources"].append(os.path.join(root, f))
    for name, t in tests.items():
        t["sources"].sort()
        t["class"] = any(s.endswith(name + "_good1.cpp")
                         for s in t["sources"])
    return tests


def entry_points(test, t):
    """(good, bad) entry expressions from the test's own main(), each None
    if that variant does not exist; plus "c" or "cpp"."""
    for src in t["sources"]:
        text = open(src, errors="replace").read()
        i = text.find("#ifdef INCLUDEMAIN")
        if i < 0 or "main(" not in text[i:]:
            continue
        body = text[i:]
        lang = "cpp" if src.endswith(".cpp") else "c"
        ns = re.search(r"using namespace (\w+);", body)

        def call(guard):
            m = re.search(r"#ifndef " + guard + r"(.*?)#endif", body, re.S)
            if not m:
                return None
            c = re.search(r"(\w+)\s*\(\s*\)\s*;\s*\n\s*printLine\(\"Finished",
                          m.group(1))
            if not c:
                return None
            fn = c.group(1)
            if lang == "cpp" and ns and fn in ("good", "bad"):
                return f"{ns.group(1)}::{fn}"
            return fn
        return call("OMITGOOD"), call("OMITBAD"), lang
    return None, None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=os.path.expanduser(
        "~/hiwi/juliet-test-suite-c"))
    ap.add_argument("--work", default=os.path.expanduser("~/hiwi/juliet-gem5"))
    ap.add_argument("--cwes", default=",".join(map(str, DEFAULT_CWES)))
    ap.add_argument("--abis", default="purecap,hybrid")
    ap.add_argument("--shard-size", type=int, default=250)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--sdk", default=os.environ.get(
        "CHERI_SDK", os.path.expanduser("~/cheri/output/sdk")))
    args = ap.parse_args()

    sdk = args.sdk
    cc, cxx = os.path.join(sdk, "bin", "clang"), os.path.join(sdk, "bin",
                                                              "clang++")
    strip = os.path.join(sdk, "bin", "llvm-strip")
    support = os.path.join(args.src, "testcasesupport")
    work = os.path.abspath(args.work)
    outroot = os.path.join(work, "out")
    os.makedirs(outroot, exist_ok=True)
    cwes = [int(c.removeprefix("CWE")) for c in args.cwes.split(",")]
    cwe_dirs = {}
    for c in cwes:
        d = [x for x in os.listdir(os.path.join(args.src, "testcases"))
             if re.match(rf"CWE{c}_", x)]
        if not d:
            sys.exit(f"no testcases for CWE{c}")
        cwe_dirs[c] = os.path.join(args.src, "testcases", d[0])

    summary = {}
    pool = cf.ThreadPoolExecutor(max_workers=args.jobs)
    for abi in args.abis.split(","):
        cfg = ["--config", CFG[abi]]
        for c in cwes:
            extra = ["-cheri-bounds=subobject-safe"] if (
                c == 188 and abi == "purecap") else []
            flags = cfg + extra + ["-O0", "-g", "-w", "-I", support]
            bdir = os.path.join(work, "build", abi, f"CWE{c}")
            odir = os.path.join(outroot, abi, f"CWE{c}")
            shutil.rmtree(bdir, ignore_errors=True)
            shutil.rmtree(odir, ignore_errors=True)
            os.makedirs(os.path.join(bdir, "obj"))
            os.makedirs(os.path.join(odir, "sep"))
            log = []
            tests = scan(cwe_dirs[c])

            # Support library objects (as the suite's `support` library).
            sup = []
            for s in ("io.c", "std_thread.c"):
                o = os.path.join(bdir, s + ".o")
                if not run([cc] + flags + ["-c", os.path.join(support, s),
                                           "-o", o], log):
                    sys.exit("\n".join(log))
                sup.append(o)

            # Separate executables: class-based tests (and, below, any test
            # that fails in a multi-call binary).
            def build_sep(name, t):
                ok = {}
                for kind, omit in (("good", "OMITBAD"), ("bad", "OMITGOOD")):
                    if t["class"]:
                        srcs = [s for s in t["sources"] if s.endswith(
                            "_good1.cpp" if kind == "good" else "_bad.cpp")]
                    else:
                        srcs = t["sources"]
                    exe = os.path.join(bdir, "sep", f"{name}-{kind}")
                    os.makedirs(os.path.dirname(exe), exist_ok=True)
                    comp = cxx if any(s.endswith(".cpp") for s in srcs) else cc
                    if srcs and run([comp] + flags + [
                            "-static", "-DINCLUDEMAIN", "-D" + omit] + srcs
                            + sup + ["-o", exe, "-lpthread", "-lm"], log):
                        dst = os.path.join(odir, "sep", f"{name}-{kind}")
                        run([strip, "-o", dst, exe], log)
                        ok[kind] = True
                return name, ok

            # Multi-call: compile every source once (both variants, no main).
            def compile_test(name, t):
                objs = []
                for s in t["sources"]:
                    o = os.path.join(bdir, "obj",
                                     os.path.basename(s) + ".o")
                    comp = cxx if s.endswith(".cpp") else cc
                    if not run([comp] + flags + ["-c", s, "-o", o], log):
                        return name, None
                    objs.append(o)
                return name, objs

            multi = {n: t for n, t in tests.items() if not t["class"]}
            entries, objs = {}, {}
            for n, t in multi.items():
                g, b, lang = entry_points(n, t)
                if g is None and b is None:
                    log.append(f"{n}: no entry points found in its main()")
                    continue
                entries[n] = (g, b, lang)
            for n, o in pool.map(lambda kv: compile_test(*kv),
                                 [(n, multi[n]) for n in sorted(entries)]):
                if o is not None:
                    objs[n] = o
            names = sorted(objs)
            shards, sep_tests = [], [n for n, t in tests.items()
                                     if t["class"]]

            def link_shard(idx, members, tag=None):
                """Link one multi-call binary; `tag` names a trial link
                (parallel trials must not share files)."""
                base = tag or f"s{idx:02d}"
                decls, table = [], []
                for n in members:
                    g, b, lang = entries[n]
                    for fn in (g, b):
                        if fn is None:
                            continue
                        if lang == "c":
                            decls.append(f'extern "C" void {fn}(void);')
                        else:
                            ns, f = fn.split("::")
                            decls.append(f"namespace {ns} {{ void {f}(); }}")
                    table.append('    {"%s", %s, %s},' % (
                        n, g or "NULL", b or "NULL"))
                src = os.path.join(bdir, base + ".cpp")
                with open(src, "w") as f:
                    f.write(DISPATCH.replace("@DECLS@", "\n".join(decls))
                            .replace("@TABLE@", "\n".join(table))
                            .replace("@CWE@", f"CWE{c}"))
                exe = os.path.join(bdir, base)
                lg = []
                ok = run([cxx] + flags + ["-static", src] +
                         [o for n in members for o in objs[n]] + sup +
                         ["-o", exe, "-lpthread", "-lm"], lg)
                return idx, members, exe, ok, "".join(lg)

            # Link shards; a shard that fails to link (clashing symbols) is
            # split into halves until the culprits are isolated, and those
            # go to separate executables.
            pending = [names[i:i + args.shard_size]
                       for i in range(0, len(names), args.shard_size)]
            good_groups = []
            trial = 0
            while pending:
                trials = [(m, f"trial{trial + i}") for i, m in
                          enumerate(pending)]
                trial += len(trials)
                results = list(pool.map(
                    lambda mt: link_shard(0, mt[0], mt[1]), trials))
                pending = []
                for _, members, _, ok, lg in results:
                    if ok:
                        good_groups.append(members)
                    elif len(members) == 1:
                        log.append(lg)
                        sep_tests.append(members[0])
                    else:
                        h = len(members) // 2
                        pending += [members[:h], members[h:]]
            good_groups.sort()
            # Re-pack the linkable groups into shards in name order.
            flat = sorted(n for g in good_groups for n in g)
            groups = [flat[i:i + args.shard_size]
                      for i in range(0, len(flat), args.shard_size)]
            for idx, members, exe, ok, lg in pool.map(
                    lambda im: link_shard(*im), list(enumerate(groups))):
                if not ok:  # members linked before, so should not happen
                    log.append(lg)
                    sep_tests += members
                    continue
                run([strip, "-o", os.path.join(odir, f"s{idx:02d}"), exe],
                    log)
                shards.append({
                    "shard": f"s{idx:02d}",
                    "tests": members,
                    "good": [n for n in members if entries[n][0]],
                    "bad": [n for n in members if entries[n][1]],
                })
            seps = dict(pool.map(lambda n: build_sep(n, tests[n]),
                                 sorted(set(sep_tests))))
            separate = {n: sorted(k) for n, k in seps.items() if k}
            with open(os.path.join(odir, "shards.json"), "w") as f:
                json.dump({"cwe": c, "abi": abi, "shards": shards,
                           "separate": separate}, f, indent=1)
            with open(os.path.join(work, "build", abi, f"CWE{c}.log"),
                      "w") as f:
                f.write("\n".join(log))
            built = sum(len(s["tests"]) for s in shards) + len(separate)
            summary[f"{abi}/CWE{c}"] = {
                "tests": len(tests),
                "built": built,
                "multi_call": sum(len(s["tests"]) for s in shards),
                "separate": len(separate),
                "failed": sorted(set(tests) - {n for s in shards
                                               for n in s["tests"]}
                                 - set(separate)),
                "shards": len(shards),
            }
            print(f"{abi} CWE{c}: {len(tests)} tests, {built} built "
                  f"({len(separate)} separate), {len(shards)} shards",
                  flush=True)

    jr = os.path.join(outroot, "jrun")
    if not run([cc, "--config", CFG["purecap"], "-O2", "-static", "-o", jr,
                os.path.join(HERE, "jrun.c")], log := []):
        sys.exit("\n".join(log))
    run([strip, jr], log)
    with open(os.path.join(work, "build-summary.json"), "w") as f:
        json.dump({"sdk": sdk, "src": os.path.abspath(args.src),
                   "shard_size": args.shard_size, "cwes": summary}, f,
                  indent=1)
    with open(os.path.join(work, "build-summary.txt"), "w") as f:
        for k, v in summary.items():
            f.write(f"{k} tests={v['tests']} built={v['built']} "
                    f"separate={v['separate']} failed={len(v['failed'])}\n")
    print(f"built: {outroot} (summary: {work}/build-summary.txt)")


if __name__ == "__main__":
    main()
