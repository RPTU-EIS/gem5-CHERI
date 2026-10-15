from m5.objects.Probe import ProbeListenerObject
from m5.params import *


class PrivModeTracker(ProbeListenerObject):
    """Counts committed instructions and cycles per privilege mode of a
    CPU (cycles go to the mode of the next committed instruction)."""

    type = "PrivModeTracker"
    cxx_header = "cpu/probes/priv_mode_tracker.hh"
    cxx_class = "gem5::PrivModeTracker"

    core = Param.BaseCPU("the CPU to track")
    priv_misc_reg = Param.Int(
        0, "misc register holding the privilege mode (RISC-V: MISCREG_PRV)"
    )
