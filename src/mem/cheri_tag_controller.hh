/*
 * CHERI tag controller: models the timing of a tag table in DRAM
 * behind leaf and optional root tag caches. Tag values stay in the
 * functional tag table, so only timing changes.
 */

#ifndef __MEM_CHERI_TAG_CONTROLLER_HH__
#define __MEM_CHERI_TAG_CONTROLLER_HH__

#include <bitset>
#include <unordered_map>
#include <vector>

#include "base/addr_range.hh"
#include "base/statistics.hh"
#include "mem/qport.hh"
#include "sim/clocked_object.hh"

namespace gem5
{

struct CheriTagControllerParams;
class System;

class CheriTagController : public ClockedObject
{
  public:
    CheriTagController(const CheriTagControllerParams &p);

    void init() override;
    Port &getPort(const std::string &if_name,
                  PortID idx=InvalidPortID) override;
    /** Wait for outstanding tag-table reads and held responses. */
    DrainState drain() override;

  private:
    /** Set-associative, LRU, write-back cache of tag-table lines;
     *  size 0 means no cache. */
    class TagCache
    {
      public:
        /** Data lines a leaf line covers (for spatial/temporal hits). */
        static constexpr unsigned SubLines = 128;

        TagCache(uint64_t size_bytes, unsigned assoc);

        /** Look up a line (LRU); *temporal says whether it already
         *  served data line sub. */
        bool access(Addr line, bool make_dirty, int sub = -1,
                    bool *temporal = nullptr);
        void markDirty(Addr line);
        /** Record that a cached line served data line sub. */
        void serve(Addr line, int sub);
        /** Insert a missed line; true if a dirty victim must be
         *  written back. */
        bool insert(Addr line, bool dirty, Addr &victim,
                    bool *evicted = nullptr);
        /** False when built with size 0 (no cache: always misses). */
        bool enabled() const { return numSets != 0; }

      private:
        struct Way
        {
            Addr line = 0;
            bool valid = false;
            bool dirty = false;
            uint64_t lastUse = 0;
            std::bitset<SubLines> served;
        };
        Way *find(Addr line);
        unsigned numSets;
        unsigned assoc;
        uint64_t useClock = 0;
        std::vector<Way> ways;

        unsigned setOf(Addr line) const;
    };

    class RequestPort : public QueuedRequestPort
    {
      public:
        RequestPort(const std::string &name, CheriTagController &parent);

      protected:
        bool recvTimingResp(PacketPtr pkt) override;
        void recvRangeChange() override;

      private:
        CheriTagController &parent;
    };

    class ResponsePort : public QueuedResponsePort
    {
      public:
        ResponsePort(const std::string &name, CheriTagController &parent);

      protected:
        Tick recvAtomic(PacketPtr pkt) override;
        bool recvTimingReq(PacketPtr pkt) override;
        void recvFunctional(PacketPtr pkt) override;
        AddrRangeList getAddrRanges() const override;

      private:
        CheriTagController &parent;
    };

    /** A data access waiting on the tag table. */
    struct Waiter
    {
        PacketPtr pkt;   // data read whose response waits; nullptr: write
        Addr dataAddr;
        bool isWrite;
        unsigned size;   // bytes written (writes)
    };

    /** An outstanding tag-table line read (an MSHR). */
    struct TagFill
    {
        bool isRoot;
        std::vector<Waiter> waiters;
    };

    /** A data read whose response must wait for its tags. */
    struct HeldRead
    {
        bool tagsPending = true;
        PacketPtr response = nullptr;   // set once the data response arrived
        Tick responseArrival = 0;
    };

    // Configuration
    System *system;
    const AddrRange dataRange;
    const Addr leafBase;
    const Addr rootBase;
    const bool enabled;
    const bool hierarchical;
    const bool silentWriteElim;
    const Cycles lookupLatency;
    RequestorID requestorId = 0;

    TagCache leafCache;
    TagCache rootCache;

    RequestPort requestPort;
    ResponsePort responsePort;
    ReqPacketQueue reqQueue;
    RespPacketQueue respQueue;
    SnoopRespPacketQueue snoopRespQueue;

    std::unordered_map<Addr, TagFill> fills;
    std::unordered_map<PacketPtr, HeldRead> heldReads;

    // Tag-table geometry
    static constexpr Addr LineBytes = 64;
    static constexpr Addr LeafLineCoverage = LineBytes * 8 * 16;  // 8 KiB
    static constexpr Addr RootLineCoverage =
        LineBytes * 8 * LeafLineCoverage;                         // 4 MiB

    static constexpr Addr DataLineBytes = 64;

    Addr leafLineOf(Addr data_addr) const;
    Addr rootLineOf(Addr data_addr) const;
    Addr leafRegionOf(Addr data_addr) const;
    bool leafRegionHasTags(Addr data_addr) const;
    /** Index of the data line within its leaf line's coverage. */
    int subLineOf(Addr data_addr) const;

    // Tag values, for silent-write elimination
    /** One bit per 16-byte granule of a leaf line's 8 KiB. */
    using LeafBits = std::bitset<LeafLineCoverage / 16>;
    /** Leaf lines as in memory and in the leaf cache; they lag the
     *  functional table until data is written back. */
    std::unordered_map<Addr, LeafBits> memTags;
    std::unordered_map<Addr, LeafBits> cachedTags;

    /** Does a data write change its leaf line's tags? Always true
     *  without elimination. */
    bool writeChangesTags(Addr leaf, const Waiter &w);
    /** Insert a leaf line; true, with victim set, if a dirty line is
     *  evicted. */
    bool insertLeaf(Addr leaf, Addr &victim);
    /** Apply the waiting accesses to a leaf line that just came in. */
    bool applyFill(Addr leaf, const std::vector<Waiter> &ws);

    // Request handling
    bool needsTagWork(PacketPtr pkt) const;
    /** Start the tag work for a data access; true if it waits on a
     *  tag fill. */
    bool startTagWork(const Waiter &w);
    /** Leaf-level step, once the root is known (or without a root). */
    bool leafStep(const Waiter &w);
    void attachToFill(Addr line, bool is_root, const Waiter &w);
    void issueTagRead(Addr line);
    void issueTagWriteback(Addr line);
    void handleTagResponse(PacketPtr pkt);
    void releaseWaiter(const Waiter &w);
    void insertLine(bool is_root, Addr line, bool dirty);

    Tick atomicTagWork(const Waiter &w);
    Tick atomicTagAccess(Addr line, MemCmd cmd);

    bool handleDataResponse(PacketPtr pkt);
    bool trySatisfyFunctional(PacketPtr pkt);

    struct Stats : public statistics::Group
    {
        Stats(statistics::Group *parent);

        statistics::Scalar leafHits;
        statistics::Scalar leafSpatialHits;
        statistics::Scalar leafTemporalHits;
        statistics::Scalar leafMisses;
        statistics::Scalar leafEvictions;
        statistics::Scalar leafDirtyEvictions;
        statistics::Scalar silentWrites;
        statistics::Scalar rootHits;
        statistics::Scalar rootMisses;
        statistics::Scalar zeroElided;
        statistics::Scalar tagReads;
        statistics::Scalar tagWrites;
        statistics::Scalar dataReads;
        statistics::Scalar dataWrites;
        statistics::Scalar delayedReads;
        statistics::Scalar delayTicks;
        statistics::Formula avgDelayTicks;
        statistics::Formula leafHitRate;
        statistics::Formula leafDirtyEvictionRatio;
        statistics::Formula tagTrafficRatio;
    } stats;
};

} // namespace gem5

#endif // __MEM_CHERI_TAG_CONTROLLER_HH__
