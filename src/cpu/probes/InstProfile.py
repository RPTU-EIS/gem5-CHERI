from m5.objects.Probe import ProbeListenerObject
from m5.params import *


class InstProfile(ProbeListenerObject):
    """Committed (micro-)ops per (privilege mode, mnemonic) of a CPU,
    written to <outdir>/<file_prefix>-<n>.csv at every statistics dump."""

    type = "InstProfile"
    cxx_header = "cpu/probes/inst_profile.hh"
    cxx_class = "gem5::InstProfile"

    core = Param.BaseCPU("the CPU to profile")
    priv_misc_reg = Param.Int(
        0, "misc register holding the privilege mode (RISC-V: MISCREG_PRV)"
    )
    file_prefix = Param.String("instprof", "output file name prefix")
