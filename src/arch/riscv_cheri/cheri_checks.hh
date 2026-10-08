/*
 * CHERI-RISC-V (ISAv9) capability checks.
 *
 * Pure functions (no simulator state) that implement the architectural
 * checks performed on memory accesses, jumps and instruction fetch, in the
 * priority order of the Sail reference model (sail-cheri-riscv). They return
 * the CHERI exception cause; the caller decides whether to raise it (see
 * capEnforce() in faults.hh) and which capability register to report.
 *
 * Bounds are decoded with the reference CC128 algorithm (cheri-compressed-cap
 * compute_base_top) and a 65-bit top, so a capability whose top is 2^64 (the
 * root/almighty capability) is handled without special cases.
 *
 * Metadata convention: this model stores the null capability -- and every
 * integer written to the merged register file -- with metadata 0. On real
 * hardware those carry the null capability's pesbt (no permissions, unsealed,
 * bounds [0, 2^64)), which memory stores XORed with that same value so that it
 * reads back as 0. capPesbt() maps metadata 0 to that pesbt before any field
 * is interpreted, so null-derived values get ISAv9 semantics (unsealed,
 * otype -1, length 2^64).
 */

#ifndef __ARCH_RISCV_CHERI_CHERI_CHECKS_HH__
#define __ARCH_RISCV_CHERI_CHERI_CHECKS_HH__

#include <cstdint>

#include "arch/generic/cap_reg.hh"
#include "arch/generic/cheri_defs.hh"
#include "arch/riscv_cheri/regs/cc128_bounds.hh"

