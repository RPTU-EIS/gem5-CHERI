/*
 * Counts committed instructions and cycles per privilege mode; stall
 * cycles count for the mode of the next committed instruction.
 */

#ifndef __CPU_PROBES_PRIV_MODE_TRACKER_HH__
#define __CPU_PROBES_PRIV_MODE_TRACKER_HH__

#include "base/statistics.hh"
#include "cpu/base.hh"
#include "params/PrivModeTracker.hh"
#include "sim/probe/probe.hh"

namespace gem5
{

class PrivModeTracker : public ProbeListenerObject
{
  public:
    PrivModeTracker(const PrivModeTrackerParams &params);

    /** listen to the core's RetiredInstsPC probe */
    void regProbeListeners() override;

    /** count one committed instruction (and the cycles before it) */
    void retired(const Addr &pc);

    /** restart cycle attribution from now on a statistics reset */
    void resetStats() override;

  private:
    static constexpr int numModes = 4;

    BaseCPU *cpu;
    int privMiscReg;
    Cycles lastCommit;

    struct PrivModeStats : public statistics::Group
    {
        PrivModeStats(statistics::Group *parent);

        statistics::Vector insts;
        statistics::Vector cycles;
    } stats;
};

} // namespace gem5

#endif // __CPU_PROBES_PRIV_MODE_TRACKER_HH__
