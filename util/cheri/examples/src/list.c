/*
 * Pointer chasing: walk a linked list whose nodes are visited in a random
 * order. Purecap nodes hold a 16-byte capability instead of an 8-byte
 * pointer, so the list is larger and misses more in the caches.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define NODES	16384
#define WALKS	8

struct node {
	struct node *next;
	uint64_t value;
};

int
main(void)
{
	struct node *nodes, *n;
	uint32_t *order, seed = 1;
	uint64_t sum = 0;
	int i, j, w;

	nodes = malloc(NODES * sizeof(*nodes));
	order = malloc(NODES * sizeof(*order));
	if (nodes == NULL || order == NULL)
		return (1);

	/* Shuffle the visiting order with a fixed-seed LCG. */
	for (i = 0; i < NODES; i++)
		order[i] = i;
	for (i = NODES - 1; i > 0; i--) {
		uint32_t t;

		seed = seed * 1103515245 + 12345;
		j = (seed >> 8) % (i + 1);
		t = order[i];
		order[i] = order[j];
		order[j] = t;
	}
	for (i = 0; i < NODES; i++) {
		nodes[order[i]].next = &nodes[order[(i + 1) % NODES]];
		nodes[order[i]].value = i;
	}

	for (w = 0; w < WALKS; w++) {
		n = &nodes[order[0]];
		for (i = 0; i < NODES; i++) {
			sum += n->value;
			n = n->next;
		}
	}

	printf("list: %d nodes of %zu bytes, %d walks, sum %llu\n", NODES,
	    sizeof(struct node), WALKS, (unsigned long long)sum);
	return (sum == (uint64_t)WALKS * NODES * (NODES - 1) / 2 ? 0 : 1);
}
