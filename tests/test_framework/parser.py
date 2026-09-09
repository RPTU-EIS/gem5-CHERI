"""
parser.py — Tokenize a minimal assembly source.

Supported syntax:
  - One instruction per line: `mnemonic op1, op2, op3`
  - Whitespace insensitive, mnemonic case insensitive
  - Comments: '#' or '//' to end of line
  - Blank lines ignored

No labels, no directives. The user said minimal — we keep it minimal.
"""


def strip_comment(line):
    """Remove '#...' or '//...' comments. Returns the cleaned line."""
    for marker in ("#", "//"):
        idx = line.find(marker)
        if idx >= 0:
            line = line[:idx]
    return line


def split_operands(operand_str):
    """Split an operand list by commas. Returns [] for empty input."""
    if not operand_str.strip():
        return []
    return [tok.strip() for tok in operand_str.split(",")]


def parse_source(text):
    """
    Parse assembly source text.

    Returns a list of (mnemonic, [operand_tokens], original_line_number).
    Blank/comment-only lines are skipped.
    """
    result = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = strip_comment(raw).strip()
        if not line:
            continue

        parts = line.split(None, 1)
        mnemonic = parts[0].lower()
        operands = split_operands(parts[1]) if len(parts) > 1 else []
        result.append((mnemonic, operands, lineno))
    return result
