#ifndef __MEM_CHERI_TAG_TABLE_HH__
#define __MEM_CHERI_TAG_TABLE_HH__

#include <algorithm>
#include <cstdint>
#include <unordered_map>
#include <vector>

#include "base/types.hh"
#include "base/logging.hh"
#include "base/trace.hh"
#include "base/types.hh"
#include "cpu/inst_seq.hh"
#include "debug/CHERI.hh"
#include "sim/serialize.hh"

namespace gem5
{
    class CheriTagTable : public Serializable
    {
        private:
            std::unordered_map<uint64_t, bool> tagTable;

            // Per-granule sequence number of the last write admitted by
            // admitWrite() below. Only tracked for writes that pass a
            // sequence number (i.e. come from an O3 store's completeAcc);
            // callers with no ordering information (atomic CPU, the
            // initial kernel-image tag load, AMO instructions that are
            // already correctly serialized via IsNonSpeculative) don't
            // need it and never populate this map.
            //
            // Unlike tagTable (which only ever holds entries for
            // currently-tagged granules, and so stays naturally bounded),
            // this map would otherwise grow by one entry per DISTINCT
            // granule address any sequenced store has ever written across
            // the whole run -- unbounded, and large: this OOM-killed a
            // full CheriBSD boot+userspace run at ~35GB before the cap
            // below was added. The actual reordering this guards against
            // can only span instructions simultaneously in flight in the
            // pipeline (the ROB/LSQ window, a few hundred entries at
            // most), so it is safe to drop everything once the map grows
            // far beyond that -- any entry old enough to be evicted is
            // long past the point where a stale completion could still
            // race it.
            static constexpr size_t LAST_WRITE_SEQ_CAP = 1 << 18; // 262144
            std::unordered_map<uint64_t, InstSeqNum> lastWriteSeq;

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

            // Under O3, two stores to the same (or overlapping) 16-byte
            // granule are issued to memory in program order, but their
            // *responses* -- and therefore the completeAcc call where the
            // tag-table write actually happens -- can arrive out of that
            // order (e.g. a byte-wise scalar write that misses, followed
            // in program order by a capability store that hits and
            // completes first; the miss's eventual, now-stale clear then
            // lands after the capability store's correct set). Reject a
            // write whose sequence number is older than the newest one
            // already admitted for this granule, so the tag table always
            // reflects the program-order-latest write regardless of
            // completion order. Single-core only: InstSeqNum is a
            // per-thread-context counter, not globally comparable across
            // cores, so a multi-core board would need per-context
            // disambiguation here.
            bool admitWrite(uint64_t idx, bool hasSeq, InstSeqNum seq) {
                if (!hasSeq)
                    return true;
                if (lastWriteSeq.size() >= LAST_WRITE_SEQ_CAP)
                    lastWriteSeq.clear();
                auto it = lastWriteSeq.find(idx);
                if (it != lastWriteSeq.end() && it->second > seq) {
                    DPRINTF(CHERI, "TagTable: rejecting stale write to "
                            "granule %#x (seq %llu, newest applied %llu)\n",
                            idx, (unsigned long long)seq,
                            (unsigned long long)it->second);
                    return false;
                }
                lastWriteSeq[idx] = seq;
                return true;
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

            void setTag(Addr addr, bool tag, bool hasSeq = false,
                         InstSeqNum seq = 0) {
                uint64_t idx = granuleIndex(addr);

                if (!admitWrite(idx, hasSeq, seq))
                    return;

                DPRINTF(CHERI, "TagTable: setTag(0x%016x) = %d\n", addr, tag);

                if (tag) {
                    tagTable[idx] = true;
                } else {
                    // Erase rather than store false — saves memory.
                    // Absent entries are implicitly false.
                    tagTable.erase(idx);
                }
            }

            void clearTagsInRange(Addr paddr, size_t size,
                                   bool hasSeq = false, InstSeqNum seq = 0) {
                if (size == 0) return;

                // Find the first and last granule indices affected
                Addr startAligned = alignAddress(paddr);
                Addr endAligned = alignAddress(paddr + size - 1);

                for (Addr a = startAligned; a <= endAligned; a += CAP_SIZE) {
                    uint64_t idx = granuleIndex(a);
                    if (!admitWrite(idx, hasSeq, seq))
                        continue;
                    auto it = tagTable.find(idx);
                    if (it != tagTable.end()) {
                        DPRINTF(CHERI, "TagTable: clearTag(0x%016x) "
                                "due to write at 0x%016x size %d\n",
                                a, paddr, size);
                        tagTable.erase(it);
                    }
                }
            }

            // True if any 16-byte granule in [paddr, paddr + size) holds a
            // valid tag (used by timing models, e.g. tag-table zero
            // elision in CheriTagController).
            bool anyTagInRange(Addr paddr, size_t size) const {
                if (size == 0 || tagTable.empty()) return false;
                Addr end = alignAddress(paddr + size - 1);
                for (Addr a = alignAddress(paddr); a <= end; a += CAP_SIZE) {
                    if (tagTable.count(granuleIndex(a)))
                        return true;
                }
                return false;
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

            // Checkpoint: the indices of the tagged granules, as one sorted
            // array (a full CheriBSD boot holds ~10^5..10^6 tags).
            void serialize (CheckpointOut &cp) const override {
                std::vector<uint64_t> granules;
                granules.reserve(tagTable.size());
                for (const auto &[idx, tag] : tagTable) {
                    if (tag)
                        granules.push_back(idx);
                }
                std::sort(granules.begin(), granules.end());
                SERIALIZE_CONTAINER(granules);
            }

            void unserialize (CheckpointIn &cp) override {
                std::vector<uint64_t> granules;
                UNSERIALIZE_CONTAINER(granules);
                tagTable.clear();
                tagTable.reserve(granules.size());
                for (uint64_t idx : granules)
                    tagTable[idx] = true;
            }

    };
} // namespace gem5


#endif
