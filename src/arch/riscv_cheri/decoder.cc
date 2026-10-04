/*
 * Copyright (c) 2012 Google
 * Copyright (c) The University of Virginia
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

#include "arch/riscv_cheri/decoder.hh"

#include "arch/riscv_cheri/cheri_checks.hh"
#include "arch/riscv_cheri/faults.hh"
#include "arch/riscv_cheri/insts/pseudo.hh"
#include "arch/riscv_cheri/isa.hh"
#include "arch/riscv_cheri/regs/misc.hh"
#include "arch/riscv_cheri/types.hh"
#include "base/bitfield.hh"
#include "debug/Decode.hh"
#include "debug/Faults.hh"
#include "sim/full_system.hh"

namespace gem5
{

namespace CHERIRiscvISA
{

namespace
{

// Stands in for an instruction whose fetch PCC does not authorise it:
// executing it raises the CHERI exception against PCC (cap_idx 32). Doing the
// check at decode covers every fetched instruction, including the second
// half-word instruction of a parcel the CPU already fetched.
class CheriFetchFault : public PseudoOp
{
  private:
    const CheriCapException code;

  public:
    CheriFetchFault(ExtMachInst mach_inst, CheriCapException _code)
        : PseudoOp("cheri_fetch_fault", mach_inst, No_OpClass), code(_code)
    {
        flags[IsNonSpeculative] = true;
    }

    Fault
    execute(ExecContext *, trace::InstRecord *) const override
    {
        return std::make_shared<CheriCapFault>(code, CHERI_CAPIDX_PCC);
    }
};

} // anonymous namespace

Decoder::Decoder(const CHERIRiscvDecoderParams &p) : InstDecoder(p, &machInst)
{
    isa = dynamic_cast<ISA*>(p.isa);
    vlen = isa->getVecLenInBits();
    elen = isa->getVecElemLenInBits();
    reset();
}

void Decoder::reset()
{
    aligned = true;
    mid = false;
    machInst = 0;
    emi = 0;
}

void
Decoder::moreBytes(const PCStateBase &pc, Addr fetchPC)
{
    // The MSB of the upper and lower halves of a machine instruction.
    constexpr size_t max_bit = sizeof(machInst) * 8 - 1;
    constexpr size_t mid_bit = sizeof(machInst) * 4 - 1;

    auto inst = letoh(machInst);
    DPRINTF(Decode, "Requesting bytes 0x%08x from address %#x\n", inst,
            fetchPC);

    bool aligned = pc.instAddr() % sizeof(machInst) == 0;
    if (aligned) {
        emi.instBits = inst;
        if (compressed(inst))
            emi.instBits = bits(inst, mid_bit, 0);
        outOfBytes = !compressed(emi);
        instDone = true;
    } else {
        if (mid) {
            assert(bits(emi.instBits, max_bit, mid_bit + 1) == 0);
            replaceBits(emi.instBits, max_bit, mid_bit + 1, inst);
            mid = false;
            outOfBytes = false;
            instDone = true;
        } else {
            emi.instBits = bits(inst, max_bit, mid_bit + 1);
            mid = !compressed(emi);
            outOfBytes = true;
            instDone = compressed(emi);
        }
    }
}

StaticInstPtr
Decoder::decode(ExtMachInst mach_inst, Addr addr)
{
    DPRINTF(Decode, "Decoding instruction 0x%08x at address %#x\n",
            mach_inst.instBits, addr);

    StaticInstPtr &si = instMap[mach_inst];
    if (!si)
        si = decodeInst(mach_inst);

    si->size(compressed(mach_inst) ? 2 : 4);

    DPRINTF(Decode, "Decode: Decoded %s instruction: %#x\n",
            si->getName(), mach_inst);
    return si;
}

StaticInstPtr
Decoder::decode(PCStateBase &_next_pc)
{
    if (!instDone)
        return nullptr;
    instDone = false;

    auto &next_pc = _next_pc.as<PCState>();

    if (compressed(emi)) {
        next_pc.npc(next_pc.instAddr() + sizeof(machInst) / 2);
        next_pc.compressed(true);
    } else {
        next_pc.npc(next_pc.instAddr() + sizeof(machInst));
        next_pc.compressed(false);
    }

    emi.vl      = next_pc.vl();
    emi.vtype8  = next_pc.vtype() & 0xff;
    emi.vill    = next_pc.vtype().vill;
    emi.rv_type = static_cast<int>(next_pc.rvType());

    StaticInstPtr si = decode(emi, next_pc.instAddr());

    // CHERI: the whole instruction must lie within PCC, and PCC must be a
    // tagged, unsealed, executable capability.
    if (FullSystem && cheriEnforcingAt((CHERIPrivilegeMode)
                isa->readMiscRegNoEffect(MISCREG_PRV))) {
        CapRegContainer pcc = next_pc.pcc();
        pcc.setAddress(next_pc.instAddr());
        CheriCapException code =
            capCheckFetch(pcc, next_pc.instAddr(), si->size());
        if (code != CheriCapException::None) {
            CapBounds b = capDecodeBounds(pcc);
            DPRINTF(Faults, "CHERI fetch violation cause %#x pc %#x size %d "
                    "PCC %s base %#x top %#x%016x otype %#x perms %#x\n",
                    (unsigned)code, next_pc.instAddr(), (int)si->size(),
                    pcc.getString(), b.base, (uint64_t)(b.top >> 64),
                    (uint64_t)b.top, capOtype(pcc), capPerms(pcc));
            StaticInstPtr fault_si = new CheriFetchFault(emi, code);
            fault_si->size(si->size());
            return fault_si;
        }
    }
    return si;
}

} // namespace CHERIRiscvISA
} // namespace gem5
