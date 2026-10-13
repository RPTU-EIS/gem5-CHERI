/*
 * CHERI tag controller: a timing model of capability tag storage.
 *
 * CHERI keeps one tag bit per 16-byte granule. Main memory has no room for
 * it, so CHERI systems store tags in a table in DRAM and put a tag
 * controller with a small tag cache between the last-level cache and the
 * memory controller: each line fill needs the line's tags, and each
 * writeback updates them. This object models the cost of that design: tag
 * cache hits and misses, the extra DRAM traffic for tag-table reads and
 * writes, and the latency a data response waits for its tags.
 *
 * Tag *values* are not modelled here: the functional tag table
 * (System::cheritagtable) stays the single source of truth, so adding this
 * controller never changes what the simulated program observes, only when.
 *
 * Tag table layout (Joannou et al., "Efficient Tagged Memory", ICCD 2017):
 *  - leaf level: 1 bit per 16-byte granule; a 64-byte leaf line holds the
 *    tags of 8 KiB of data;
 *  - optional root level ("hierarchical"): 1 bit per leaf line, set if any
 *    tag in that leaf line is set; a 64-byte root line covers 4 MiB. If the
 *    root says a leaf line is all zero, the leaf is neither read nor
 *    cached (zero elision).
 * The table lives at tag_table_base, which must be memory the guest does
 * not use (the board reserves it in the device tree).
 */

#ifndef __MEM_CHERI_TAG_CONTROLLER_HH__
#define __MEM_CHERI_TAG_CONTROLLER_HH__

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
    /** Set-associative, LRU, write-back cache of 64-byte tag-table lines.
     *  Size 0 means no cache. */
    class TagCache
    {
      public:
        TagCache(uint64_t size_bytes, unsigned assoc);

        /** Look up a line (updates LRU); optionally mark it dirty. */
        bool access(Addr line, bool make_dirty);
        /** Insert a line that missed. Returns true if a dirty line was
         *  evicted, with its address in victim. */
        bool insert(Addr line, bool dirty, Addr &victim);
        /** False when built with size 0 (no cache: always misses). */
        bool enabled() const { return numSets != 0; }

      private:
        struct Way
        {
            Addr line = 0;
            bool valid = false;
            bool dirty = false;
            uint64_t lastUse = 0;
        };
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

    // ---- Configuration ----
    System *system;
    const AddrRange dataRange;
    const Addr leafBase;
    const Addr rootBase;
    const bool enabled;
    const bool hierarchical;
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

    // ---- Tag-table geometry ----
    static constexpr Addr LineBytes = 64;
    static constexpr Addr LeafLineCoverage = LineBytes * 8 * 16;  // 8 KiB
    static constexpr Addr RootLineCoverage =
        LineBytes * 8 * LeafLineCoverage;                         // 4 MiB

    Addr leafLineOf(Addr data_addr) const;
    Addr rootLineOf(Addr data_addr) const;
    Addr leafRegionOf(Addr data_addr) const;
    bool leafRegionHasTags(Addr data_addr) const;

    // ---- Request handling ----
    bool needsTagWork(PacketPtr pkt) const;
    /** Timing: start the tag work for a data access. Returns true if the
     *  access now waits on a tag fill. */
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
        statistics::Scalar leafMisses;
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
        statistics::Formula tagTrafficRatio;
    } stats;
};

} // namespace gem5

#endif // __MEM_CHERI_TAG_CONTROLLER_HH__
