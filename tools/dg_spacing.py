"""DG-only whitespace: native 0F 00 clears/advances 6 px; 81 40 is 12 px.

Do not install this alias in the generic EXE/name codec: 0F is interpreted by
the DG row renderer (800F34E4), not the generic glyph renderer (800A5B48).
Both representations consume two bytes in the original DG consumer.
The original uploader rounds glyph X down to four pixels. Expanded DG builds
use dg_pixel_row to compose the row at exact six-pixel spacing before upload,
following the user's revised decision on 2026-09-28.
"""
from restore_text import LegacyCodec


def dialogue_codec(mapping):
    values = {e['code']: e['character'] for e in mapping['entries']}
    if '0F00' in values or ' ' in values.values():
        raise ValueError('DG half-space alias collision')
    values['0F00'] = ' '
    return LegacyCodec(values)


def is_half_space(token, codec):
    return token['raw'].upper() == '0F00' and codec.mapping.get('0F00') == ' '
