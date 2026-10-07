/*
 * Copyright (c) 2016 RISC-V Foundation
 * Copyright (c) 2016 The University of Virginia
 * Copyright (c) 2018 TU Dresden
 * Copyright (c) 2024 University of Rostock
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

#ifndef __ARCH_RISCV_CHERI_FAULTS_HH__
#define __ARCH_RISCV_CHERI_FAULTS_HH__

#include <cstdint>
#include <string>

#include "arch/generic/cheri_defs.hh"
#include "arch/riscv_cheri/cheri_checks.hh"
#include "arch/riscv_cheri/isa.hh"
#include "cpu/null_static_inst.hh"
#include "sim/faults.hh"

namespace gem5
{

class ThreadContext;

namespace CHERIRiscvISA
{

enum FloatException : uint64_t
{
    FloatInexact = 0x1,
    FloatUnderflow = 0x2,
    FloatOverflow = 0x4,
    FloatDivZero = 0x8,
    FloatInvalid = 0x10
};

/*
 * In RISC-V, exception and interrupt codes share some values. They can be
 * differentiated by an 'Interrupt' flag that is enabled for interrupt faults
 * but not exceptions. The full fault cause can be computed by placing the
 * exception (or interrupt) code in the least significant bits of the CAUSE
 * CSR and then setting the highest bit of CAUSE with the 'Interrupt' flag.
 * For more details on exception causes, see Chapter 3.1.20 of the RISC-V
 * privileged specification v 1.10. Codes are enumerated in Table 3.6.
 */
enum ExceptionCode : uint64_t
{
    INST_ADDR_MISALIGNED = 0,
    INST_ACCESS = 1,
    INST_ILLEGAL = 2,
    BREAKPOINT = 3,
    LOAD_ADDR_MISALIGNED = 4,
    LOAD_ACCESS = 5,
    STORE_ADDR_MISALIGNED = 6,
    AMO_ADDR_MISALIGNED = 6,
    STORE_ACCESS = 7,
    AMO_ACCESS = 7,
    ECALL_USER = 8,
    ECALL_SUPER = 9,
    ECALL_MACHINE = 11,
    INST_PAGE = 12,
    LOAD_PAGE = 13,
    STORE_PAGE = 15,
    AMO_PAGE = 15,
    // CHERI-RISC-V (ISAv9): capability page faults (PTE CR/CW) and CHERI
    // capability exceptions. CheriBSD: SCAUSE_LOAD_CAP_PAGE_FAULT,
    // SCAUSE_STORE_AMO_CAP_PAGE_FAULT and SCAUSE_CHERI.
    LOAD_CAP_PAGE = 26,
    STORE_AMO_CAP_PAGE = 27,
    CHERI_CAPABILITY = 28,

    INT_SOFTWARE_USER = 0,
    INT_SOFTWARE_SUPER = 1,
    INT_SOFTWARE_MACHINE = 3,
    INT_TIMER_USER = 4,
    INT_TIMER_SUPER = 5,
    INT_TIMER_MACHINE = 7,
    INT_EXT_USER = 8,
    INT_EXT_SUPER = 9,
    INT_EXT_MACHINE = 11,
    INT_LOCAL_0 = 16,
    INT_LOCAL_1 = 17,
    INT_LOCAL_2 = 18,
    INT_LOCAL_3 = 19,
    INT_LOCAL_4 = 20,
    INT_LOCAL_5 = 21,
    INT_LOCAL_6 = 22,
    INT_LOCAL_7 = 23,
    INT_LOCAL_8 = 24,
    INT_LOCAL_9 = 25,
    INT_LOCAL_10 = 26,
    INT_LOCAL_11 = 27,
    INT_LOCAL_12 = 28,
    INT_LOCAL_13 = 29,
    INT_LOCAL_14 = 30,
    INT_LOCAL_15 = 31,
    INT_LOCAL_16 = 32,
    INT_LOCAL_17 = 33,
    INT_LOCAL_18 = 34,
    INT_LOCAL_19 = 35,
    INT_LOCAL_20 = 36,
    INT_LOCAL_21 = 37,
    INT_LOCAL_22 = 38,
    INT_LOCAL_23 = 39,
    INT_LOCAL_24 = 40,
    INT_LOCAL_25 = 41,
    INT_LOCAL_26 = 42,
    INT_LOCAL_27 = 43,
    INT_LOCAL_28 = 44,
    INT_LOCAL_29 = 45,
    INT_LOCAL_30 = 46,
    INT_LOCAL_31 = 47,
    INT_LOCAL_32 = 48,
    INT_LOCAL_33 = 49,
    INT_LOCAL_34 = 50,
    INT_LOCAL_35 = 51,
    INT_LOCAL_36 = 52,
    INT_LOCAL_37 = 53,
    INT_LOCAL_38 = 54,
    INT_LOCAL_39 = 55,
    INT_LOCAL_40 = 56,
    INT_LOCAL_41 = 57,
    INT_LOCAL_42 = 58,
    INT_LOCAL_43 = 59,
    INT_LOCAL_44 = 60,
    INT_LOCAL_45 = 61,
    INT_LOCAL_46 = 62,
    INT_LOCAL_47 = 63,
    NumInterruptTypes,
    // INT_NMI does not exist in the spec, it's a modeling artifact for NMI. We
    // intentionally set it to be NumInterruptTypes so it can never conflict
    // with any real INT_NUM in used.
    INT_NMI = NumInterruptTypes,
};