namespace gem5
{
namespace CHERIRiscvISA
{

typedef unsigned __int128 cap_len_t;

constexpr unsigned CC128_MANTISSA_WIDTH = 14;
constexpr unsigned CC128_MAX_EXPONENT = 52;

// pesbt of the null capability: no permissions, otype unsealed (-1), internal
// exponent with E = 52 and T = B = 0 (bounds [0, 2^64)).
constexpr uint64_t
cc128NullPesbt()
{
    return (uint64_t(CHERIMeta::OTYPE_UNSEALED) << CHERIMeta::OTYPE_SHIFT) |
           (uint64_t(1) << 26) |                         // IE
           (uint64_t((CC128_MAX_EXPONENT >> 3) & 7) << 14) |   // TE = E[5:3]
           uint64_t(CC128_MAX_EXPONENT & 7);             // BE = E[2:0]
}

inline uint64_t
capPesbt(uint64_t meta)
{
    return meta == 0 ? cc128NullPesbt() : meta;
}

inline uint32_t
capPerms(const CapRegContainer &c)
{
    return (capPesbt(c.getMetadata()) >> CHERIMeta::PERM_SHIFT) &
           CHERIMeta::PERM_MASK;
}

inline bool
capHasPerm(const CapRegContainer &c, uint32_t perm)
{
    return (capPerms(c) & perm) == perm;
}

inline uint32_t
capOtype(const CapRegContainer &c)
{
    return (capPesbt(c.getMetadata()) >> CHERIMeta::OTYPE_SHIFT) &
           CHERIMeta::OTYPE_MASK;
}

inline bool
capIsSealed(const CapRegContainer &c)
{
    return capOtype(c) != CHERIMeta::OTYPE_UNSEALED;
}

inline bool
capIsSentry(const CapRegContainer &c)
{
    return capOtype(c) == CHERIMeta::OTYPE_SENTRY;
}

struct CapBounds
{
    uint64_t base;
    cap_len_t top;  // up to 2^64 inclusive
};

// Reference cheri-compressed-cap CC128 compute_base_top().
inline CapBounds
capDecodeBounds(uint64_t addr, uint64_t meta_in)
{
    CAPTYPE meta = capPesbt(meta_in);
    const unsigned MW = CC128_MANTISSA_WIDTH;

    unsigned E;
    uint64_t B, T;
    unsigned lmsb;
    if (meta.IE == 0) {
        E = 0;
        B = (uint64_t(meta.B) << 3) | meta.BE;
        T = (uint64_t(meta.T) << 3) | meta.TE;
        lmsb = 0;
    } else {
        E = (unsigned(meta.TE) << 3) | unsigned(meta.BE);
        B = uint64_t(meta.B) << 3;
        T = uint64_t(meta.T) << 3;
        lmsb = 1;
    }
    // Reconstruct T[13:12] from B[13:12], the carry out of the low bits and
    // the implied length MSB.
    unsigned lcarry = (T & 0xFFF) < (B & 0xFFF) ? 1 : 0;
    T = (T & 0xFFF) | (uint64_t((((B >> 12) & 3) + lcarry + lmsb) & 3) << 12);

    if (E > CC128_MAX_EXPONENT)
        E = CC128_MAX_EXPONENT;

    unsigned a3 = (unsigned)((addr >> (E + MW - 3)) & 7);
    unsigned B3 = (unsigned)((B >> (MW - 3)) & 7);
    unsigned T3 = (unsigned)((T >> (MW - 3)) & 7);
    unsigned R3 = (B3 - 1) & 7;
    int aHi = a3 < R3 ? 1 : 0;
    int bHi = B3 < R3 ? 1 : 0;
    int tHi = T3 < R3 ? 1 : 0;
    int corr_base = bHi - aHi;
    int corr_top = tHi - aHi;

    unsigned a_top_shift = E + MW;
    uint64_t a_top = a_top_shift >= 64 ? 0 : addr >> a_top_shift;

    const cap_len_t len_mask = (cap_len_t(1) << 65) - 1;
    cap_len_t base = cap_len_t(uint64_t(int64_t(a_top) + corr_base));
    base = (((base << MW) | B) << E) & len_mask;
    cap_len_t top = cap_len_t(uint64_t(int64_t(a_top) + corr_top));
    top = (((top << MW) | T) << E) & len_mask;

    // If base and top are more than an address space apart, invert the MSB
    // of top (corrects for the representable region wrapping the space).
    unsigned base2 = (unsigned)((base >> 63) & 1);
    unsigned top2 = (unsigned)((top >> 63) & 3);
    if (E < (CC128_MAX_EXPONENT - 1) && ((top2 - base2) & 3) > 1)
        top ^= cap_len_t(1) << 64;

    return CapBounds{uint64_t(base), top};
}

inline CapBounds
capDecodeBounds(const CapRegContainer &c)
{
    return capDecodeBounds(c.getAddress(), c.getMetadata());
}

// Sail inCapBounds(): base <= addr && addr + size <= top (65-bit compare).
inline bool
capInBounds(const CapRegContainer &c, uint64_t addr, uint64_t size)
{
    CapBounds b = capDecodeBounds(c);
    return addr >= b.base && (cap_len_t(addr) + size) <= b.top;
}

// Kinds of data access a capability authorises. Combine for AMOs.
enum CheriAccess : unsigned
{
    CheriAccLoad = 1u << 0,
    CheriAccStore = 1u << 1,
    // The access moves a capability (clc/csc/lr.c/sc.c/amoswap.c).
    CheriAccCap = 1u << 2,
    // cloadtags: reading tags additionally requires PERMIT_LOAD_CAP.
    CheriAccLoadTags = 1u << 3,
};

// Memory access authorised by `auth` (Sail handle_load_data_via_cap,
// handle_store_cap_via_cap, ...). For capability stores `stored` is the value
// being written: storing a tagged capability needs PERMIT_STORE_CAP, and a
// tagged local (non-GLOBAL) one additionally PERMIT_STORE_LOCAL_CAP. A
// capability *load* through an authority without PERMIT_LOAD_CAP does not
// trap; the loaded tag is cleared instead (see capLoadResult()).
inline CheriCapException
capCheckMemAccess(const CapRegContainer &auth, uint64_t ea, uint64_t size,
                  unsigned acc, const CapRegContainer *stored = nullptr)
{
    if (!auth.getTag())
        return CheriCapException::TagViolation;
    if (capIsSealed(auth))
        return CheriCapException::SealViolation;
    if ((acc & CheriAccLoad) && !capHasPerm(auth, CHERIPerms::LOAD))
        return CheriCapException::PermitLoadViolation;
    if ((acc & CheriAccLoadTags) && !capHasPerm(auth, CHERIPerms::LOAD_CAP))
        return CheriCapException::PermitLoadCapViolation;
    if ((acc & CheriAccStore) && !capHasPerm(auth, CHERIPerms::STORE))
        return CheriCapException::PermitStoreViolation;
    if ((acc & CheriAccStore) && (acc & CheriAccCap) && stored &&
        stored->getTag()) {
        if (!capHasPerm(auth, CHERIPerms::STORE_CAP))
            return CheriCapException::PermitStoreCapViolation;
        if (!capHasPerm(*stored, CHERIPerms::GLOBAL) &&
            !capHasPerm(auth, CHERIPerms::STORE_LOCAL))
            return CheriCapException::PermitStoreLocalViolation;
    }
    if (!capInBounds(auth, ea, size))
        return CheriCapException::LengthViolation;
    return CheriCapException::None;
}

// Value written to the destination of a capability load: the tag survives
// only if the authorising capability grants PERMIT_LOAD_CAP.
inline CapRegContainer
capLoadResult(const CapRegContainer &loaded, const CapRegContainer &auth)
{
    CapRegContainer r = loaded;
    if (!capHasPerm(auth, CHERIPerms::LOAD_CAP))
        r.setTag(false);
    return r;
}

// Smallest instruction (RVC is always enabled): the bounds a jump target must
// satisfy (Sail min_instruction_bytes()).
constexpr uint64_t CHERI_MIN_INST_BYTES = 2;

// Indirect jump through `target` with immediate offset `imm` (Sail CJALR /
// C.CJR / C.CJALR). As in Sail, the target's bounds are checked at the jump,
// against `target` (not later, on fetch, against the new PCC).
inline CheriCapException
capCheckJump(const CapRegContainer &target, int64_t imm)
{
    if (!target.getTag())
        return CheriCapException::TagViolation;
    if (capIsSealed(target) && !(capIsSentry(target) && imm == 0))
        return CheriCapException::SealViolation;
    if (!capHasPerm(target, CHERIPerms::EXECUTE))
        return CheriCapException::PermitExecuteViolation;
    uint64_t new_pc = (target.getAddress() + imm) & ~uint64_t(1);
    if (!capInBounds(target, new_pc, CHERI_MIN_INST_BYTES))
        return CheriCapException::LengthViolation;
    return CheriCapException::None;
}

// Direct jump or taken branch to `target_pc` under the current PCC (Sail
// ext_control_check_pc / ext_control_check_addr): checked at the branch.
inline CheriCapException
capCheckBranch(const CapRegContainer &pcc, uint64_t target_pc)
{
    if (!capInBounds(pcc, target_pc & ~uint64_t(1), CHERI_MIN_INST_BYTES))
        return CheriCapException::LengthViolation;
    return CheriCapException::None;
}

// Instruction fetch of `size` bytes at `pc` under `pcc`.
inline CheriCapException
capCheckFetch(const CapRegContainer &pcc, uint64_t pc, uint64_t size)
{
    if (!pcc.getTag())
        return CheriCapException::TagViolation;
    if (capIsSealed(pcc))
        return CheriCapException::SealViolation;
    if (!capHasPerm(pcc, CHERIPerms::EXECUTE))
        return CheriCapException::PermitExecuteViolation;
    if (!capInBounds(pcc, pc, size))
        return CheriCapException::LengthViolation;
    return CheriCapException::None;
}

// Return capability written by a jump-and-link: the PCC with its address set
// to the return address, sealed as a sentry (Sail CJAL / CJALR).
inline CapRegContainer
capMakeSentryLink(const CapRegContainer &pcc, uint64_t ret_addr)
{
    CapRegContainer link = pcc;
    link.setAddress(ret_addr);
    CAPTYPE meta = capPesbt(link.getMetadata());
    meta.otype = CHERIMeta::OTYPE_SENTRY;
    link.setMetadata(meta);
    return link;
}

// New PCC after a jump to `target_addr` through `target`: sentries are
// unsealed on entry.
inline CapRegContainer
capJumpTargetPcc(const CapRegContainer &target, uint64_t target_addr)
{
    CapRegContainer pcc = target;
    pcc.setAddress(target_addr);
    if (capIsSentry(pcc)) {
        CAPTYPE meta = pcc.getMetadata();
        meta.otype = CHERIMeta::OTYPE_UNSEALED;
        pcc.setMetadata(meta);
    }
    return pcc;
}

// ---- Capability manipulation (ISAv9 tag-clearing semantics) ----
//
// Each returns the architectural result. Where the ISA clears the tag on a
// violation (instead of trapping), the returned capability is untagged.

inline bool
capBoundsEqual(const CapRegContainer &a, const CapRegContainer &b)
{
    CapBounds ba = capDecodeBounds(a), bb = capDecodeBounds(b);
    return ba.base == bb.base && ba.top == bb.top;
}

// CSetAddr / CIncOffset / CSetOffset / CFromPtr: change the address. The tag
// is cleared if the source is sealed or the bounds would no longer decode
// identically (not representable).
inline CapRegContainer
capSetAddr(const CapRegContainer &c, uint64_t addr)
{
    CapRegContainer r = c;
    r.setAddress(addr);
    if (r.getTag() && (capIsSealed(c) || !capBoundsEqual(c, r)))
        r.setTag(false);
    return r;
}

// ---- Trap-vector / exception-PC capabilities ----
//
// The integer CSRs xtvec and xepc are views of the address of xTCC and
// xEPCC. Writes go through capSetAddr (Sail update_cap_with_integer_pc).

// Sail legalize_xepc: epc[0] is 0, and so is epc[1] without RVC.
inline uint64_t
capLegalizeXepc(uint64_t v, bool rvc)
{
    return v & ~uint64_t(rvc ? 1 : 3);
}

// Sail legalize_epcc: applied when xEPCC is read or used by xRET, not on
// writes. Untouched if already legal (so a sentry keeps its tag).
inline CapRegContainer
capLegalizeEpcc(const CapRegContainer &epcc, bool rvc)
{
    uint64_t a = epcc.getAddress();
    uint64_t l = capLegalizeXepc(a, rvc);
    return l == a ? epcc : capSetAddr(epcc, l);
}

// Sail legalize_tvec: a reserved mode (2, 3) keeps the old mode.
inline uint64_t
capLegalizeTvec(uint64_t old_tvec, uint64_t v)
{
    if ((v & 3) >= 2)
        v = (v & ~uint64_t(3)) | (old_tvec & 3);
    return v;
}

// Sail legalize_tcc: xTCC written with `v` (CSpecialRW).
inline CapRegContainer
capLegalizeTcc(const CapRegContainer &old_tcc, const CapRegContainer &v)
{
    return capSetAddr(v, capLegalizeTvec(old_tcc.getAddress(),
                                         v.getAddress()));
}

// CSetBounds / CSetBoundsImm / CSetBoundsExact: bounds [address,
// address + len). The tag is cleared if the source is sealed, the requested
// region is not within the source bounds, or (exact) it is not exactly
// representable.
inline CapRegContainer
capSetBounds(const CapRegContainer &c, uint64_t len, bool exact_required)
{
    uint64_t base = c.getAddress();
    bool exact = false;
    CAPTYPE m = cc128EncodeBounds(capPesbt(c.getMetadata()), base, len,
                                  &exact);
    CapRegContainer r(base, m, c.getTag());
    CapBounds sb = capDecodeBounds(c);
    bool in_bounds = base >= sb.base && (cap_len_t(base) + len) <= sb.top;
    if (!in_bounds || capIsSealed(c) || (exact_required && !exact))
        r.setTag(false);
    return r;
}

// Architectural permission mask (hardware perms 0..11, user perms at
// 15..18) <-> stored 16-bit field (user perm 0 at bit 15, user perms 1..3 at
// bits 12..14). See cgetperm/candperm.
inline uint64_t
capArchPerms(const CapRegContainer &c)
{
    uint64_t stored = capPerms(c);
    return (stored & 0x8FFFULL) | ((stored & 0x7000ULL) << 4);
}

inline uint32_t
capStoredPermMask(uint64_t arch_mask)
{
    return (uint32_t)((arch_mask & 0x8FFFULL) |
                      ((arch_mask >> 4) & 0x7000ULL));
}

inline CapRegContainer
capWithPesbt(const CapRegContainer &c, CAPTYPE m)
{
    CapRegContainer r = c;
    r.setMetadata(m);
    return r;
}

// CAndPerm: tag cleared if the source is sealed.
inline CapRegContainer
capAndPerm(const CapRegContainer &c, uint64_t arch_mask)
{
    CAPTYPE m = capPesbt(c.getMetadata());
    m.perm = m.perm & capStoredPermMask(arch_mask);
    CapRegContainer r = capWithPesbt(c, m);
    if (capIsSealed(c))
        r.setTag(false);
    return r;
}

// CSetFlags: tag cleared if the source is sealed.
inline CapRegContainer
capSetFlags(const CapRegContainer &c, uint64_t flags)
{
    CAPTYPE m = capPesbt(c.getMetadata());
    m.flag = flags & 1;
    CapRegContainer r = capWithPesbt(c, m);
    if (capIsSealed(c))
        r.setTag(false);
    return r;
}

inline CapRegContainer
capWithOtype(const CapRegContainer &c, uint64_t otype)
{
    CAPTYPE m = capPesbt(c.getMetadata());
    m.otype = otype;
    return capWithPesbt(c, m);
}

// Largest otype usable with CSeal; the top four values are reserved
// (unsealed, sentry, and two reserved types).
constexpr uint64_t CHERI_MAX_OTYPE = CHERIMeta::OTYPE_UNSEALED - 4;

// Is `auth` a valid sealing (perm = SEAL) or unsealing (perm = UNSEAL)
// authority for its address, i.e. tagged, unsealed, permitted, with the
// address in bounds and a non-reserved object type?
inline bool
capSealAuthOk(const CapRegContainer &auth, uint32_t perm)
{
    uint64_t t = auth.getAddress();
    return auth.getTag() && !capIsSealed(auth) && capHasPerm(auth, perm) &&
           capInBounds(auth, t, 1) && t <= CHERI_MAX_OTYPE;
}

// CSeal cd, cs1, cs2.
inline CapRegContainer
capSeal(const CapRegContainer &c, const CapRegContainer &auth)
{
    CapRegContainer r = capWithOtype(c, auth.getAddress());
    if (!c.getTag() || capIsSealed(c) ||
        !capSealAuthOk(auth, CHERIPerms::SEAL)) {
        r = c;
        r.setTag(false);
    }
    return r;
}

// CUnseal cd, cs1, cs2: the result is GLOBAL only if both inputs are.
inline CapRegContainer
capUnseal(const CapRegContainer &c, const CapRegContainer &auth)
{
    CapRegContainer r = capWithOtype(c, CHERIMeta::OTYPE_UNSEALED);
    if (!capHasPerm(auth, CHERIPerms::GLOBAL)) {
        CAPTYPE m = r.getMetadata();
        m.perm = m.perm & ~CHERIPerms::GLOBAL;
        r.setMetadata(m);
    }
    if (!c.getTag() || !capIsSealed(c) || capOtype(c) > CHERI_MAX_OTYPE ||
        !capSealAuthOk(auth, CHERIPerms::UNSEAL) ||
        auth.getAddress() != capOtype(c))
        r.setTag(false);
    return r;
}

// CCSeal cd, cs1, cs2: seal only if cs2 is a usable sealing authority; an
// untagged cs2 or one whose address is -1 leaves cs1 unchanged.
inline CapRegContainer
capCSeal(const CapRegContainer &c, const CapRegContainer &auth)
{
    if (!c.getTag() || !auth.getTag() || auth.getAddress() == ~0ULL)
        return c;
    return capSeal(c, auth);
}

// CSealEntry: seal as a sentry; tag cleared if sealed or not executable.
inline CapRegContainer
capSealEntry(const CapRegContainer &c)
{
    CapRegContainer r = capWithOtype(c, CHERIMeta::OTYPE_SENTRY);
    if (capIsSealed(c) || !capHasPerm(c, CHERIPerms::EXECUTE))
        r.setTag(false);
    return r;
}

// CBuildCap cd, cs1 (authority), cs2 (bit pattern): rederive cs2 from cs1
// if it is a subset of it.
inline CapRegContainer
capBuild(const CapRegContainer &auth, const CapRegContainer &bits)
{
    CapBounds ab = capDecodeBounds(auth), bb = capDecodeBounds(bits);
    CapRegContainer r = bits;
    bool ok = auth.getTag() && !capIsSealed(auth) &&
              cap_len_t(bb.base) <= bb.top && bb.base >= ab.base &&
              bb.top <= ab.top &&
              (capPerms(bits) & capPerms(auth)) == capPerms(bits) &&
              (!capIsSealed(bits) || capIsSentry(bits));
    r.setTag(ok);
    return r;
}

// CCopyType cd, cs1, cs2: a capability whose address is cs2's otype, derived
// from cs1 (reserved otypes yield an untagged integer of the otype).
inline CapRegContainer
capCopyType(const CapRegContainer &auth, const CapRegContainer &sealed)
{
    uint64_t ot = capOtype(sealed);
    if (ot > CHERI_MAX_OTYPE) {
        // Reserved types read back sign-extended (unsealed = -1, ...).
        CapRegContainer r;
        r.setAddress(ot | ~uint64_t(CHERIMeta::OTYPE_MASK));
        return r;
    }
    CapRegContainer r = capSetAddr(auth, ot);
    if (!auth.getTag() || capIsSealed(auth) || !capInBounds(auth, ot, 1))
        r.setTag(false);
    return r;
}

// CGetType: reserved otypes sign-extend (unsealed reads -1, sentry -2).
inline uint64_t
capGetType(const CapRegContainer &c)
{
    uint64_t ot = capOtype(c);
    return ot > CHERI_MAX_OTYPE ? (ot | ~uint64_t(CHERIMeta::OTYPE_MASK)) : ot;
}

constexpr cap_len_t CAP_ADDR_MAX = cap_len_t(~0ULL);

// CGetLen / CGetTop saturate at 2^64 - 1.
inline uint64_t
capGetLen(const CapRegContainer &c)
{
    CapBounds b = capDecodeBounds(c);
    cap_len_t len = b.top >= b.base ? b.top - b.base : 0;
    return len > CAP_ADDR_MAX ? ~0ULL : uint64_t(len);
}

inline uint64_t
capGetTop(const CapRegContainer &c)
{
    CapBounds b = capDecodeBounds(c);
    return b.top > CAP_ADDR_MAX ? ~0ULL : uint64_t(b.top);
}

inline uint64_t
capGetBase(const CapRegContainer &c)
{
    return capDecodeBounds(c).base;
}

// CTestSubset rd, cs1, cs2: cs2 is (non-strictly) contained in cs1, with
// matching tags.
inline bool
capTestSubset(const CapRegContainer &outer, const CapRegContainer &inner)
{
    CapBounds ob = capDecodeBounds(outer), ib = capDecodeBounds(inner);
    return outer.getTag() == inner.getTag() && ib.base >= ob.base &&
           ib.top <= ob.top &&
           (capPerms(inner) & capPerms(outer)) == capPerms(inner);
}

// Capability register indices reported in xTVAL for special capabilities.
constexpr int CHERI_CAPIDX_PCC = 32;
constexpr int CHERI_CAPIDX_DDC = 33;

} // namespace CHERIRiscvISA
} // namespace gem5

#endif // __ARCH_RISCV_CHERI_CHERI_CHECKS_HH__
