/*
 * Run one Octane benchmark under the Duktape interpreter, as Joannou et al.
 * ("Efficient Tagged Memory", ICCD 2017) did on their CHERI FPGA. The
 * JavaScript (Octane's base.js, the benchmark, octane_runner.js) is
 * compiled in (OCTANE_JS, from build.py), so the binary needs no files.
 *
 * Usage: duk-<bench> [ITERATIONS]
 */

#include <stdio.h>
#include <stdlib.h>

#include "duktape.h"
#include "octane_js.h"

static duk_ret_t
js_print(duk_context *ctx)
{
    duk_idx_t n = duk_get_top(ctx);
    for (duk_idx_t i = 0; i < n; i++) {
        if (i)
            fputc(' ', stdout);
        fputs(duk_safe_to_string(ctx, i), stdout);
    }
    fputc('\n', stdout);
    return 0;
}

static void
fatal(void *udata, const char *msg)
{
    (void)udata;
    fprintf(stderr, "duktape fatal: %s\n", msg ? msg : "(no message)");
    fflush(stderr);
    abort();
}

int
main(int argc, char **argv)
{
    int iterations = argc > 1 ? atoi(argv[1]) : 1;
    duk_context *ctx = duk_create_heap(NULL, NULL, NULL, NULL, fatal);
    if (!ctx) {
        fprintf(stderr, "duk_create_heap_default failed\n");
        return 2;
    }
    duk_push_c_function(ctx, js_print, DUK_VARARGS);
    duk_put_global_string(ctx, "print");
    duk_push_int(ctx, iterations);
    duk_put_global_string(ctx, "__iterations");
    if (duk_peval_lstring(ctx, (const char *)octane_js,
                          sizeof(octane_js)) != 0) {
        if (duk_is_error(ctx, -1)) {
            duk_get_prop_string(ctx, -1, "stack");
            fprintf(stderr, "error: %s\n", duk_safe_to_string(ctx, -1));
        } else {
            fprintf(stderr, "error: %s\n", duk_safe_to_string(ctx, -1));
        }
        return 1;
    }
    duk_destroy_heap(ctx);
    return 0;
}
