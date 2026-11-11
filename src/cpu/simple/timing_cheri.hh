/*
 * CHERI-RISC-V PCC check at fetch for the TimingSimpleCPU, kept apart
 * so that timing.cc builds without the CHERI-RISC-V headers.
 */

#ifndef __CPU_SIMPLE_TIMING_CHERI_HH__
#define __CPU_SIMPLE_TIMING_CHERI_HH__

#include "arch/generic/pcstate.hh"
#include "sim/faults.hh"

namespace gem5
{

/** NoFault, unless pc is a CHERI-RISC-V PC state whose PCC is untagged or
 *  lacks execute permission: then the CHERI fault to raise. */
Fault cheriFetchCheck(const PCStateBase &pc);

} // namespace gem5

#endif // __CPU_SIMPLE_TIMING_CHERI_HH__
