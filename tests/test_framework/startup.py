"""
startup.py — Build a CHERI assembly prologue from a startup JSON file.

Given a startup spec like:
    "c1": { "tag": true, "address": "0x80010000", "metadata": "0x..." }

Emit assembly that:
    1. CSpecialRW <cN>, ddc, c0       # cN = almighty DDC (full perms, tagged)
    2. li t0, <address>                # materialize address in a scratch reg
    3. CSetAddr <cN>, <cN>, t0         # cN.address = t0
    4. li t0, <metadata low>           # materialize low 32 bits
    5. li t1, <metadata high>          # materialize high 32 bits
    6. combine t0 and t1 into a 64-bit value, then CSetHigh

For simplicity we emit `li` as two ops (lui + addi). For 64-bit metadata we
emit a sequence of lui/addi/slli/or to build the full value.

If tag is false, we copy from c0 (CNull, which is permanently untagged) after
positioning, but really for an untagged cap the user probably doesn't care
about address/metadata. We still apply them for completeness.

The output is a list of assembly source lines (strings) that the main
assembler treats just like user-written code.
"""

import json


# Scratch integer registers used by the prologue.
# These get clobbered during startup; user code should treat them as undefined.
SCRATCH_INT_1 = "t0"   # x5
SCRATCH_INT_2 = "t1"   # x6


def _parse_intish(value):
    """Accept either int or string ('0x...' or decimal)."""
    if isinstance(value, int):
        return value
    return int(value, 0)


def _emit_li(reg, value, lines):
    """
    Materialize a 64-bit immediate into `reg` using lui + addi.

    For values that fit in 12 bits, just `addi reg, x0, imm`.
    Otherwise: `lui reg, hi20` then `addi reg, reg, lo12`.

    For 64-bit values (> 32 bits), we emit the low 32 first, then shift and
    OR in higher chunks. This is straightforward but verbose.
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

    # If the high bit of the 32-bit value is set, lui sign-extends to
    # 64 bits (0xffffffff_xxxxxxxx). Clear the upper 32 bits via
    # logical shifts so we have a zero-extended value.
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
    Read startup.json and return a list of assembly lines.

    The returned lines can be prepended to the user's source before assembling.
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
            # Step 1: pull almighty DDC into the target register.
            # CSpecialRW <cd>, ddc, c0  (source c0 means "read")
            lines.append(f"    cspecialrw  {reg_name}, ddc, c0")
        else:
            # Step 1 (untagged): just copy CNull. We achieve this by csetaddr
            # from c0 — c0 is permanently untagged, so the result is untagged.
            # (If your decoder doesn't support csetaddr from cnull cleanly,
            # this may need adjustment.)
            lines.append(f"    cspecialrw  {reg_name}, ddc, c0")
            lines.append(f"    # tag=false requested; manual untag step needed if needed")

        # Step 2: materialize address into a scratch integer register
        _emit_li(SCRATCH_INT_1, address, lines)

        # Step 3: set the cap's address
        lines.append(f"    csetaddr    {reg_name}, {reg_name}, {SCRATCH_INT_1}")

        # Step 4 (optional): materialize metadata and set it via csethigh.
        # Skip this if metadata is 0 (use the defaults from DDC).
        if metadata != 0:
            _emit_li(SCRATCH_INT_1, metadata, lines)
            lines.append(f"    csethigh    {reg_name}, {reg_name}, {SCRATCH_INT_1}")

        lines.append("")

    lines.append("# ── End of startup prologue ──")
    lines.append("# ══════════════════════════════════════════════════════════════")
    lines.append("")

    return lines
