/*
 * memcpy/memmove/bcopy with 8-byte words, as in a non-CHERI FreeBSD libc.
 *
 * CheriBSD's hybrid (lib64) bcopy.c copies in capability-sized (16-byte)
 * words so that it keeps tags, and falls back to copying single bytes when
 * source and destination differ in their address mod 16: e.g. an 8-byte
 * aligned struct copied by value. A plain RISC-V libc copies such data in
 * 8-byte words. Linked into the hybrid baseline binaries (which hold no
 * capabilities in memory) so the baseline pays what a non-CHERI system
 * pays. Same algorithm as FreeBSD lib/libc/string/bcopy.c.
 */
#include <stddef.h>
#include <stdint.h>

typedef unsigned long word;
#define	wsize	sizeof(word)
#define	wmask	(wsize - 1)

static void *
copy(void *dst0, const void *src0, size_t length)
{
	char *dst = dst0;
	const char *src = src0;
	size_t t;

	if (length == 0 || dst == src)
		return (dst0);
#define	TLOOP(s) if (t) TLOOP1(s)
#define	TLOOP1(s) do { s; } while (--t)
	if ((uintptr_t)dst < (uintptr_t)src) {
		t = (uintptr_t)src;
		if ((t | (uintptr_t)dst) & wmask) {
			if ((t ^ (uintptr_t)dst) & wmask || length < wsize)
				t = length;
			else
				t = wsize - (t & wmask);
			length -= t;
			TLOOP1(*dst++ = *src++);
		}
		t = length / wsize;
		TLOOP(*(word *)(void *)dst = *(const word *)(const void *)src;
		    src += wsize; dst += wsize);
		t = length & wmask;
		TLOOP(*dst++ = *src++);
	} else {
		src += length;
		dst += length;
		t = (uintptr_t)src;
		if ((t | (uintptr_t)dst) & wmask) {
			if ((t ^ (uintptr_t)dst) & wmask || length <= wsize)
				t = length;
			else
				t &= wmask;
			length -= t;
			TLOOP1(*--dst = *--src);
		}
		t = length / wsize;
		TLOOP(src -= wsize; dst -= wsize;
		    *(word *)(void *)dst = *(const word *)(const void *)src);
		t = length & wmask;
		TLOOP(*--dst = *--src);
	}
	return (dst0);
}

void *
memcpy(void * __restrict dst, const void * __restrict src, size_t n)
{
	return (copy(dst, src, n));
}

void *
memmove(void *dst, const void *src, size_t n)
{
	return (copy(dst, src, n));
}

void
bcopy(const void *src, void *dst, size_t n)
{
	copy(dst, (void *)(uintptr_t)src, n);
}
