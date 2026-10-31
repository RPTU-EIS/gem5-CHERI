# CHERI tagged memory: puts a CheriTagController (timing model of the tag
# table and tag cache) in front of any memory system.
#
#   membus --> CheriTagController --> tag_xbar --> memory controllers
#
# The tag table lives in a region at the top of physical memory that the
# board reserves in the device tree, so the guest never uses it. Tag values
# still come from the functional tag table; this only adds timing/traffic.

from typing import (
    List,
    Sequence,
    Tuple,
)

from m5.objects import (
    AddrRange,
    CheriTagController,
    MemCtrl,
    NoncoherentXBar,
    Port,
)

from ...utils.override import overrides
from ..boards.abstract_board import AbstractBoard
from .abstract_memory_system import AbstractMemorySystem


# Data bytes per tag-table byte: a 64-byte leaf line holds the tags of 8 KiB
# (1 bit per 16 bytes); a root line covers 512 leaf lines.
_LEAF_RATIO = 128
_ROOT_RATIO = 128 * 512
_RESERVE_ALIGN = 2 * 1024 * 1024


class CheriTaggedMemory(AbstractMemorySystem):
    """Wraps a memory system with a CHERI tag controller.

    :param memory: The memory system to wrap.
    :param enabled: If False the controller is a pass-through (same
                    topology, no tag traffic): use it as the baseline.
    :param hierarchical: Two-level tag table with zero elision.
    :param leaf_cache_size: Leaf tag-cache size, e.g. "32KiB".
    :param leaf_cache_assoc: Leaf tag-cache associativity.
    :param root_cache_size: Root tag-cache size.
    :param root_cache_assoc: Root tag-cache associativity.
    :param silent_write_elimination: A data write dirties its tag-table
                                     line only if it changes its tags.
    """

    def __init__(
        self,
        memory: AbstractMemorySystem,
        enabled: bool = True,
        hierarchical: bool = True,
        leaf_cache_size: str = "32KiB",
        leaf_cache_assoc: int = 8,
        root_cache_size: str = "1KiB",
        root_cache_assoc: int = 4,
        silent_write_elimination: bool = False,
    ) -> None:
        super().__init__()
        self._memory = memory
        self.memory = memory
        self.tag_controller = CheriTagController(
            enabled=enabled,
            hierarchical=hierarchical,
            leaf_cache_size=leaf_cache_size,
            leaf_cache_assoc=leaf_cache_assoc,
            root_cache_size=root_cache_size,
            root_cache_assoc=root_cache_assoc,
            silent_write_elimination=silent_write_elimination,
        )
        # Fans the controller out to the (possibly interleaved) channels. No
        # added latency, so enabled=False matches the plain memory system.
        self.tag_xbar = NoncoherentXBar(
            width=64,
            frontend_latency=0,
            forward_latency=0,
            response_latency=0,
        )
        self._range = None
        self._reserved = None

    def _reserve_size(self, size: int) -> int:
        need = size // _LEAF_RATIO + size // _ROOT_RATIO
        align = _RESERVE_ALIGN
        return (need + align - 1) // align * align

    @overrides(AbstractMemorySystem)
    def incorporate_memory(self, board: AbstractBoard) -> None:
        self._memory.incorporate_memory(board)
        for _, port in self._memory.get_mem_ports():
            self.tag_xbar.mem_side_ports = port
        self.tag_controller.mem_side_port = self.tag_xbar.cpu_side_ports

    @overrides(AbstractMemorySystem)
    def get_mem_ports(self) -> Sequence[Tuple[AddrRange, Port]]:
        return [(self._range, self.tag_controller.cpu_side_port)]

    @overrides(AbstractMemorySystem)
    def get_memory_controllers(self) -> List[MemCtrl]:
        return self._memory.get_memory_controllers()

    @overrides(AbstractMemorySystem)
    def get_size(self) -> int:
        return self._memory.get_size()

    @overrides(AbstractMemorySystem)
    def set_memory_range(self, ranges: List[AddrRange]) -> None:
        self._memory.set_memory_range(ranges)
        if len(ranges) != 1:
            raise Exception("CheriTaggedMemory requires a single range.")
        rng = ranges[0]
        reserve = self._reserve_size(rng.size())
        base = rng.start + rng.size() - reserve
        self._range = rng
        self._reserved = AddrRange(start=base, size=reserve)
        self.tag_controller.data_range = rng
        self.tag_controller.tag_table_base = base

    @overrides(AbstractMemorySystem)
    def get_uninterleaved_range(self) -> List[AddrRange]:
        return self._memory.get_uninterleaved_range()

    def get_reserved_ranges(self) -> List[AddrRange]:
        """Physical ranges the guest must not use (the tag table)."""
        return [self._reserved]
