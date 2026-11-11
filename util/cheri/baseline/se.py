# Baseline check: run one freestanding RV64GC binary in SE mode with the
# full-system runs' core, caches and memory (3 GHz, 16kB L1I/L1D, 256kB L2,
# dual-channel DDR4-2400). Works with upstream gem5 (--isa riscv) and this
# tree (--isa riscv or riscv_cheri), so the same ELF can be compared across
# simulator builds. Only the stdlib's stock components are used (unchanged
# by the CHERI work), without the full-system runs' prefetcher settings.
#
#   gem5.opt [--outdir D] util/cheri/baseline/se.py --isa riscv_cheri \
#       --cpu minor --binary ~/hiwi/baseline-gem5/bin/ptrchase

import argparse

from gem5.components.boards.simple_board import SimpleBoard
from gem5.components.cachehierarchies.classic.private_l1_private_l2_cache_hierarchy import (
    PrivateL1PrivateL2CacheHierarchy,
)
from gem5.components.memory import DualChannelDDR4_2400
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA
from gem5.resources.resource import BinaryResource
from gem5.simulate.simulator import Simulator

ap = argparse.ArgumentParser()
ap.add_argument("--isa", choices=("riscv", "riscv_cheri"), default="riscv")
ap.add_argument(
    "--cpu", choices=("atomic", "timing", "minor", "o3"), default="atomic"
)
ap.add_argument("--binary", required=True)
args = ap.parse_args()

board = SimpleBoard(
    clk_freq="3GHz",
    processor=SimpleProcessor(
        cpu_type=getattr(CPUTypes, args.cpu.upper()),
        isa=getattr(ISA, args.isa.upper()),
        num_cores=1,
    ),
    memory=DualChannelDDR4_2400(size="3GB"),
    cache_hierarchy=PrivateL1PrivateL2CacheHierarchy(
        l1d_size="16kB", l1i_size="16kB", l2_size="256kB"
    ),
)
board.set_se_binary_workload(BinaryResource(local_path=args.binary))
Simulator(board=board).run()
