#ifndef __ARCH_RISCV_CHERI_CAP_REG_HH__
#define __ARCH_RISCV_CHERI_CAP_REG_HH__

#include <array>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

#include "base/cprintf.hh"
#include "base/logging.hh"
#include "base/types.hh"
#include "sim/serialize_handlers.hh"
#include "arch/generic/cheri_defs.hh"

namespace gem5
{
    class CapRegContainer {
    public:
        static constexpr inline size_t size() { 
            return 17; 
        }; // 128 bits + 1 tag bit

        using Container = std::array<uint8_t, 17>;

    private:
        uint64_t address; 
        uint64_t metadata; 
        bool tag; 

        alignas(16) Container container;
    
    public:
        CapRegContainer() : address(0), metadata(0), tag(false) {}

        CapRegContainer(uint64_t addr, uint64_t meta, bool t)
            : address(addr), metadata(meta), tag(t) {}

        CapRegContainer(const CapRegContainer &) = default;

        void zero() { 
            address = 0; 
            metadata = 0; 
            tag = false; 
        }

        // accessors
        uint64_t getAddress() const { 
            return address; 
        }

        uint64_t getMetadata() const { 
            return metadata; 
        }

        bool getTag() const { 
            return tag; 
        }

        void setAddress(uint64_t addr) { 
            address = addr; 
        }

        void setMetadata(uint64_t meta) { 
            metadata = meta; 
        }

        void setTag(bool t) { 
            tag = t; 
        }

        void set(uint64_t addr, uint64_t meta, bool t) {
            address = addr;
            metadata = meta;
            tag = t;
        }

        // Equality operator
        CapRegContainer&
        operator=(const CapRegContainer& that) {
            if (&that != this) {
                address = that.address;
                metadata = that.metadata;
                tag = that.tag;
            }
            return *this;
        }

        inline bool
        operator==(const CapRegContainer& that) const {
            return (address == that.address) &&
                   (metadata == that.metadata) &&
                   (tag == that.tag);
        }

        bool
        operator!=(const CapRegContainer& that) const {
            return !operator==(that);
        }

        std::array<uint8_t, 17> toBytes() const {
            
            std::array<uint8_t, 17> bytes = {0};

            // Pack address (bytes 0-7)
            for (int i = 0; i < 8; i++) {
                bytes[i] = (address >> (i * 8)) & 0xFF;
            }
            
            // Pack metadata (bytes 8-15)
            for (int i = 0; i < 8; i++) {
                bytes[8 + i] = (metadata >> (i * 8)) & 0xFF;
            }
            
            // Pack tag (byte 16, bit 0)
            bytes[16] = tag ? 0x01 : 0x00;

            return bytes;
        }

        void fromBytes(const std::array<uint8_t, 17>& bytes) {
            // Unpack address (bytes 0-7)
            address = 0;
            for (int i = 0; i < 8; i++) {
                address |= static_cast<uint64_t>(bytes[i]) << (i * 8);
            }
            
            // Unpack metadata (bytes 8-15)
            metadata = 0;
            for (int i = 0; i < 8; i++) {
                metadata |= static_cast<uint64_t>(bytes[8 + i]) << (i * 8);
            }
            
            // Unpack tag (byte 16, bit 0)
            tag = (bytes[16] & 0x01) != 0;
        }

        void toMemory(uint8_t* dst) const {
            // little endian
            for (int i = 0; i < 8; i++){ 
                dst[i] = (address >> (i * 8)) & 0xFF;
                dst[8 + i] = (metadata >> (i * 8)) & 0xFF;
            }
            // Tag not needed here? stored seperately in tagged memory? 
        }

        void fromMemory(const uint8_t* src, bool memTag) {
            address = 0;
            metadata = 0;
            for (int i = 0; i < 8; i++) {
                address |= static_cast<uint64_t>(src[i]) << (i * 8);
                metadata |= static_cast<uint64_t>(src[8 + i]) << (i * 8);
            }
            tag = memTag;
        }

        friend std::ostream& 
        operator<<(std::ostream &out, const CapRegContainer & cap) {
            ccprintf(out, "CapRegContainer(Address: 0x%016x, Metadata: 0x%016x, Tag: %d)",
                     cap.address, cap.metadata, cap.tag ? 1 : 0);
            return out;
        }

        std::string getString() const {
            std::stringstream s;
            s << "[tag=" << tag << " addr=0x" << std::hex << std::setfill('0') << std::setw(16) << address
                << " meta=0x" << std::hex << std::setfill('0') << std::setw(16) << metadata << "]";
            return s.str();
        }

        friend ShowParam<CapRegContainer>;

    public:

        uint32_t getPerms() const {
            return (metadata >> CHERIMeta::PERM_SHIFT) & CHERIMeta::PERM_MASK;
        }

