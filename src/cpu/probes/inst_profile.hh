/*
 * Per-mnemonic profile of committed (micro-)ops.
 *
 * Listens to a CPU's "RetiredInstsStatic" probe and counts every committed
 * op per (privilege mode, static instruction); the mode comes from a
 * miscellaneous register (RISC-V: MISCREG_PRV). At every statistics dump
 * the counts since the last reset are written, aggregated by mnemonic, to
 * <outdir>/<prefix>-<n>.csv (mode,mnemonic,op_class,load,store,count;
 * n = 1, 2, ...), so the files line up with the stats.txt dumps. Lets the
 * instruction mix be split beyond gem5's op classes, e.g. capability-width
 * loads/stores from integer ones (util/cheri/overhead_bars.py).
 */

#ifndef __CPU_PROBES_INST_PROFILE_HH__
#define __CPU_PROBES_INST_PROFILE_HH__

#include <string>
#include <unordered_map>
#include <vector>

#include "cpu/base.hh"
#include "cpu/static_inst.hh"
#include "params/InstProfile.hh"
#include "sim/probe/probe.hh"

namespace gem5
{

class InstProfile : public ProbeListenerObject
{
  public:
    InstProfile(const InstProfileParams &params);

    void regProbeListeners() override;
    void retired(const StaticInstPtr &inst);
    void resetStats() override;

  private:
    /** write the counts since the last reset to the next profile file */
    void write();

    BaseCPU *cpu;
    int privMiscReg;
    std::string prefix;
    int dumps;
    /** per privilege mode (0-3): static instruction -> committed count */
    std::unordered_map<StaticInst *, uint64_t> counts[4];
    /** keeps every counted static instruction alive until the next write */
    std::vector<StaticInstPtr> keep;
};

} // namespace gem5

#endif // __CPU_PROBES_INST_PROFILE_HH__
