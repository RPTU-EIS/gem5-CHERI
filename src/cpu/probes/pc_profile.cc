#include "cpu/probes/pc_profile.hh"

#include <algorithm>
#include <vector>

#include "base/output.hh"
#include "base/statistics.hh"
#include "cpu/thread_context.hh"

namespace gem5
{

PcProfile::PcProfile(const PcProfileParams &p)
    : ProbeListenerObject(p),
      cpu(p.core),
      privMiscReg(p.priv_misc_reg),
      prefix(p.file_prefix),
      lastCommit(0),
      dumps(0)
{
    if (!cpu)
        fatal("PcProfile: no CPU");
    statistics::registerDumpCallback([this]() { write(); });
}

void
PcProfile::regProbeListeners()
{
    typedef ProbeListenerArg<PcProfile, Addr> Listener;
    listeners.push_back(new Listener(this, "RetiredInstsPC",
                                     &PcProfile::retired));
}

void
PcProfile::retired(const Addr &pc)
{
    RegVal mode = cpu->getContext(0)->readMiscRegNoEffect(privMiscReg) & 3;
    Cycles now = cpu->curCycle();
    Count &c = counts[mode][pc];
    c.insts++;
    c.cycles += now > lastCommit ? now - lastCommit : Cycles(0);
    lastCommit = now;
}

void
PcProfile::resetStats()
{
    ProbeListenerObject::resetStats();
    for (auto &m : counts)
        m.clear();
    lastCommit = cpu->curCycle();
}

void
PcProfile::write()
{
    dumps++;
    OutputStream *os = simout.create(
        prefix + "-" + std::to_string(dumps) + ".csv");
    std::ostream &out = *os->stream();
    out << "mode,pc,insts,cycles\n";
    for (int mode = 0; mode < 4; mode++) {
        std::vector<std::pair<Addr, Count>> rows(counts[mode].begin(),
                                                 counts[mode].end());
        std::sort(rows.begin(), rows.end(), [](const auto &a,
                                               const auto &b) {
            return a.first < b.first;
        });
        for (const auto &[pc, c] : rows) {
            out << mode << ",0x" << std::hex << pc << std::dec << ","
                << c.insts << "," << c.cycles << "\n";
        }
    }
    simout.close(os);
}

} // namespace gem5