        void setPerms(uint32_t perms) {
            metadata &= ~(CHERIMeta::PERM_MASK << CHERIMeta::PERM_SHIFT);
            metadata |= (static_cast<uint64_t>(perms) & CHERIMeta::PERM_MASK)
                         << CHERIMeta::PERM_SHIFT;
        }

        bool hasPerm(uint32_t perm) const {
            return (getPerms() & perm) != 0;
        }

        bool hasExecute()  const { return hasPerm(CHERIPerms::EXECUTE); }
        bool hasLoad()     const { return hasPerm(CHERIPerms::LOAD); }
        bool hasStore()    const { return hasPerm(CHERIPerms::STORE); }
        bool hasLoadCap()  const { return hasPerm(CHERIPerms::LOAD_CAP); }
        bool hasStoreCap() const { return hasPerm(CHERIPerms::STORE_CAP); }
        bool hasGlobal()   const { return hasPerm(CHERIPerms::GLOBAL); }
        bool hasASR()      const { return hasPerm(CHERIPerms::ASR); }

        void andPerms(uint32_t mask) {
            setPerms(getPerms() & mask);
        }

        // ──────────────────────────────────────────
        // Otype / sealing
        // ──────────────────────────────────────────

        uint32_t getOtype() const {
            return (metadata >> CHERIMeta::OTYPE_SHIFT) & CHERIMeta::OTYPE_MASK;
        }

        void setOtype(uint32_t otype) {
            metadata &= ~(CHERIMeta::OTYPE_MASK << CHERIMeta::OTYPE_SHIFT);
            metadata |= (static_cast<uint64_t>(otype) & CHERIMeta::OTYPE_MASK)
                         << CHERIMeta::OTYPE_SHIFT;
        }

        bool isSealed() const {
            return getOtype() != CHERIMeta::OTYPE_UNSEALED;
        }

        bool isSentry() const {
            uint32_t ot = getOtype();
            return (ot == CHERIMeta::OTYPE_SENTRY_INTER) ||
                   (ot == CHERIMeta::OTYPE_SENTRY_BACK) ||
                   (ot == CHERIMeta::OTYPE_SENTRY_FWD);
        }

        bool isUnsealed() const { return !isSealed(); }

        void seal(uint32_t otype) { setOtype(otype); }
        void unseal() { setOtype(CHERIMeta::OTYPE_UNSEALED); }

        // ──────────────────────────────────────────
        // Address/base/top decoding and bounds checking
        // ──────────────────────────────────────────

        // Need to revamp the decoder to get bounds from here. 
        static void decodeBounds(uint64_t meta, uint64_t addr,
                                 uint64_t &out_base, uint64_t &out_top) {
            CHERIRiscvISA::CAPTYPE m = meta;

            uint64_t B_hi = m.B;
            uint64_t T_hi = m.T;
            uint64_t B_E = m.BE;
            uint64_t T_E = m.TE;
            uint64_t I_E = m.IE;

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
            uint64_t R = (B_3 - 1) & 0x7;

            int64_t c_b;
            bool cond1_b = (A_3 < R);
            bool cond2_b = (B_3 < R);
            if (!cond1_b && !cond2_b) c_b = 0;
            else if (!cond1_b && cond2_b) c_b = 1;
            else if (cond1_b && !cond2_b) c_b = -1;
            else c_b = 0;

            int64_t c_t;
            bool cond1_t = (A_3 < R);
            bool cond2_t = (T_3 < R);
            if (!cond1_t && !cond2_t) c_t = 0;
            else if (!cond1_t && cond2_t) c_t = 1;
            else if (cond1_t && !cond2_t) c_t = -1;
            else c_t = 0;

            uint64_t a_top = (addr >> (E + 14));
            out_base = ((a_top + c_b) << (E + 14)) | (B << E);
            out_top  = ((a_top + c_t) << (E + 14)) | (T << E);
        }

        // ── Static bounds check ──
        //   if (!CapRegContainer::inBounds(meta, addr, EA, 4))
        //       return fault;
        static bool inBounds(uint64_t meta, uint64_t addr,
                             uint64_t accessAddr, uint64_t accessSize) {
            uint64_t base, top;
            decodeBounds(meta, addr, base, top);

            if (accessAddr < base)
                return false;
            if (accessSize > (top - accessAddr))
                return false;
            return true;
        }