enum class FaultType
{
    INTERRUPT,
    NON_MASKABLE_INTERRUPT,
    OTHERS,
};

class RiscvFault : public FaultBase
{
  protected:
    const FaultName _name;
    const FaultType _fault_type;
    ExceptionCode _code;

    RiscvFault(FaultName n, FaultType ft, ExceptionCode c)
        : _name(n), _fault_type(ft), _code(c)
    {}

    FaultName name() const override { return _name; }
    bool isInterrupt() const { return _fault_type == FaultType::INTERRUPT; }
    bool isNonMaskableInterrupt() const
    {
        return _fault_type == FaultType::NON_MASKABLE_INTERRUPT;
    }
    ExceptionCode exception() const { return _code; }
    virtual RegVal trap_value() const { return 0; }

    virtual void invokeSE(ThreadContext *tc, const StaticInstPtr &inst);
    void invoke(ThreadContext *tc, const StaticInstPtr &inst) override;
};

class Reset : public FaultBase
{
  private:
    const FaultName _name;

  public:
    Reset() : _name("reset") {}
    FaultName name() const override { return _name; }

    void invoke(ThreadContext *tc, const StaticInstPtr &inst =
        nullStaticInstPtr) override;
};

class InterruptFault : public RiscvFault
{
  public:
    InterruptFault(ExceptionCode c)
        : RiscvFault("interrupt", FaultType::INTERRUPT, c)
    {}
    InterruptFault(int c) : InterruptFault(static_cast<ExceptionCode>(c)) {}
};

class NonMaskableInterruptFault : public RiscvFault
{
  public:
    NonMaskableInterruptFault()
        : RiscvFault("non_maskable_interrupt",
                     FaultType::NON_MASKABLE_INTERRUPT,
                     static_cast<ExceptionCode>(0))
    {}
};

class InstFault : public RiscvFault
{
  protected:
    const ExtMachInst _inst;

  public:
    InstFault(FaultName n, const ExtMachInst inst)
        : RiscvFault(n, FaultType::OTHERS, INST_ILLEGAL), _inst(inst)
    {}

    RegVal trap_value() const override { return _inst.instBits; }
};

class UnknownInstFault : public InstFault
{
  public:
    UnknownInstFault(const ExtMachInst inst)
        : InstFault("Unknown instruction", inst)
    {}

    void invokeSE(ThreadContext *tc, const StaticInstPtr &inst) override;
};

class IllegalInstFault : public InstFault
{
  private:
    const std::string reason;

  public:
    IllegalInstFault(std::string r, const ExtMachInst inst)
        : InstFault("Illegal instruction", inst),
          reason(r)
    {}

    void invokeSE(ThreadContext *tc, const StaticInstPtr &inst) override;
};

class UnimplementedFault : public InstFault
{
  private:
    const std::string instName;

  public:
    UnimplementedFault(std::string name, const ExtMachInst inst)
        : InstFault("Unimplemented instruction", inst),
          instName(name)
    {}

    void invokeSE(ThreadContext *tc, const StaticInstPtr &inst) override;
};

class IllegalFrmFault: public InstFault
{
  private:
    const uint8_t frm;

  public:
    IllegalFrmFault(uint8_t r, const ExtMachInst inst)
        : InstFault("Illegal floating-point rounding mode", inst),
          frm(r)
    {}

    void invokeSE(ThreadContext *tc, const StaticInstPtr &inst) override;
};

class AddressFault : public RiscvFault
{
  private:
    const Addr _addr;

