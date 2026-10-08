/*
 * CHERI-RISC-V fault conformance tests for the gem5 model.
 *
 * Each test runs in a forked child that performs exactly one capability
 * violation (or none, for the "nofault" tests). A SA_SIGINFO handler reports
 * signal, si_code and si_capreg, and the result is compared with what the
 * CHERI ISAv9 / CheriBSD would deliver (SIGPROT + PROT_CHERI_*). Control-flow
 * tests also check si_addr (the trapping PC): as in Sail, a jump or branch to
 * a target outside its bounds faults at the jump, not at the target.
 *
 * Build (purecap, static):
 *   ~/cheri/output/sdk/bin/clang --config cheribsd-riscv64-purecap.cfg \
 *       -O0 -static -o cheri_faults cheri_faults.c
 * Run all tests, or name some: ./cheri_faults [test...]
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
#define PROT_CHERI_SEALED 3
#define PROT_CHERI_PERM 5
#define PROT_CHERI_STORELOCAL 8
#endif

#define NOFAULT (-1)

static volatile int exp_sig, exp_code, exp_capreg;
static volatile __ptraddr_t exp_pc;       /* 0: don't care */
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
        __ptraddr_t pc = cheri_address_get(si->si_addr);
        int ok = sig == exp_sig && si->si_code == exp_code &&
            (exp_capreg < 0 || si->si_capreg == exp_capreg) &&
            (exp_pc == 0 || pc == exp_pc);
        (void)uc;
        report("%-28s %s  got sig=%d code=%d capreg=%d pc=%#lx  (want sig=%d"
            " code=%d capreg=%d pc=%#lx)\n", cur_name, ok ? "PASS" : "FAIL",
            sig, si->si_code, si->si_capreg, (unsigned long)pc, exp_sig,
            exp_code, exp_capreg, (unsigned long)exp_pc);
        _exit(ok ? 0 : 1);
}

/* Heap-like object with exact bounds, and a few helpers. */
static char *
bounded(size_t len)
{
        char *p = malloc(len < 64 ? 64 : len);

        return (cheri_bounds_set_exact(p, len));
}

static void
callee(void)
{
}

/* ---- data loads/stores ---- */
static void t_bounds_store(void) { char *b = bounded(16); b[16] = 'A'; }
static void
t_bounds_load(void)
{
    volatile char *b = bounded(16);
    (void)b[16];
}
static void
t_bounds_underflow(void)
{
    volatile char *b = bounded(16);
    (void)b[-1];
}
static void t_bounds_store_word(void)
{
        volatile int *b = (volatile int *)bounded(16);
        b[4] = 1;
}
static void t_bounds_load_dword(void)
{
        volatile long *b = (volatile long *)bounded(16);
        (void)b[2];
}
static void t_bounds_straddle(void)
{
        /* 8-byte access starting 4 bytes before the top. */
        char *b = bounded(16);
        volatile int64_t *p = (volatile int64_t *)(void *)(b + 8);
        p = (volatile int64_t *)cheri_bounds_set_exact((void *)p, 4);
        (void)*p;
}
static void t_tag_load(void)
{
        volatile char *b = cheri_tag_clear(bounded(16));
        (void)b[0];
}
static void
t_tag_store(void)
{
    char *b = cheri_tag_clear(bounded(16));
    b[0] = 1;
}
static void t_perm_load(void)
{
        volatile char *b = cheri_perms_and(bounded(16), ~CHERI_PERM_LOAD);
        (void)b[0];
}
static void t_perm_store(void)
{
        char *b = cheri_perms_and(bounded(16), ~CHERI_PERM_STORE);
        b[0] = 1;
}
static void t_sealed_load(void)
{
        /* Function pointers are sentries (sealed) in purecap CheriBSD. */
        volatile char *p = (volatile char *)(void *)&callee;
        (void)*p;
}

