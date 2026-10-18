#include "cpu/probes/inst_profile.hh"

#include <map>
#include <tuple>

#include "base/output.hh"
#include "base/statistics.hh"
#include "cpu/thread_context.hh"
#include "enums/OpClass.hh"

namespace gem5
{

InstProfile::InstProfile(const InstProfileParams &p)
    : ProbeListenerObject(p),
      cpu(p.core),
      privMiscReg(p.priv_misc_reg),
      prefix(p.file_prefix),
      dumps(0)
{
    if (!cpu)
        fatal("InstProfile: no CPU");
    statistics::registerDumpCallback([this]() { write(); });
}

void
InstProfile::regProbeListeners()
{
    typedef ProbeListenerArg<InstProfile, StaticInstPtr> Listener;
    listeners.push_back(new Listener(this, "RetiredInstsStatic",
                                     &InstProfile::retired));
}

void
InstProfile::retired(const StaticInstPtr &inst)
{
    RegVal mode = cpu->getContext(0)->readMiscRegNoEffect(privMiscReg) & 3;
    auto res = counts[mode].emplace(inst.get(), 0);
    if (res.second)
        keep.push_back(inst);
    res.first->second++;
}

void
InstProfile::resetStats()
{
    ProbeListenerObject::resetStats();
    for (auto &m : counts)
        m.clear();
    keep.clear();
}

void
InstProfile::write()
{
    dumps++;
    // (mode, mnemonic, op class, load, store) -> count
    std::map<std::tuple<int, std::string, std::string, bool, bool>,
             uint64_t> rows;
    for (int mode = 0; mode < 4; mode++) {
        for (const auto &[si, n] : counts[mode]) {
            rows[{mode, si->getName(), enums::OpClassStrings[si->opClass()],
                  si->isLoad(), si->isStore() || si->isAtomic()}] += n;
        }
    }
    OutputStream *os = simout.create(
        prefix + "-" + std::to_string(dumps) + ".csv");
    std::ostream &out = *os->stream();
    out << "mode,mnemonic,op_class,load,store,count\n";
    for (const auto &[k, n] : rows) {
        out << std::get<0>(k) << "," << std::get<1>(k) << ","
            << std::get<2>(k) << "," << std::get<3>(k) << ","
            << std::get<4>(k) << "," << n << "\n";
    }
    simout.close(os);
}

} // namespace gem5
