/* Print the ABI and the capability of a stack object. */
#include <stdio.h>

int
main(void)
{
	char buf[32];

#ifdef __CHERI_PURE_CAPABILITY__
	printf("hello: purecap, pointers are %zu-byte capabilities\n",
	    sizeof(void *));
	printf("hello: &buf = %#p\n", (void *)buf);
#else
	printf("hello: plain RV64, pointers are %zu-byte integers\n",
	    sizeof(void *));
	printf("hello: &buf = %p\n", (void *)buf);
#endif
	return (0);
}
