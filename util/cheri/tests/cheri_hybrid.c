/*
 * Hybrid (integer-pointer mode) tests for the gem5 CHERI-RISC-V model.
 *
 * Built as a plain RV64 program (no capability mode), so the CPU runs it in
 * integer encoding mode: ordinary loads/stores are authorised by DDC,
 * jal/jalr/auipc produce integers, and the compressed encodings that are
 * capability loads in capability mode are FP loads (c.fld/c.fsd/...).
 * __capability pointers use the explicit .cap instructions.
 *
 * Each test runs in a forked child, as in cheri_faults.c.
 *
 * Build (hybrid, static):
 *   ~/cheri/output/sdk/bin/clang \
 *       --config cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg \
 *       -O2 -static -o cheri_hybrid cheri_hybrid.c
 * Run all tests, or name some: ./cheri_hybrid [test...]
 */
#include <cheriintrin.h>
#include <signal.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef SIGPROT
#define SIGPROT 34
#endif
#ifndef PROT_CHERI_BOUNDS
#define PROT_CHERI_BOUNDS 1
#define PROT_CHERI_TAG 2
#endif

#define NOFAULT (-1)
#define ANYCODE (-2)

static volatile int exp_sig, exp_code, exp_capreg;
static volatile int alt_sig;    /* also accepted (kernel policy), 0: none */
static const char *volatile cur_name;

static void
report(const char *fmt, ...)
{
        char buf[256];
        va_list ap;
        int n;

        va_start(ap, fmt);
        n = vsnprintf(buf, sizeof(buf), fmt, ap);
        va_end(ap);
        if (n > 0)
                write(1, buf, (size_t)n);
}

static void
handler(int sig, siginfo_t *si, void *uc)
{
        int ok = (sig == exp_sig &&
            (exp_code == ANYCODE || si->si_code == exp_code) &&
            (exp_capreg < 0 || si->si_capreg == exp_capreg)) ||
            (alt_sig != 0 && sig == alt_sig);

        (void)uc;
        report("%-26s %s  got sig=%d code=%d capreg=%d  (want sig=%d code=%d"
            " capreg=%d)\n", cur_name, ok ? "PASS" : "FAIL", sig, si->si_code,
            si->si_capreg, exp_sig, exp_code, exp_capreg);
        _exit(ok ? 0 : 1);
}

static void
fail(const char *what)
{
        report("%-26s FAIL  %s\n", cur_name, what);
        _exit(1);
}

/* ---- integer-mode execution: results must be right ---- */

static int __attribute__((noinline))
fib(int n)
{
        return (n < 2 ? n : fib(n - 1) + fib(n - 2));
}

typedef long (*op_t)(long, long);
static long __attribute__((noinline)) op_add(long a, long b) { return a + b; }
static long __attribute__((noinline)) op_mul(long a, long b) { return a * b; }
static long __attribute__((noinline)) op_sub(long a, long b) { return a - b; }
static op_t volatile ops[] = { op_add, op_mul, op_sub };

static double vec[64];

static double __attribute__((noinline))
dot(const double *a, const double *b, int n)
{
        double s = 0;

        for (int i = 0; i < n; i++)
                s += a[i] * b[i];
        return (s);
}

static void
t_nofault_compute(void)
{
        /* jal/jalr (integer links), auipc (globals), function pointers. */
        if (fib(20) != 6765)
                fail("fib(20) != 6765");
        if (ops[0](3, 4) != 7 || ops[1](3, 4) != 12 || ops[2](3, 4) != -1)
                fail("function-pointer calls");
        /* Doubles: c.fld/c.fsd/c.fldsp/c.fsdsp in integer mode. */
        for (int i = 0; i < 64; i++)
                vec[i] = i * 0.5;
        if (dot(vec, vec, 64) != 0.25 * (63.0 * 64 * 127 / 6))
                fail("double dot product");
}

static void
t_nofault_cap_roundtrip(void)
{
        /* lc/sc on an integer address are DDC-relative and keep tags. */
        static char buf[32];
        static char *__capability slot[2];
        char *__capability c = (__cheri_tocap char *__capability)buf;

        slot[1] = c;
        if (!cheri_tag_get(slot[1]))
                fail("tag lost through DDC-relative sc/lc");
        if (cheri_address_get(slot[1]) != (ptraddr_t)buf)
                fail("address changed through sc/lc");
}

static void
t_nofault_ddc_asm(void)
{
        /* Explicit .ddc forms. */
        static volatile long word = 0x1234567890abcdefL;
        long v, nv = 42;

        __asm__ volatile("ld.ddc %0, (%1)" : "=r"(v) : "r"(&word));
        if (v != 0x1234567890abcdefL)
                fail("ld.ddc value");
        __asm__ volatile("sd.ddc %0, (%1)" :: "r"(nv), "r"(&word) : "memory");
        if (word != 42)
                fail("sd.ddc value");
}

