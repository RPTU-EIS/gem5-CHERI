/*
 * Copyright (c) 2009 The Regents of The University of Michigan
 * Copyright (c) 2009 The University of Edinburgh
 * Copyright (c) 2014 Sven Karlsson
 * Copyright (c) 2016 RISC-V Foundation
 * Copyright (c) 2016 The University of Virginia
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

#ifndef __ARCH_RISCV_CHERI_ISA_HH__
#define __ARCH_RISCV_CHERI_ISA_HH__

#include <unordered_map>
#include <vector>

#include "arch/generic/isa.hh"
#include "arch/riscv_cheri/pcstate.hh"
#include "arch/riscv_cheri/regs/misc.hh"
#include "arch/riscv_cheri/regs/cap.hh"
#include "arch/generic/cap_reg.hh"
#include "arch/riscv_cheri/types.hh"
#include "base/types.hh"

namespace gem5
{

struct CHERIRiscvISAParams;
class Checkpoint;

namespace CHERIRiscvISA
{

enum CHERIPrivilegeMode
{
    PRV_U = 0,
    PRV_S = 1,
    PRV_M = 3
};

enum FPUStatus
{
    OFF = 0,
    INITIAL = 1,
    CLEAN = 2,
    DIRTY = 3,
};

using VPUStatus = FPUStatus;

class ISA : public BaseISA
{
  protected:
    CHERIRiscvType _rvType;
    std::vector<RegVal> miscRegFile;
    bool enableRvv;

    std::vector<CapRegContainer> capMiscRegFile;

    bool hpmCounterEnabled(int counter) const;

    // Load reserve - store conditional monitor
    const int WARN_FAILURE = 10000;
    const Addr INVALID_RESERVATION_ADDR = (Addr)-1;
    std::unordered_map<int, Addr> load_reservation_addrs;

    /** Length of each vector register in bits.
     *  VLEN in Ch. 2 of RISC-V vector spec
     */
    unsigned vlen;

    /** Length of each vector element in bits.
     *  ELEN in Ch. 2 of RISC-V vector spec
    */
    unsigned elen;

    /** The combination of privilege modes
     *  in Privilege Levels section of RISC-V privileged spec
     */
    CHERIPrivilegeModeSet _privilegeModeSet;

  public:
    using Params = CHERIRiscvISAParams;

    void clear() override;

    PCStateBase*
    newPCState(Addr new_inst_addr=0) const override
    {
        unsigned vlenb = vlen >> 3;
        return new PCState(new_inst_addr, _rvType, vlenb);
    }

  public:
    RegVal readMiscRegNoEffect(RegIndex idx) const override;
    RegVal readMiscReg(RegIndex idx) override;
    void setMiscRegNoEffect(RegIndex idx, RegVal val) override;
    void setMiscReg(RegIndex idx, RegVal val) override;

    // Misc registers that are capability registers. These are accessed by custom CSRs in the same way as other CSRs, but they are stored separately in the ISA class and accessed through separate read/set functions.
    CapRegContainer readCapMiscRegNoEffect(RegIndex idx) const;
    CapRegContainer readCapMiscReg(RegIndex idx);
    void setCapMiscRegNoEffect(RegIndex idx, const CapRegContainer& val);
    void setCapMiscReg(RegIndex idx, const CapRegContainer& val);

    bool isCapabilityMiscReg(RegIndex idx) const{
        return isCapMiscReg(idx);
    }

    // Get capability misc reg file index from MISCREG index
    int getCapMiscRegFileIndex(RegIndex idx) const{
        if (idx == MISCREG_PCC) return -1;  // PCC is special
        if (idx == MISCREG_DDC) return 0;
        if (idx >= MISCREG_UTCC && idx <= MISCREG_UEPCC) 
            return 1 + (idx - MISCREG_UTCC);
        if (idx >= MISCREG_STCC && idx <= MISCREG_SEPCC)
            return 5 + (idx - MISCREG_STCC);
        if (idx >= MISCREG_MTCC && idx <= MISCREG_MEPCC)
            return 9 + (idx - MISCREG_MTCC);
        return -1;  // Invalid
    }

    // Derived class could provide knowledge of non-standard CSRs to other
    // components by overriding the two getCSRxxxMap here and properly
    // implementing the corresponding read/set function. However, customized
    // maps should always be compatible with the standard maps.
    virtual const std::unordered_map<int, CSRMetadata>&
    getCSRDataMap() const
    {
        return CSRData;
    }
    virtual const std::unordered_map<int, RegVal>&
    getCSRMaskMap() const
    {
        return CSRMasks[_rvType][_privilegeModeSet];
    }

    bool inUserMode() const override;
    void copyRegsFrom(ThreadContext *src) override;

    void serialize(CheckpointOut &cp) const override;
    void unserialize(CheckpointIn &cp) override;

    ISA(const Params &p);

    void handleLockedRead(const RequestPtr &req) override;

    bool handleLockedWrite(const RequestPtr &req,
            Addr cacheBlockMask) override;

    void handleLockedSnoop(PacketPtr pkt, Addr cacheBlockMask) override;

    void globalClearExclusive() override;

    void resetThread() override;

    CHERIRiscvType rvType() const { return _rvType; }

    bool getEnableRvv() const { return enableRvv; }

    void
    clearLoadReservation(ContextID cid)
    {
        Addr& load_reservation_addr = load_reservation_addrs[cid];
        load_reservation_addr = INVALID_RESERVATION_ADDR;
    }

    /** Methods for getting VLEN, VLENB and ELEN values */
    unsigned getVecLenInBits() { return vlen; }
    unsigned getVecLenInBytes() { return vlen >> 3; }
    unsigned getVecElemLenInBits() { return elen; }

    int64_t getVectorLengthInBytes() const override { return vlen >> 3; }

    CHERIPrivilegeModeSet getPrivilegeModeSet() { return _privilegeModeSet; }

    virtual Addr getFaultHandlerAddr(
        RegIndex idx, uint64_t cause, bool intr) const;
};

} // namespace CHERIRiscvISA
} // namespace gem5

std::ostream &operator<<(std::ostream &os,
        gem5::CHERIRiscvISA::CHERIPrivilegeMode pm);

#endif // __ARCH_RISCV_CHERI_ISA_HH__
