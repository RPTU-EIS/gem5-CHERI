"""
encoders.py — instruction word encoders for each RISC-V format.

Each function takes the field values and returns a 32-bit instruction word.
All bit layouts follow the RISC-V Unprivileged ISA spec.
"""


def _mask(value, bits):
    """Truncate `value` to `bits` bits (handles negative values via two's complement)."""
    return value & ((1 << bits) - 1)


def encode_r(opcode, funct3, funct7, rd, rs1, rs2):
    """R-type:  funct7[31:25] rs2[24:20] rs1[19:15] funct3[14:12] rd[11:7] opcode[6:0]"""
    return (
        (_mask(funct7, 7)  << 25) |
        (_mask(rs2,    5) << 20) |
        (_mask(rs1,    5) << 15) |
        (_mask(funct3, 3) << 12) |
        (_mask(rd,     5) <<  7) |
         _mask(opcode, 7)
    )


def encode_i(opcode, funct3, rd, rs1, imm12):
    """I-type:  imm12[31:20] rs1[19:15] funct3[14:12] rd[11:7] opcode[6:0]"""
    return (
        (_mask(imm12, 12) << 20) |
        (_mask(rs1,    5) << 15) |
        (_mask(funct3, 3) << 12) |
        (_mask(rd,     5) <<  7) |
         _mask(opcode,  7)
    )


def encode_s(opcode, funct3, rs1, rs2, imm12):
    """S-type:  imm[11:5]→[31:25] rs2[24:20] rs1[19:15] funct3[14:12] imm[4:0]→[11:7] opcode[6:0]"""
    imm = _mask(imm12, 12)
    imm_hi = (imm >> 5) & 0x7f   # bits [11:5]
    imm_lo =  imm       & 0x1f   # bits [4:0]
    return (
        (imm_hi          << 25) |
        (_mask(rs2,   5) << 20) |
        (_mask(rs1,   5) << 15) |
        (_mask(funct3,3) << 12) |
        (imm_lo          <<  7) |
         _mask(opcode, 7)
    )


def encode_u(opcode, rd, imm20):
    """U-type:  imm20[31:12] rd[11:7] opcode[6:0]"""
    return (
        (_mask(imm20, 20) << 12) |
        (_mask(rd,     5) <<  7) |
         _mask(opcode,  7)
    )


def encode_b(opcode, funct3, rs1, rs2, imm):
    """
    B-type (branches): imm bits are scattered:
      imm[12] → bit 31
      imm[10:5] → bits [30:25]
      imm[4:1]  → bits [11:8]
      imm[11]   → bit 7
    imm[0] is always 0 (branches are 2-byte aligned, but we use 4-byte).
    """
    imm = imm & 0x1fff  # 13-bit signed
    b12   = (imm >> 12) & 0x1
    b10_5 = (imm >>  5) & 0x3f
    b4_1  = (imm >>  1) & 0xf
    b11   = (imm >> 11) & 0x1
    return (
        (b12 << 31) | (b10_5 << 25) |
        (_mask(rs2, 5) << 20) | (_mask(rs1, 5) << 15) |
        (_mask(funct3, 3) << 12) |
        (b4_1 << 8) | (b11 << 7) |
        _mask(opcode, 7)
    )


def encode_j(opcode, rd, imm):
    """
    J-type (JAL): imm bits scattered as:
      imm[20]    → bit 31
      imm[10:1]  → bits [30:21]
      imm[11]    → bit 20
      imm[19:12] → bits [19:12]
    """
    imm = imm & 0x1fffff   # 21-bit signed
    b20    = (imm >> 20) & 0x1
    b10_1  = (imm >>  1) & 0x3ff
    b11    = (imm >> 11) & 0x1
    b19_12 = (imm >> 12) & 0xff
    return (
        (b20 << 31) | (b10_1 << 21) | (b11 << 20) | (b19_12 << 12) |
        (_mask(rd, 5) << 7) |
        _mask(opcode, 7)
    )
