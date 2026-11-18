# cheri-riscv-cheribsd-run-o3-detail.py
#
# Run the O3 CheriBSD boot untraced up to a target instruction count,
# then enable the O3CPUAll debug flag for a short window.
#
# Usage:
#   ./build/RISCV_CHERI/gem5.opt --outdir=<dir> \
#       configs/example/gem5_library/cheri-riscv-cheribsd-run-o3-detail.py \
#       <insts_before_window> <window_size>

import sys

import m5
from m5 import debug

from gem5.components.boards.riscv_cheri_board import RiscvCheriBoard
from gem5.components.cachehierarchies.classic.private_l1_private_l2_walk_cache_hierarchy import (
    PrivateL1PrivateL2WalkCacheHierarchy,
)
from gem5.components.memory import DualChannelDDR4_2400
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA
from gem5.resources.resource import (
    DiskImageResource,
    FileResource,
)
from gem5.simulate.simulator import Simulator
from gem5.utils.requires import requires

requires(isa_required=ISA.RISCV_CHERI)

insts_before = int(sys.argv[1]) if len(sys.argv) > 1 else 4_925_800
window_size = int(sys.argv[2]) if len(sys.argv) > 2 else 150

cache_hierarchy = PrivateL1PrivateL2WalkCacheHierarchy(
    l1d_size="16kB", l1i_size="16kB", l2_size="256kB"
)
memory = DualChannelDDR4_2400(size="3GB")
processor = SimpleProcessor(
    cpu_type=CPUTypes.O3, isa=ISA.RISCV_CHERI, num_cores=1
)

board = RiscvCheriBoard(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)

board.set_kernel_disk_workload(
    kernel=FileResource(
        local_path="/data/gem5-CHERI/tests/kernel",
    ),
    disk_image=DiskImageResource(
        local_path="/data/cheri/output/cheribsd-riscv64-purecap.img",
        root_partition="1",
    ),
    readfile="/data/gem5-CHERI/scratch/m5_init_script_cheri.sh",
    kernel_args=[
        "-s",
        "console=ttyS0",
        "root={root_value}",
        "disk_device={disk_device}",
        "rw",
        "init_script=/etc/m5_init.sh",
        "init_shell=/bin/sh",
    ],
)

simulator = Simulator(board=board)

print(
    f"DETAIL: running untraced to {insts_before} instructions...", flush=True
)
simulator.schedule_max_insts(insts_before)
simulator.run()
print(
    f"DETAIL: reached ~{insts_before} insts, tick={m5.curTick()}. "
    f"Enabling O3CPUAll for {window_size} more instructions.",
    flush=True,
)

debug.flags["O3CPUAll"].enable()
simulator.schedule_max_insts(window_size)
simulator.run()

print(f"DETAIL: window done at tick={m5.curTick()}.", flush=True)
