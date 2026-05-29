#!/usr/bin/env python3
"""
cheri_asm.py — CHERI-RISC-V assembler.

Reads:
  - cheri_isa.json      (instruction encodings, register maps)
  - startup.json        (optional: capability register state)
  - <program>.s         (user assembly, pure capability mode)

Produces:
  - <out>.bin           (flat binary)
  - <out>.lst           (listing: PC + hex + source)
  - <out>.elf           (single-segment R+X ELF)

Usage:
  python3 cheri_asm.py prog.s
  python3 cheri_asm.py prog.s --startup startup.json --base 0x80000000 --out build/prog

The startup prologue (if given) is emitted first, then the user assembly
follows immediately. They share the same address space; PC begins at --base.

Pipeline:
  1. Load ISA JSON (encodings + register maps)
  2. If --startup given, generate prologue assembly lines from it
  3. Read user assembly file
  4. Concatenate: prologue + user assembly
  5. Parse → list of (mnemonic, operands, lineno)
  6. Encode each → 32-bit word
  7. Write .bin (raw little-endian words), .lst (commented listing),
     .elf (wrapping the .bin)
"""

import argparse
import struct
import sys
from pathlib import Path

from isa import ISA
from encode import encode_instruction
from parser import parse_source
from startup import generate_startup
from elf_wrap import wrap_elf


# Default code base address. Overridable via --base.
DEFAULT_BASE = 0x80000000


def assemble(source_lines, isa, base_addr):
    """
    Encode a list of source lines.

    Returns: (bin_bytes, listing_lines)
      bin_bytes:     concatenated little-endian 32-bit words
      listing_lines: ['  80000000:  04200293    addi    x5, x0, 0x42', ...]
    """
    parsed = parse_source("\n".join(source_lines))

    blob = bytearray()
    listing = []
    pc = base_addr

    for mnemonic, operands, lineno in parsed:
        try:
            word = encode_instruction(mnemonic, operands, isa)
        except Exception as e:
            raise ValueError(f"Line {lineno}: {e}") from e

        blob.extend(struct.pack("<I", word))
        operand_str = ", ".join(operands) if operands else ""
        listing.append(f"  {pc:08x}:  {word:08x}    {mnemonic:<10s} {operand_str}")
        pc += 4

    return bytes(blob), listing


def main():
    p = argparse.ArgumentParser(description="CHERI-RISC-V assembler")
    p.add_argument("source", help="Assembly source file (.s)")
    p.add_argument("--isa", default=None,
                   help="ISA JSON file (default: cheri_isa.json next to this script)")
    p.add_argument("--startup", default=None,
                   help="Startup JSON file (capability register init)")
    p.add_argument("--base", default=hex(DEFAULT_BASE),
                   help=f"Code base address in hex (default {hex(DEFAULT_BASE)})")
    p.add_argument("--out", default=None,
                   help="Output file stem (default: <source-stem>). "
                        "Produces <stem>.bin, <stem>.lst, <stem>.elf")
    args = p.parse_args()

    # ── Resolve paths ──
    script_dir = Path(__file__).parent
    isa_path = Path(args.isa) if args.isa else script_dir / "cheri_isa.json"
    src_path = Path(args.source)

    if not isa_path.exists():
        print(f"error: ISA file not found: {isa_path}", file=sys.stderr)
        sys.exit(1)
    if not src_path.exists():
        print(f"error: source file not found: {src_path}", file=sys.stderr)
        sys.exit(1)

    out_stem = Path(args.out) if args.out else src_path.with_suffix("")
    out_stem.parent.mkdir(parents=True, exist_ok=True)

    base_addr = int(args.base, 0)

    # ── Load ISA ──
    isa = ISA(str(isa_path))

    # ── Build source: startup prologue + user assembly ──
    all_lines = []

    if args.startup:
        startup_path = Path(args.startup)
        if not startup_path.exists():
            print(f"error: startup file not found: {startup_path}", file=sys.stderr)
            sys.exit(1)
        all_lines.extend(generate_startup(str(startup_path)))

    all_lines.append("# ══════════════════════════════════════════════════════════════")
    all_lines.append("# User assembly program")
    all_lines.append("# ══════════════════════════════════════════════════════════════")
    all_lines.append("")
    all_lines.extend(src_path.read_text().splitlines())

    # ── Assemble ──
    try:
        blob, listing = assemble(all_lines, isa, base_addr)
    except ValueError as e:
        print(f"assembly error: {e}", file=sys.stderr)
        sys.exit(2)

    # ── Write outputs ──
    bin_path = out_stem.with_suffix(".bin")
    lst_path = out_stem.with_suffix(".lst")
    elf_path = out_stem.with_suffix(".elf")

    bin_path.write_bytes(blob)

    # Build listing file with section separator markers
    lst_text = []
    lst_text.append(f"# Assembled from: {src_path.name}")
    if args.startup:
        lst_text.append(f"# Startup config: {args.startup}")
    lst_text.append(f"# Base address:   {hex(base_addr)}")
    lst_text.append(f"# Total size:     {len(blob)} bytes "
                    f"({len(blob) // 4} instructions)")
    lst_text.append("")
    lst_text.extend(listing)
    lst_path.write_text("\n".join(lst_text) + "\n")

    elf_blob = wrap_elf(blob, base_addr)
    elf_path.write_bytes(elf_blob)

    # ── Report ──
    print(f"✓ {bin_path} ({len(blob)} bytes)")
    print(f"✓ {lst_path}")
    print(f"✓ {elf_path}")


if __name__ == "__main__":
    main()
