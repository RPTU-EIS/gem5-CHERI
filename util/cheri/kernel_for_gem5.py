#!/usr/bin/env python3
"""Prepare a CheriBSD kernel ELF for gem5 full-system boot.

FreeBSD links its kernel with a dummy program interpreter (PT_INTERP
"/red/herring"). gem5's ELF loader tries to open the interpreter of any ELF
it loads, so booting such a kernel fails with
  image_file_data.cc: fatal: Failed to open file /red/herring.
This copies the kernel and turns its PT_INTERP program header into PT_NULL;
nothing else changes (sections, symbols and debug info stay, so the copy
still symbolises profiles).

Usage: util/cheri/kernel_for_gem5.py KERNEL_ELF OUT_ELF
"""

import shutil
import struct
import sys

PT_NULL, PT_INTERP = 0, 3


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1:]
    shutil.copyfile(src, dst)
    with open(dst, "r+b") as f:
        ident = f.read(16)
        if ident[:4] != b"\x7fELF" or ident[4] != 2 or ident[5] != 1:
            sys.exit(f"{src}: not a little-endian ELF64 file")
        f.seek(0x20)
        (phoff,) = struct.unpack("<Q", f.read(8))
        f.seek(0x36)
        phentsize, phnum = struct.unpack("<HH", f.read(4))
        changed = 0
        for i in range(phnum):
            off = phoff + i * phentsize
            f.seek(off)
            (ptype,) = struct.unpack("<I", f.read(4))
            if ptype == PT_INTERP:
                f.seek(off)
                f.write(struct.pack("<I", PT_NULL))
                changed += 1
    print(f"wrote {dst} ({changed} PT_INTERP header(s) -> PT_NULL)")


if __name__ == "__main__":
    main()
