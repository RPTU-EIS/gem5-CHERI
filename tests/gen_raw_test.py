#!/usr/bin/env python3
# Generate a flat RV64 binary that runs every CHERI capability-inspection
# instruction on one capability register (default CNull), stores the
# results at RESULT_BASE and hits EBREAK (cheri_inspect.bin and .lst).
from dataclasses import dataclass
from typing import List, Tuple
import argparse
import struct
import sys

# ---------------- Encoding helpers ----------------

def mask(x, bits):
    m = (1 << bits) - 1
    return x & m

def sign12(i):
    # return 12-bit two's complement
    return mask(i, 12)

def i_type(opcode, funct3, rd, rs1, imm12):
    imm12 = sign12(imm12)
    return ((imm12 & 0xfff) << 20) | ((rs1 & 0x1f) << 15) | ((funct3 & 0x7) << 12) | ((rd & 0x1f) << 7) | (opcode & 0x7f)

def s_type(opcode, funct3, rs1, rs2, imm12):
    imm12 = sign12(imm12)
    imm11_5 = (imm12 >> 5) & 0x7f
    imm4_0  = imm12 & 0x1f
    return ((imm11_5 & 0x7f) << 25) | ((rs2 & 0x1f) << 20) | ((rs1 & 0x1f) << 15) | ((funct3 & 0x7) << 12) | ((imm4_0 & 0x1f) << 7) | (opcode & 0x7f)

def u_type(opcode, rd, imm20):
    return ((imm20 & 0xfffff) << 12) | ((rd & 0x1f) << 7) | (opcode & 0x7f)

def r_type(opcode, funct3, funct7, rd, rs1, rs2):
    return ((funct7 & 0x7f) << 25) | ((rs2 & 0x1f) << 20) | ((rs1 & 0x1f) << 15) | ((funct3 & 0x7) << 12) | ((rd & 0x1f) << 7) | (opcode & 0x7f)

# CHERI inspect encoding:
# funct7 = 0x7f, funct3 = 0, major opcode = 0x5b, subop in [24:20]
def cheri_inspect(rd, cs1, subop):
    funct7 = 0x7f
    funct3 = 0x0
    opcode = 0x5b
    # Assemble like an R-type with rs2=subop packed into [24:20]
    word = ((funct7 & 0x7f) << 25) | ((subop & 0x1f) << 20) \
           | ((cs1 & 0x1f) << 15) | ((funct3 & 0x7) << 12) \
           | ((rd & 0x1f) << 7) | (opcode & 0x7f)
    return word

# ---------------- Program builder ----------------

# Integer opcodes
OP_LUI  = 0x37
OP_ADDI = 0x13
OP_SD   = 0x23  # funct3=0x3 for SD (RV64)
FUNCT3_ADDI = 0x0
FUNCT3_SD   = 0x3

# A couple of handy registers (RV64)
X_ZERO = 0
X_RA   = 1
X_SP   = 2
X_A0   = 10
X_T0   = 5

# Test result buffer start (in DRAM range)
RESULT_BASE = 0x80010000

@dataclass
class InspectOp:
    name: str
    subop: int

# CHERI inspect subop mapping (per spec B.1.1 / B.4 summary)
INSPECT_OPS: List[InspectOp] = [
    InspectOp("CGetPerm",   0x00),
    InspectOp("CGetType",   0x01),
    InspectOp("CGetBase",   0x02),
    InspectOp("CGetLen",    0x03),
    InspectOp("CGetTag",    0x04),
    InspectOp("CGetSealed", 0x05),
    InspectOp("CGetOffset", 0x06),
    InspectOp("CGetFlags",  0x07),
    InspectOp("CGetHigh",   0x17),
    InspectOp("CGetTop",    0x18),
]

def split_lui_addi_imm(addr: int) -> Tuple[int, int]:
    # Standard LUI+ADDI materialization (handles negative low 12 properly)
    hi = (addr + 0x800) >> 12
    lo = (addr - (hi << 12))
    if lo >= 2048:
        lo -= 4096
    return hi, lo

def assemble(cs1_cap: int, rd_int: int, store_width: int = 8) -> Tuple[bytes, List[str]]:
    words = []
    listing = []

    pc = 0x80000000  # typical DRAM start for RISC-V in gem5 baremetal

    def emit(w, comment=""):
        nonlocal pc
        words.append(w)
        listing.append(f"{pc:016x}: {w:08x}  {comment}")
        pc += 4

    # a0 = RESULT_BASE
    hi, lo = split_lui_addi_imm(RESULT_BASE)
    emit(u_type(OP_LUI, X_A0, hi),           f"lui   a0, 0x{hi:x}   # RESULT_BASE hi")
    emit(i_type(OP_ADDI, FUNCT3_ADDI, X_A0, X_A0, lo), f"addi  a0, a0, {lo}   # RESULT_BASE lo")

    # For each inspect op: rd <- Inspect(cs1); sd rd, 0(a0); addi a0, a0, +8
    for idx, op in enumerate(INSPECT_OPS):
        emit(cheri_inspect(rd_int, cs1_cap, op.subop),
             f"{op.name} x{rd_int}, c{cs1_cap}")
        # store result
        emit(s_type(OP_SD, FUNCT3_SD, X_A0, rd_int, 0),
             f"sd    x{rd_int}, 0(a0)   # store {op.name} result")
        emit(i_type(OP_ADDI, FUNCT3_ADDI, X_A0, X_A0, store_width),
             f"addi  a0, a0, {store_width}")

    # ebreak to stop (0x00100073)
    emit(0x00100073, "ebreak")

    # Pack little-endian
    blob = b"".join(struct.pack("<I", w) for w in words)
    return blob, listing

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cs1", type=int, default=0,
                   help="capability source register index (0..31). Default 0 = CNull")
    p.add_argument("--rd", type=int, default=X_T0,
                   help="integer destination register for all ops (default x5 = t0)")
    p.add_argument("--out", default="cheri_inspect.bin",
                   help="output flat binary filename")
    p.add_argument("--lst", default="cheri_inspect.lst",
                   help="output listing filename")
    args = p.parse_args()

    if not (0 <= args.cs1 <= 31) or not (0 <= args.rd <= 31):
        print("cs1 and rd must be in 0..31", file=sys.stderr)
        sys.exit(2)

    blob, listing = assemble(args.cs1, args.rd)

    with open(args.out, "wb") as f:
        f.write(blob)
    with open(args.lst, "w") as f:
        for line in listing:
            f.write(line + "\n")

    print(f"Wrote {args.out} ({len(blob)} bytes) and {args.lst}")
    print("Results layout (8 bytes each) at 0x%08x in this order:" % RESULT_BASE)
    for i, op in enumerate(INSPECT_OPS):
        print("  +%03d: %s" % (i*8, op.name))

if __name__ == "__main__":
    main()
