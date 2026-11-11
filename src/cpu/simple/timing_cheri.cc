/*
 * CHERI-RISC-V PCC check at fetch for the TimingSimpleCPU (see
 * timing_cheri.hh). Built only with the CHERI-RISC-V ISA.
 */

#include "cpu/simple/timing_cheri.hh"

#include "arch/riscv_cheri/faults.hh"
#include "arch/riscv_cheri/pcstate.hh"

namespace gem5
{

Fault
cheriFetchCheck(const PCStateBase &pc)
{
    // A build with several ISAs may run another one on this CPU.
    auto *cheri_pc = dynamic_cast<const CHERIRiscvISA::PCState *>(&pc);
    if (!cheri_pc)
        return NoFault;

    const auto &pcc = cheri_pc->pcc();
    if (!pcc.getTag()) {
        return std::make_shared<CHERIRiscvISA::CheriCapFault>(
            CHERIRiscvISA::CheriCapException::TagViolation);
    }
    CHERIRiscvISA::CAPTYPE meta = pcc.getMetadata();
    if (meta.perm == 0) {
        return std::make_shared<CHERIRiscvISA::CheriCapFault>(
            CHERIRiscvISA::CheriCapException::PermitExecuteViolation);
    }
    // Sentry and bounds violations could be checked the same way.
    return NoFault;
}

} // namespace gem5
