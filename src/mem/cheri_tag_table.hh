#ifndef __MEM_CHERI_TAG_TABLE_HH__
#define __MEM_CHERI_TAG_TABLE_HH__

#include <unordered_map>
#include <cstdint> 

#include "base/types.hh"
#include "base/logging.hh"
#include "base/trace.hh"
#include "base/types.hh"
#include "debug/CHERI.hh"    
#include "sim/serialize.hh"

namespace gem5
{
    class CheriTagTable : public Serializable { 
        private: 
            std::unordered_map<uint64_t, bool> tagTable;

        public:
            static constexpr uint64_t CAP_SIZE = 16;
            static constexpr uint64_t CAP_ALIGN_MASK = ~(CAP_SIZE - 1);

        private: 
            // Helper function to align addresses to capability boundaries
            uint64_t alignAddress(Addr addr) const {
                return addr & CAP_ALIGN_MASK;
            }

            uint64_t granuleIndex(Addr addr) const {
                return addr >> 4; // Divide by 16 to get the index
            }
        
        public:
            CheriTagTable() = default;

            bool getTag(Addr addr) const {
                uint64_t index = granuleIndex(addr);
                auto it = tagTable.find(index);
                if (it != tagTable.end()) {
                    DPRINTF(CHERI, "TagTable: getTag(0x%016x) -> %d\n", addr, it->second);
                    return it->second;
                } else {
                    DPRINTF(CHERI, "TagTable: getTag(0x%016x) -> %d\n", addr, false);
                    return false; // Default to untagged if not found
                }
            }

            void setTag(Addr addr, bool tag) {
                uint64_t idx = granuleIndex(addr);

                DPRINTF(CHERI, "TagTable: setTag(0x%016x) = %d\n", addr, tag);

                if (tag) {
                    tagTable[idx] = true;
                } else {
                    // Erase rather than store false — saves memory.
                    // Absent entries are implicitly false.
                    tagTable.erase(idx);
                }
            }

            void clearTagsInRange(Addr paddr, size_t size) {
                if (size == 0) return;

                // Find the first and last granule indices affected
                Addr startAligned = alignAddress(paddr);
                Addr endAligned = alignAddress(paddr + size - 1);

                for (Addr a = startAligned; a <= endAligned; a += CAP_SIZE) {
                    uint64_t idx = granuleIndex(a);
                    auto it = tagTable.find(idx);
                    if (it != tagTable.end()) {
                        DPRINTF(CHERI, "TagTable: clearTag(0x%016x) "
                                "due to write at 0x%016x size %d\n",
                                a, paddr, size);
                        tagTable.erase(it);
                    }
                }
            }

            void clear() {
                DPRINTF(CHERI, "TagTable: clear all tags\n");
                tagTable.clear();
            }

            size_t numTaggedGranules() const {
                return tagTable.size();
            }

            static bool isCapAligned(Addr addr) {
                return (addr & (CAP_SIZE - 1)) == 0;
            }

            void serialize (CheckpointOut &cp) const override {
                // Serialize the number of entries and then each entry
                uint64_t numTags = tagTable.size();
                SERIALIZE_SCALAR(numTags);

                int i = 0;
                for (const auto &[idx, tag] : tagTable) {
                    // Store the physical address (granule index << 4)
                    Addr paddr = idx << 4;
                    paramOut(cp, csprintf("tagAddr_%d", i), paddr);
                    paramOut(cp, csprintf("tagVal_%d", i), tag);
                    i++;
                }
            }

            void unserialize (CheckpointIn &cp) override {
                tagTable.clear();
                uint64_t numTags;
                UNSERIALIZE_SCALAR(numTags);

                for (uint64_t i = 0; i < numTags; i++) {
                    Addr paddr;
                    bool tag;
                    paramIn(cp, csprintf("tagAddr_%d", i), paddr);
                    paramIn(cp, csprintf("tagVal_%d", i), tag);
                    uint64_t idx = granuleIndex(paddr);
                    if (tag) {
                        tagTable[idx] = true;
                    }
                }
            }

    };
} // namespace gem5


#endif