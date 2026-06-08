# cheri-riscv-cheribsd-run.py
import m5
from m5.objects import Root

from gem5.components.boards.riscv_cheri_board import RiscvCheriBoard
from gem5.components.cachehierarchies.classic.private_l1_private_l2_walk_cache_hierarchy import (
    PrivateL1PrivateL2WalkCacheHierarchy,
)
from gem5.components.memory import DualChannelDDR4_2400
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_processor import SimpleProcessor
from gem5.isas import ISA
from gem5.resources.resource import (
    FileResource,
    DiskImageResource,
)
from gem5.simulate.simulator import Simulator
from gem5.utils.requires import requires

requires(isa_required=ISA.RISCV_CHERI)

# ── Cache hierarchy (required by board for _setup_io_devices) ──
cache_hierarchy = PrivateL1PrivateL2WalkCacheHierarchy(
    l1d_size="16kB", l1i_size="16kB", l2_size="256kB"
)

# ── Memory ──
memory = DualChannelDDR4_2400(size="3GB")

# ── Processor ──
processor = SimpleProcessor(
    cpu_type=CPUTypes.TIMING, isa=ISA.RISCV_CHERI, num_cores=1
)

# ── Board ──
board = RiscvCheriBoard(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,   # NOT None
)

# ── Workload ──
board.set_kernel_disk_workload(
    kernel=FileResource(
        local_path="/import/public/Linux/gem5/CHERI-RISCV/kernel",
    ),
    disk_image=DiskImageResource(
        local_path="/import/public/Linux/gem5/CHERI-RISCV/cheribsd-riscv64-purecap.img",
        root_partition="1",
    ),
)

# import sys
# wl = board.workload
# print("=== Workload state ===", file=sys.stderr)
# print(f"  Type: {type(wl).__name__}", file=sys.stderr)
# for attr_name in dir(wl):
#     if attr_name.startswith("_"):
#         continue
#     try:
#         val = getattr(wl, attr_name)
#         # Skip methods, just show simple values
#         if isinstance(val, (str, int, bool, float)):
#             print(f"  {attr_name}: {val!r}", file=sys.stderr)
#     except:
#         pass

# print("=== Disk state ===", file=sys.stderr)
# # disk_obj = board.platform.disk
# print(f"  Image: {disk_obj.vio.image}", file=sys.stderr)
# print(f"  Image file: {disk_obj.vio.image.image_file}", file=sys.stderr)
# # if hasattr(disk_obj.vio.image, 'child'):
# #     print(f"  Child image_file: {disk_obj.vio.image.child.image_file}", file=sys.stderr)

simulator = Simulator(board=board)
simulator.run()