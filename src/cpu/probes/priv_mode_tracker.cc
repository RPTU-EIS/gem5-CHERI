#include "cpu/probes/priv_mode_tracker.hh"

#include "cpu/thread_context.hh"

namespace gem5
{

PrivModeTracker::PrivModeTracker(const PrivModeTrackerParams &p)
    : ProbeListenerObject(p),
      cpu(p.core),
      privMiscReg(p.priv_misc_reg),
      lastCommit(0),
      stats(this)
{
    if (!cpu)
        fatal("PrivModeTracker: no CPU");
}

void
PrivModeTracker::regProbeListeners()
{
    typedef ProbeListenerArg<PrivModeTracker, Addr> Listener;
    listeners.push_back(new Listener(this, "RetiredInstsPC",
                                     &PrivModeTracker::retired));
}

void
PrivModeTracker::retired(const Addr &pc)
{
    RegVal mode = cpu->getContext(0)->readMiscRegNoEffect(privMiscReg);
    if (mode >= numModes)
        mode = numModes - 1;
    Cycles now = cpu->curCycle();
    stats.insts[mode]++;
    stats.cycles[mode] += now > lastCommit ? now - lastCommit : Cycles(0);
    lastCommit = now;
}

void
PrivModeTracker::resetStats()
{
    ProbeListenerObject::resetStats();
    lastCommit = cpu->curCycle();
}

PrivModeTracker::PrivModeStats::PrivModeStats(statistics::Group *parent)
    : statistics::Group(parent),
      ADD_STAT(insts, statistics::units::Count::get(),
               "Committed instructions per privilege mode"),
      ADD_STAT(cycles, statistics::units::Cycle::get(),
               "Cycles per privilege mode, each attributed to the mode of "
               "the next committed instruction")
{
    const char *names[numModes] = {"user", "supervisor", "hypervisor",
                                   "machine"};
    insts.init(numModes);
    cycles.init(numModes);
    for (int i = 0; i < numModes; i++) {
        insts.subname(i, names[i]);
        cycles.subname(i, names[i]);
    }
}

} // namespace gem5
