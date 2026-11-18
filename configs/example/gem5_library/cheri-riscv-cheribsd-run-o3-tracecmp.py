# cheri-riscv-cheribsd-run-o3-tracecmp.py: O3 boot for a fixed number of
# instructions, to compare its trace with the atomic run
import m5
from m5.objects import Root

from gem5.components.boards.riscv_cheri_board import RiscvCheriBoard
from gem5.components.cachehierarchies.classic.no_cache import NoCache
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

# Cache hierarchy (the board needs one for its I/O devices)
cache_hierarchy = PrivateL1PrivateL2WalkCacheHierarchy(
    l1d_size="16kB", l1i_size="16kB", l2_size="256kB"
)

# Memory
memory = DualChannelDDR4_2400(size="3GB")

# Processor
processor = SimpleProcessor(
    cpu_type=CPUTypes.O3, isa=ISA.RISCV_CHERI, num_cores=1
)
# Stop after N committed instructions, as the atomic run does
processor.cores[0].get_simobject().max_insts_any_thread = 6500000

# Board
board = RiscvCheriBoard(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)

# Workload
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


simulator.run()
