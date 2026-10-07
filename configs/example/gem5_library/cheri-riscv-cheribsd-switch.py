# cheri-riscv-cheribsd-switch.py
#
# Boot CheriBSD on the fast atomic CPU, then switch to a detailed CPU when the
# guest executes `m5 workbegin` (the region of interest). Statistics are reset
# at the switch, so stats.txt describes the detailed run only.
#
# Environment variables:
#   CHERI_SWITCH_CPU  detailed CPU to switch to: timing (default), minor, o3
#   CHERI_READFILE    file returned by `m5 readfile` (the image's
#                     /etc/m5_init.sh runs it)
#   CHERI_KERNEL      kernel (default ./tests/kernel)
#   CHERI_DISK        disk image (default ./tests/cheribsd-riscv64-purecap.img)

import os

import m5

from gem5.components.boards.riscv_cheri_board import RiscvCheriBoard
from gem5.components.cachehierarchies.classic.private_l1_private_l2_walk_cache_hierarchy import (
    PrivateL1PrivateL2WalkCacheHierarchy,
)
from gem5.components.memory import DualChannelDDR4_2400
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_switchable_processor import (
    SimpleSwitchableProcessor,
)
from gem5.isas import ISA
from gem5.resources.resource import (
    DiskImageResource,
    FileResource,
)
from gem5.simulate.exit_event import ExitEvent
from gem5.simulate.simulator import Simulator
from gem5.utils.requires import requires

requires(isa_required=ISA.RISCV_CHERI)

switch_cpus = {
    "timing": CPUTypes.TIMING,
    "minor": CPUTypes.MINOR,
    "o3": CPUTypes.O3,
}
switch_cpu = os.environ.get("CHERI_SWITCH_CPU", "timing").lower()
if switch_cpu not in switch_cpus:
    raise ValueError(
        f"CHERI_SWITCH_CPU must be one of {list(switch_cpus)}, "
        f"not '{switch_cpu}'"
    )

cache_hierarchy = PrivateL1PrivateL2WalkCacheHierarchy(
    l1d_size="16kB", l1i_size="16kB", l2_size="256kB"
)
memory = DualChannelDDR4_2400(size="3GB")
processor = SimpleSwitchableProcessor(
    starting_core_type=CPUTypes.ATOMIC,
    switch_core_type=switch_cpus[switch_cpu],
    isa=ISA.RISCV_CHERI,
    num_cores=1,
)

board = RiscvCheriBoard(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
)

board.set_kernel_disk_workload(
    kernel=FileResource(
        local_path=os.environ.get("CHERI_KERNEL", "./tests/kernel"),
    ),
    disk_image=DiskImageResource(
        local_path=os.environ.get(
            "CHERI_DISK", "./tests/cheribsd-riscv64-purecap.img"
        ),
        root_partition="1",
    ),
    readfile=os.environ.get("CHERI_READFILE", "./tests/overflow"),
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


def on_workbegin():
    # First workbegin: switch to the detailed CPU and start counting.
    print(
        f"[switch] m5 workbegin: switching to the {switch_cpu} CPU", flush=True
    )
    processor.switch()
    m5.stats.reset()
    yield False
    # Later workbegins: just reset the statistics.
    while True:
        m5.stats.reset()
        yield False


def on_workend():
    while True:
        m5.stats.dump()
        yield False


simulator = Simulator(
    board=board,
    on_exit_event={
        ExitEvent.WORKBEGIN: on_workbegin(),
        ExitEvent.WORKEND: on_workend(),
    },
)
simulator.run()
