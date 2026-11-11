# cheri-riscv-cheribsd-switch.py
#
# Boot CheriBSD on the atomic CPU and switch to a detailed CPU at the guest's
# `m5 workbegin`, so the statistics describe the detailed region only.
#
# Environment variables:
#   CHERI_SWITCH_CPU   CPU after workbegin: timing (default), minor, o3, atomic
#   CHERI_READFILE     file returned by `m5 readfile` (run by m5_init.sh)
#   CHERI_KERNEL       kernel (default ./tests/kernel)
#   CHERI_DISK         disk (default ./tests/cheribsd-riscv64-purecap.img)
#   CHERI_TAG_MODEL    tag timing: none (default), passthrough, flat,
#                      hierarchical, or nocache (flat without a tag cache)
#   CHERI_TAG_CACHE    leaf tag-cache size (default 32KiB)
#   CHERI_TAG_ASSOC    leaf tag-cache associativity (default 8)
#   CHERI_TAG_ROOT_CACHE  root tag-cache size, hierarchical (default 1KiB)
#   CHERI_TAG_SWE      1: silent-write elimination in the tag controller
#   CHERI_L1D, CHERI_L1I, CHERI_L2  cache sizes (default 16kB, 16kB, 256kB)
#   CHERI_L1D_PF, CHERI_L2_PF  L1D / L2 prefetcher (default stride): none,
#                     stride, tagged, bop, ampm, dcpt, indirect, isb, spp
#   CHERI_PF_ON_ACCESS 1: the prefetchers train on every access
#   CHERI_VIRTIO_SEG_MAX  virtio disk F_SEG_MAX segments (CheriBSD 2026: 126)
#   CHERI_MISALIGNED   1: misaligned DRAM accesses complete instead of trapping
#   CHERI_CKPT_OUT     save a checkpoint at `m5 checkpoint`, then exit
#   CHERI_CKPT_IN      restore from that checkpoint instead of booting
#   CHERI_PRIV_STATS   1: committed instructions and cycles per privilege mode
#   CHERI_PC_PROFILE   1: per-PC profile, pcprof-<n>.csv
#   CHERI_INST_PROFILE 1: per-mnemonic profile, instprof-<n>.csv
#   CHERI_STATS_AT_PC  PC[:COUNT],...: dump the statistics (no reset) when PC
#                      commits for the COUNT-th time, to split the region into
#                      phases (use a separate results directory)
#
# Statistics are reset at every `m5 workbegin` and dumped at every
# `m5 workend`; a booted run also dumps the boot first ("[boot-stats] dump").

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

PREFETCHERS = {
    "stride": "StridePrefetcher",
    "tagged": "TaggedPrefetcher",
    "bop": "BOPPrefetcher",
    "ampm": "AMPMPrefetcher",
    "dcpt": "DCPTPrefetcher",
    "indirect": "IndirectMemoryPrefetcher",
    "isb": "IrregularStreamBufferPrefetcher",
    "spp": "SignaturePathPrefetcher",
}
pf_choice = {
    level: os.environ.get(var, "stride").lower()
    for level, var in (("l1d", "CHERI_L1D_PF"), ("l2", "CHERI_L2_PF"))
}
for level, kind in pf_choice.items():
    if kind != "none" and kind not in PREFETCHERS:
        raise ValueError(
            f"{level} prefetcher must be none or one of {list(PREFETCHERS)}, "
            f"not '{kind}'"
        )


def make_prefetcher(kind):
    import m5.objects
    from m5.params import NULL

    return NULL if kind == "none" else getattr(m5.objects, PREFETCHERS[kind])()


