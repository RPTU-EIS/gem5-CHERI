#ifndef __ARCH_RISCV_CHERI_DEFS_HH__
#define __ARCH_RISCV_CHERI_DEFS_HH__

#include <cstdint>
#include "base/bitunion.hh"

namespace gem5
{

// Permission bits
namespace CHERIPerms
{
    constexpr uint32_t GLOBAL        = 1 << 0;
    constexpr uint32_t EXECUTE       = 1 << 1;
    constexpr uint32_t LOAD          = 1 << 2;
    constexpr uint32_t STORE         = 1 << 3;
    constexpr uint32_t LOAD_CAP      = 1 << 4;
    constexpr uint32_t STORE_CAP     = 1 << 5;
    constexpr uint32_t STORE_LOCAL   = 1 << 6;
    constexpr uint32_t SEAL          = 1 << 7;
    constexpr uint32_t CINVOKE       = 1 << 8;
    constexpr uint32_t UNSEAL        = 1 << 9;
    constexpr uint32_t ASR           = 1 << 10;
    constexpr uint32_t SETCID        = 1 << 11;
    constexpr uint32_t ALL           = 0xFFF;

    // Software-defined permissions; CheriBSD requires bit 15 in PCC
    // for system calls, so the root capability carries them.
    constexpr uint32_t SW            = 0xF000;      // bits 12-15
    constexpr uint32_t ALL_WITH_SW   = ALL | SW;   // 0xFFFF
}

// Metadata layout, matching the CAPTYPE bitunion (CC128)
namespace CHERIMeta
{
    constexpr int PERM_SHIFT = 48;
    constexpr uint64_t PERM_MASK = 0xFFFFULL;

    constexpr int OTYPE_SHIFT = 27;
    constexpr uint64_t OTYPE_MASK = 0x3FFFFULL;
    constexpr uint64_t OTYPE_UNSEALED = 0x3FFFFULL;

    // ISAv9 reserved object types (CHERI_OTYPE_SENTRY == -2 in CheriBSD's
    // cherireg.h); -3 and -4 are reserved and behave as sealed.
    constexpr uint64_t OTYPE_SENTRY       = 0x3FFFEULL;

    // Pre-ISAv9 sentry flavours; not produced by any instruction here.
    constexpr uint64_t OTYPE_SENTRY_INTER = 0x3FFFDULL;
    constexpr uint64_t OTYPE_SENTRY_BACK  = 0x3FFFCULL;
    constexpr uint64_t OTYPE_SENTRY_FWD   = 0x3FFFBULL;
}

// Capability exception codes
namespace CHERIRiscvISA
{
    enum CheriCapException : uint64_t
    {
        None = 0x00,
        LengthViolation,
        TagViolation,
        SealViolation,
        TypeViolation,
        SoftwareDefinedPermissionViolation = 0x08,
        GlobalViolation = 0x10,
        PermitExecuteViolation,
        PermitLoadViolation,
        PermitStoreViolation,
        PermitLoadCapViolation,
        PermitStoreCapViolation,
        PermitStoreLocalViolation,
        PermitAccessSystemRegistersViolation = 0x18,
        PermitInvokeViolation,
        PermitSetCIDViolation = 0x1c
    };
}


namespace CHERIRiscvISA
{
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
}

} // namespace gem5

#endif // __ARCH_RISCV_CHERI_DEFS_HH__
