# cheri-riscv-cheribsd-run-stepcmp.py
#
# Run the CheriBSD boot (atomic or O3) in fixed instruction steps of one
# simulation, printing a STEPLOOP line after every step.
#
# Usage:
#   ./build/RISCV_CHERI/gem5.opt --debug-flags=Exec --outdir=<dir> \
#       configs/example/gem5_library/cheri-riscv-cheribsd-run-stepcmp.py \
#       <atomic|o3> [step_size] [max_steps]

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
step_size = int(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000
max_steps = int(sys.argv[3]) if len(sys.argv) > 3 else 1000

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
    f"STEPLOOP: cpu={cpu_arg} step_size={step_size} max_steps={max_steps}",
    flush=True,
)

total_insts = 0
for step_num in range(max_steps):
    simulator.schedule_max_insts(step_size)
    try:
        simulator.run()
    except NotImplementedError as e:
        total_insts += step_size
        print(
            f"STEPLOOP: NATURAL EXIT after step {step_num} "
            f"(~{total_insts} insts, tick={m5.curTick()}): {e}",
            flush=True,
        )
        break
    except Exception as e:
        total_insts += step_size
        print(
            f"STEPLOOP: UNEXPECTED EXCEPTION after step {step_num} "
            f"(~{total_insts} insts, tick={m5.curTick()}): "
            f"{type(e).__name__}: {e}",
            flush=True,
        )
        break
    total_insts += step_size
    print(
        f"STEPLOOP: paused after step {step_num}, "
        f"~{total_insts} insts, tick={m5.curTick()}",
        flush=True,
    )
else:
    print(
        f"STEPLOOP: reached max_steps ({max_steps}) without a natural "
        f"exit; stopping.",
        flush=True,
    )

print("STEPLOOP: done.", flush=True)