class CheriCacheHierarchy(PrivateL1PrivateL2WalkCacheHierarchy):
    """The default hierarchy, with the L1D/L2 prefetchers replaced as asked
    (the caches only exist once the board incorporates the hierarchy)."""

    def incorporate_cache(self, board):
        super().incorporate_cache(board)
        from gem5.components.cachehierarchies.classic.caches.l1dcache import (
            L1DCache,
        )
        from gem5.components.cachehierarchies.classic.caches.l2cache import (
            L2Cache,
        )

        on_access = os.environ.get("CHERI_PF_ON_ACCESS", "0") == "1"
        for obj in self.descendants():
            for cls, level in ((L1DCache, "l1d"), (L2Cache, "l2")):
                if not isinstance(obj, cls):
                    continue
                if pf_choice[level] != "stride":
                    obj.prefetcher = make_prefetcher(pf_choice[level])
                if on_access and pf_choice[level] != "none":
                    # prefetch_on_pf_hit takes precedence, so clear it
                    obj.prefetcher.prefetch_on_access = True
                    obj.prefetcher.prefetch_on_pf_hit = False


cache_hierarchy = CheriCacheHierarchy(
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
        silent_write_elimination=os.environ.get("CHERI_TAG_SWE", "0") == "1",
    )
processor = SimpleSwitchableProcessor(
    starting_core_type=CPUTypes.ATOMIC,
    switch_core_type=switch_cpus[switch_cpu],
    isa=ISA.RISCV_CHERI,
    num_cores=1,
)

# the detailed CPU switched in at the first workbegin
switch_core = processor._switchable_cores["switch"][0].get_simobject()

if os.environ.get("CHERI_PRIV_STATS", "0") == "1":
    from m5.objects import PrivModeTracker

    switch_core.priv_tracker = PrivModeTracker(
        core=switch_core, manager=switch_core
    )

if os.environ.get("CHERI_PC_PROFILE", "0") == "1":
    from m5.objects import PcProfile

    switch_core.pc_profile = PcProfile(core=switch_core, manager=switch_core)

if os.environ.get("CHERI_INST_PROFILE", "0") == "1":
    from m5.objects import InstProfile

    switch_core.inst_profile = InstProfile(
        core=switch_core, manager=switch_core
    )
    # the boot CPU too (instprof-start-<n>.csv): the boot's instruction mix
    start_core = processor._switchable_cores["start"][0].get_simobject()
    start_core.inst_profile = InstProfile(
        core=start_core, manager=start_core, file_prefix="instprof-start"
    )

pc_targets = []
for item in filter(None, os.environ.get("CHERI_STATS_AT_PC", "").split(",")):
    pc, _, count = item.strip().partition(":")
    pc_targets.append((int(pc, 16), int(count or 1)))
if pc_targets:
    from m5.objects import (
        PcCountTracker,
        PcCountTrackerManager,
    )
    from m5.params import PcCountPair

    pairs = [PcCountPair(pc, n) for pc, n in pc_targets]
    switch_core.pc_stats_manager = PcCountTrackerManager(targets=pairs)
    switch_core.pc_stats_tracker = PcCountTracker(
        targets=pairs,
        core=switch_core,
        ptmanager=switch_core.pc_stats_manager,
        manager=switch_core,
    )

board = RiscvCheriBoard(
    clk_freq="3GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
    misaligned_dram=os.environ.get("CHERI_MISALIGNED", "0") == "1",
)
board.disk.vio.seg_max = int(os.environ.get("CHERI_VIRTIO_SEG_MAX", "0"))

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
    # First workbegin: dump the boot statistics (if booted), switch to
    # the detailed CPU and reset.
    if not os.environ.get("CHERI_CKPT_IN"):
        print(f"[boot-stats] dump: boot + setup, tick={m5.curTick()}",
              flush=True)
        m5.stats.dump()
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


def on_pc_target():
    # CHERI_STATS_AT_PC: a target PC was committed for the COUNT-th time
    n = 0
    while True:
        n += 1
        pair = switch_core.pc_stats_manager.getCurrentPcCountPair()
        print(
            f"[pc-stats] dump {n}: pc={pair.get_pc():#x} "
            f"count={pair.get_count()} tick={m5.curTick()}",
            flush=True,
        )
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
        ExitEvent.SIMPOINT_BEGIN: on_pc_target(),
    },
)
simulator.run()
