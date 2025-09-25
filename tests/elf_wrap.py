#!/usr/bin/env python3
import sys, struct, os

if len(sys.argv) != 4:
    print("Usage: elf_wrap.py <in.bin> <out.elf> <entry-addr-hex>")
    sys.exit(2)

in_bin, out_elf, entry = sys.argv[1], sys.argv[2], int(sys.argv[3], 16)
code = open(in_bin, "rb").read()

PAGE = 0x1000
EHDR_SIZE = 64
PHDR_SIZE = 56
PT_LOAD, PF_R, PF_X = 1, 4, 1

# e_ident: 64-bit, little-endian, version=1
e_ident = b"\x7fELF" + bytes([2, 1, 1]) + bytes(9)
ehdr = struct.pack(
    "<16sHHIQQQIHHHHHH",
    e_ident,             # e_ident
    2,                   # e_type = ET_EXEC
    243,                 # e_machine = EM_RISCV
    1,                   # e_version
    entry,               # e_entry
    EHDR_SIZE,           # e_phoff
    0,                   # e_shoff
    0,                   # e_flags
    EHDR_SIZE,           # e_ehsize
    PHDR_SIZE,           # e_phentsize
    1,                   # e_phnum
    0, 0, 0              # section header fields (none)
)

phdr = struct.pack(
    "<IIQQQQQQ",
    PT_LOAD,             # p_type
    PF_R | PF_X,         # p_flags
    PAGE,                # p_offset
    entry,               # p_vaddr
    entry,               # p_paddr
    len(code),           # p_filesz
    len(code),           # p_memsz
    PAGE                 # p_align
)

with open(out_elf, "wb") as f:
    f.write(ehdr)
    f.write(phdr)
    f.write(b"\x00" * (PAGE - f.tell()))
    f.write(code)

print(f"Wrote {out_elf} (entry=0x{entry:x}, {len(code)} bytes payload)")