/* Forced instruction encodings (capability-mode RISC-V). */
static void t_asm_lb(void)
{
        char *b = bounded(16) + 16;
        long r;
        __asm__ volatile(".option push\n.option norvc\n"
            "lb %0, 0(%1)\n.option pop" : "=r"(r) : "C"(b));
}
static void t_asm_c_lw(void)
{
        register char *b __asm__("ca1") = bounded(16) + 16;
        register long r __asm__("a0");
        __asm__ volatile(".option push\n.option rvc\n"
            "lw %0, 0(%1)\n.option pop" : "=r"(r) : "C"(b));
}
static void t_asm_c_sd(void)
{
        register char *b __asm__("ca1") = bounded(16) + 16;
        register long v __asm__("a0") = 0;
        __asm__ volatile(".option push\n.option rvc\n"
            "sd %0, 0(%1)\n.option pop" :: "r"(v), "C"(b) : "memory");
}
static void t_asm_amoadd(void)
{
        int *b = (int *)(void *)(bounded(16) + 16);
        int r;
        __asm__ volatile("amoadd.w %0, %2, (%1)" : "=r"(r) : "C"(b), "r"(1)
            : "memory");
}
static void t_asm_lr(void)
{
        long *b = (long *)(void *)(bounded(16) + 16);
        long r;
        __asm__ volatile("lr.d %0, (%1)" : "=r"(r) : "C"(b) : "memory");
}
static void t_asm_sc_perm(void)
{
        long *b = (long *)(void *)cheri_perms_and(bounded(16),
            ~CHERI_PERM_STORE);
        long r;
        __asm__ volatile("sc.d %0, %2, (%1)" : "=r"(r) : "C"(b), "r"(1L)
            : "memory");
}
static void t_asm_fld(void)
{
        double *b = (double *)(void *)(bounded(16) + 16);
        double r;
        __asm__ volatile("fld %0, 0(%1)" : "=f"(r) : "C"(b));
}

/* ---- capability loads/stores ---- */
static void t_cap_load_bounds(void)
{
        void *volatile *b = (void *volatile *)(void *)bounded(16);
        (void)b[1];
}
static void t_cap_store_bounds(void)
{
        void *volatile *b = (void *volatile *)(void *)bounded(16);
        b[1] = NULL;
}
static void t_c_lq_bounds(void)
{
        register char *b __asm__("ca1") = bounded(16) + 16;
        register void *r __asm__("ca0");
        __asm__ volatile(".option push\n.option rvc\n"
            "clc %0, 0(%1)\n.option pop" : "=C"(r) : "C"(b));
}
static void t_store_cap_perm(void)
{
        void **b = cheri_perms_and((void **)(void *)bounded(16),
            ~CHERI_PERM_STORE_CAP);
        b[0] = (void *)b;   /* tagged value -> PERMIT_STORE_CAP needed */
}
static void t_nofault_store_untagged_cap(void)
{
        void **b = cheri_perms_and((void **)(void *)bounded(16),
            ~CHERI_PERM_STORE_CAP);
        b[0] = cheri_tag_clear((void *)b);  /* untagged: allowed */
}
static void t_store_local(void)
{
        void **b = cheri_perms_and((void **)(void *)bounded(16),
            ~CHERI_PERM_STORE_LOCAL_CAP);
        void *local = cheri_perms_and((void *)b, ~CHERI_PERM_GLOBAL);
        b[0] = local;
}
static void t_nofault_load_cap_noperm(void)
{
        void **slot = (void **)(void *)bounded(16);
        void **ro;
        void *v;

        slot[0] = (void *)slot;
        ro = cheri_perms_and(slot, ~CHERI_PERM_LOAD_CAP);
        v = *(void *volatile *)ro;
        if (cheri_tag_get(v)) {
                report("%-28s FAIL  loaded tag survived without "
                    "PERMIT_LOAD_CAP\n", cur_name);
                _exit(1);
        }
}

/* ---- control flow ---- */
typedef void (*fn_t)(void);

