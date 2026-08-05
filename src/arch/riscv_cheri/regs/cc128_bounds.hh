/*
 * CHERI Concentrate (CC128) bounds compression helpers.
 *
 * These are shared, self-consistent encode/decode routines for the 128-bit
 * compressed-capability bounds. The format matches the reference
 * CTSRD-CHERI/cheri-compressed-cap CC128 layout:
 *
 *   metadata bit 26      : IE (internal exponent) flag
 *   metadata bits 25..14 : TOP field    (T=25..17, TE=16..14)
 *   metadata bits 13..0  : BOTTOM field (B=13..3,  BE=2..0)
 *   MANTISSA_WIDTH = 14, MAX_EXPONENT = 52, no LEN_MSB.
 *
 * The DECODE below is byte-for-byte the same math the cgetbase / cgetlen /
 * cgettop / cincoffset decoders use, so anything this header encodes will
 * round-trip through those instructions.
 *
 * The ENCODE picks the smallest exponent whose encoding decodes back to
 * exactly [req_base, req_base+req_length). Representability in CC128 depends
 * on base alignment, not just length (a page-sized region needs IE=1 even at
 * E=0), so rather than a closed-form E = f(length) -- which has gaps and bit
 * us before -- we verify each candidate against the real decode. This mirrors
 * the reference's iterative "incE" step but guarantees consistency with our
 * own decoder.
 */
#ifndef __ARCH_RISCV_CHERI_REGS_CC128_BOUNDS_HH__
#define __ARCH_RISCV_CHERI_REGS_CC128_BOUNDS_HH__

#include <cstdint>

#include "arch/generic/cheri_defs.hh"

namespace gem5
{
namespace CHERIRiscvISA
{

// Decode [base, top) from a capability address and metadata. This is the exact
// reconstruction cgetbase/cgetlen use; keep the two in sync.
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
        L_carry_out = (T < B) ? 1 : 0;
        L_msb = 0;
    } else {
        E = (T_E << 3) | B_E;
        T = T_hi << 3;
        B = B_hi << 3;
        L_carry_out = (T_hi < B_hi) ? 1 : 0;
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

    // Guard every shift: during encoding we probe exponents up to 52, so
    // E+14 can reach/exceed 64 (a shift >= width is undefined in C++). Real
    // capabilities only ever use a small E, so clamping the out-of-range high
    // part to 0 never affects a selected encoding.
    uint64_t sh_hi  = E + 14;
    uint64_t a_top  = (sh_hi >= 64) ? 0 : (addr >> sh_hi);
    uint64_t base_hi = (sh_hi >= 64) ? 0 : (((a_top + (uint64_t)c_b) & 0xFFFFFFFFFFFFFFFFULL) << sh_hi);
    uint64_t top_hi  = (sh_hi >= 64) ? 0 : (((a_top + (uint64_t)c_t) & 0xFFFFFFFFFFFFFFFFULL) << sh_hi);
    uint64_t base_lo = (E >= 64) ? 0 : (B << E);
    uint64_t top_lo  = (E >= 64) ? 0 : (T << E);
    out_base = base_hi | base_lo;
    out_top  = top_hi | top_lo;
}

// Build candidate bounds metadata for a given exponent and IE choice, keeping
// the non-bounds fields (perms/otype/...) from src.
inline CAPTYPE
cc128BuildMeta(CAPTYPE src, uint64_t E, bool ie,
               uint64_t req_base, uint64_t req_top)
{
    CAPTYPE m = src;
    if (!ie) {
        // IE == 0: E is 0, B is 14 bits, T is 12 bits (top 2 reconstructed).
        uint64_t Bm = req_base & 0x3FFFULL;
        uint64_t Tm = req_top  & 0x3FFFULL;
        m.IE = 0;
        m.BE = Bm & 0x7;
        m.B  = (Bm >> 3) & 0x7FF;
        m.TE = Tm & 0x7;
        m.T  = (Tm >> 3) & 0x1FF;
    } else {
        // IE == 1: low 3 bits of TOP/BOTTOM hold E; mantissas lose 3 bits.
        uint64_t sh    = E + 3;
        uint64_t tmask = (sh >= 64) ? ~0ULL : ((1ULL << sh) - 1);
        uint64_t Bm    = (sh >= 64) ? 0 : ((req_base >> sh) & 0x7FFULL);
        uint64_t Tm    = (sh >= 64) ? 0 : ((req_top  >> sh) & 0x7FFULL);
        if (req_top & tmask)            // round the top up if bits are lost
            Tm = (Tm + 1) & 0x7FFULL;
        m.IE = 1;
        m.BE = E & 0x7;                 // exponent low part
        m.TE = (E >> 3) & 0x7;          // exponent high part
        m.B  = Bm & 0x7FF;              // 11-bit bottom mantissa
        m.T  = Tm & 0x1FF;              // 9-bit top mantissa (2 more reconstructed)
    }
    return m;
}

// Encode [req_base, req_base+req_length) into src's bounds fields. Picks the
// smallest exponent that decodes back exactly; if no exponent is exact
// (unusual for the aligned allocations a kernel makes), returns the smallest
// exponent that at least COVERS the region and sets *exact=false.
inline CAPTYPE
cc128EncodeBounds(CAPTYPE src, uint64_t req_base, uint64_t req_length,
                  bool *exact)
{
    uint64_t req_top = req_base + req_length;

    bool have_cover = false;
    CAPTYPE cover_meta = src;

    for (uint64_t E = 0; E <= 52; E++) {
        // At E==0 an IE==0 encoding may be exact; otherwise use IE==1.
        for (int ie = (E == 0 ? 0 : 1); ie <= 1; ie++) {
            CAPTYPE cand = cc128BuildMeta(src, E, ie != 0, req_base, req_top);
            uint64_t db, dt;
            cc128DecodeBounds(req_base, cand, db, dt);
            if (db == req_base && dt == req_top) {
                if (exact) *exact = true;
                return cand;
            }
            if (!have_cover && db <= req_base && dt >= req_top) {
                have_cover = true;
                cover_meta = cand;
            }
        }
    }

    if (exact) *exact = false;
    return have_cover ? cover_meta : src;
}

} // namespace CHERIRiscvISA
} // namespace gem5

#endif // __ARCH_RISCV_CHERI_REGS_CC128_BOUNDS_HH__
