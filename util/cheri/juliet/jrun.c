/*
 * Juliet test launcher for the gem5 CHERI-RISC-V experiments.
 *
 * Runs every test listed in LIST (lines "<cwe> <good|bad> <path>") with
 * stdin from INPUT, stdout/stderr to /dev/null, no core dumps and a
 * SIGALRM timeout, and prints one console line per test:
 *
 *   JL <cwe> <good|bad> <name> exit <status>
 *   JL <cwe> <good|bad> <name> signal <signo>
 *   JL <cwe> <good|bad> <name> timeout
 *
 * One fork+exec per test (a shell loop around timeout(1) costs two more
 * process creations, which dominate simulated time).
 *
 * Usage: jrun TIMEOUT_SECONDS INPUT LIST
 */
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>

#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int
main(int argc, char **argv)
{
	char line[1024], cwe[64], kind[16], path[900];
	unsigned timeout;
	FILE *list;
	int ran = 0;

	if (argc != 4) {
		fprintf(stderr, "usage: jrun TIMEOUT_SECONDS INPUT LIST\n");
		return (2);
	}
	timeout = (unsigned)strtoul(argv[1], NULL, 10);
	if ((list = fopen(argv[3], "r")) == NULL) {
		perror(argv[3]);
		return (2);
	}
	setvbuf(stdout, NULL, _IOLBF, 0);
	while (fgets(line, sizeof(line), list) != NULL) {
		const char *name;
		int status;
		pid_t pid;

		if (sscanf(line, "%63s %15s %899s", cwe, kind, path) != 3)
			continue;
		name = strrchr(path, '/') ? strrchr(path, '/') + 1 : path;
		pid = fork();
		if (pid < 0) {
			perror("fork");
			return (1);
		}
		if (pid == 0) {
			struct rlimit nocore = { 0, 0 };
			char *args[] = { path, NULL };
			int in = open(argv[2], O_RDONLY);
			int null = open("/dev/null", O_WRONLY);

			setrlimit(RLIMIT_CORE, &nocore);
			if (in >= 0)
				dup2(in, 0);
			if (null >= 0) {
				dup2(null, 1);
				dup2(null, 2);
			}
			alarm(timeout);
			execv(path, args);
			_exit(127);
		}
		while (waitpid(pid, &status, 0) < 0)
			;
		if (WIFSIGNALED(status) && WTERMSIG(status) == SIGALRM)
			printf("JL %s %s %s timeout\n", cwe, kind, name);
		else if (WIFSIGNALED(status))
			printf("JL %s %s %s signal %d\n", cwe, kind, name,
			    WTERMSIG(status));
		else
			printf("JL %s %s %s exit %d\n", cwe, kind, name,
			    WEXITSTATUS(status));
		ran++;
	}
	printf("JL-DONE %d\n", ran);
	return (0);
}