static void t_jump_untagged(void)
{
        fn_t f = (fn_t)cheri_tag_clear((void *)&callee);
        f();
}
static void t_jump_noexec(void)
{
        char *d = bounded(64);
        fn_t f = (fn_t)(void *)d;   /* data capability: no EXECUTE */
        f();
}
static void t_fetch_bounds(void)
{
        /* An unsealed PCC-derived capability for callee() bounded to 2 bytes:
         * the jump is legal, executing past the first parcel is not. */
        void *pcc = cheri_pcc_get();
        void *c = cheri_address_set(pcc, cheri_address_get((void *)&callee));
        c = cheri_bounds_set(c, 2);
        ((fn_t)c)();
}
/*
 * Out-of-bounds jumps and branches. Each cf_nb_* region is entered through a
 * PCC bounded to just that region; its jump/branch then targets the ret at
 * cf_nb_jal + 0x80, outside the bounds. The *_site labels mark the jumping
 * instruction, which is where the fault must be reported.
 */
void cf_nb_jal(void), cf_nb_jal_site(void);
void cf_nb_beq(void), cf_nb_beq_site(void);
void cf_nb_cj(void), cf_nb_cj_site(void);
void cf_nb_ok(void);
void cf_jalr_site(void);
__asm__(
"        .text\n"
"        .p2align 2\n"
"        .option push\n"
"        .option norvc\n"
"        .globl cf_nb_jal, cf_nb_jal_site, cf_nb_beq, cf_nb_beq_site\n"
"        .globl cf_nb_ok, cf_nb_cj, cf_nb_cj_site\n"
"        .type cf_nb_jal, @function\n"
"        .type cf_nb_jal_site, @function\n"
"        .type cf_nb_beq, @function\n"
"        .type cf_nb_beq_site, @function\n"
"        .type cf_nb_ok, @function\n"
"        .type cf_nb_cj, @function\n"
"        .type cf_nb_cj_site, @function\n"
/* Raw encodings in a fixed layout: the assembler would otherwise expand the
 * branches (beq -> bnez + j, c.j -> j). The out-of-bounds target is +0x80. */
"cf_nb_jal:\n"                  /* 0x00, 8 bytes */
"        nop\n"
"cf_nb_jal_site:\n"             /* 0x04 */
"        .4byte 0x07c0006f\n"       /* jal zero, +0x7c */
"cf_nb_beq:\n"                  /* 0x08, 8 bytes */
"        nop\n"
"cf_nb_beq_site:\n"             /* 0x0c */
"        .4byte 0x06000a63\n"       /* beq zero, zero, +0x74 */
"cf_nb_ok:\n"                   /* 0x10, 12 bytes: in-bounds branch */
"        .4byte 0x00000463\n"       /* beq zero, zero, +8 */
"        nop\n"
"        ret\n"                  /* 0x18 */
"        .option rvc\n"
"cf_nb_cj:\n"                   /* 0x1c, 4 bytes */
"        c.nop\n"
"cf_nb_cj_site:\n"              /* 0x1e */
"        .2byte 0xa08d\n"           /* c.j +0x62 */
"        .option norvc\n"
"        .fill 24, 4, 0x00000013\n"     /* 0x20 .. 0x7f: nops */
"        ret\n"                  /* 0x80: the target */
"        .option pop\n");

static void
call_narrow(void (*start)(void), size_t len)
{
        void *c = cheri_address_set(cheri_pcc_get(),
            cheri_address_get((void *)start));

        ((fn_t)cheri_bounds_set_exact(c, len))();
}
static void t_branch_bounds_jal(void) { call_narrow(cf_nb_jal, 8); }
static void t_branch_bounds_beq(void) { call_narrow(cf_nb_beq, 8); }
static void t_branch_bounds_cj(void) { call_narrow(cf_nb_cj, 4); }
static void t_nofault_branch_inbounds(void) { call_narrow(cf_nb_ok, 12); }
static void
t_jump_bounds(void)
{
        /* CJALR to callee + 64 through a capability bounded to callee's
         * first 16 bytes: a length violation on cs1 (ct1 = c6), at the
         * jalr, before cra is written. */
        void *c = cheri_address_set(cheri_pcc_get(),
            cheri_address_get((void *)&callee));
        register void *t __asm__("ct1") = cheri_address_set(
            cheri_bounds_set_exact(c, 16), cheri_address_get(c) + 64);
        __asm__ volatile(".globl cf_jalr_site\n"
            ".type cf_jalr_site, @function\n"
            "cf_jalr_site:\n"
            "        jalr cra, 0(%0)" :: "C"(t) : "ra", "memory");
}
static void t_nofault_call_return(void)
{
        /* jal/jalr link capabilities must be valid sentries. */
        callee();
        fn_t f = &callee;
        f();
}

