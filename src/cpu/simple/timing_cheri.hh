/*
 * CHERI-RISC-V PCC check at fetch for the TimingSimpleCPU, in its own file
 * so that timing.cc does not include the CHERI-RISC-V headers: they need
 * that ISA's generated headers, which only builds with it have (SCons
 * scans #include lines regardless of #ifdef).
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
