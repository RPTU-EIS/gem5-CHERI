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

namespace gem5
{  
    class CapRegContainer{
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