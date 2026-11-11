/*
 * Minimal RISC-V SBI emulation for CHERI-RISCV. See sbi.hh.
 */
#include "arch/riscv_cheri/sbi.hh"

#include <fcntl.h>
#include <unistd.h>

#include <cstdint>
#include <iostream>

#include "arch/generic/cap_reg.hh"
#include "arch/riscv_cheri/faults.hh"
#include "arch/riscv_cheri/isa.hh"
#include "arch/riscv_cheri/regs/cap.hh"
#include "cpu/base.hh"
#include "cpu/thread_context.hh"
#include "mem/port_proxy.hh"
#include "sim/sim_exit.hh"
#include "sim/system.hh"

namespace gem5
{
namespace CHERIRiscvISA
{

namespace
{

// a0..a7 are integer registers x10..x17. With the merged register file, the
// integer value is the address field of the corresponding capability register.
enum { A0 = 10, A1 = 11, A2 = 12, A3 = 13,
       A4 = 14, A5 = 15, A6 = 16, A7 = 17 };

uint64_t
rdReg(ThreadContext *tc, int idx)
{
    CapRegContainer c;
    tc->getReg(capRegClass[idx], &c);
    return c.getAddress();
}

// Write an integer result: a null-derived (untagged) capability holding val.
void
wrReg(ThreadContext *tc, int idx, uint64_t val)
{
    CapRegContainer c;
    c.setAddress(val);
    c.setTag(false);
    tc->setReg(capRegClass[idx], &c);
}

void
putConsole(char ch)
{
    // Flush each character, so prompts without a newline appear at once
    std::cout << ch;
    std::cout.flush();
}

// Read one byte from gem5's stdin without blocking (-1 if none), which
// makes the SBI console interactive.
int
getConsole()
{
    static bool inited = false;
    if (!inited) {
        int fl = ::fcntl(STDIN_FILENO, F_GETFL);
        if (fl != -1)
            ::fcntl(STDIN_FILENO, F_SETFL, fl | O_NONBLOCK);
        inited = true;
    }
    unsigned char ch;
    ssize_t n = ::read(STDIN_FILENO, &ch, 1);
    if (n == 1) {
        return (int)ch;
    }
    return -1;
}

// sbi_set_timer(stime_value): arm the S-mode timer (see ISA::sbiTimecmp; the
// CLINT raises STIP when mtime reaches it) and clear any pending STIP.
void
setTimer(ThreadContext *tc, uint64_t stime_value)
{
    auto *isa = static_cast<ISA *>(tc->getIsaPtr());
    isa->sbiTimecmp = stime_value;
    tc->getCpuPtr()->clearInterrupt(tc->threadId(),
                                    ExceptionCode::INT_TIMER_SUPER, 0);
}

// SBI error codes
constexpr int64_t SBI_SUCCESS = 0;
constexpr int64_t SBI_ERR_NOT_SUPPORTED = -2;

// Legacy (v0.1) extension IDs
constexpr uint64_t EXT_SET_TIMER          = 0x00;
constexpr uint64_t EXT_CONSOLE_PUTCHAR    = 0x01;
constexpr uint64_t EXT_CONSOLE_GETCHAR    = 0x02;
constexpr uint64_t EXT_CLEAR_IPI          = 0x03;
constexpr uint64_t EXT_SEND_IPI           = 0x04;
constexpr uint64_t EXT_REMOTE_FENCE_I     = 0x05;
constexpr uint64_t EXT_REMOTE_SFENCE_VMA  = 0x06;
constexpr uint64_t EXT_REMOTE_SFENCE_ASID = 0x07;
constexpr uint64_t EXT_SHUTDOWN           = 0x08;

// v0.2+ extension IDs
constexpr uint64_t EXT_BASE   = 0x10;
constexpr uint64_t EXT_TIME   = 0x54494D45; // "TIME"
constexpr uint64_t EXT_IPI    = 0x00735049; // "sPI"
constexpr uint64_t EXT_RFENCE = 0x52464E43; // "RFNC"
constexpr uint64_t EXT_HSM    = 0x0048534D; // "HSM"
constexpr uint64_t EXT_SRST   = 0x53525354; // "SRST"
constexpr uint64_t EXT_DBCN   = 0x4442434E; // "DBCN"

bool
extSupported(uint64_t ext)
{
    switch (ext) {
      case EXT_BASE: case EXT_TIME: case EXT_IPI: case EXT_RFENCE:
      case EXT_HSM: case EXT_SRST: case EXT_DBCN:
      case EXT_SET_TIMER: case EXT_CONSOLE_PUTCHAR: case EXT_CONSOLE_GETCHAR:
      case EXT_SEND_IPI: case EXT_REMOTE_FENCE_I: case EXT_REMOTE_SFENCE_VMA:
      case EXT_REMOTE_SFENCE_ASID: case EXT_SHUTDOWN:
        return true;
      default:
        return false;
    }
}

} // anonymous namespace

void
handleSbiEcall(ThreadContext *tc)
{
    const uint64_t eid = rdReg(tc, A7);
    const uint64_t fid = rdReg(tc, A6);
    const uint64_t a0  = rdReg(tc, A0);

    // ── Legacy (v0.1): single return value in a0 ──
    if (eid < EXT_BASE) {
        uint64_t ret = 0;
        switch (eid) {
          case EXT_CONSOLE_PUTCHAR:
            putConsole((char)a0);
            break;
          case EXT_CONSOLE_GETCHAR:
            // Return a byte from gem5's stdin, or -1 if none (SBI convention).
            ret = (uint64_t)(int64_t)getConsole();
            break;
          case EXT_SHUTDOWN:
            std::cout.flush();
            exitSimLoop("SBI shutdown (legacy)");
            break;
          case EXT_SET_TIMER:
            setTimer(tc, a0);
            break;
          case EXT_CLEAR_IPI:
          case EXT_SEND_IPI:
          case EXT_REMOTE_FENCE_I:
          case EXT_REMOTE_SFENCE_VMA:
          case EXT_REMOTE_SFENCE_ASID:
          default:
            // stub: succeed silently (single hart, timer handled elsewhere)
            break;
        }
        wrReg(tc, A0, ret);
        return;
    }

    // ── v0.2+: (error in a0, value in a1) ──
    int64_t err = SBI_SUCCESS;
    uint64_t val = 0;

    switch (eid) {
      case EXT_BASE:
        switch (fid) {
          case 0: val = 0x00000002; break; // get_spec_version -> v0.2
          case 1: val = 1;          break; // get_impl_id -> OpenSBI-like
          case 2: val = 0x00010000; break; // get_impl_version
          case 3: val = extSupported(a0) ? 1 : 0; break; // probe_extension
          case 4: case 5: case 6: val = 0; break; // mvendorid/marchid/mimpid
          default: err = SBI_ERR_NOT_SUPPORTED; break;
        }
        break;

      case EXT_DBCN:
        // Debug console: fid 0 writes a buffer, 1 reads, 2 writes a byte
        if (fid == 0) {
            const uint64_t num = a0;
            const uint64_t alo = rdReg(tc, A1);
            const uint64_t ahi = rdReg(tc, A2);
            // On RV64 base_addr_lo already holds the full physical address;
            // base_addr_hi is only meaningful when phys addrs exceed XLEN.
            const Addr paddr = ahi ? ((ahi << 32) | (alo & 0xffffffffULL)) : alo;
            PortProxy &proxy = tc->getSystemPtr()->physProxy;
            for (uint64_t i = 0; i < num; i++) {
                uint8_t ch = 0;
                proxy.readBlob(paddr + i, &ch, 1);
                putConsole((char)ch);
            }
            std::cout.flush();
            val = num;              // bytes written
        } else if (fid == 1) {
            // console_read(num_bytes=a0, base_lo=a1, base_hi=a2): read up to num
            // bytes from gem5's stdin into the guest buffer; return count read.
            const uint64_t num = a0;
            const uint64_t alo = rdReg(tc, A1);
            const uint64_t ahi = rdReg(tc, A2);
            const Addr paddr = ahi ? ((ahi << 32) | (alo & 0xffffffffULL)) : alo;
            PortProxy &proxy = tc->getSystemPtr()->physProxy;
            uint64_t got = 0;
            for (; got < num; got++) {
                int c = getConsole();
                if (c < 0)
                    break;
                uint8_t b = (uint8_t)c;
                proxy.writeBlob(paddr + got, &b, 1);
            }
            val = got;              // bytes read
        } else if (fid == 2) {
            putConsole((char)a0);
        } else {
            err = SBI_ERR_NOT_SUPPORTED;
        }
        break;

      case EXT_TIME:
        if (fid == 0)
            setTimer(tc, a0);
        else
            err = SBI_ERR_NOT_SUPPORTED;
        break;

      case EXT_IPI:    // send_ipi -- single hart
      case EXT_RFENCE: // remote fences -- single hart
        err = SBI_SUCCESS;
        break;

      case EXT_HSM:
        // hart_start/stop/get_status -- single hart already running
        err = SBI_SUCCESS;
        break;

      case EXT_SRST:
        std::cout.flush();
        exitSimLoop("SBI system reset");
        break;

      default:
        err = SBI_ERR_NOT_SUPPORTED;
        break;
    }

    wrReg(tc, A0, (uint64_t)err);
    wrReg(tc, A1, val);
}

} // namespace CHERIRiscvISA
} // namespace gem5
