/*
 * Write one byte past a 16-byte heap buffer. Purecap traps with SIGPROT
 * (capability bounds violation); plain RV64 silently corrupts the heap.
 */
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef SIGPROT
#define SIGPROT 34
#endif

static void
on_sigprot(int sig, siginfo_t *si, void *ctx)
{
	static const char msg[] =
	    "bounds: SIGPROT, the out-of-bounds write was stopped\n";

	(void)sig;
	(void)si;
	(void)ctx;
	write(STDOUT_FILENO, msg, sizeof(msg) - 1);
	_exit(0);
}

int
main(void)
{
	struct sigaction sa;
	volatile char *buf;
	int i;

	memset(&sa, 0, sizeof(sa));
	sa.sa_sigaction = on_sigprot;
	sa.sa_flags = SA_SIGINFO;
	sigaction(SIGPROT, &sa, NULL);

	buf = malloc(16);
	for (i = 0; i <= 16; i++)
		buf[i] = 'A';
	printf("bounds: wrote buf[16], the out-of-bounds write went "
	    "undetected\n");
	return (0);
}
