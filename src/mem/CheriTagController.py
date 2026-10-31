# CHERI tag controller: timing model of capability tag storage (tag table in
# DRAM behind a tag cache). See src/mem/cheri_tag_controller.hh.

from m5.params import *
from m5.proxy import *
from m5.objects.ClockedObject import ClockedObject


class CheriTagController(ClockedObject):
    type = "CheriTagController"
    cxx_header = "mem/cheri_tag_controller.hh"
    cxx_class = "gem5::CheriTagController"

    cpu_side_port = ResponsePort("Port facing the memory bus")
    mem_side_port = RequestPort("Port facing the memory controllers")

    system = Param.System(Parent.any, "System (functional tag table)")
    data_range = Param.AddrRange("Physical memory whose tags are tracked")
    tag_table_base = Param.Addr(
        "Base of the reserved region holding the tag table (inside "
        "data_range, not used by the guest)"
    )

    enabled = Param.Bool(
        True, "Model tag storage; if False, a pure pass-through"
    )
    hierarchical = Param.Bool(
        True, "Two-level table with a root level and zero elision"
    )
    leaf_cache_size = Param.MemorySize(
        "32KiB",
        "Leaf tag-cache size; 0 = no tag cache (every lookup reads the tag "
        "table, every tag write is a read-modify-write of its line)",
    )
    leaf_cache_assoc = Param.Unsigned(8, "Leaf tag-cache associativity")
    root_cache_size = Param.MemorySize("1KiB", "Root tag-cache size")
    root_cache_assoc = Param.Unsigned(4, "Root tag-cache associativity")
    silent_write_elimination = Param.Bool(
        False,
        "A data write dirties its tag-table line only if it changes the "
        "line's tags (Joannou et al., ICCD 2017); otherwise every data "
        "write dirties it",
    )
    lookup_latency = Param.Cycles(
        2, "Tag-cache lookup latency on the miss path"
    )
