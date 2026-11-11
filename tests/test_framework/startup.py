"""
startup.py: CHERI assembly prologue that sets up capability registers
(tag, address, metadata) from a startup JSON file.
"""

import json


# Scratch registers, clobbered by the prologue
SCRATCH_INT_1 = "t0"   # x5
SCRATCH_INT_2 = "t1"   # x6


def _parse_intish(value):
    """Accept either int or string ('0x...' or decimal)."""
    if isinstance(value, int):
        return value
    return int(value, 0)


def _emit_li(reg, value, lines):
    """
    Append instructions that load the 64-bit `value` into `reg`.
    """
    # Sign-extend the 32-bit slice for clean lui+addi
    low32 = value & 0xffffffff

    if low32 < 0x800 and (value >> 32) == 0:
        # Fits in addi
        lines.append(f"    addi    {reg}, x0, {hex(low32)}    # = {hex(value)}")
        return

    hi = (low32 + 0x800) >> 12
    lo = low32 - (hi << 12)
    if lo >= 2048:
        lo -= 4096

    lines.append(f"    lui     {reg}, {hex(hi & 0xfffff)}    # hi20 of {hex(value)}")

    # lui sign-extends: clear the upper 32 bits
    if (low32 & 0x80000000) != 0:
        lines.append(f"    slli    {reg}, {reg}, 32          # kill sign-extension")
        lines.append(f"    srli    {reg}, {reg}, 32          # zero-extend low 32")

    if (lo & 0xfff) != 0:
        lines.append(f"    addi    {reg}, {reg}, {hex(lo & 0xfff)}    # lo12 of {hex(value)}")

    if (value >> 32) != 0:
        lines.append(
            f"    # WARNING: value {hex(value)} > 32 bits; upper bits dropped."
        )


def generate_startup(startup_path):
    """
    Return the prologue lines for startup.json.
    """
    with open(startup_path) as f:
        spec = json.load(f)

    regs = spec.get("startup_registers", {})

    lines = [
        "# ══════════════════════════════════════════════════════════════",
        "# Startup prologue generated from startup.json",
        "# Materializes capability registers before user code runs.",
        "# ══════════════════════════════════════════════════════════════",
        "",
    ]

    for reg_name, state in regs.items():
        if reg_name.startswith("_"):
            continue

        tag      = state.get("tag", False)
        address  = _parse_intish(state.get("address", 0))
        metadata = _parse_intish(state.get("metadata", 0))

        lines.append(f"# ── Initialize {reg_name}: tag={tag} "
                     f"addr={hex(address)} meta={hex(metadata)} ──")

        if tag:
            # Start from the almighty DDC
            lines.append(f"    cspecialrw  {reg_name}, ddc, c0")
        else:
            # Untagged: also starts from DDC (no untag step yet)
            lines.append(f"    cspecialrw  {reg_name}, ddc, c0")
            lines.append(f"    # tag=false requested; manual untag step needed if needed")

        # Step 2: materialize address into a scratch integer register
        _emit_li(SCRATCH_INT_1, address, lines)

        # Step 3: set the cap's address
        lines.append(f"    csetaddr    {reg_name}, {reg_name}, {SCRATCH_INT_1}")

        # Set the metadata with csethigh, unless it is 0 (keep DDC's)
        if metadata != 0:
            _emit_li(SCRATCH_INT_1, metadata, lines)
            lines.append(f"    csethigh    {reg_name}, {reg_name}, {SCRATCH_INT_1}")

        lines.append("")

    lines.append("# ── End of startup prologue ──")
    lines.append("# ══════════════════════════════════════════════════════════════")
    lines.append("")

    return lines
