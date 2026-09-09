"""
elf_wrap.py — wrap a flat binary in a minimal RV64 ELF.

Layout matches the reference script the user provided:
  - ELF header at offset 0x000   (64 bytes)
  - Program header at offset 0x040 (56 bytes)
  - Zero padding up to offset 0x1000
  - Payload at offset 0x1000
  - Single PT_LOAD segment, flags R+X, vaddr = paddr = entry
"""

import struct


PAGE = 0x1000
EHDR_SIZE = 64
PHDR_SIZE = 56
PT_LOAD, PF_R, PF_X = 1, 4, 1


def wrap_elf(code_bytes, entry_addr):
    """
    Return an ELF blob containing `code_bytes` as a single PT_LOAD segment
    with R+X permissions, loaded at `entry_addr`.
    """
    # 16-byte e_ident: 0x7fELF, class=2 (64-bit), data=1 (little endian),
    # version=1, then 9 padding bytes.
    e_ident = b"\x7fELF" + bytes([2, 1, 1]) + bytes(9)

    ehdr = struct.pack(
        "<16sHHIQQQIHHHHHH",
        e_ident,            # e_ident
        2,                  # e_type = ET_EXEC
        243,                # e_machine = EM_RISCV
        1,                  # e_version
        entry_addr,         # e_entry
        EHDR_SIZE,          # e_phoff
        0,                  # e_shoff (no section headers)
        0,                  # e_flags
        EHDR_SIZE,          # e_ehsize
        PHDR_SIZE,          # e_phentsize
        1,                  # e_phnum
        0, 0, 0             # e_shentsize, e_shnum, e_shstrndx (none)
    )

    phdr = struct.pack(
        "<IIQQQQQQ",
        PT_LOAD,            # p_type
        PF_R | PF_X,        # p_flags
        PAGE,               # p_offset
        entry_addr,         # p_vaddr
        entry_addr,         # p_paddr
        len(code_bytes),    # p_filesz
        len(code_bytes),    # p_memsz
        PAGE                # p_align
    )

    pad = PAGE - (len(ehdr) + len(phdr))
    if pad < 0:
        raise RuntimeError("ELF headers exceed page size")

    return ehdr + phdr + (b"\x00" * pad) + code_bytes
