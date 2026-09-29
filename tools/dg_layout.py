"""DG dialogue width budget: 252px, full-cell glyphs and 6px half spaces.

Dynamic name/table bounds follow the existing consumer byte budgets. Width is
not byte count: raw button/unit glyphs occupy one cell, color controls none.
"""
import re

MAX_LINE_PIXELS = 252
DYNAMIC_TABLE_MAX_CHARS = 10
DYNAMIC_TABLE_OPCODES = (0x07, 0x08, 0x09, 0x11, 0x12)
INLINE_NAME_MAX_CHARS = 9  # 20-byte field: nine 2-byte units plus byte NUL.
# RAM 800F44E0..4884 / digit loops 800F4F44: byte budgets for rendered
# numeric fields and six-cell names. Table names use the user's ten-cell
# ceiling (2026-09-28), not an exhaustive measurement of their source tables.
DYNAMIC_BYTES = {4: 6, 5: 12, 6: 12, 10: 12, 11: 8, 16: 10,
                 19: 6, 20: 6, 21: 6}
DYNAMIC_BYTES.update({op: 2 * DYNAMIC_TABLE_MAX_CHARS for op in DYNAMIC_TABLE_OPCODES})
# 07 copies the digimon-name table and 09 copies the item-name table. Both
# come from 20-byte inline fields; catalog reinsertion enforces this bound.
DYNAMIC_BYTES.update({0x07: 2 * INLINE_NAME_MAX_CHARS,
                      0x09: 2 * INLINE_NAME_MAX_CHARS})
LINE = '⟦0D00⟧'
ATOM = re.compile(r'⟦(?:G:)?[0-9A-F]{4,8}⟧|[^⟦⟧]')


def atom_width(atom):
    if not atom.startswith('⟦'):
        if len(atom) != 1 or ord(atom) < 32:
            raise ValueError('Use explicit DG tokens for line breaks/control characters')
        return 6 if atom == ' ' else 12
    if atom.startswith('⟦G:'):
        return 12
    raw = bytes.fromhex(atom[1:-1])
    if raw[0] == 1:
        return 0
    if raw[0] == 15:
        return 6
    if raw[0] in DYNAMIC_BYTES:
        return DYNAMIC_BYTES[raw[0]] // 2 * 12
    raise ValueError('Unestablished pixel width for '+atom)


def line_widths(text):
    if ''.join(ATOM.findall(text)) != text:
        raise ValueError('Malformed dialogue token')
    lines = text.split(LINE)
    if lines[-1] == '':
        lines.pop()
    return [sum(atom_width(a) for a in ATOM.findall(line)) for line in lines]


def validate_layout(text):
    widths = line_widths(text)
    for index, width in enumerate(widths, 1):
        if width > MAX_LINE_PIXELS:
            raise ValueError(f'DG line {index} exceeds {MAX_LINE_PIXELS}px: {width}px')
    return widths


def validate_encoded_layout(tokens):
    text = ''.join(('⟦G:' if t['kind']=='glyph' else '⟦')+t['raw'].upper()+'⟧'
                   for t in tokens if t['kind']!='terminator')
    # 8140 full space is a full-cell glyph, like every other glyph.
    return validate_layout(text)
