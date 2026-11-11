/*
 * CHERI Concentrate (CC128) bounds encoding and decoding, following the
 * reference cheri-compressed-cap library (compute_ebt, compute_base_top).
 */
#ifndef __ARCH_RISCV_CHERI_REGS_CC128_BOUNDS_HH__
#define __ARCH_RISCV_CHERI_REGS_CC128_BOUNDS_HH__

#include <cstdint>

#include "arch/generic/cheri_defs.hh"

namespace gem5
{
namespace CHERIRiscvISA
{

// Decode [base, top) from a capability's address and metadata
inline void
cc128DecodeBounds(uint64_t addr, CAPTYPE meta,
                  uint64_t &out_base, uint64_t &out_top)
{
    uint64_t B_hi = meta.B;
    uint64_t T_hi = meta.T;
    uint64_t B_E  = meta.BE;
    uint64_t T_E  = meta.TE;
    uint64_t I_E  = meta.IE;

    uint64_t E, B, T, L_carry_out, L_msb;
    if (I_E == 0) {
        E = 0;
        T = (T_hi << 3) | T_E;
        B = (B_hi << 3) | B_E;
        L_carry_out = (T < (B & 0xFFF)) ? 1 : 0;
        L_msb = 0;
    } else {
        E = (T_E << 3) | B_E;
        T = T_hi << 3;
        B = B_hi << 3;
        L_carry_out = (T < (B & 0xFFF)) ? 1 : 0;
        L_msb = 1;
    }

    uint64_t B_top2 = (B >> 12) & 0x3;
    T |= ((B_top2 + L_carry_out + L_msb) & 0x3) << 12;

    uint64_t A_3 = (addr >> (E + 11)) & 0x7;
    uint64_t B_3 = (B >> 11) & 0x7;
    uint64_t T_3 = (T >> 11) & 0x7;
    uint64_t R   = (B_3 - 1) & 0x7;

    int64_t c_b;
    {
        bool cond1 = (A_3 < R);
        bool cond2 = (B_3 < R);
        if (!cond1 && !cond2) c_b = 0;
        else if (!cond1 && cond2) c_b = 1;
        else if (cond1 && !cond2) c_b = -1;
        else c_b = 0;
    }
    int64_t c_t;
    {
        bool cond1 = (A_3 < R);
        bool cond2 = (T_3 < R);
        if (!cond1 && !cond2) c_t = 0;
        else if (!cond1 && cond2) c_t = 1;
        else if (cond1 && !cond2) c_t = -1;
        else c_t = 0;
    }

    // Encoding probes E up to 52: guard shifts of 64 or more
    uint64_t sh_hi  = E + 14;
    uint64_t a_top  = (sh_hi >= 64) ? 0 : (addr >> sh_hi);
    uint64_t base_hi = (sh_hi >= 64) ? 0 : (((a_top + (uint64_t)c_b) & 0xFFFFFFFFFFFFFFFFULL) << sh_hi);
    uint64_t top_hi  = (sh_hi >= 64) ? 0 : (((a_top + (uint64_t)c_t) & 0xFFFFFFFFFFFFFFFFULL) << sh_hi);
    uint64_t base_lo = (E >= 64) ? 0 : (B << E);
    uint64_t top_lo  = (E >= 64) ? 0 : (T << E);
    out_base = base_hi | base_lo;
    out_top  = top_hi | top_lo;
}

// Exponent for a requested length (reference compute_e)
inline uint32_t
cc128GetExponent(uint64_t req_length)
{
    if (req_length < (1ULL << 13))
        return 0;
    return (uint32_t)(63 - __builtin_clzll(req_length)) - 12;
}

// Encode [req_base, req_base + req_length) into src's bounds (reference
// compute_ebt, with the incE step); *exact says whether it is exact.
inline CAPTYPE
cc128EncodeBounds(CAPTYPE src, uint64_t req_base, uint64_t req_length,
                  bool *exact)
{
    uint64_t req_top = req_base + req_length;
    uint32_t E = cc128GetExponent(req_length);
    // Internal exponent whenever E != 0, or the length already reaches bit 12
    // (a page-sized region needs IE even at E == 0).
    bool ie = (E != 0) || ((req_length >> 12) & 1);

    CAPTYPE m = src;

    if (!ie) {
        // IE == 0: B is 14 bits, T is 12 bits (top 2 reconstructed on decode).
        uint64_t bot = req_base & 0x3FFFULL;
        uint64_t top = req_top  & 0x0FFFULL;
        m.IE = 0;
        m.BE = bot & 0x7;
        m.B  = (bot >> 3) & 0x7FF;
        m.TE = top & 0x7;
        m.T  = (top >> 3) & 0x1FF;
        if (exact) *exact = true;
        return m;
    }

    const uint32_t LOW = 3;   // exponent low-part width (EXP_LOW_WIDTH)
    const uint32_t BW  = 11;  // internal-exponent mantissa width

    uint64_t bot = (req_base >> (E + LOW)) & 0x7FFULL;
    uint64_t top = (req_top  >> (E + LOW)) & 0x7FFULL;
    uint64_t maskLo = (1ULL << (E + LOW)) - 1;
    bool lostBase = (req_base & maskLo) != 0;
    bool lostTop  = (req_top  & maskLo) != 0;
    if (lostTop)
        top = (top + 1) & 0x7FFULL;

    uint64_t len_ie = (top - bot) & 0x7FFULL;
    uint32_t newE = E;
    if ((len_ie >> (BW - 1)) & 1) {
        // Length mantissa overflowed: increment E and recompute at +1 shift.
        lostBase = lostBase || (bot & 1);
        lostTop  = lostTop  || (top & 1);
        bot = (req_base >> (E + LOW + 1)) & 0x7FFULL;
        bool incT = lostTop;
        top = (req_top >> (E + LOW + 1)) & 0x7FFULL;
        if (incT)
            top = (top + 1) & 0x7FFULL;
        newE = E + 1;
    }

    m.IE = 1;
    m.BE = newE & 0x7;          // exponent low part
    m.TE = (newE >> 3) & 0x7;   // exponent high part
    m.B  = bot & 0x7FF;         // 11-bit bottom mantissa
    m.T  = top & 0x1FF;         // 9-bit top mantissa (2 more reconstructed)
    if (exact)
        *exact = !lostBase && !lostTop;
    return m;
}

// CRepresentableAlignmentMask: aligns a base down so that req_length is
// exactly representable (reference get_alignment_mask).
inline uint64_t
cc128AlignMask(uint64_t req_length)
{
    if (req_length == 0)
        return ~0ULL;
    uint32_t E = cc128GetExponent(req_length);
    bool ie = (E != 0) || ((req_length >> 12) & 1);
    if (!ie)
        return ~0ULL;   // E == 0, IE == 0: any base is representable.

    const uint32_t LOW = 3;
    const uint32_t BW  = 11;
    // req_base == 0 so bot == 0 and len_ie == top.
    uint64_t top = (req_length >> (E + LOW)) & 0x7FFULL;
    uint64_t maskLo = (1ULL << (E + LOW)) - 1;
    if (req_length & maskLo)
        top = (top + 1) & 0x7FFULL;
    if ((top >> (BW - 1)) & 1)
        return ~0ULL << (E + LOW + 1);
    return ~0ULL << (E + LOW);
}

// CRoundRepresentableLength: smallest length >= req_length that is exactly
// representable at a base aligned with cc128AlignMask(req_length). Mirrors the
// reference get_representable_length.
inline uint64_t
cc128RoundLength(uint64_t req_length)
{
    if (req_length == 0)
        return 0;
    uint64_t mask = cc128AlignMask(req_length);
    return (req_length + ~mask) & mask;
}

} // namespace CHERIRiscvISA
} // namespace gem5

#endif // __ARCH_RISCV_CHERI_REGS_CC128_BOUNDS_HH__