  public:
    AddressFault(const Addr addr, ExceptionCode code)
        : RiscvFault("Address", FaultType::OTHERS, code), _addr(addr)
    {}

    RegVal trap_value() const override { return _addr; }
};

class BreakpointFault : public RiscvFault
{
  private:
    const PCState pcState;

  public:
    BreakpointFault(const PCStateBase &pc)
        : RiscvFault("Breakpoint", FaultType::OTHERS, BREAKPOINT),
        pcState(pc.as<PCState>())
    {}

    RegVal trap_value() const override { return pcState.pc(); }
    void invokeSE(ThreadContext *tc, const StaticInstPtr &inst) override;
};

class SyscallFault : public RiscvFault
{
  public:
    SyscallFault(CHERIPrivilegeMode prv)
        : RiscvFault("System call", FaultType::OTHERS, ECALL_USER)
    {
        switch (prv) {
          case PRV_U:
            _code = ECALL_USER;
            break;
          case PRV_S:
            _code = ECALL_SUPER;
            break;
          case PRV_M:
            _code = ECALL_MACHINE;
            break;
          default:
            panic("Unknown privilege mode %d.", prv);
            break;
        }
    }

    void invokeSE(ThreadContext *tc, const StaticInstPtr &inst) override;
};

// CHERI capability exception (ISAv9): xCAUSE = 28 and
// xTVAL = {cap_idx[10:5], cause[4:0]}, where cap_idx is the capability
// register that authorised the operation (0-31), or 32 + the special
// capability register index (PCC = 32, DDC = 33, ...). This is what
// CheriBSD's TVAL_CAP_CAUSE()/TVAL_CAP_IDX() decode into SIGPROT si_code /
// si_capreg.
class CheriCapFault : public RiscvFault
{
  private:
    const CheriCapException _cheri_code;
    const int _cap_reg; // capability register index (see above)
    const Addr _addr;   // faulting address, for debugging only

  public:
    CheriCapFault(CheriCapException code, int capReg = 0, Addr addr = 0)
        : RiscvFault("cheri_cap", FaultType::OTHERS, CHERI_CAPABILITY),
          _cheri_code(code), _cap_reg(capReg < 0 ? 0 : capReg), _addr(addr)
    {}

    CheriCapException cheriCode() const { return _cheri_code; }
    int capReg() const { return _cap_reg; }
    Addr faultAddr() const { return _addr; }

    RegVal
    trap_value() const override
    {
        return ((RegVal(_cap_reg) & 0x3f) << 5) |
               (RegVal(_cheri_code) & 0x1f);
    }
    void invokeSE(ThreadContext *tc, const StaticInstPtr &inst) override;
};

// Whether CHERI capability exceptions are raised for code running at the
// current privilege level. All checks funnel through here so the remaining
// bring-up relaxation lives in one place.
bool cheriEnforcing(ThreadContext *tc);
bool cheriEnforcingAt(CHERIPrivilegeMode prv);

// Turn the result of a capability check into a fault: NoFault when `code` is
// None or enforcement is off (cheriEnforcing()), else a CheriCapFault naming
// capability register `capReg`. `addr` is informational.
Fault capEnforce(ThreadContext *tc, CheriCapException code,
                 int capReg = 0, Addr addr = 0);

// Check a data memory access of `size` bytes at `ea` authorised by `auth`,
// the value of capability register `capIdx` (the index is reported in
// xTVAL). `acc` is a mask of CheriAccess flags (cheri_checks.hh); `stored`
// is the capability being written by a capability store. Callers pass the
// operand value they read, so this works on pipelined/out-of-order CPUs.
Fault cheriCheckMem(ThreadContext *tc, const CapRegContainer &auth,
                    int capIdx, Addr ea, unsigned size, unsigned acc,
                    const CapRegContainer *stored = nullptr);

// Check an indirect jump through capability register `capIdx` (value
// `target`) with immediate `imm`.
Fault cheriCheckJump(ThreadContext *tc, const CapRegContainer &target,
                     int capIdx, int64_t imm);

/**
 * Returns true if the fault passed as a first argument was triggered
 * by a memory access, false otherwise.
 * If true it is storing the faulting address in the va argument
 *
 * @param fault generated fault
 * @param va function will modify this passed-by-reference parameter
 *           with the correct faulting virtual address
 * @return true if va contains a valid value, false otherwise
 */
bool getFaultVAddr(Fault fault, Addr &va);

} // namespace CHERIRiscvISA
} // namespace gem5

#endif // __ARCH_RISCV_CHERI_FAULTS_HH__
