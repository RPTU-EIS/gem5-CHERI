from m5.objects.Probe import ProbeListenerObject
from m5.params import *


class PcProfile(ProbeListenerObject):
    """Committed instructions and cycles per (privilege mode, PC) of a CPU,
    written to <outdir>/<file_prefix>-<n>.csv at every statistics dump."""

    type = "PcProfile"
    cxx_header = "cpu/probes/pc_profile.hh"
    cxx_class = "gem5::PcProfile"

    core = Param.BaseCPU("the CPU to profile")
    priv_misc_reg = Param.Int(
        0, "misc register holding the privilege mode (RISC-V: MISCREG_PRV)"
    )
    file_prefix = Param.String("pcprof", "output file name prefix")
