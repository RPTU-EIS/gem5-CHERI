# CoreMark-PRO toolchain: plain RV64 baseline. The same CHERI LLVM, sysroot
# and flags as the hybrid ABI, but the program is compiled without the CHERI
# extension (-march=rv64imafdc): what a core without CHERI runs. CHERI_MEMCPY64
# (util/cheri/common/memcpy64.c, built by build.sh) replaces the hybrid libc's
# tag-preserving memcpy/memmove with plain 8-byte-word copies.
# Identical flags for both ABIs so purecap/hybrid differ only in pointers.
# CHERI_SDK defaults to ~/cheri/output/sdk.
CHERI_SDK ?= $(HOME)/cheri/output/sdk
CC		= $(CHERI_SDK)/bin/clang --config cheribsd-riscv64-hybrid-for-purecap-rootfs.cfg -march=rv64imafdc
OBJOUT	= -o
COBJT	= -c
CINCD	= -I
CDEFN	= -D
OEXT	= .o
AS		= $(CC)
LD		= $(CC)
EXEOUT	= -o
EXE		= .exe
AR		= $(CHERI_SDK)/bin/llvm-ar
LIBTYPE	= .a
LIBOUT	=
COMPILER_FLAGS	= -g -O2 $(CDEFN)NDEBUG $(CDEFN)HOST_EXAMPLE_CODE=1 -std=gnu99
COMPILER_NOOPT	= -O0 -g $(CDEFN)NDEBUG $(CDEFN)HOST_EXAMPLE_CODE=1
COMPILER_DEBUG	= -O0 -g $(CDEFN)HOST_EXAMPLE_CODE=1 -DBMDEBUG=1 -DTHDEBUG=1
PACK_OPTS =
ifdef DDB
 CFLAGS = $(COMPILER_DEBUG) $(COMPILER_DEFS) $(PLATFORM_DEFS) $(PACK_OPTS)
else
 ifdef DDN
  CFLAGS = $(COMPILER_NOOPT) $(COMPILER_DEFS) $(PLATFORM_DEFS) $(PACK_OPTS)
 else
  CFLAGS = $(COMPILER_FLAGS) $(COMPILER_DEFS) $(PLATFORM_DEFS) $(PACK_OPTS)
 endif
endif
ifdef DDT
 CFLAGS += -DTHDEBUG=1
endif
WARNING_OPTIONS	=	\
        -Wall -Wno-long-long -fno-asm -fsigned-char
COMPILER_INCLUDES =
COMPILER_DEFINES += HAVE_SYS_STAT_H=1 USE_NATIVE_PTHREAD=1 GCC_INLINE_MACRO=1 NO_RESTRICT_QUALIFIER=1
# Size of a pointer as an integer (ee_iptr_t). The purecap patch makes
# core's ee_ptr_int an intptr_t, so this only describes addresses.
COMPILER_DEFINES += EE_SIZEOF_LONG=8 EE_SIZEOF_PTR=8
COMPILER_DEFS = $(addprefix $(CDEFN),$(COMPILER_DEFINES))
PLATFORM_DEFS = $(addprefix $(CDEFN),$(PLATFORM_DEFINES))
ASSEMBLER_FLAGS		=
ASSEMBLER_INCLUDES	=
LINKER_FLAGS	+= -static
LINKER_INCLUDES	=
LINKER_LAST		+= $(CHERI_MEMCPY64) -lm -lpthread
LIBRARY_FLAGS	= scr
SIZE		= $(CHERI_SDK)/bin/llvm-size
SIZE_FLAGS	=
ARFLAGS = $(LIBRARY_FLAGS)
LIBRARY = $(AR) $(ARFLAGS)
LIBRARY_LAST =
