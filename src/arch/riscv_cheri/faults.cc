/*
 * Copyright (c) 2016 RISC-V Foundation
 * Copyright (c) 2016 The University of Virginia
 * Copyright (c) 2018 TU Dresden
 * Copyright (c) 2020 Barkhausen Institut
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

#include "arch/riscv_cheri/faults.hh"

#include "arch/riscv_cheri/insts/static_inst.hh"
#include "arch/riscv_cheri/isa.hh"
#include "arch/riscv_cheri/mmu.hh"
#include "arch/riscv_cheri/pmp.hh"
#include "arch/riscv_cheri/regs/misc.hh"
#include "arch/riscv_cheri/utility.hh"
#include "cpu/base.hh"
#include "cpu/thread_context.hh"
#include "debug/Faults.hh"
#include "sim/debug.hh"
#include "sim/full_system.hh"
#include "sim/workload.hh"

namespace gem5
{

namespace CHERIRiscvISA
{

void
RiscvFault::invokeSE(ThreadContext *tc, const StaticInstPtr &inst)
{
    panic("Fault %s encountered at pc %s.", name(), tc->pcState());
}

void
RiscvFault::invoke(ThreadContext *tc, const StaticInstPtr &inst)
{
    auto pc_state = tc->pcState().as<PCState>();

    DPRINTFS(Faults, tc->getCpuPtr(), "Fault (%s, %u) at PC: %s\n",
             name(), exception(), pc_state);

    if (FullSystem) {
        CHERIPrivilegeMode pp = (CHERIPrivilegeMode)tc->
            readMiscReg(MISCREG_PRV);
        CHERIPrivilegeMode prv = PRV_M;
        MISA misa = tc->readMiscRegNoEffect(MISCREG_ISA);
        STATUS status = tc->readMiscReg(MISCREG_STATUS);

        // According to riscv-privileged-v1.11, if a NMI occurs at the middle
        // of a M-mode trap handler, the state (epc/cause) will be overwritten
        // and is not necessary recoverable. There's nothing we can do here so
        // we'll just warn our user that the CPU state might be broken.
        warn_if(isNonMaskableInterrupt() && pp == PRV_M && status.mie == 0,
                "NMI overwriting M-mode trap handler state");

        // Set fault handler privilege mode
        if (isNonMaskableInterrupt()) {
            prv = PRV_M;
        } else if (isInterrupt()) {
            if (pp != PRV_M &&
                bits(tc->readMiscReg(MISCREG_MIDELEG), _code) != 0) {
                prv = (misa.rvs) ? PRV_S : ((misa.rvn) ? PRV_U : PRV_M);
            }
            if (pp == PRV_U && misa.rvs && misa.rvn &&
                bits(tc->readMiscReg(MISCREG_SIDELEG), _code) != 0) {
                prv = PRV_U;
            }
        } else {
            if (pp != PRV_M &&
                bits(tc->readMiscReg(MISCREG_MEDELEG), _code) != 0) {
                prv = (misa.rvs) ? PRV_S : ((misa.rvn) ? PRV_U : PRV_M);
            }
            if (pp == PRV_U && misa.rvs && misa.rvn &&
                bits(tc->readMiscReg(MISCREG_SEDELEG), _code) != 0) {
                prv = PRV_U;
            }
        }

        // Set fault registers and status
        MiscRegIndex cause, epc, tvec, tval;
        switch (prv) {
          case PRV_U:
            cause = MISCREG_UCAUSE;
            epc = MISCREG_UEPC;
            tvec = MISCREG_UTVEC;
            tval = MISCREG_UTVAL;

            status.upie = status.uie;
            status.uie = 0;
            break;
          case PRV_S:
            cause = MISCREG_SCAUSE;
            epc = MISCREG_SEPC;
            tvec = MISCREG_STVEC;
            tval = MISCREG_STVAL;

            status.spp = pp;
            status.spie = status.sie;
            status.sie = 0;
            break;
          case PRV_M:
            cause = MISCREG_MCAUSE;
            epc = MISCREG_MEPC;
            tvec = isNonMaskableInterrupt() ? MISCREG_NMIVEC : MISCREG_MTVEC;
            tval = MISCREG_MTVAL;

            status.mpp = pp;
            status.mpie = status.mie;
            status.mie = 0;
            break;
          default:
            panic("Unknown privilege mode %d.", prv);
            break;
        }

        // Set fault cause, privilege, and return PC
        // ── Determine which CHERI SCRs to use, matching the privilege level
        // we're entering. PCC saves to xEPCC; new PCC loads from xTCC. ──
        MiscRegIndex epcc_idx, tcc_idx;
        switch (prv) {
          case PRV_U: epcc_idx = MISCREG_UEPCC; tcc_idx = MISCREG_UTCC; break;
          case PRV_S: epcc_idx = MISCREG_SEPCC; tcc_idx = MISCREG_STCC; break;
          case PRV_M: epcc_idx = MISCREG_MEPCC; tcc_idx = MISCREG_MTCC; break;
          default: panic("Unknown privilege mode %d.", prv);
        }

        // Set fault cause, privilege, and return PC
        uint64_t _cause = _code;
        if (isInterrupt()) {
           _cause |= CAUSE_INTERRUPT_MASKS[pc_state.rvType()];
        }
        tc->setMiscReg(cause, _cause);
        tc->setMiscReg(epc, tc->pcState().instAddr());
        tc->setMiscReg(tval, trap_value());
        tc->setMiscReg(MISCREG_PRV, prv);
        tc->setMiscReg(MISCREG_STATUS, status);

        if (isNonMaskableInterrupt()) {
            tc->setMiscReg(MISCREG_NMIE, 0);
        }

        // Clear load reservation
        auto isa = static_cast<CHERIRiscvISA::ISA*>(tc->getIsaPtr());
        isa->clearLoadReservation(tc->contextId());

        // ── CHERI: save current PCC into xEPCC ──
        // Address of saved PCC = faulting instruction's PC. Bounds/perms
        // are the existing PCC's. CheriBSD reads MEPCC/SEPCC on xret and
        // restores PCC from it.
        CapRegContainer saved_pcc = pc_state.pcc();
        saved_pcc.setAddress(pc_state.instAddr());
        isa->setCapMiscReg(epcc_idx, saved_pcc);

        // ── CHERI: load new PCC from xTCC ──
        // The trap vector cap holds bounds/perms for the handler.
        // Its address is the handler entry point (matching MTVEC address).
        CapRegContainer new_pcc = isa->readCapMiscReg(tcc_idx);

        // Compute handler address per RISC-V tvec format (direct vs vectored).
        // In CHERI-RISC-V the trap vector IS xTCC; its address field serves as
        // xTVEC. The purecap kernel programs xTCC (via cspecialrw), NOT the
        // legacy xTVEC CSR (which stays 0), so derive the handler address from
        // xTCC's address rather than getFaultHandlerAddr(tvec)/xTVEC (which
        // returned 0 and vectored every trap to PC=0 -> fetch-fault loop).
        (void)tvec;  // legacy xTVEC index unused on the purecap trap path
        uint64_t vec = new_pcc.getAddress();
        Addr addr = mbits(vec, 63, 2);
        if (isInterrupt() && bits(vec, 1, 0) == 1)
            addr += 4 * _code;
        new_pcc.setAddress(addr);

        pc_state.pcc(new_pcc);
        pc_state.set(addr);
        tc->pcState(pc_state);
    }
}

void
Reset::invoke(ThreadContext *tc, const StaticInstPtr &inst)
{
    // ── Emulate the OpenSBI -> kernel handoff (no firmware in this setup). ──
    // On real hardware M-mode firmware (OpenSBI) delegates traps to S-mode and
    // drops to S-mode before entering the S-mode kernel. We have no OpenSBI, so
    // do the equivalent here: enter the kernel directly in S-mode with traps
    // delegated. Otherwise the kernel runs in M-mode and its page faults etc.
    // are delivered to the unset MTVEC (the kernel only programs STVEC) and the
    // machine hangs. faults.cc already honours MEDELEG/MIDELEG when the faulting
    // privilege is < M. To revert, set PRV_M and drop the two deleg writes.
    tc->setMiscReg(MISCREG_PRV, PRV_S);
    // Delegate exceptions to S-mode, EXCEPT ecall-from-S (9) / ecall-from-M
    // (11), which must stay in M-mode so our inline SBI emulation still fires.
    // Bits: 0-8 (misaligned/access/illegal/breakpoint/ecall-U) + 12/13/15
    // (instr/load/store page fault) = 0xB1FF, plus the CHERI causes 26/27
    // (capability load/store page fault) and 28 (CHERI exception), which
    // OpenSBI delegates on CHERI hardware so CheriBSD's S-mode handler sees
    // them (SCAUSE_CHERI -> SIGPROT).
    tc->setMiscReg(MISCREG_MEDELEG,
                   0xB1FF | (1ULL << LOAD_CAP_PAGE) |
                   (1ULL << STORE_AMO_CAP_PAGE) | (1ULL << CHERI_CAPABILITY));
    // Delegate S-mode interrupts (SSIP/STIP/SEIP = bits 1/5/9) = 0x222.
    tc->setMiscReg(MISCREG_MIDELEG, 0x222);
    STATUS status = tc->readMiscReg(MISCREG_STATUS);
    status.mie = 0;
    status.mprv = 0;
    tc->setMiscReg(MISCREG_STATUS, status);
    tc->setMiscReg(MISCREG_MCAUSE, 0);

    // Advance the PC to the implementation-defined reset vector
    auto workload = dynamic_cast<Workload *>(tc->getSystemPtr()->workload);
    std::unique_ptr<PCState> new_pc(dynamic_cast<PCState *>(
        tc->getIsaPtr()->newPCState(workload->getEntry())));
    panic_if(!new_pc, "Failed create new PCState from ISA pointer");
    VTYPE vtype = 0;
    vtype.vill = 1;
    new_pc->vtype(vtype);
    new_pc->vl(0);
    tc->pcState(*new_pc);

    // Reset PMP Cfg
    auto* mmu = dynamic_cast<CHERIRiscvISA::MMU*>(tc->getMMUPtr());
    if (mmu == nullptr) {
        warn("MMU is not CHERI Riscv MMU instance, we can't reset PMP");
        return;
    }
    mmu->getPMP()->pmpReset();
}

void
UnknownInstFault::invokeSE(ThreadContext *tc, const StaticInstPtr &inst)
{
    auto *rsi = static_cast<CHERIRiscvStaticInst *>(inst.get());
    panic("Unknown instruction 0x%08x at pc %s", rsi->machInst,
        tc->pcState());
}

void
IllegalInstFault::invokeSE(ThreadContext *tc, const StaticInstPtr &inst)
{
    if (! tc->getSystemPtr()->trapToGdb(GDBSignal::ILL, tc->contextId()) ) {
        auto *rsi = static_cast<CHERIRiscvStaticInst *>(inst.get());
        panic("Illegal instruction 0x%08x at pc %s: %s", rsi->machInst,
            tc->pcState(), reason.c_str());
    }
}

void
UnimplementedFault::invokeSE(ThreadContext *tc, const StaticInstPtr &inst)
{
    panic("Unimplemented instruction %s at pc %s", instName, tc->pcState());
}

void
IllegalFrmFault::invokeSE(ThreadContext *tc, const StaticInstPtr &inst)
{
    panic("Illegal floating-point rounding mode 0x%x at pc %s.",
            frm, tc->pcState());
}

void
BreakpointFault::invokeSE(ThreadContext *tc, const StaticInstPtr &inst)
{
    if (! tc->getSystemPtr()->trapToGdb(GDBSignal::TRAP, tc->contextId()) ) {
        schedRelBreak(0);
    }
}

void
SyscallFault::invokeSE(ThreadContext *tc, const StaticInstPtr &inst)
{
    /* Advance the PC to next instruction so - once (simulated) syscall
       is executed - execution continues. */
    auto pc_state = tc->pcState().as<PCState>();
    inst->advancePC(pc_state);
    tc->pcState(pc_state);

    tc->getSystemPtr()->workload->syscall(tc);
}

