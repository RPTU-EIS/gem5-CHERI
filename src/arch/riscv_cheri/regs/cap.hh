/*
 * Copyright (c) 2013 ARM Limited
 * Copyright (c) 2014-2015 Sven Karlsson
 * Copyright (c) 2019 Yifei Liu
 * Copyright (c) 2020 Barkhausen Institut
 * Copyright (c) 2021 StreamComputing Corp
 * All rights reserved
 *
 * The license below extends only to copyright in the software and shall
 * not be construed as granting a license to any other intellectual
 * property including but not limited to intellectual property relating
 * to a hardware implementation of the functionality of the software
 * licensed hereunder.  You may use the software subject to the license
 * terms below provided that you ensure that this notice is replicated
 * unmodified and in its entirety in all distributions of the software,
 * modified or unmodified, in source code or in binary form.
 *
 * Copyright (c) 2016 RISC-V Foundation
 * Copyright (c) 2016 The University of Virginia
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

#ifndef __ARCH_RISCV_CHERI_REGS_CAP_HH__
#define __ARCH_RISCV_CHERI_REGS_CAP_HH__

#include <string>
#include <vector>

#include "base/bitunion.hh"
#include "cpu/reg_class.hh"
#include "debug/CapRegs.hh"

namespace gem5
{

    namespace CHERIRiscvISA
    {

        namespace cap_reg
        {

            enum : RegIndex
            {
                _CNullIdx, _CRaIdx, _CSpIdx,  _CGpIdx,
                _CTpIdx,   _CT0Idx, _CT1Idx,  _CT2Idx,
                _CS0Idx,   _CS1Idx, _CA0Idx,  _CA1Idx,
                _CA2Idx,   _CA3Idx, _CA4Idx,  _CA5Idx,
                _CA6Idx,   _CA7Idx, _CS2Idx,  _CS3Idx,
                _CS4Idx,   _CS5Idx, _CS6Idx,  _CS7Idx,
                _CS8Idx,   _CS9Idx, _CS10Idx, _CS11Idx,
                _CT3Idx,   _CT4Idx, _CT5Idx,  _CT6Idx,

                NumArchCapRegs,

                _CUreg0Idx = NumArchCapRegs,

                _CNullDataIdx, _CRaDataIdx, _CSpDataIdx,  _CGpDataIdx,
                _CTpDataIdx,   _CT0DataIdx, _CT1DataIdx,  _CT2DataIdx,
                _CS0DataIdx,   _CS1DataIdx, _CA0DataIdx,  _CA1DataIdx,
                _CA2DataIdx,   _CA3DataIdx, _CA4DataIdx,  _CA5DataIdx,
                _CA6DataIdx,   _CA7DataIdx, _CS2DataIdx,  _CS3DataIdx,
                _CS4DataIdx,   _CS5DataIdx, _CS6DataIdx,  _CS7DataIdx,
                _CS8DataIdx,   _CS9DataIdx, _CS10DataIdx, _CS11DataIdx,
                _CT3DataIdx,   _CT4DataIdx, _CT5DataIdx,  _CT6DataIdx,

                _CNullTagIdx, _CRaTagIdx, _CSpTagIdx,  _CGpTagIdx,
                _CTpTagIdx,   _CT0TagIdx, _CT1TagIdx,  _CT2TagIdx,
                _CS0TagIdx,   _CS1TagIdx, _CA0TagIdx,  _CA1TagIdx,
                _CA2TagIdx,   _CA3TagIdx, _CA4TagIdx,  _CA5TagIdx,
                _CA6TagIdx,   _CA7TagIdx, _CS2TagIdx,  _CS3TagIdx,
                _CS4TagIdx,   _CS5TagIdx, _CS6TagIdx,  _CS7TagIdx,
                _CS8TagIdx,   _CS9TagIdx, _CS10TagIdx, _CS11TagIdx,
                _CT3TagIdx,   _CT4TagIdx, _CT5TagIdx,  _CT6TagIdx,

                NumCapRegs
            };

        } // namespace cap_reg

        inline constexpr RegClass capRegClass(CapRegClass, CapRegClassName,
                cap_reg::NumCapRegs, debug::CapRegs);

        namespace cap_reg
        {

            inline constexpr RegId
                CNull = capRegClass[_CNullIdx],
                    CRa = capRegClass[_CRaIdx],
                    CSp = capRegClass[_CSpIdx],
                    CGp = capRegClass[_CGpIdx],
                    CTp = capRegClass[_CTpIdx],
                    CT0 = capRegClass[_CT0Idx],
                    CT1 = capRegClass[_CT1Idx],
                    CT2 = capRegClass[_CT2Idx],
                    CS0 = capRegClass[_CS0Idx],
                    CS1 = capRegClass[_CS1Idx],
                    CA0 = capRegClass[_CA0Idx],
                    CA1 = capRegClass[_CA1Idx],
                    CA2 = capRegClass[_CA2Idx],
                    CA3 = capRegClass[_CA3Idx],
                    CA4 = capRegClass[_CA4Idx],
                    CA5 = capRegClass[_CA5Idx],
                    CA6 = capRegClass[_CA6Idx],
                    CA7 = capRegClass[_CA7Idx],
                    CS2 = capRegClass[_CS2Idx],
                    CS3 = capRegClass[_CS3Idx],
                    CS4 = capRegClass[_CS4Idx],
                    CS5 = capRegClass[_CS5Idx],
                    CS6 = capRegClass[_CS6Idx],
                    CS7 = capRegClass[_CS7Idx],
                    CS8 = capRegClass[_CS8Idx],
                    CS9 = capRegClass[_CS9Idx],
                    CS10 = capRegClass[_CS10Idx],
                    CS11 = capRegClass[_CS11Idx],
                    CT3 = capRegClass[_CT3Idx],
                    CT4 = capRegClass[_CT4Idx],
                    CT5 = capRegClass[_CT5Idx],
                    CT6 = capRegClass[_CT6Idx],
                    CUreg0 = capRegClass[_CUreg0Idx],
                    //Additional Registers for the
                    // information going alongside the address
            CNullData = capRegClass[_CNullDataIdx],
                    CRaData = capRegClass[_CRaDataIdx],
                    CSpData = capRegClass[_CSpDataIdx],
                    CGpData = capRegClass[_CGpDataIdx],
                    CTpData = capRegClass[_CTpDataIdx],
                    CT0Data = capRegClass[_CT0DataIdx],
                    CT1Data = capRegClass[_CT1DataIdx],
                    CT2Data = capRegClass[_CT2DataIdx],
                    CS0Data = capRegClass[_CS0DataIdx],
                    CS1Data = capRegClass[_CS1DataIdx],
                    CA0Data = capRegClass[_CA0DataIdx],
                    CA1Data = capRegClass[_CA1DataIdx],
                    CA2Data = capRegClass[_CA2DataIdx],
                    CA3Data = capRegClass[_CA3DataIdx],
                    CA4Data = capRegClass[_CA4DataIdx],
                    CA5Data = capRegClass[_CA5DataIdx],
                    CA6Data = capRegClass[_CA6DataIdx],
                    CA7Data = capRegClass[_CA7DataIdx],
                    CS2Data = capRegClass[_CS2DataIdx],
                    CS3Data = capRegClass[_CS3DataIdx],
                    CS4Data = capRegClass[_CS4DataIdx],
                    CS5Data = capRegClass[_CS5DataIdx],
                    CS6Data = capRegClass[_CS6DataIdx],
                    CS7Data = capRegClass[_CS7DataIdx],
                    CS8Data = capRegClass[_CS8DataIdx],
                    CS9Data = capRegClass[_CS9DataIdx],
                    CS10Data = capRegClass[_CS10DataIdx],
                    CS11Data = capRegClass[_CS11DataIdx],
                    CT3Data = capRegClass[_CT3DataIdx],
                    CT4Data = capRegClass[_CT4DataIdx],
                    CT5Data = capRegClass[_CT5DataIdx],
                    CT6Data = capRegClass[_CT6DataIdx],
                //Additional Registers for the tags
                CNullTag = capRegClass[_CNullTagIdx],
                    CRaTag = capRegClass[_CRaTagIdx],
                    CSpTag = capRegClass[_CSpTagIdx],
                    CGpTag = capRegClass[_CGpTagIdx],
                    CTpTag = capRegClass[_CTpTagIdx],
                    CT0Tag = capRegClass[_CT0TagIdx],
                    CT1Tag = capRegClass[_CT1TagIdx],
                    CT2Tag = capRegClass[_CT2TagIdx],
                    CS0Tag = capRegClass[_CS0TagIdx],
                    CS1Tag = capRegClass[_CS1TagIdx],
                    CA0Tag = capRegClass[_CA0TagIdx],
                    CA1Tag = capRegClass[_CA1TagIdx],
                    CA2Tag = capRegClass[_CA2TagIdx],
                    CA3Tag = capRegClass[_CA3TagIdx],
                    CA4Tag = capRegClass[_CA4TagIdx],
                    CA5Tag = capRegClass[_CA5TagIdx],
                    CA6Tag = capRegClass[_CA6TagIdx],
                    CA7Tag = capRegClass[_CA7TagIdx],
                    CS2Tag = capRegClass[_CS2TagIdx],
                    CS3Tag = capRegClass[_CS3TagIdx],
                    CS4Tag = capRegClass[_CS4TagIdx],
                    CS5Tag = capRegClass[_CS5TagIdx],
                    CS6Tag = capRegClass[_CS6TagIdx],
                    CS7Tag = capRegClass[_CS7TagIdx],
                    CS8Tag = capRegClass[_CS8TagIdx],
                    CS9Tag = capRegClass[_CS9TagIdx],
                    CS10Tag = capRegClass[_CS10TagIdx],
                    CS11Tag = capRegClass[_CS11TagIdx],
                    CT3Tag = capRegClass[_CT3TagIdx],
                    CT4Tag = capRegClass[_CT4TagIdx],
                    CT5Tag = capRegClass[_CT5TagIdx],
                    CT6Tag = capRegClass[_CT6TagIdx];

            const std::vector<std::string> RegNames = {
                    "cnull", "cra", "csp", "cgp",
                    "ctp", "ct0", "ct1", "ct2",
                    "cs0", "cs1", "ca0", "ca1",
                    "ca2", "ca3", "ca4", "ca5",
                    "ca6", "ca7", "cs2", "cs3",
                    "cs4", "cs5", "cs6", "cs7",
                    "cs8", "cs9", "cs10", "cs11",
                    "ct3", "ct4", "ct5", "ct6"
            };

        } // namespace cap_reg

// Semantically meaningful register indices
        inline constexpr auto
                &ReturnAddrCap = cap_reg::CRa,
                &StackPointerCap = cap_reg::CSp,
                &ThreadPointerCap = cap_reg::CTp,
                &ReturnValueCap = cap_reg::CA0,
                &AMOTempCap = cap_reg::CUreg0,
                &SyscallNumCap = cap_reg::CA7;

        inline constexpr RegId CapArgumentRegs[] = {
        cap_reg::CA0, cap_reg::CA1, cap_reg::CA2, cap_reg::CA3,
        cap_reg::CA4, cap_reg::CA5, cap_reg::CA6, cap_reg::CA7
    };

    //! CHERI Concentrate Register
    BitUnion64(CAPTYPE)
    Bitfield<63, 48> perm;
    Bitfield<47> flag;
    Bitfield<46, 45> reserved;
    Bitfield<44, 27> otype;
    Bitfield<26> IE;
    Bitfield<25, 17> T;
    Bitfield<16, 14> TE;
    Bitfield<13, 3> B;
    Bitfield<2, 0> BE;
    EndBitUnion(CAPTYPE)


} // namespace CHERIRiscvISA
} // namespace gem5

#endif // __ARCH_RISCV_CHERI_REGS_CAP_HH__
