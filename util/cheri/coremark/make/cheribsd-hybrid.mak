# CoreMark-PRO platform: CheriBSD RISC-V, hybrid ABI (gem5 CHERI experiments).
PLATFORM=cheribsd-hybrid
SHELL=/bin/bash
ifndef TOOLCHAIN
TOOLCHAIN=clang-cheribsd-hybrid
endif
LOAD		=
RUN			=
RUN_FLAGS	=
PLATFORM_DEFINES = EE_SIZEOF_INT=4 EE_SIZEOF_LONG=8
CMD_SEP=
COPY_DATA=cp -Ru --remove-destination
