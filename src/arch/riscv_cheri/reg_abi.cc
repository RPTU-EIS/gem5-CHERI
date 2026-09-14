/*
 * Copyright 2020 Google Inc.
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

#include "arch/riscv_cheri/reg_abi.hh"

#include "arch/riscv_cheri/regs/cap.hh"
#include "arch/riscv_cheri/regs/int.hh"

namespace gem5
{

namespace CHERIRiscvISA
{

// M5Op/pseudo-inst arguments are read through the merged register file's
// capability view (see reg_abi.hh's Argument<RegABI64, ...> override), so
// these need to be the capability RegIds, not the disconnected int_reg
// ones -- see arch/riscv_cheri/sbi.cc for the same pattern used by SBI
// ecalls.
const std::vector<RegId> RegABI64::ArgumentRegs = {
    cap_reg::CA0, cap_reg::CA1, cap_reg::CA2, cap_reg::CA3,
    cap_reg::CA4, cap_reg::CA5, cap_reg::CA6
};

const std::vector<RegId> RegABI32::ArgumentRegs = {
    int_reg::A0, int_reg::A1, int_reg::A2, int_reg::A3,
    int_reg::A4, int_reg::A5, int_reg::A6
};


} // namespace CHERIRiscvISA
} // namespace gem5