        // Permission checks for loads and stores, including capability loads/stores
        static CHERIRiscvISA::CheriCapException checkForLoad(
            uint64_t meta, uint64_t addr, bool capTag, bool sealed,
            uint64_t accessAddr, uint64_t loadSize, bool capLoad) {
            if (!capTag)
                return CHERIRiscvISA::CheriCapException::TagViolation;
            if (sealed)
                return CHERIRiscvISA::CheriCapException::SealViolation;

            uint32_t perms = (meta >> CHERIMeta::PERM_SHIFT) & CHERIMeta::PERM_MASK;
            if (!(perms & CHERIPerms::LOAD))
                return CHERIRiscvISA::CheriCapException::PermitLoadViolation;
            if (capLoad && !(perms & CHERIPerms::LOAD_CAP))
                return CHERIRiscvISA::CheriCapException::PermitLoadCapViolation;

            if (!inBounds(meta, addr, accessAddr, loadSize))
                return CHERIRiscvISA::CheriCapException::LengthViolation;

            return CHERIRiscvISA::CheriCapException::None;
        }

        static CHERIRiscvISA::CheriCapException checkForStore(
            uint64_t meta, uint64_t addr, bool capTag, bool sealed,
            uint64_t accessAddr, uint64_t storeSize, bool capStore) {
            if (!capTag)
                return CHERIRiscvISA::CheriCapException::TagViolation;
            if (sealed)
                return CHERIRiscvISA::CheriCapException::SealViolation;

            uint32_t perms = (meta >> CHERIMeta::PERM_SHIFT) & CHERIMeta::PERM_MASK;
            if (!(perms & CHERIPerms::STORE))
                return CHERIRiscvISA::CheriCapException::PermitStoreViolation;
            if (capStore && !(perms & CHERIPerms::STORE_CAP))
                return CHERIRiscvISA::CheriCapException::PermitStoreCapViolation;

            if (!inBounds(meta, addr, accessAddr, storeSize))
                return CHERIRiscvISA::CheriCapException::LengthViolation;

            return CHERIRiscvISA::CheriCapException::None;
        }

        static CHERIRiscvISA::CheriCapException checkForFetch(
            uint64_t meta, uint64_t addr, bool capTag,
            bool sealed, bool sentry,
            uint64_t accessAddr, uint64_t fetchSize) {
            if (!capTag)
                return CHERIRiscvISA::CheriCapException::TagViolation;
            if (sealed && !sentry)
                return CHERIRiscvISA::CheriCapException::SealViolation;

            uint32_t perms = (meta >> CHERIMeta::PERM_SHIFT) & CHERIMeta::PERM_MASK;
            if (!(perms & CHERIPerms::EXECUTE))
                return CHERIRiscvISA::CheriCapException::PermitExecuteViolation;

            if (!inBounds(meta, addr, accessAddr, fetchSize))
                return CHERIRiscvISA::CheriCapException::LengthViolation;

            return CHERIRiscvISA::CheriCapException::None;
        }

        /**
         * Almighty (root) capability — full permissions, full address
         * space bounds, tagged, unsealed.
         */
        static CapRegContainer almighty(uint64_t addr = 0) {
            CapRegContainer cap;
            cap.tag = true;
            cap.address = addr;

            CHERIRiscvISA::CAPTYPE meta = 0;
            meta.perm = CHERIPerms::ALL;
            meta.otype = CHERIMeta::OTYPE_UNSEALED;
            // Full address space bounds using Concentrate:
            // IE=1, E=52 gives enough exponent to cover 2^64
            meta.IE = 1;
            meta.BE = 0x4;   // E bits [2:0] = 4
            meta.TE = 0x6;   // E bits [5:3] = 6 -> E = 52
            meta.B = 0;
            meta.T = 0x100;  // T << E overflows to cover full space
            
            cap.metadata = meta;

            return cap;
        }
        /**
         * Null capability — zeroed, untagged.
         */
        static CapRegContainer null() {
            CapRegContainer cap;
            cap.zero();
            return cap;
        }

    };

    template <>
    struct ParseParam<CapRegContainer> {
        static bool
        parse(const std::string &str, CapRegContainer &value){
        // Expected format: "tag,address,metadata" in hex
        // Example: "1,0000000000000000,0000000000000000"
        
            if (str.empty()) {
                value.zero();
                return true;
            }
            
            // Simple parsing: expect 33 hex chars (1 for tag + 16 for addr + 16 for meta)
            if (str.size() != 33) {
                warn("Capability register parse: unexpected string length");
                return false;
            }
            
            try {
                bool tag = (str[0] == '1');
                uint64_t addr = std::stoull(str.substr(1, 16), nullptr, 16);
                uint64_t meta = std::stoull(str.substr(17, 16), nullptr, 16);
                
                value.set(addr, meta, tag);
                return true;
            } catch (...) {
                warn("Capability register parse failed");
                return false;
            }
        }

    };

    template <>
    struct ShowParam<CapRegContainer> {
        static void
        show(std::ostream &os, const CapRegContainer &value)
        {
            // Output format: "tag,address,metadata"
            ccprintf(os, "%d%016x%016x",
                    value.getTag() ? 1 : 0,
                    value.getAddress(),
                    value.getMetadata());
        }
    };

} // namespace gem5

#endif /* __ARCH_RISCV_CHERI_CAP_REG_HH__ */