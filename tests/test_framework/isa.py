"""
isa.py — load ISA JSON and resolve register/operand references.
"""

import json


class ISA:
    """Wraps the loaded ISA JSON. Provides lookups for instructions, registers, SCRs."""

    def __init__(self, json_path):
        with open(json_path) as f:
            data = json.load(f)
        self.instructions = data["instructions"]
        self.int_regs = data["registers"]["integer"]
        self.cap_regs = data["registers"]["capability"]
        self.scrs = data.get("scrs", {})
        self.perms = data.get("perms_table", {})

    def resolve_register(self, name, kind):
        """
        Resolve a register name to its numeric index.

        kind: 'integer' | 'capability' | 'scr'
        Lowercases the name, strips whitespace, and looks it up.
        """
        name = name.strip().lower()
        # Skip underscore-prefixed comment keys
        if kind == "integer":
            table = self.int_regs
        elif kind == "capability":
            table = self.cap_regs
        elif kind == "scr":
            table = self.scrs
        else:
            raise ValueError(f"Unknown register kind: {kind}")

        if name not in table:
            raise ValueError(f"Unknown {kind} register: {name}")
        return table[name]

    def get_instruction(self, mnemonic):
        """Return the JSON dict for an instruction, or raise."""
        m = mnemonic.lower()
        if m not in self.instructions or m.startswith("_"):
            raise ValueError(f"Unknown instruction: {mnemonic}")
        return self.instructions[m]
