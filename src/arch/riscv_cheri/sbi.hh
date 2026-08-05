/*
 * Minimal RISC-V SBI (Supervisor Binary Interface) emulation for CHERI-RISCV.
 *
 * CheriBSD is an S-mode kernel that expects M-mode firmware (OpenSBI) to
 * service `ecall`-based SBI requests. This gem5 setup has no firmware, so we
 * emulate the SBI directly: an S/M-mode ecall is intercepted and handled here
 * instead of trapping. Enough of the SBI is implemented to get the kernel past
 * sbi_init and to route console output to the simulator.
 */
#ifndef __ARCH_RISCV_CHERI_SBI_HH__
#define __ARCH_RISCV_CHERI_SBI_HH__

namespace gem5
{

class ThreadContext;

namespace CHERIRiscvISA
{

// Handle an SBI call issued via `ecall`. Reads a7 (EID), a6 (FID) and
// a0..a5 (args) from the (merged) register file, performs the service, and
// writes the result back (legacy calls return in a0; v0.2+ calls return
// error in a0 and value in a1). Always "handles" the call -- unknown
// EIDs/FIDs return SBI_ERR_NOT_SUPPORTED.
void handleSbiEcall(ThreadContext *tc);

} // namespace CHERIRiscvISA
} // namespace gem5

#endif // __ARCH_RISCV_CHERI_SBI_HH__
