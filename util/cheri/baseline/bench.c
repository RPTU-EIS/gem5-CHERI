/*
 * Freestanding RV64GC kernels for the baseline check: the same ELF runs in
 * SE mode on upstream gem5 (RISCV), this tree's RISCV build and its
 * RISCV_CHERI build (integer mode), so any difference in committed
 * instructions or cycles comes from the simulator, not the software.
 * No libc: only the write and exit syscalls. Build one binary per kernel
 * with -DKERNEL_<NAME> (see build.sh).
 */

typedef unsigned long u64;
typedef unsigned int u32;

static long
syscall3(long n, long a0, long a1, long a2)
{
    register long x10 asm("a0") = a0;
    register long x11 asm("a1") = a1;
    register long x12 asm("a2") = a2;
    register long x17 asm("a7") = n;
    asm volatile("ecall" : "+r"(x10) : "r"(x11), "r"(x12), "r"(x17)
                 : "memory");
    return x10;
}

static void
put(const char *s, u64 v)
{
    char buf[64];
    int n = 0;
    while (*s)
        buf[n++] = *s++;
    for (int i = 60; i >= 0; i -= 4)
        buf[n++] = "0123456789abcdef"[(v >> i) & 0xf];
    buf[n++] = '\n';
    syscall3(64, 1, (long)buf, n);  /* write(1, buf, n) */
}

static u64 lcg = 12345;

static u32
rnd(void)
{
    lcg = lcg * 6364136223846793005UL + 1442695040888963407UL;
    return (u32)(lcg >> 33);
}

#if defined(KERNEL_PTRCHASE)
/* Dependent loads over a randomly linked 4 MiB list: memory latency. */
#define N (1 << 18)
struct node { struct node *next; u64 val; };
static struct node nodes[N];
static u32 perm[N];

static u64
kernel(void)
{
    for (u32 i = 0; i < N; i++)
        perm[i] = i;
    for (u32 i = N - 1; i > 0; i--) {
        u32 j = rnd() % (i + 1), t = perm[i];
        perm[i] = perm[j];
        perm[j] = t;
    }
    for (u32 i = 0; i < N; i++) {
        nodes[perm[i]].next = &nodes[perm[(i + 1) % N]];
        nodes[perm[i]].val = i;
    }
    u64 sum = 0;
    struct node *p = &nodes[perm[0]];
    for (u32 i = 0; i < 4 * N; i++) {
        sum += p->val;
        p = p->next;
    }
    return sum;
}

#elif defined(KERNEL_TREE)
/* Binary search tree from a node pool: pointer-heavy, branchy. */
#define N (1 << 17)
struct tnode { struct tnode *l, *r; u64 key; };
static struct tnode pool[N];

static u64
kernel(void)
{
    struct tnode *root = 0;
    for (u32 i = 0; i < N; i++) {
        struct tnode *n = &pool[i], **at = &root;
        n->key = rnd();
        while (*at)
            at = n->key < (*at)->key ? &(*at)->l : &(*at)->r;
        *at = n;
    }
    u64 found = 0;
    lcg = 12345;
    for (u32 i = 0; i < 2 * N; i++) {
        u64 k = rnd();
        struct tnode *p = root;
        while (p && p->key != k)
            p = k < p->key ? p->l : p->r;
        found += p ? 1 : 0;
    }
    return found;
}

#elif defined(KERNEL_QSORT)
/* Quicksort of 128 Ki integers: branch prediction. */
#define N (1 << 17)
static int a[N];

static void
qs(int *v, long lo, long hi)
{
    while (lo < hi) {
        int p = v[(lo + hi) / 2];
        long i = lo, j = hi;
        while (i <= j) {
            while (v[i] < p) i++;
            while (v[j] > p) j--;
            if (i <= j) {
                int t = v[i];
                v[i++] = v[j];
                v[j--] = t;
            }
        }
        if (j - lo < hi - i) {
            qs(v, lo, j);
            lo = i;
        } else {
            qs(v, i, hi);
            hi = j;
        }
    }
}

static u64
kernel(void)
{
    for (u32 i = 0; i < N; i++)
        a[i] = (int)rnd();
    qs(a, 0, N - 1);
    u64 sum = 0;
    for (u32 i = 0; i < N; i += 97)
        sum = sum * 31 + (u32)a[i];
    return sum;
}

#elif defined(KERNEL_MATMUL)
/* Dense double-precision matrix multiply: FP pipeline and L1. */
#define M 96
static double A[M][M], B[M][M], C[M][M];

static u64
kernel(void)
{
    for (int i = 0; i < M; i++)
        for (int j = 0; j < M; j++) {
            A[i][j] = (double)(rnd() % 1000) / 7.0;
            B[i][j] = (double)(rnd() % 1000) / 3.0;
        }
    for (int i = 0; i < M; i++)
        for (int j = 0; j < M; j++) {
            double s = 0;
            for (int k = 0; k < M; k++)
                s += A[i][k] * B[k][j];
            C[i][j] = s;
        }
    u64 sum = 0;
    for (int i = 0; i < M; i++)
        sum += (u64)C[i][(i * 7) % M];
    return sum;
}

#elif defined(KERNEL_CRC32)
/* Table-driven CRC32 over 1 MiB, 8 passes: integer ALU and loads. */
#define N (1 << 20)
static unsigned char buf[N];
static u32 table[256];

static u64
kernel(void)
{
    for (u32 i = 0; i < 256; i++) {
        u32 c = i;
        for (int k = 0; k < 8; k++)
            c = c & 1 ? 0xedb88320u ^ (c >> 1) : c >> 1;
        table[i] = c;
    }
    for (u32 i = 0; i < N; i++)
        buf[i] = (unsigned char)rnd();
    u32 crc = 0xffffffffu;
    for (int pass = 0; pass < 8; pass++)
        for (u32 i = 0; i < N; i++)
            crc = table[(crc ^ buf[i]) & 0xff] ^ (crc >> 8);
    return crc ^ 0xffffffffu;
}

#elif defined(KERNEL_STREAM)
/* STREAM-like triad over three 2 MiB arrays: bandwidth, prefetching. */
#define N (1 << 18)
static double x[N], y[N], z[N];

static u64
kernel(void)
{
    for (u32 i = 0; i < N; i++) {
        x[i] = 1.0;
        y[i] = 2.0;
        z[i] = 0.0;
    }
    for (int it = 0; it < 6; it++)
        for (u32 i = 0; i < N; i++)
            z[i] = x[i] + 3.0 * y[i] + z[i] * 0.5;
    double s = 0;
    for (u32 i = 0; i < N; i += 64)
        s += z[i];
    return (u64)s;
}

#else
#error "define one KERNEL_<NAME>"
#endif

int
main(void)
{
    put("checksum=", kernel());
    return 0;
}

asm(".globl _start\n"
    "_start:\n"
    "  call main\n"
    "  li a7, 93\n"      /* exit(main's return value) */
    "  ecall\n");