struct test
{
        const char *name;
        void (*fn)(void);
        int sig, code, capreg;  /* capreg -1: don't care */
        void (*site)(void);     /* expected trapping PC; NULL: don't care */
};

#define F(n, c, r) { #n, t_##n, SIGPROT, PROT_CHERI_##c, r, NULL }
#define FPC(n, c, r, s) { #n, t_##n, SIGPROT, PROT_CHERI_##c, r, s }
#define NF(n) { #n, t_##n, NOFAULT, 0, -1, NULL }

static const struct test tests[] = {
        F(bounds_store, BOUNDS, -1),
        F(bounds_load, BOUNDS, -1),
        F(bounds_underflow, BOUNDS, -1),
        F(bounds_store_word, BOUNDS, -1),
        F(bounds_load_dword, BOUNDS, -1),
        F(bounds_straddle, BOUNDS, -1),
        F(tag_load, TAG, -1),
        F(tag_store, TAG, -1),
        F(perm_load, PERM, -1),
        F(perm_store, PERM, -1),
        F(sealed_load, SEALED, -1),
        F(asm_lb, BOUNDS, -1),
        F(asm_c_lw, BOUNDS, 11),
        F(asm_c_sd, BOUNDS, 11),
        F(asm_amoadd, BOUNDS, -1),
        F(asm_lr, BOUNDS, -1),
        F(asm_sc_perm, PERM, -1),
        F(asm_fld, BOUNDS, -1),
        F(cap_load_bounds, BOUNDS, -1),
        F(cap_store_bounds, BOUNDS, -1),
        F(c_lq_bounds, BOUNDS, 11),
        F(store_cap_perm, PERM, -1),
        NF(nofault_store_untagged_cap),
        F(store_local, STORELOCAL, -1),
        NF(nofault_load_cap_noperm),
        F(jump_untagged, TAG, -1),
        F(jump_noexec, PERM, -1),
        F(fetch_bounds, BOUNDS, 32),
        FPC(jump_bounds, BOUNDS, 6, cf_jalr_site),
        FPC(branch_bounds_jal, BOUNDS, 32, cf_nb_jal_site),
        FPC(branch_bounds_beq, BOUNDS, 32, cf_nb_beq_site),
        FPC(branch_bounds_cj, BOUNDS, 32, cf_nb_cj_site),
        NF(nofault_branch_inbounds),
        NF(nofault_call_return),
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
                sigaction(SIGPROT, &sa, NULL);
                sigaction(SIGSEGV, &sa, NULL);
                sigaction(SIGBUS, &sa, NULL);
                sigaction(SIGILL, &sa, NULL);
                exp_sig = t->sig;
                exp_code = t->code;
                exp_capreg = t->capreg;
                exp_pc = t->site ? cheri_address_get((void *)t->site) : 0;
                cur_name = t->name;
                t->fn();
                if (t->sig == NOFAULT) {
                        report("%-28s PASS  no fault\n", t->name);
                        _exit(0);
                }
                report("%-28s FAIL  no fault (want sig=%d code=%d)\n", t->name,
                    t->sig, t->code);
                _exit(1);
        }
        if (waitpid(pid, &status, 0) < 0)
                return (1);
        if (WIFSIGNALED(status)) {
                report("%-28s FAIL  killed by signal %d\n", t->name,
                    WTERMSIG(status));
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
        printf("cheri_faults: %d/%d passed\n", ran - fails, ran);
        return (fails != 0);
}
