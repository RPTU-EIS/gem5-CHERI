# cheri-riscv-cheribsd-switch.py
#
# Boot CheriBSD on the fast atomic CPU, then switch to a detailed CPU when the
# guest executes `m5 workbegin` (the region of interest). Statistics are reset
# at the switch, so stats.txt describes the detailed run only.
#
# Environment variables:
#   CHERI_SWITCH_CPU  CPU to switch to at the first workbegin: timing
#                     (default), minor, o3, or atomic (fast instruction
#                     counts; same processor layout, so checkpoints restore
#                     into any of them)
#   CHERI_READFILE    file returned by `m5 readfile` (the image's
#                     /etc/m5_init.sh runs it)
#   CHERI_KERNEL      kernel (default ./tests/kernel)
#   CHERI_DISK        disk image (default ./tests/cheribsd-riscv64-purecap.img)
#   CHERI_TAG_MODEL   tag-storage timing model (CheriTagController):
#                       none (default)  no tag controller
#                       passthrough     controller present, no tag traffic
#                                       (baseline with the same topology)
#                       flat            single-level tag table + tag cache
#                       hierarchical    root level with zero elision
#                       nocache         flat table without a tag cache: every
#                                       lookup reads the tag table in DRAM
#   CHERI_TAG_CACHE   leaf tag-cache size (default 32KiB)
#   CHERI_TAG_ASSOC   leaf tag-cache associativity (default 8)
#   CHERI_TAG_ROOT_CACHE  root tag-cache size, hierarchical (default 1KiB)
#   CHERI_L1D, CHERI_L1I, CHERI_L2
#                     cache sizes (default 16kB, 16kB, 256kB)
#   CHERI_MISALIGNED  1: misaligned data accesses to DRAM complete (as on
#                     QEMU or with firmware emulation) instead of trapping
#                     (SIGBUS in the guest); default 0
#   CHERI_CKPT_OUT    save a checkpoint there when the guest runs
#                     `m5 checkpoint`, then exit
#   CHERI_CKPT_IN     restore from that checkpoint instead of booting
#
# Statistics are reset at every `m5 workbegin` and dumped at every
# `m5 workend`, so a guest can bracket several regions in one run.

import os

import m5

from gem5.components.boards.riscv_cheri_board import RiscvCheriBoard
from gem5.components.cachehierarchies.classic.private_l1_private_l2_walk_cache_hierarchy import (
    PrivateL1PrivateL2WalkCacheHierarchy,
)
from gem5.components.memory import DualChannelDDR4_2400
from gem5.components.memory.cheri_tagged_memory import CheriTaggedMemory
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
    "atomic": CPUTypes.ATOMIC,
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
    l1d_size=os.environ.get("CHERI_L1D", "16kB"),
    l1i_size=os.environ.get("CHERI_L1I", "16kB"),
    l2_size=os.environ.get("CHERI_L2", "256kB"),
)
memory = DualChannelDDR4_2400(size="3GB")

tag_model = os.environ.get("CHERI_TAG_MODEL", "none").lower()
if tag_model not in ("none", "passthrough", "nocache", "flat", "hierarchical"):
    raise ValueError(f"Unknown CHERI_TAG_MODEL '{tag_model}'")
if tag_model != "none":
    memory = CheriTaggedMemory(
        memory,
        enabled=tag_model != "passthrough",
        hierarchical=tag_model == "hierarchical",
        # nocache: flat table, no tag cache (every lookup reads the table)
        leaf_cache_size="0B"
        if tag_model == "nocache"
        else os.environ.get("CHERI_TAG_CACHE", "32KiB"),
        leaf_cache_assoc=int(os.environ.get("CHERI_TAG_ASSOC", "8")),
        root_cache_size=os.environ.get("CHERI_TAG_ROOT_CACHE", "1KiB"),
    )
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
    misaligned_dram=os.environ.get("CHERI_MISALIGNED", "0") == "1",
)

# Checked here: otherwise gem5 only panics when the guest runs m5 readfile.
readfile = os.environ.get("CHERI_READFILE", "./tests/overflow")
if not os.path.isfile(readfile):
    raise FileNotFoundError(
        f"readfile '{readfile}' not found; set CHERI_READFILE to the "
        "program or runner script the guest should execute"
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
    readfile=readfile,
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


ckpt_out = os.environ.get("CHERI_CKPT_OUT")
ckpt_in = os.environ.get("CHERI_CKPT_IN")


def on_checkpoint():
    if not ckpt_out:
        print(
            "[ckpt] m5 checkpoint ignored (CHERI_CKPT_OUT unset)", flush=True
        )
        while True:
            yield False
    print(f"[ckpt] saving checkpoint to {ckpt_out}", flush=True)
    simulator.save_checkpoint(ckpt_out)
    yield True


simulator = Simulator(
    board=board,
    checkpoint_path=ckpt_in or None,
    on_exit_event={
        ExitEvent.WORKBEGIN: on_workbegin(),
        ExitEvent.WORKEND: on_workend(),
        ExitEvent.CHECKPOINT: on_checkpoint(),
    },
)
simulator.run()
