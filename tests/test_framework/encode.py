"""
encode.py — Encode one instruction by looking it up in the ISA and dispatching
to the appropriate format encoder.

The flow:
  1. Look up the instruction's JSON entry (format + fixed fields + operands).
  2. Parse the user-supplied operand tokens, resolving registers and immediates.
  3. Place each operand value into the right field (rd / rs1 / rs2 / imm).
  4. Layer the fixed-field values on top (in case operands didn't cover them).
  5. Call the appropriate format encoder.
"""

from encoders import encode_r, encode_i, encode_s, encode_u, encode_b, encode_j


def parse_immediate(token):
    """Parse a numeric literal in dec/hex/binary. Accepts negative values."""
    token = token.strip()
    if token.startswith("-0x") or token.startswith("-0X"):
        return -int(token[3:], 16)
    if token.startswith("0x") or token.startswith("0X"):
        return int(token, 16)
    if token.startswith("0b") or token.startswith("0B"):
        return int(token, 2)
    return int(token, 10)


def _hex_field(fields, key, default=0):
    """Pull a field value from the JSON 'fields' dict. Strings are parsed as hex/dec."""
    if key not in fields:
        return default
    v = fields[key]
    if isinstance(v, int):
        return v
    return int(v, 0)


def encode_instruction(mnemonic, operand_tokens, isa):
    """
    Encode one instruction. Returns a 32-bit integer.

    operand_tokens: list of strings as written in assembly, e.g. ['x5', 'x0', '0x42']
    """
    inst = isa.get_instruction(mnemonic)
    fmt    = inst["format"]
    fields = inst.get("fields", {})
    spec   = inst.get("operands", [])

    if len(operand_tokens) != len(spec):
        raise ValueError(
            f"{mnemonic}: expected {len(spec)} operands ({', '.join(o['name'] for o in spec)}), "
            f"got {len(operand_tokens)}"
        )

    # ── Resolve each operand into a field value ──
    field_values = {
        "rd":     _hex_field(fields, "rd",     0),
        "rs1":    _hex_field(fields, "rs1",    0),
        "rs2":    _hex_field(fields, "rs2",    0),
        "imm12":  _hex_field(fields, "imm12",  0),
        "imm20":  _hex_field(fields, "imm20",  0),
    }

    for op_def, token in zip(spec, operand_tokens):
        target_field = op_def["field"]
        op_type = op_def["type"]

        if op_type in ("capability", "integer", "scr"):
            field_values[target_field] = isa.resolve_register(token, op_type)
        elif op_type == "immediate":
            field_values[target_field] = parse_immediate(token)
        else:
            raise ValueError(f"Unknown operand type: {op_type}")

    # ── Common encoding fields ──
    opcode = _hex_field(fields, "opcode")
    funct3 = _hex_field(fields, "funct3", 0)
    funct7 = _hex_field(fields, "funct7", 0)

    # ── Dispatch by format ──
    # NOTE: CHERI_R is identical bit layout to R-type, just a logical label
    if fmt == "R" or fmt == "CHERI_R":
        return encode_r(
            opcode, funct3, funct7,
            field_values["rd"], field_values["rs1"], field_values["rs2"]
        )
    elif fmt == "I":
        return encode_i(
            opcode, funct3,
            field_values["rd"], field_values["rs1"], field_values["imm12"]
        )
    elif fmt == "S":
        return encode_s(
            opcode, funct3,
            field_values["rs1"], field_values["rs2"], field_values["imm12"]
        )
    elif fmt == "U":
        return encode_u(opcode, field_values["rd"], field_values["imm20"])
    elif fmt == "B":
        return encode_b(
            opcode, funct3,
            field_values["rs1"], field_values["rs2"], field_values["imm12"]
        )
    elif fmt == "J":
        return encode_j(opcode, field_values["rd"], field_values["imm20"])
    else:
        raise ValueError(f"Unsupported instruction format: {fmt}")
