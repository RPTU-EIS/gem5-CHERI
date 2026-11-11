/*
 * Minimal RISC-V SBI emulation for CHERI-RISCV: there is no M-mode
 * firmware (OpenSBI), so S/M-mode ecalls are handled here.
 */
#ifndef __ARCH_RISCV_CHERI_SBI_HH__
#define __ARCH_RISCV_CHERI_SBI_HH__

namespace gem5
{

class ThreadContext;

namespace CHERIRiscvISA
{

// Handle an SBI call (EID in a7, FID in a6, arguments in a0..a5);
// unknown calls return SBI_ERR_NOT_SUPPORTED.
void handleSbiEcall(ThreadContext *tc);

} // namespace CHERIRiscvISA
} // namespace gem5

#endif // __ARCH_RISCV_CHERI_SBI_HH__
