/*
 * Per-PC profile of committed instructions and cycles, per privilege
 * mode, written to <outdir>/<prefix>-<n>.csv at every statistics dump.
 */

#ifndef __CPU_PROBES_PC_PROFILE_HH__
#define __CPU_PROBES_PC_PROFILE_HH__

#include <string>
#include <unordered_map>

#include "cpu/base.hh"
#include "params/PcProfile.hh"
#include "sim/probe/probe.hh"

namespace gem5
{

class PcProfile : public ProbeListenerObject
{
  public:
    PcProfile(const PcProfileParams &params);

    void regProbeListeners() override;
    void retired(const Addr &pc);
    void resetStats() override;

  private:
    struct Count
    {
        uint64_t insts = 0;
        uint64_t cycles = 0;
    };

    /** write the counts since the last reset to the next profile file */
    void write();

    BaseCPU *cpu;
    int privMiscReg;
    std::string prefix;
    Cycles lastCommit;
    int dumps;
    /** per privilege mode (0-3): PC -> counts */
    std::unordered_map<Addr, Count> counts[4];
};

} // namespace gem5

#endif // __CPU_PROBES_PC_PROFILE_HH__
