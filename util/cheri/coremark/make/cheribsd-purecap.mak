# CoreMark-PRO platform: CheriBSD RISC-V, purecap ABI (gem5 CHERI experiments).
PLATFORM=cheribsd-purecap
SHELL=/bin/bash
ifndef TOOLCHAIN
TOOLCHAIN=clang-cheribsd-purecap
endif
LOAD		=
RUN			=
RUN_FLAGS	=
PLATFORM_DEFINES = EE_SIZEOF_INT=4 EE_SIZEOF_LONG=8
CMD_SEP=
COPY_DATA=cp -Ru --remove-destination
