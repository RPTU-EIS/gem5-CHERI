# CHERI-RISC-V Test Infrastructure

Minimal assembler for CHERI-RISC-V test programs running in pure capability
mode on gem5. Reads a JSON-driven ISA database, optionally prepends a
JSON-driven startup prologue, and emits `.bin` + `.lst` + `.elf`.

## File layout

```
cheri_test_infra/
├── cheri_asm.py        Main driver (CLI entry point)
├── cheri_isa.json      Instruction encodings + register maps
├── isa.py              JSON loader, register/SCR resolution
├── encoders.py         Bit-level encoders for R/I/S/U/B/J formats
├── encode.py           Per-instruction dispatch + operand placement
├── parser.py           Minimal source tokenizer
├── startup.py          Generates CHERI assembly from startup.json
├── elf_wrap.py         Wraps a flat binary in a minimal RV64 ELF
└── examples/
    ├── startup.json    Sample capability register init
    └── test_caps.s     Sample test program
```

Each Python file has a single, narrow responsibility. To follow what happens
when you assemble a program, start in `cheri_asm.py:main()` and work down.

## Usage

```bash
python3 cheri_asm.py prog.s
python3 cheri_asm.py prog.s --startup startup.json
python3 cheri_asm.py prog.s --startup startup.json --base 0x80000000 --out build/prog
```

Produces `<out>.bin`, `<out>.lst`, `<out>.elf` (default `<out>` is the source
filename without extension).

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--isa` | `cheri_isa.json` next to script | Instruction encoding database |
| `--startup` | none | If given, prepend CHERI prologue from this JSON |
| `--base` | `0x80000000` | Code base address |
| `--out` | source stem | Output filename stem |

## Assembly syntax

Minimal. One instruction per line:

```
mnemonic op1, op2, op3   # comment
mnemonic op1, op2        // also a comment
```

No labels, no directives, no pseudo-instructions. To branch, hand-compute
relative offsets.

Register names follow ABI convention: `x0..x31`, `zero`, `ra`, `sp`, `t0..t6`,
`a0..a7`, `s0..s11`. Capability variants: `c0..c31`, `cra`, `csp`, `ct0..ct2`,
`ca0..ca7`, `cs0..cs11`.

Immediates accept decimal, hex (`0x...`), and binary (`0b...`), positive or
negative.

## Adding a new instruction

Edit `cheri_isa.json` → `instructions`. Each entry has three parts:

```json
"my_op": {
    "format": "CHERI_R",
    "fields": {
        "opcode": "0x5b",
        "funct3": "0x0",
        "funct7": "0x55"
    },
    "operands": [
        {"name": "cd",  "type": "capability", "field": "rd"},
        {"name": "cs1", "type": "capability", "field": "rs1"},
        {"name": "rs2", "type": "integer",    "field": "rs2"}
    ]
}
```

- `format`: one of `R`, `I`, `S`, `U`, `B`, `J`, `CHERI_R`.
- `fields`: fixed encoding bits that are independent of operands.
- `operands`: list in source order. Each operand has `name` (what the user
  writes — informational), `type` (`capability` / `integer` / `immediate` /
  `scr`), and `field` (which RISC-V encoding field it goes into).

No Python changes are needed for instructions that fit the existing formats.

## Startup file

Each entry materializes one capability register before user code runs:

```json
{
  "startup_registers": {
    "c1": {
      "tag": true,
      "address": "0x80010000",
      "metadata": "0x0fff1ffffe018004"
    },
    "c2": { "tag": true, "address": "0x80020000", "metadata": "0x..." }
  }
}
```

For each entry, the assembler emits:

```
cspecialrw  c1, ddc, c0           # c1 = almighty DDC (full perms, tagged)
lui         t0, <hi20 of address>
addi        t0, t0, <lo12 of address>
csetaddr    c1, c1, t0            # c1.address = t0
lui         t0, <hi20 of metadata>
addi        t0, t0, <lo12 of metadata>
csethigh    c1, c1, t0            # c1.metadata = t0
```

Both `t0` and `t1` are clobbered during startup. User code should treat them
as undefined on entry.

**Note:** the prologue assumes `cspecialrw`, `csetaddr`, and `csethigh` are
implemented in your decoder. If you haven't implemented `csethigh` yet, drop
the `metadata` field from each startup entry and the prologue will skip those
two instructions.

## Output formats

### `.bin`
Raw little-endian instruction words. Concatenated startup + user code, no
header. Suitable for loading directly into gem5 memory.

### `.lst`
Annotated listing:
```
# Assembled from: test_caps.s
# Startup config: examples/startup.json
# Base address:   0x80000000
# Total size:     104 bytes (26 instructions)

  80000000:  021000db    cspecialrw c1, ddc, c0
  80000004:  800102b7    lui        t0, 0x80010
  ...
```

### `.elf`
Single PT_LOAD segment, R+X, vaddr = paddr = base. Layout:
- ELF header at offset 0x000 (64 bytes)
- Program header at offset 0x040 (56 bytes)
- Zero padding through 0x0fff
- Payload at offset 0x1000

Matches the reference `elf_wrap.py` you provided.

## Adding new instruction formats

If you need a format not in `encoders.py` (e.g. CSR-immediate, an extension's
custom layout), add a new function there following the pattern, then add a
dispatch case in `encode.py:encode_instruction()`.