/* ---- faults ---- */

static void
t_ddc_kernel_addr(void)
{
        /*
         * Outside DDC: a length violation against DDC (cap index 33),
         * delivered as SIGPROT. Recent CheriBSD kernels instead deliver
         * SIGSEGV to non-CheriABI processes whose DDC is the default user
         * range (trap.c); older ones do not, so accept either.
         */
        alt_sig = SIGSEGV;
        (void)*(volatile int *)(uintptr_t)0xffffffc000000000UL;
}

static void
t_cap_bounds(void)
{
        static char buf[32];
        char *__capability c = (__cheri_tocap char *__capability)buf;

        c = cheri_bounds_set(c, 16);
        (void)((volatile char *__capability)c)[16];
}

static void
t_cap_tag(void)
{
        static char buf[32];
        char *__capability c = (__cheri_tocap char *__capability)buf;

        c = cheri_tag_clear(c);
        (void)*(volatile char *__capability)c;
}

static void
t_ddc_narrow(void)
{
        /*
         * Narrow DDC so a normal integer-addressed load falls outside it:
         * the load must be checked against DDC (cap index 33). The signal
         * handler inherits the narrow DDC and cannot run, so the child dies
         * of SIGPROT (checked by the parent).
         */
        static volatile int target;
        void *__capability ddc = cheri_ddc_get();
        void *__capability nd = cheri_bounds_set(
            cheri_address_set(ddc, (ptraddr_t)&target), sizeof(int));
        int v;

        nd = cheri_address_set(nd, 0);
        __asm__ volatile("cspecialw ddc, %1\n\t"
            "lw %0, 0(%2)"
            : "=r"(v) : "C"(nd), "r"((uintptr_t)&target + 64) : "memory");
        (void)v;
}

struct test
{
        const char *name;
        void (*fn)(void);
        int sig, code, capreg;  /* capreg -1: don't care */
        int killed;             /* expect the child to die of `sig` */
};

#define F(n, s, c, r) { #n, t_##n, s, c, r, 0 }
#define K(n, s) { #n, t_##n, s, 0, -1, 1 }
#define NF(n) { #n, t_##n, NOFAULT, 0, -1, 0 }

static const struct test tests[] = {
        NF(nofault_compute),
        NF(nofault_cap_roundtrip),
        NF(nofault_ddc_asm),
        F(ddc_kernel_addr, SIGPROT, PROT_CHERI_BOUNDS, 33),
        F(cap_bounds, SIGPROT, PROT_CHERI_BOUNDS, -1),
        F(cap_tag, SIGPROT, PROT_CHERI_TAG, -1),
        K(ddc_narrow, SIGPROT),
};

static int
run(const struct test *t)
{
        pid_t pid;
        int status;

        fflush(stdout);
        pid = fork();
        if (pid == 0) {
                struct sigaction sa;

                memset(&sa, 0, sizeof(sa));
                sa.sa_sigaction = handler;
                sa.sa_flags = SA_SIGINFO;
                if (!t->killed) {
                        sigaction(SIGPROT, &sa, NULL);
                        sigaction(SIGSEGV, &sa, NULL);
                        sigaction(SIGBUS, &sa, NULL);
                        sigaction(SIGILL, &sa, NULL);
                }
                exp_sig = t->sig;
                exp_code = t->code;
                exp_capreg = t->capreg;
                cur_name = t->name;
                t->fn();
                if (t->sig == NOFAULT) {
                        report("%-26s PASS  no fault\n", t->name);
                        _exit(0);
                }
                report("%-26s FAIL  no fault (want sig=%d)\n", t->name,
                    t->sig);
                _exit(1);
        }
        if (waitpid(pid, &status, 0) < 0)
                return (1);
        if (WIFSIGNALED(status)) {
                int ok = t->killed && WTERMSIG(status) == t->sig;

                report("%-26s %s  killed by signal %d (want %d)\n", t->name,
                    ok ? "PASS" : "FAIL", WTERMSIG(status),
                    t->killed ? t->sig : 0);
                return (!ok);
        }
        if (t->killed) {
                report("%-26s FAIL  exited %d, want death by signal %d\n",
                    t->name, WEXITSTATUS(status), t->sig);
                return (1);
        }
        return (WEXITSTATUS(status) != 0);
}

int
main(int argc, char **argv)
{
        size_t i;
        int fails = 0, ran = 0;

        for (i = 0; i < sizeof(tests) / sizeof(tests[0]); i++) {
                if (argc > 1) {
                        int j, want = 0;

                        for (j = 1; j < argc; j++)
                                want |= strcmp(argv[j], tests[i].name) == 0;
                        if (!want)
                                continue;
                }
                fails += run(&tests[i]);
                ran++;
        }
        printf("cheri_hybrid: %d/%d passed\n", ran - fails, ran);
        return (fails != 0);
}
