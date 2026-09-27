"""Reviewed JP control restorations, bound to exact legacy payloads and IDs.
Only protected-token differences are authorized; wording and row checks still apply.
See docs/control-restorations.md. No source game text is stored here.
"""
from hashlib import sha256
import re

RESTORATIONS = {
    'dg-text-01e28e': (
        '4a3cc21207211d5f2fa6a5da8754ed3c7c00e70483051562e4a48d3c674575fe',
        (('control', '0107'), ('control', '0101'), ('control', '0d00'), ('control', '0d00'), ('terminator', '0000'))),
    'dg-text-01e2d0': (
        '11393459a9affd64b74236b06d6f1bace3b025e6054df5afe4a1ee82db01b4be',
        (('control', '0107'), ('control', '0101'), ('control', '0d00'), ('control', '0d00'), ('control', '0d00'), ('terminator', '0000'))),
    'dg-text-036110': (
        '87fe12756058b880adce1f459af38edd187dc0bb5e950e44f69ea3e0bfbe7869',
        (('control', '0107'), ('control', '0101'), ('control', '0d00'), ('control', '0d00'), ('terminator', '0000'))),
    'dg-text-036192': (
        '30975674a1cee870fd017ec5793699c1d26f865361e82cb14a8fd20b5f9bd128',
        (('control', '0107'), ('control', '0101'), ('control', '0d00'), ('control', '0d00'), ('terminator', '0000'))),
    'dg-text-0365e8': (
        '0260b94da912c9e042664eb19435b2f8b540aeb560fe5dda987c569a4bfb9fe0',
        (('control', '0107'), ('control', '0101'), ('control', '0d00'), ('control', '0d00'), ('terminator', '0000'))),
    'dg-text-03e106': (
        'f20cbc99b511744185a84cbf405442c7dfd88f5503c52803072629df0c66f8fd',
        (('control', '0107'), ('control', '0101'), ('control', '0d00'), ('control', '0d00'), ('control', '0d00'), ('control', '0d00'), ('terminator', '0000'))),
    'dg-text-063b2c': (
        'f4af77487a3a617e42a5fbae359e9edb15f6450d4a909e37e73da534631acfa7',
        (('control', '0106'), ('control', '0500'), ('control', '0101'), ('control', '0d00'), ('control', '0d00'), ('terminator', '0000'))),
    'dg-text-06f8a2': (
        '16e118c290c434f9f81c36defcf858b2f5eba920b5568963eab6f85eafaea752',
        (('control', '0104'), ('glyph', '8283'), ('control', '0101'), ('control', '0d00'), ('control', '0d00'), ('control', '0105'), ('glyph', '8284'), ('control', '0101'), ('control', '0d00'), ('control', '0d00'), ('terminator', '0000'))),
    'dg-text-096f02': (
        'a20da7c1719df914506268b8254361e5b04776290069060e9dcf34ce2578588a',
        (('control', '0d00'), ('control', '0106'), ('control', '0500'), ('control', '0101'), ('control', '0d00'), ('control', '0d00'), ('terminator', '0000'))),
}


def restoration_allowed(entry_id, old, protected):
    rule = RESTORATIONS.get(entry_id)
    return rule is not None and rule == (sha256(old).hexdigest(), tuple(protected))


def review_restoration_allowed(row, text):
    """Permit only the reviewed token stream, including authorized row breaks."""
    old_hex = row.get('raw', {}).get('kor')
    if not old_hex:
        return False
    tokens = []
    for glyph, raw in re.findall(r'⟦(G:)?([0-9A-F]{4,8})⟧', text):
        if not glyph and raw == '0F00':
            continue
        tokens.append(('glyph' if glyph else 'control', raw.lower()))
    tokens.append(('terminator', '0000'))
    return restoration_allowed(row['id'], bytes.fromhex(old_hex), tokens)
