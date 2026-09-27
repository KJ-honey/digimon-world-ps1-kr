#!/usr/bin/env python3
"""Prepare bitmap-only RAM experiments for same-scene font screenshots.

This does not build an ISO or change the expanded font provider. Load a state
from the alignment-only development image before the dialogue is rendered,
write the selected table to RAM 0x80128D38, and replay identical inputs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont, __version__ as PIL_VERSION


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(asset_root, output):
    work = asset_root / 'work'
    exe = (work / 'survey/files/kor/SLPS_017.97').read_bytes()
    original = exe[0x98D38:0x9E278]
    assert len(original) == 992 * 22
    cmap_path = work / 'text/character-map.json'
    entries = json.loads(cmap_path.read_text())['entries']
    hangul = [e for e in entries if e.get('character') and
              len(e['character']) == 1 and '가' <= e['character'] <= '힣']
    assert len(hangul) == 913
    output.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'runtime bitmap comparison, not a product font build',
              'pillow': PIL_VERSION, 'character_map_sha256': sha(cmap_path.read_bytes()),
              'ram_address': '0x80128D38', 'ram_region_offset': '0x128D38',
              'exe_logical_offset': '0x98D38', 'length': len(original),
              'rendering': '12px, Pillow 1-bit, anchor=lt, origin=(0,0), no rescaling; 12x11 cell',
              'changed_population': '913 legacy Hangul slots; symbols and fallback preserved',
              'variants': []}
    variants = [('01-current', None), ('02-galmuri11', 'Galmuri11.ttf'),
                ('03-mona12textkr', 'Mona12TextKR.ttf'),
                ('04-thindunggeunmo', 'ThinDungGeunMo.ttf')]
    for name, filename in variants:
        table = bytearray(original)
        variant = {'name': name, 'font': filename or 'existing Korean bitmap (Gulim based)'}
        if filename:
            path = work / 'font-compare' / filename
            font = ImageFont.truetype(str(path), 12)
            font_map = TTFont(path).getBestCmap()
            for e in hangul:
                char, index = e['character'], e['index']
                assert int(e['code'], 16) == struct.unpack_from('<H', exe, 0x98578 + index*2)[0]
                if ord(char) not in font_map:
                    raise ValueError(f'{filename}: missing {char}')
                # Padded raster detects actual ink outside the target rectangle.
                padded = Image.new('1', (40, 40))
                ImageDraw.Draw(padded).text((8, 8), char, font=font, fill=1, anchor='lt')
                bounds = padded.getbbox()
                if not bounds or bounds[0] < 8 or bounds[1] < 8 or bounds[2] > 20 or bounds[3] > 19:
                    raise ValueError(f'{filename}: empty or clipped {char}: {bounds}')
                rows = [sum((0 if padded.getpixel((x+8, y+8)) else 1) << (15-x)
                            for x in range(12)) | 15 for y in range(11)]
                table[index*22:(index+1)*22] = struct.pack('<11H', *rows)
            variant['font_sha256'] = sha(path.read_bytes())
        changed = {i for i in range(992) if table[i*22:(i+1)*22] != original[i*22:(i+1)*22]}
        assert changed <= {e['index'] for e in hangul}
        variant.update(table_sha256=sha(table), changed_slots=len(changed))
        (output / (name + '.bin')).write_bytes(table)
        # Small chunks fit the debugger's write limit. All addresses are RAM offsets.
        chunks = [{'address': hex(0x128D38+i), 'hex': table[i:i+1024].hex()}
                  for i in range(0, len(table), 1024)]
        (output / (name + '.json')).write_text(json.dumps(chunks))
        report['variants'].append(variant)
    (output / 'profiles.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('work/font-compare/tables'))
    args = parser.parse_args()
    print(json.dumps(prepare(args.asset_root, args.output), ensure_ascii=False, indent=2))
