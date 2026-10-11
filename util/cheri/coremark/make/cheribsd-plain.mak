# CoreMark-PRO platform: CheriBSD RISC-V, plain RV64 (no CHERI instructions; gem5 CHERI experiments).
PLATFORM=cheribsd-plain
SHELL=/bin/bash
ifndef TOOLCHAIN
TOOLCHAIN=clang-cheribsd-plain
endif
LOAD		=
RUN			=
RUN_FLAGS	=
PLATFORM_DEFINES = EE_SIZEOF_INT=4 EE_SIZEOF_LONG=8
CMD_SEP=
COPY_DATA=cp -Ru --remove-destination
