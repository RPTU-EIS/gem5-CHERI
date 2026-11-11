# cheri-riscv-cheribsd-checkpoint-continue.py
#
# Restore a checkpoint of cheri-riscv-cheribsd-checkpoint-save.py and run
# on the atomic or O3 CPU; debug ticks count from the checkpoint's tick.
#
# Usage:
#   ./build/RISCV_CHERI/gem5.opt [--debug-flags=... --debug-start=... \
#       --debug-end=...] --outdir=<dir> \
#       configs/example/gem5_library/cheri-riscv-cheribsd-checkpoint-continue.py \
#       <atomic|o3> <checkpoint_dir> [extra_insts] [step_size]

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

cpu_arg = sys.argv[1] if len(sys.argv) > 1 else "atomic"
checkpoint_dir = (
    sys.argv[2]
    if len(sys.argv) > 2
    else "/data/schmitz/gem5-CHERI/scratch/checkpoints/boot-atomic"
)
extra_insts = int(sys.argv[3]) if len(sys.argv) > 3 else 20_000_000
step_size = int(sys.argv[4]) if len(sys.argv) > 4 else extra_insts

cpu_type = CPUTypes.O3 if cpu_arg == "o3" else CPUTypes.ATOMIC

cache_hierarchy = PrivateL1PrivateL2WalkCacheHierarchy(
    l1d_size="16kB", l1i_size="16kB", l2_size="256kB"
)
memory = DualChannelDDR4_2400(size="3GB")
processor = SimpleProcessor(
    cpu_type=cpu_type, isa=ISA.RISCV_CHERI, num_cores=1
)

board = RiscvCheriBoard(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)

board.set_kernel_disk_workload(
    kernel=FileResource(
        local_path="/data/schmitz/gem5-CHERI/tests/kernel",
    ),
    disk_image=DiskImageResource(
        local_path="/data/schmitz/cheri/output/cheribsd-riscv64-purecap.img",
        root_partition="1",
    ),
    readfile="/data/schmitz/gem5-CHERI/scratch/m5_init_script_cheri.sh",
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

# A str, not a Path: _m5.core.getCheckpoint() only takes a str
simulator = Simulator(board=board, checkpoint_path=checkpoint_dir)

print(
    f"CKPTCONT: restored {checkpoint_dir}, cpu={cpu_arg}, "
    f"tick={m5.curTick()}. Running {extra_insts} more insts in steps of "
    f"{step_size}...",
    flush=True,
)

total_insts = 0
steps = (extra_insts + step_size - 1) // step_size
for step_num in range(steps):
    this_step = min(step_size, extra_insts - total_insts)
    simulator.schedule_max_insts(this_step)
    try:
        simulator.run()
    except NotImplementedError as e:
        total_insts += this_step
        print(
            f"CKPTCONT: NATURAL EXIT after step {step_num} "
            f"(~{total_insts} extra insts, tick={m5.curTick()}): {e}",
            flush=True,
        )
        break
    except Exception as e:
        total_insts += this_step
        print(
            f"CKPTCONT: UNEXPECTED EXCEPTION after step {step_num} "
            f"(~{total_insts} extra insts, tick={m5.curTick()}): "
            f"{type(e).__name__}: {e}",
            flush=True,
        )
        break
    total_insts += this_step
    print(
        f"CKPTCONT: paused after step {step_num}, "
        f"~{total_insts} extra insts, tick={m5.curTick()}",
        flush=True,
    )

print("CKPTCONT: done.", flush=True)
