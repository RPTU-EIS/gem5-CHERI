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

#include "arch/riscv_cheri/faults.hh"
#include "arch/riscv_cheri/regs/cap.hh"
#include "base/loader/dtb_file.hh"
#include "base/loader/object_file.hh"
#include "base/loader/symtab.hh"
#include "cpu/pc_event.hh"
#include "kern/linux/events.hh"
#include "sim/kernel_workload.hh"
#include "sim/sim_exit.hh"
#include "sim/system.hh"

namespace gem5
{

namespace CHERIRiscvISA
{

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
            // Seed the *capability* a1 with the DTB physical (RISC-V boot
            // convention a1=dtb). The merged register file means the decoder
            // reads a1 from the CAP register class, so setReg(int_reg::A1,...)
            // wrote dead storage; write cap_reg::CA1 so locore's DTB-mapping
            // block (which reads ca1) actually sees the pointer.
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

        // ── EXPERIMENT (bring-up): keep the DTB pointer alive in a1. ──
        // CheriBSD locore maps the DTB into its devmap region only if a1 (the
        // DTB physical pointer) is non-zero at VA 0xf4 (`c.beqz a1`). But the
        // kernel clears a1 at VA 0x48 (`c.li a1,0` = 0x4581), so with no real
        // loader/firmware to re-provide it that mapping is skipped, and the
        // later DTB read faults into an unrecoverable trap. We seed a1 with the
        // DTB physical (see loadDtb, survives Reset) and neutralise the clear
        // by patching 0x80200048: c.li a1,0 (0x4581) -> c.nop (0x0001), so
        // locore maps the DTB itself. Remove this block to restore stock
        // kernel behaviour.
        {
            const Addr a1_clear_paddr = 0x80200048ULL;
            uint16_t before = 0;
            system->physProxy.readBlob(a1_clear_paddr,
                                       (uint8_t *)&before, sizeof(before));
            if (before == 0x4581) {
                uint16_t cnop = 0x0001;  // c.nop
                system->physProxy.writeBlob(a1_clear_paddr,
                                        (const uint8_t *)&cnop, sizeof(cnop));
                inform("Patched c.li a1,0 @%#x -> c.nop (preserve DTB ptr in "
                       "a1)\n", a1_clear_paddr);
            } else {
                warn("Expected c.li a1,0 (0x4581) @%#x but found %#x; DTB "
                     "a1-preserve patch NOT applied\n", a1_clear_paddr, before);
            }
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

        // For bring-up, use almighty bounds rather than exact bounds.
        // This is incorrect security-wise but lets the kernel proceed.
        CapRegContainer cap = CapRegContainer::almighty(cap_address);

        // TODO: Set proper bounds [obj_base, obj_base + obj_size)
        // TODO: Set proper permissions from perm_bits
        // TODO: If is_function, mark sentry-sealed

        // Translate target VA -> PA and write the cap
        Addr cap_loc_paddr = va_to_pa(cap_loc);

        // Write 16 bytes (CC128 layout)
        uint64_t cap_addr_bits = cap.getAddress();
        uint64_t cap_meta_bits = cap.getMetadata();   // or however your API exposes it
        system->physProxy.writeBlob(cap_loc_paddr + 0, &cap_addr_bits, 8);
        system->physProxy.writeBlob(cap_loc_paddr + 8, &cap_meta_bits, 8);

        // ── CHERI: mark the stored capability as tagged (valid) ──
        // cap_relocs produce *valid* capabilities. Without setting the tag
        // bit here, clc loads these pointers back untagged (tag=0), and
        // cjalr/cjr refuse to jump to an untagged capability — which hangs
        // the boot in the early init-array call sequence.
        system->cheritagtable.setTag(cap_loc_paddr, true);

        //inform("cap_reloc[%lu]: VA %#lx -> cap{base=%#lx size=%#lx perms=%#lx} stored at PA %#lx\n",
        //    i, cap_loc, obj_base, obj_size, perms, cap_loc_paddr);
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
            // Seed the *capability* a1 with the DTB physical (RISC-V boot
            // convention a1=dtb). The merged register file means the decoder
            // reads a1 from the CAP register class, so setReg(int_reg::A1,...)
            // wrote dead storage; write cap_reg::CA1 so locore's DTB-mapping
            // block (which reads ca1) actually sees the pointer.
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

    // ── Enter the kernel PHYSICALLY (not at its virtual link address). ──
    // CheriBSD's early locore runs *before* it enables paging and derives the
    // page-table root for `satp` from the current PC via PC-relative (auipcc)
    // addressing. That only yields a valid *physical* root if the PC is
    // physical. Entering at the virtual entry (0xffffffc0...) made the kernel
    // program `satp` with a virtual (and 44-bit-truncated -> bogus) page-table
    // root, so the first page-walk read garbage and the PC went to 0. Convert
    // the virtual entry to its physical load address; locore then runs
    // physically and switches to virtual itself once it enables paging.
    // (Initial PCC/DDC are almighty, so a physical PC is in-bounds.)
    // To revert to the old virtual-entry behaviour, delete this block.
    constexpr Addr KERNEL_VA_BASE = 0xffffffc000000000ULL;
    constexpr Addr KERNEL_PA_BASE = 0x80200000ULL;
    if (entryPoint >= KERNEL_VA_BASE) {
        Addr phys_entry = entryPoint - KERNEL_VA_BASE + KERNEL_PA_BASE;
        inform("Entering kernel physically: VA %#x -> PA %#x\n",
               entryPoint, phys_entry);
        entryPoint = phys_entry;
    }

    for (auto *tc: system->threads) {
        CHERIRiscvISA::Reset().invoke(tc);
        tc->activate();
    }
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
