# cheri-riscv-cheribsd-checkpoint-save.py
#
# Boot CheriBSD on the atomic CPU up to a target instruction count, then
# save a checkpoint; continue it with
# cheri-riscv-cheribsd-checkpoint-continue.py.
#
# Usage:
#   ./build/RISCV_CHERI/gem5.opt --outdir=<dir> \
#       configs/example/gem5_library/cheri-riscv-cheribsd-checkpoint-save.py \
#       <target_insts> <checkpoint_dir>

import sys

import m5

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

target_insts = int(sys.argv[1]) if len(sys.argv) > 1 else 645_000_000
checkpoint_dir = (
    sys.argv[2]
    if len(sys.argv) > 2
    else "/data/gem5-CHERI/scratch/checkpoints/boot-atomic"
)

cache_hierarchy = PrivateL1PrivateL2WalkCacheHierarchy(
    l1d_size="16kB", l1i_size="16kB", l2_size="256kB"
)
memory = DualChannelDDR4_2400(size="3GB")
processor = SimpleProcessor(
    cpu_type=CPUTypes.ATOMIC, isa=ISA.RISCV_CHERI, num_cores=1
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
    f"CKPT: running atomic untraced to {target_insts} insts before "
    f"checkpointing to {checkpoint_dir}...",
    flush=True,
)

simulator.schedule_max_insts(target_insts)
try:
    simulator.run()
except Exception as e:
    print(
        f"CKPT: run() raised before reaching target "
        f"(tick={m5.curTick()}): {type(e).__name__}: {e}",
        flush=True,
    )
    raise

print(
    f"CKPT: reached ~{target_insts} insts, tick={m5.curTick()}. "
    f"Saving checkpoint...",
    flush=True,
)

from pathlib import Path

simulator.save_checkpoint(Path(checkpoint_dir))

print(
    f"CKPT: checkpoint saved to {checkpoint_dir} at tick={m5.curTick()}.",
    flush=True,
)
print("CKPT: done.", flush=True)
