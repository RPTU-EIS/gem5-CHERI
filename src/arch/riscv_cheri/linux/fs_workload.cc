/*
 * Copyright (c) 2021 Huawei International
 * All rights reserved
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

#include "arch/riscv_cheri/linux/fs_workload.hh"

#include <fstream>
#include <memory>

#include "arch/riscv_cheri/cheri_checks.hh"
#include "arch/riscv_cheri/faults.hh"
#include "arch/riscv_cheri/pcstate.hh"
#include "arch/riscv_cheri/regs/cap.hh"
#include "base/loader/dtb_file.hh"
#include "base/loader/object_file.hh"
#include "base/loader/symtab.hh"
#include "cpu/pc_event.hh"
#include "cpu/thread_context.hh"
#include "kern/linux/events.hh"
#include "sim/kernel_workload.hh"
#include "sim/sim_exit.hh"
#include "sim/system.hh"

namespace gem5
{

namespace CHERIRiscvISA
{

namespace
{

} // anonymous namespace

void
FsLinux::initState()
{
    KernelWorkload::initState();

    if (params().dtb_filename != "") {
        inform("Loading DTB file: %s at address %#x\n", params().dtb_filename,
                params().dtb_addr);

        auto *dtb_file = new loader::DtbFile(params().dtb_filename);

        if (!dtb_file->addBootCmdLine(
                    commandLine.c_str(), commandLine.size())) {
            warn("couldn't append bootargs to DTB file: %s\n",
                 params().dtb_filename);
        }

        dtb_file->buildImage().offset(params().dtb_addr)
            .write(system->physProxy);
        delete dtb_file;

        for (auto *tc: system->threads) {
            // a1 = DTB physical address (RISC-V boot convention), written
            // to the capability register (merged register file).
            CapRegContainer dtb_cap =
                CapRegContainer::almighty(params().dtb_addr);
            tc->setReg(cap_reg::CA1, &dtb_cap);
        }
    } else {
        warn("No DTB file specified\n");
    }

    for (auto *tc: system->threads) {
        CHERIRiscvISA::Reset().invoke(tc);
        tc->activate();
    }
}

void
FsLinux::startup()
{
    KernelWorkload::startup();

    addExitOnKernelPanicEvent();
    addExitOnKernelOopsEvent();
}

void
FsLinux::addExitOnKernelPanicEvent()
{
    const std::string dmesg_output = name() + ".dmesg";
    if (params().exit_on_kernel_panic) {
        kernelPanicPcEvent = addKernelFuncEvent<linux::PanicOrOopsEvent>(
            "panic", "Kernel panic in simulated system.",
            dmesg_output, params().on_panic
        );
        warn_if(!kernelPanicPcEvent, "Failed to find kernel symbol 'panic'");
    }
}

void
FsLinux::addExitOnKernelOopsEvent()
{
    const std::string dmesg_output = name() + ".dmesg";
    if (params().exit_on_kernel_oops) {
        kernelOopsPcEvent = addKernelFuncEvent<linux::PanicOrOopsEvent>(
            "oops_exit", "Kernel oops in simulated system.",
            dmesg_output, params().on_oops
        );
        warn_if(!kernelOopsPcEvent,
                "Failed to find kernel symbol 'oops_exit'");
    }
}

void
BootloaderKernelWorkload::loadBootloaderSymbolTable()
{
    if (params().bootloader_filename != "") {
        Addr bootloader_paddr_offset = params().bootloader_addr;
        bootloader = loader::createObjectFile(params().bootloader_filename);
        bootloaderSymbolTable = bootloader->symtab();
        auto renamedBootloaderSymbolTable = \
            bootloaderSymbolTable.offset(
                bootloader_paddr_offset
            )->functionSymbols()->rename(
                [](const std::string &name) {
                    return "bootloader." + name;
                }
            );
        loader::debugSymbolTable.insert(*renamedBootloaderSymbolTable);
    }
}

void
BootloaderKernelWorkload::loadKernelSymbolTable()
{
    if (params().object_file != "") {
        kernel = loader::createObjectFile(params().object_file);
        kernelSymbolTable = kernel->symtab();
        auto renamedKernelSymbolTable = \
            kernelSymbolTable.functionSymbols()->rename(
                [](const std::string &name) {
                    return "kernel." + name;
                }
            );
        loader::debugSymbolTable.insert(*renamedKernelSymbolTable);
    }
}

void
BootloaderKernelWorkload::loadBootloader()
{
    if (params().bootloader_filename != "") {
        Addr bootloader_addr_offset = params().bootloader_addr;
        bootloader->buildImage().offset(bootloader_addr_offset).write(
            system->physProxy
        );
        delete bootloader;

        inform("Loaded bootloader \'%s\' at 0x%llx\n",
               params().bootloader_filename,
               bootloader_addr_offset);
    } else {
        inform("Bootloader is not specified.\n");
    }
}

void
BootloaderKernelWorkload::loadKernel()
{
    if (params().object_file != "") {
        Addr kernel_paddr_offset = params().kernel_addr;
        kernel->buildImage().offset(kernel_paddr_offset).write(
            system->physProxy
        );

        processCapRelocs();

        // Patch _start to keep the DTB pointer, as there is no loader
        // (2024: c.li a1,0 -> c.nop; 2026: c.li s4,0 -> c.mv s4,a1).
        {
            constexpr Addr VA_BASE = 0xffffffc000000000ULL;
            constexpr Addr PA_BASE = 0x80200000ULL;
            auto sym = kernelSymbolTable.find("_start");
            Addr start_pa = sym != kernelSymbolTable.end()
                ? sym->address() - VA_BASE + PA_BASE : 0x80200044ULL;
            bool patched = false;
            for (Addr pa = start_pa; pa < start_pa + 16 && !patched;
                 pa += 2) {
                uint16_t insn = 0;
                system->physProxy.readBlob(pa, (uint8_t *)&insn,
                                           sizeof(insn));
                uint16_t repl = 0;
                const char *what = nullptr;
                if (insn == 0x4581) {
                    repl = 0x0001;
                    what = "c.li a1,0 -> c.nop";
                } else if (insn == 0x4a01) {
                    repl = 0x8a2e;
                    what = "c.li s4,0 -> c.mv s4,a1";
                }
                if (what) {
                    system->physProxy.writeBlob(pa, (const uint8_t *)&repl,
                                                sizeof(repl));
                    inform("Patched %s @%#x (keep the DTB pointer)\n",
                           what, pa);
                    patched = true;
                }
            }
            if (!patched)
                warn("No DTB-pointer clear found near _start @%#x; DTB "
                     "patch NOT applied\n", start_pa);
        }

        delete kernel;

        inform("Loaded kernel \'%s\' at 0x%llx\n",
                params().object_file,
                kernel_paddr_offset);
    } else {
        inform("Kernel is not specified.\n");
    }
}

void
BootloaderKernelWorkload::processCapRelocs()
{
    using namespace gem5::CHERIRiscvISA;

    // 1. Find symbol bounds of __cap_relocs section
    auto start_sym = kernelSymbolTable.find("__start___cap_relocs");
    auto stop_sym  = kernelSymbolTable.find("__stop___cap_relocs");

    if (start_sym == kernelSymbolTable.end() ||
        stop_sym == kernelSymbolTable.end()) {
        warn("No __cap_relocs section found, skipping\n");
        return;
    }

    Addr start_vaddr = start_sym->address();
    Addr stop_vaddr  = stop_sym->address();
    Addr total_size  = stop_vaddr - start_vaddr;

    inform("Processing __cap_relocs: VA [%#lx, %#lx) size=%#lx\n",
        start_vaddr, stop_vaddr, total_size);

    // 2. Determine VA->PA translation
    // For CheriBSD: VA 0xffffffc000000000 -> PA 0x80200000
    constexpr Addr KERNEL_VA_BASE = 0xffffffc000000000ULL;
    constexpr Addr KERNEL_PA_BASE = 0x80200000ULL;

    auto va_to_pa = [&](Addr va) -> Addr {
        return va - KERNEL_VA_BASE + KERNEL_PA_BASE;
    };

    // 3. Walk entries (40 bytes each)
    constexpr size_t ENTRY_SIZE = 40;
    size_t num_entries = total_size / ENTRY_SIZE;

    inform("Processing %lu cap_reloc entries\n", num_entries);

    for (size_t i = 0; i < num_entries; ++i) {
        Addr entry_paddr = va_to_pa(start_vaddr + i * ENTRY_SIZE);

        // Read the 5 fields of the cap_reloc entry
        uint64_t fields[5];
        system->physProxy.readBlob(entry_paddr, fields, ENTRY_SIZE);

        uint64_t cap_loc   = fields[0];  // target VA where to store the cap
        uint64_t obj_base  = fields[1];  // base of object
        uint64_t offset    = fields[2];  // initial address within object
        uint64_t obj_size  = fields[3];  // length for bounds
        uint64_t perms     = fields[4];  // permissions (bit 63 = function flag)

        // Construct the capability
        Addr cap_address = obj_base + offset;
        bool is_function = (perms >> 63) & 1;
        uint64_t perm_bits = perms & 0x7FFFFFFFFFFFFFFFULL;

        // Almighty placeholder: the kernel's locore rewrites every entry
        // with its real bounds and permissions before using any of them.
        CapRegContainer cap = CapRegContainer::almighty(cap_address);

        // Translate target VA -> PA and write the cap
        Addr cap_loc_paddr = va_to_pa(cap_loc);

        // Write 16 bytes (CC128 layout)
        uint64_t cap_addr_bits = cap.getAddress();
        uint64_t cap_meta_bits = cap.getMetadata();
        system->physProxy.writeBlob(cap_loc_paddr + 0, &cap_addr_bits, 8);
        system->physProxy.writeBlob(cap_loc_paddr + 8, &cap_meta_bits, 8);

        // Relocated capabilities are valid: set their tag
        system->cheritagtable.setTag(cap_loc_paddr, true);

    }

    inform("Processed %lu cap_relocs entries\n", num_entries);
}


void
BootloaderKernelWorkload::loadDtb()
{
    if (params().dtb_filename != "") {
        auto *dtb_file = new loader::DtbFile(params().dtb_filename);

        dtb_file->buildImage().offset(params().dtb_addr)
            .write(system->physProxy);
        delete dtb_file;

        inform("Loaded DTB \'%s\' at 0x%llx\n",
                params().dtb_filename,
                params().dtb_addr);

        for (auto *tc: system->threads) {
            // a1 = DTB physical address (RISC-V boot convention), written
            // to the capability register (merged register file).
            CapRegContainer dtb_cap =
                CapRegContainer::almighty(params().dtb_addr);
            tc->setReg(cap_reg::CA1, &dtb_cap);
        }
    } else {
        inform("DTB file is not specified.\n");
    }
}

void
BootloaderKernelWorkload::addExitOnKernelPanicEvent()
{
    const std::string dmesg_output = name() + ".dmesg";
    if (params().exit_on_kernel_panic) {
        kernelPanicPcEvent = addFuncEvent<linux::PanicOrOopsEvent>(
            kernelSymbolTable, "panic", "Kernel panic in simulated system.",
            dmesg_output, params().on_panic
        );
    }
}

void
BootloaderKernelWorkload::addExitOnKernelOopsEvent()
{
    const std::string dmesg_output = name() + ".dmesg";
    if (params().exit_on_kernel_oops) {
        kernelOopsPcEvent = addFuncEvent<linux::PanicOrOopsEvent>(
            kernelSymbolTable, "oops_exit", "Kernel oops in simulated system.",
            dmesg_output, params().on_oops
        );
    }
}

void
BootloaderKernelWorkload::initState()
{
    loadBootloader();
    loadKernel();
    loadDtb();


    // Enter the kernel at its physical entry: locore derives the
    // page-table root from the PC before paging is on.
    constexpr Addr KERNEL_VA_BASE = 0xffffffc000000000ULL;
    constexpr Addr KERNEL_PA_BASE = 0x80200000ULL;
    if (entryPoint >= KERNEL_VA_BASE) {
        Addr phys_entry = entryPoint - KERNEL_VA_BASE + KERNEL_PA_BASE;
        inform("Entering kernel physically: VA %#x -> PA %#x\n",
               entryPoint, phys_entry);
        entryPoint = phys_entry;
    }

    // A capability-mode ELF (the purecap kernel) is entered with PCC in
    // capability mode, as OpenSBI/QEMU do.
    const bool cap_mode_entry = kernelIsCapMode();
    inform("Entering kernel in %s mode\n",
           cap_mode_entry ? "capability" : "integer");

    for (auto *tc: system->threads) {
        CHERIRiscvISA::Reset().invoke(tc);
        if (cap_mode_entry) {
            std::unique_ptr<PCStateBase> pc(tc->pcState().clone());
            auto &cpc = pc->as<CHERIRiscvISA::PCState>();
            cpc.pcc(CHERIRiscvISA::capSetFlags(cpc.pcc(), 1));
            tc->pcState(*pc);
        }
        tc->activate();
    }
}

bool
BootloaderKernelWorkload::kernelIsCapMode() const
{
    // ELF64 header: EI_CLASS (byte 4) == ELFCLASS64, e_flags at offset 48.
    constexpr uint32_t EF_RISCV_CAP_MODE = 0x00020000;
    if (params().object_file == "")
        return false;
    std::ifstream f(params().object_file, std::ios::binary);
    uint8_t hdr[52] = {};
    if (!f.read(reinterpret_cast<char *>(hdr), sizeof(hdr)) ||
            hdr[0] != 0x7f || hdr[1] != 'E' || hdr[4] != 2) {
        return false;
    }
    uint32_t e_flags = hdr[48] | hdr[49] << 8 | hdr[50] << 16 |
                       (uint32_t)hdr[51] << 24;
    return e_flags & EF_RISCV_CAP_MODE;
}

void
BootloaderKernelWorkload::startup()
{
    Workload::startup();

    addExitOnKernelPanicEvent();
    addExitOnKernelOopsEvent();
}

void
BootloaderKernelWorkload::serialize(CheckpointOut &checkpoint) const
{
    bootloaderSymbolTable.serialize("bootloader_symbol_table", checkpoint);
    kernelSymbolTable.serialize("kernel_symbol_table", checkpoint);
}

void
BootloaderKernelWorkload::unserialize(CheckpointIn &checkpoint)
{
    bootloaderSymbolTable.unserialize("bootloader_symbol_table", checkpoint);
    kernelSymbolTable.unserialize("kernel_symbol_table", checkpoint);
}

} // namespace CHERIRiscvISA
} // namespace gem5