bool
cheriEnforcingAt(CHERIPrivilegeMode prv)
{
    // CHERI violations are raised at every privilege level. This is the one
    // place to relax enforcement (e.g. return prv == PRV_U to exempt the
    // kernel) when bringing up a new boot path.
    (void)prv;
    return true;
}

bool
cheriEnforcing(ThreadContext *tc)
{
    return cheriEnforcingAt((CHERIPrivilegeMode)tc->readMiscReg(MISCREG_PRV));
}

Fault
capEnforce(ThreadContext *tc, CheriCapException code, int capReg, Addr addr)
{
    if (code == CheriCapException::None || !cheriEnforcing(tc))
        return NoFault;
    DPRINTFS(Faults, tc->getCpuPtr(),
             "CHERI violation cause %#x cap_idx %d addr %#x at %s\n",
             (unsigned)code, capReg, addr, tc->pcState());
    return std::make_shared<CheriCapFault>(code, capReg, addr);
}

Fault
cheriCheckMem(ThreadContext *tc, const CapRegContainer &auth, int capIdx,
              Addr ea, unsigned size, unsigned acc,
              const CapRegContainer *stored)
{
    if (!cheriEnforcing(tc))
        return NoFault;
    CheriCapException code = capCheckMemAccess(auth, ea, size, acc, stored);
    if (code != CheriCapException::None) {
        DPRINTFS(Faults, tc->getCpuPtr(),
                 "CHERI mem access ea %#x size %d acc %#x via c%d %s%s%s\n",
                 ea, size, acc, capIdx, auth.getString(),
                 stored ? " storing " : "",
                 stored ? stored->getString() : "");
    }
    return capEnforce(tc, code, capIdx, ea);
}

