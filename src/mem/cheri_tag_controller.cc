/*
 * CHERI tag controller: a timing model of capability tag storage.
 * See cheri_tag_controller.hh.
 */

#include "mem/cheri_tag_controller.hh"

#include <algorithm>
#include <cstring>

#include "base/intmath.hh"
#include "base/logging.hh"
#include "base/trace.hh"
#include "debug/CheriTagCtrl.hh"
#include "mem/cheri_tag_table.hh"
#include "params/CheriTagController.hh"
#include "sim/system.hh"

namespace gem5
{

// ---------------------------------------------------------------------------
// TagCache

CheriTagController::TagCache::TagCache(uint64_t size_bytes, unsigned _assoc)
    : assoc(std::max(1u, _assoc))
{
    if (size_bytes == 0) {
        // No cache: every lookup misses and nothing is kept.
        numSets = 0;
        return;
    }
    uint64_t lines = std::max<uint64_t>(1, size_bytes / LineBytes);
    numSets = std::max<uint64_t>(1, lines / assoc);
    ways.resize((size_t)numSets * assoc);
}

unsigned
CheriTagController::TagCache::setOf(Addr line) const
{
    return (line / LineBytes) % numSets;
}

bool
CheriTagController::TagCache::access(Addr line, bool make_dirty)
{
    if (numSets == 0)
        return false;
    Way *set = &ways[(size_t)setOf(line) * assoc];
    for (unsigned i = 0; i < assoc; i++) {
        if (set[i].valid && set[i].line == line) {
            set[i].lastUse = ++useClock;
            set[i].dirty |= make_dirty;
            return true;
        }
    }
    return false;
}

bool
CheriTagController::TagCache::insert(Addr line, bool dirty, Addr &victim)
{
    if (numSets == 0) {
        victim = 0;
        return false;
    }
    Way *set = &ways[(size_t)setOf(line) * assoc];
    Way *v = &set[0];
    for (unsigned i = 0; i < assoc; i++) {
        if (!set[i].valid) {
            v = &set[i];
            break;
        }
        if (set[i].lastUse < v->lastUse)
            v = &set[i];
    }
    bool evict_dirty = v->valid && v->dirty;
    victim = v->line;
    v->line = line;
    v->valid = true;
    v->dirty = dirty;
    v->lastUse = ++useClock;
    return evict_dirty;
}

// ---------------------------------------------------------------------------
// Construction and ports

CheriTagController::CheriTagController(const CheriTagControllerParams &p)
    : ClockedObject(p),
      system(p.system),
      dataRange(p.data_range),
      leafBase(p.tag_table_base),
      rootBase(p.tag_table_base +
               roundUp(divCeil(p.data_range.size(), LeafLineCoverage) *
                       LineBytes, LineBytes)),
      enabled(p.enabled),
      hierarchical(p.hierarchical),
      lookupLatency(p.lookup_latency),
      leafCache(p.leaf_cache_size, p.leaf_cache_assoc),
      rootCache(p.root_cache_size, p.root_cache_assoc),
      requestPort(name() + ".mem_side_port", *this),
      responsePort(name() + ".cpu_side_port", *this),
      reqQueue(*this, requestPort),
      respQueue(*this, responsePort),
      snoopRespQueue(*this, requestPort),
      stats(this)
{
    fatal_if(!system, "CheriTagController needs a system (for the "
             "functional tag table)");
    requestorId = system->getRequestorId(this);
}

void
CheriTagController::init()
{
    ClockedObject::init();
    fatal_if(!responsePort.isConnected() || !requestPort.isConnected(),
             "CheriTagController is not connected on both sides");
    responsePort.sendRangeChange();
}

Port &
CheriTagController::getPort(const std::string &if_name, PortID idx)
{
    if (if_name == "mem_side_port")
        return requestPort;
    if (if_name == "cpu_side_port")
        return responsePort;
    return ClockedObject::getPort(if_name, idx);
}

CheriTagController::RequestPort::RequestPort(const std::string &_name,
                                             CheriTagController &_parent)
    : QueuedRequestPort(_name, _parent.reqQueue, _parent.snoopRespQueue),
      parent(_parent)
{
}

bool
CheriTagController::RequestPort::recvTimingResp(PacketPtr pkt)
{
    if (pkt->req->requestorId() == parent.requestorId) {
        parent.handleTagResponse(pkt);
        return true;
    }
    return parent.handleDataResponse(pkt);
}

void
CheriTagController::RequestPort::recvRangeChange()
{
    parent.responsePort.sendRangeChange();
}

CheriTagController::ResponsePort::ResponsePort(const std::string &_name,
                                               CheriTagController &_parent)
    : QueuedResponsePort(_name, _parent.respQueue), parent(_parent)
{
}

AddrRangeList
CheriTagController::ResponsePort::getAddrRanges() const
{
    return parent.requestPort.getAddrRanges();
}

void
CheriTagController::ResponsePort::recvFunctional(PacketPtr pkt)
{
    if (parent.trySatisfyFunctional(pkt))
        pkt->makeResponse();
    else
        parent.requestPort.sendFunctional(pkt);
}

bool
CheriTagController::trySatisfyFunctional(PacketPtr pkt)
{
    return responsePort.trySatisfyFunctional(pkt) ||
           requestPort.trySatisfyFunctional(pkt);
}

// ---------------------------------------------------------------------------
// Tag-table geometry

Addr
CheriTagController::leafLineOf(Addr data_addr) const
{
    return leafBase +
           ((data_addr - dataRange.start()) / LeafLineCoverage) * LineBytes;
}

Addr
CheriTagController::rootLineOf(Addr data_addr) const
{
    return rootBase +
           ((data_addr - dataRange.start()) / RootLineCoverage) * LineBytes;
}

Addr
CheriTagController::leafRegionOf(Addr data_addr) const
{
    return dataRange.start() +
           ((data_addr - dataRange.start()) / LeafLineCoverage) *
           LeafLineCoverage;
}

bool
CheriTagController::leafRegionHasTags(Addr data_addr) const
{
    return system->cheritagtable.anyTagInRange(leafRegionOf(data_addr),
                                               LeafLineCoverage);
}

bool
CheriTagController::needsTagWork(PacketPtr pkt) const
{
    if (!enabled || pkt->cacheResponding())
        return false;
    Addr a = pkt->getAddr();
    // Our own tag-table accesses (and anything else in the reserved tag
    // region) carry no tags.
    if (!dataRange.contains(a) || a >= leafBase)
        return false;
    if (pkt->isRead() && pkt->needsResponse())
        return true;
    // A clean writeback does not change memory, so not its tags either.
    return pkt->isWrite() && pkt->cmd != MemCmd::WritebackClean;
}

// ---------------------------------------------------------------------------
// Timing mode

bool
CheriTagController::ResponsePort::recvTimingReq(PacketPtr pkt)
{
    // The packet only reaches us after the header delay; we also need to
    // deserialise the payload.
    Tick receive_delay = pkt->headerDelay + pkt->payloadDelay;
    pkt->headerDelay = pkt->payloadDelay = 0;

    if (parent.needsTagWork(pkt)) {
        bool is_read = pkt->isRead();
        Waiter w{is_read ? pkt : nullptr, pkt->getAddr(), !is_read};
        if (is_read) {
            parent.stats.dataReads++;
            // Register before starting: a fill may complete synchronously
            // in principle, and releaseWaiter() expects the entry.
            parent.heldReads[pkt] = HeldRead();
            if (!parent.startTagWork(w))
                parent.heldReads.erase(pkt);
        } else {
            parent.stats.dataWrites++;
            parent.startTagWork(w);
        }
    }

    // The data access proceeds in parallel with any tag-table access.
    parent.requestPort.schedTimingReq(pkt, curTick() + receive_delay);
    return true;
}

bool
CheriTagController::startTagWork(const Waiter &w)
{
    Addr leaf = leafLineOf(w.dataAddr);
    if (leafCache.access(leaf, w.isWrite)) {
        stats.leafHits++;
        return false;
    }
    stats.leafMisses++;

    if (!hierarchical) {
        attachToFill(leaf, false, w);
        return w.pkt != nullptr;
    }

    Addr root = rootLineOf(w.dataAddr);
    if (rootCache.access(root, false)) {
        stats.rootHits++;
        return leafStep(w);
    }
    stats.rootMisses++;
    attachToFill(root, true, w);
    return w.pkt != nullptr;
}

bool
CheriTagController::leafStep(const Waiter &w)
{
    Addr leaf = leafLineOf(w.dataAddr);
    // The leaf may have been filled while the root was being read.
    if (leafCache.access(leaf, w.isWrite))
        return false;
    if (!leafRegionHasTags(w.dataAddr)) {
        // The root bit says this leaf line is all zero: no leaf access.
        stats.zeroElided++;
        return false;
    }
    attachToFill(leaf, false, w);
    return w.pkt != nullptr;
}

void
CheriTagController::attachToFill(Addr line, bool is_root, const Waiter &w)
{
    auto it = fills.find(line);
    if (it != fills.end()) {
        it->second.waiters.push_back(w);
        return;
    }
    fills[line] = TagFill{is_root, {w}};
    issueTagRead(line);
}

void
CheriTagController::issueTagRead(Addr line)
{
    auto req = std::make_shared<Request>(line, LineBytes, Request::Flags(0),
                                         requestorId);
    PacketPtr pkt = new Packet(req, MemCmd::ReadReq);
    pkt->allocate();
    stats.tagReads++;
    DPRINTF(CheriTagCtrl, "tag read %#x\n", line);
    requestPort.schedTimingReq(pkt, clockEdge(lookupLatency));
}

void
CheriTagController::issueTagWriteback(Addr line)
{
    auto req = std::make_shared<Request>(line, LineBytes, Request::Flags(0),
                                         requestorId);
    PacketPtr pkt = new Packet(req, MemCmd::WritebackDirty);
    pkt->allocate();
    // The reserved tag region is not guest memory; its contents are unused
    // (tag values come from the functional tag table).
    std::memset(pkt->getPtr<uint8_t>(), 0, LineBytes);
    stats.tagWrites++;
    DPRINTF(CheriTagCtrl, "tag writeback %#x\n", line);
    requestPort.schedTimingReq(pkt, clockEdge(lookupLatency));
}

void
CheriTagController::insertLine(bool is_root, Addr line, bool dirty)
{
    Addr victim;
    TagCache &cache = is_root ? rootCache : leafCache;
    if (cache.insert(line, dirty, victim))
        issueTagWriteback(victim);
}

void
CheriTagController::handleTagResponse(PacketPtr pkt)
{
    Addr line = pkt->getAddr();
    delete pkt;

    auto it = fills.find(line);
    panic_if(it == fills.end(), "unexpected tag-table response %#x", line);
    TagFill fill = std::move(it->second);
    fills.erase(it);

    bool any_write = std::any_of(fill.waiters.begin(), fill.waiters.end(),
                                 [](const Waiter &w) { return w.isWrite; });
    insertLine(fill.isRoot, line, !fill.isRoot && any_write);
    // Without a leaf cache a tag write is a read-modify-write of the
    // tag-table line: write it back right away (one write for all the
    // writes that waited on this read).
    if (!fill.isRoot && any_write && !leafCache.enabled())
        issueTagWriteback(line);

    for (const Waiter &w : fill.waiters) {
        // After a root fill the access still needs its leaf level.
        bool still_waiting = fill.isRoot && leafStep(w);
        if (!still_waiting)
            releaseWaiter(w);
    }

    if (drainState() == DrainState::Draining && fills.empty() &&
        heldReads.empty()) {
        signalDrainDone();
    }
}

void
CheriTagController::releaseWaiter(const Waiter &w)
{
    if (!w.pkt)
        return;
    auto it = heldReads.find(w.pkt);
    panic_if(it == heldReads.end(), "tag waiter without a held read");
    HeldRead &h = it->second;
    h.tagsPending = false;
    if (h.response) {
        stats.delayedReads++;
        stats.delayTicks += curTick() - h.responseArrival;
        responsePort.schedTimingResp(h.response, curTick());
        heldReads.erase(it);
    }
}

bool
CheriTagController::handleDataResponse(PacketPtr pkt)
{
    Tick receive_delay = pkt->headerDelay + pkt->payloadDelay;
    pkt->headerDelay = pkt->payloadDelay = 0;

    auto it = heldReads.find(pkt);
    if (it != heldReads.end()) {
        if (it->second.tagsPending) {
            // Data is back before its tags: hold the response.
            it->second.response = pkt;
            it->second.responseArrival = curTick() + receive_delay;
            return true;
        }
        heldReads.erase(it);
    }
    responsePort.schedTimingResp(pkt, curTick() + receive_delay);

    if (drainState() == DrainState::Draining && fills.empty() &&
        heldReads.empty()) {
        signalDrainDone();
    }
    return true;
}

DrainState
CheriTagController::drain()
{
    return (fills.empty() && heldReads.empty()) ? DrainState::Drained
                                                : DrainState::Draining;
}

// ---------------------------------------------------------------------------
// Atomic mode: same cache state and traffic, latencies added in series

Tick
CheriTagController::ResponsePort::recvAtomic(PacketPtr pkt)
{
    bool tag_work = parent.needsTagWork(pkt);
    bool is_read = pkt->isRead();
    Waiter w{nullptr, pkt->getAddr(), !is_read};

    Tick lat = parent.requestPort.sendAtomic(pkt);
    if (tag_work) {
        if (is_read)
            parent.stats.dataReads++;
        else
            parent.stats.dataWrites++;
        Tick tag_lat = parent.atomicTagWork(w);
        // Tags are fetched in parallel with the data.
        if (is_read)
            lat = std::max(lat, tag_lat);
    }
    return lat;
}

Tick
CheriTagController::atomicTagAccess(Addr line, MemCmd cmd)
{
    auto req = std::make_shared<Request>(line, LineBytes, Request::Flags(0),
                                         requestorId);
    Packet pkt(req, cmd);
    pkt.allocate();
    if (pkt.isWrite()) {
        std::memset(pkt.getPtr<uint8_t>(), 0, LineBytes);
        stats.tagWrites++;
    } else {
        stats.tagReads++;
    }
    return requestPort.sendAtomic(&pkt);
}

Tick
CheriTagController::atomicTagWork(const Waiter &w)
{
    Addr leaf = leafLineOf(w.dataAddr);
    if (leafCache.access(leaf, w.isWrite)) {
        stats.leafHits++;
        return 0;
    }
    stats.leafMisses++;

    Tick lat = cyclesToTicks(lookupLatency);
    Addr victim;
    if (hierarchical) {
        Addr root = rootLineOf(w.dataAddr);
        if (rootCache.access(root, false)) {
            stats.rootHits++;
        } else {
            stats.rootMisses++;
            lat += atomicTagAccess(root, MemCmd::ReadReq);
            if (rootCache.insert(root, false, victim))
                atomicTagAccess(victim, MemCmd::WritebackDirty);
        }
        if (!leafRegionHasTags(w.dataAddr)) {
            stats.zeroElided++;
            return lat;
        }
    }
    lat += atomicTagAccess(leaf, MemCmd::ReadReq);
    if (leafCache.insert(leaf, w.isWrite, victim))
        atomicTagAccess(victim, MemCmd::WritebackDirty);
    if (w.isWrite && !leafCache.enabled())
        atomicTagAccess(leaf, MemCmd::WritebackDirty);  // read-modify-write
    return lat;
}

// ---------------------------------------------------------------------------
// Statistics

CheriTagController::Stats::Stats(statistics::Group *parent)
    : statistics::Group(parent),
      ADD_STAT(leafHits, statistics::units::Count::get(),
               "Leaf tag-cache hits"),
      ADD_STAT(leafMisses, statistics::units::Count::get(),
               "Leaf tag-cache misses"),
      ADD_STAT(rootHits, statistics::units::Count::get(),
               "Root tag-cache hits"),
      ADD_STAT(rootMisses, statistics::units::Count::get(),
               "Root tag-cache misses"),
      ADD_STAT(zeroElided, statistics::units::Count::get(),
               "Leaf accesses skipped because the root bit was zero"),
      ADD_STAT(tagReads, statistics::units::Count::get(),
               "Tag-table line reads sent to memory"),
      ADD_STAT(tagWrites, statistics::units::Count::get(),
               "Tag-table line writebacks sent to memory"),
      ADD_STAT(dataReads, statistics::units::Count::get(),
               "Data reads needing tags"),
      ADD_STAT(dataWrites, statistics::units::Count::get(),
               "Data writes updating tags"),
      ADD_STAT(delayedReads, statistics::units::Count::get(),
               "Data responses that waited for their tags"),
      ADD_STAT(delayTicks, statistics::units::Tick::get(),
               "Total time data responses waited for tags"),
      ADD_STAT(avgDelayTicks, statistics::units::Rate<
                   statistics::units::Tick, statistics::units::Count>::get(),
               "Average wait of a delayed data response"),
      ADD_STAT(leafHitRate, statistics::units::Ratio::get(),
               "Leaf tag-cache hit rate"),
      ADD_STAT(tagTrafficRatio, statistics::units::Ratio::get(),
               "Tag-table accesses per data access")
{
    avgDelayTicks = delayTicks / delayedReads;
    leafHitRate = leafHits / (leafHits + leafMisses);
    tagTrafficRatio = (tagReads + tagWrites) / (dataReads + dataWrites);
}

} // namespace gem5