Fault
cheriCheckJump(ThreadContext *tc, const CapRegContainer &target, int capIdx,
               int64_t imm)
{
    CheriCapException code = capCheckJump(target, imm);
    if (code != CheriCapException::None && cheriEnforcing(tc)) {
        DPRINTFS(Faults, tc->getCpuPtr(), "CHERI jump via c%d imm %d %s\n",
                 capIdx, imm, target.getString());
    }
    return capEnforce(tc, code, capIdx, target.getAddress() + imm);
}

void
CheriCapFault::invokeSE(ThreadContext *tc, const StaticInstPtr &inst)
{
    // Try to drop into the debugger when available, otherwise fail loudly.
    if (!tc->getSystemPtr()->trapToGdb(GDBSignal::ILL, tc->contextId())) {
        // Report the CHERI fault type and any associated information.
        panic("CHERI capability fault (code=%u, creg=%d, addr=%#llx) at pc %s",
              static_cast<unsigned>(_cheri_code), _cap_reg,
              static_cast<unsigned long long>(_addr), tc->pcState());
    }
}

bool
getFaultVAddr(Fault fault, Addr &va)
{
    auto addr_fault = dynamic_cast<AddressFault *>(fault.get());
    if (addr_fault) {
        va = addr_fault->trap_value();
        return true;
    }

    auto pgt_fault = dynamic_cast<GenericPageTableFault *>(fault.get());
    if (pgt_fault) {
        va = pgt_fault->getFaultVAddr();
        return true;
    }

    auto cheri_fault = dynamic_cast<CheriCapFault *>(fault.get());
    if (cheri_fault) {
        va = static_cast<Addr>(cheri_fault->trap_value());
        return true;
    }

    return false;
}

} // namespace CHERIRiscvISA
} // namespace gem5
