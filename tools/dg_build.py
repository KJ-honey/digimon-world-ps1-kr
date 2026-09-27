#!/usr/bin/env python3
"""Reinsert verified DG text into an immutable Korean disc (development only).

No relocation or implicit padding: each text payload has exactly its old size;
every control/argument/terminator and unresolved glyph keeps its byte position.
Script 0 writes are mirrored into the actual MAPHEAD loading source.
"""
import argparse
import json
from pathlib import Path

from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
from build import OFFSET, BEFORE, AFTER, DECODED
from cd_sector import regenerate
from dg_analyze import verified_texts
from dg_script import decode, text_tokens
from restore_text import LegacyCodec, restore
from glyph_review import SOURCE
from match_gulim import DEFAULT_FONT
from survey import ROOT, SOURCES, Disc, sha, write_json


def replace_text(data, parsed, edits, codec):
    texts = verified_texts(parsed)
    result = bytearray(data)
    writes, seen = [], set()
    overlap_nodes = {pos for pair in parsed['overlaps'] for pos in pair}
    for edit in edits:
        key = edit['id']
        if key in seen:
            raise ValueError(f'Duplicate writer: {key}')
        seen.add(key)
        if key not in texts:
            raise ValueError(f'No consumer-verified text boundary: {key}')
        t = texts[key]
        if t['instruction'] in overlap_nodes:
            raise ValueError(f'Overlapping instruction path: {key}')
        start, end = t['payload'], t['end']-2
        old = data[start:end]
        if edit['expected_hex'] != old.hex():
            raise ValueError(f'Stale source text: {key}')
        new = codec.encode(edit['text'])
        if len(old) != len(new):
            raise ValueError(f'Exact-length policy: {key} needs {len(old)} bytes, got {len(new)}; no padding/truncation')
        candidate = data[:start] + new + data[end:]
        new_end, tokens = text_tokens(candidate, start, t['end'])
        if new_end != t['end'] or len(tokens) != len(t['tokens']):
            raise ValueError(f'Text token boundaries changed: {key}')
        for before, after in zip(t['tokens'], tokens):
            if before['offset'] != after['offset'] or before['kind'] != after['kind'] or len(before['raw']) != len(after['raw']):
                raise ValueError(f'Token structure changed: {key}')
            if before['raw'] == after['raw']:
                continue
            if before['kind'] != 'glyph':
                raise ValueError(f'Protected control/argument/terminator changed: {key}')
            if any(codec.mapping.get(tok['raw'].upper()) is None for tok in (before, after)):
                raise ValueError(f'Unknown/unsupplied glyph edit: {key}')
        if new != old:
            result[start:end] = new
            writes.append({'id': key, 'file': 'SCN/DG.SCN', 'file_offset': start,
                           'before': old.hex(), 'after': new.hex(), 'script': t['script']})
    changed = bytes(result)
    rebuilt = decode(changed)
    shape = lambda p: [(n['offset'], n['end'], n['opcode'], n['references']) for n in p['nodes']]
    if shape(parsed) != shape(rebuilt) or parsed['errors'] != rebuilt['errors']:
        raise ValueError('Re-extracted VM structure differs')
    for edit in edits:
        t = texts[edit['id']]
        if changed[t['payload']:t['end']-2] != codec.encode(edit['text']):
            raise ValueError('Re-extraction differs from requested text')
    return changed, writes


def sector_plan(disc, table, writes):
    """Plan disjoint logical writes before deriving any sector protection bytes."""
    sectors, allowed, owners = {}, {}, set()
    for write in writes:
        f = table[write['file']]
        offset = write['file_offset']
        before, after = bytes.fromhex(write['before']), bytes.fromhex(write['after'])
        if len(before) != len(after) or offset < 0 or offset+len(before) > f['size']:
            raise ValueError('File write exceeds unchanged extent')
        for i, (old, new) in enumerate(zip(before, after)):
            coordinate = (write['file'], offset+i)
            if coordinate in owners:
                raise ValueError('Overlapping logical writers')
            owners.add(coordinate)
            lba = f['lba']+(offset+i)//2048
            within = 24+(offset+i)%2048
            original = disc.sector(lba)
            if original[18] & 0x20 or original[within] != old:
                raise ValueError('Source sector/form/precondition mismatch')
            if lba not in sectors:
                if regenerate(original) != original:
                    raise ValueError('Original EDC/ECC mismatch')
                sectors[lba] = bytearray(original)
                allowed[lba] = set()
            sectors[lba][within] = new
            allowed[lba].add(within)
    plan = {}
    for lba, sector in sectors.items():
        final = regenerate(sector)
        permitted = allowed[lba] | set(range(2072, 2352))
        if any(a != b and i not in permitted for i, (a, b) in enumerate(zip(disc.sector(lba), final))):
            raise ValueError('Unplanned sector mutation')
        plan[lba] = final
    return plan


def build(edits_path, output, alignment=False):
    if not output.resolve().is_relative_to((ROOT/'work').resolve()) or output.exists():
        raise ValueError('Choose a new output directory under work/')
    manifest = json.loads(edits_path.read_text())
    disc = Disc(ROOT/SOURCES['kor'][0])
    try:
        if sha(disc.raw) != SOURCES['kor'][1] or manifest['source_disc_sha256'] != SOURCES['kor'][1]:
            raise ValueError('Unsupported source disc')
        table = disc.files()
        data = disc.read(**{k: table['SCN/DG.SCN'][k] for k in ('lba','size')})
        if manifest['source_dg_sha256'] != sha(data):
            raise ValueError('Stale DG input binding')
        # Rebuild the character map from reviewed pixels and human decisions;
        # translator JSON cannot substitute its own mapping or OCR guesses.
        output.mkdir(parents=True)
        restore(output/'verified-text', ROOT/'work/survey', SOURCE.parent, DEFAULT_FONT)
        map_path = output/'verified-text/character-map.json'
        if manifest['character_map_sha256'] != sha(map_path.read_bytes()):
            raise ValueError('Character map changed; review/re-export edits')
        mapping = json.loads(map_path.read_text())
        codec = LegacyCodec({e['code']: e['character'] for e in mapping['entries']})
        parsed = decode(data)
        changed, writes = replace_text(data, parsed, manifest['edits'], codec)
        mf = table['SCN/MAPHEAD.SCN']
        mirror = disc.read(mf['lba'], mf['size'])
        if mirror != data[0x800:0x800+len(mirror)]:
            raise ValueError('DG/MAPHEAD source copies disagree')
        for write in list(writes):
            if write['script'] == 0:
                offset = write['file_offset']-0x800
                if offset+len(bytes.fromhex(write['after'])) > len(mirror):
                    raise ValueError('Script 0 write outside loaded MAPHEAD')
                writes.append(dict(write, file='SCN/MAPHEAD.SCN', file_offset=offset,
                                   id=write['id']+'-maphead-mirror'))
        if alignment:
            cs = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
            if [(i.mnemonic, i.op_str) for i in cs.disasm(AFTER, 0x80090000+OFFSET)] != DECODED:
                raise ValueError('Alignment instruction decode mismatch')
            writes.append({'id': 'alignment-repair', 'file': 'SLPS_017.97', 'file_offset': OFFSET,
                           'before': BEFORE.hex(), 'after': AFTER.hex()})
        plan = sector_plan(disc, table, writes)
        image = output/'dg-dev.iso'
        with image.open('xb') as f:
            cursor = 0
            for lba, sector in sorted(plan.items()):
                at = lba*2352
                f.write(disc.raw[cursor:at]); f.write(sector)
                cursor = at+2352
            f.write(disc.raw[cursor:])
        final = Disc(image)
        try:
            if len(final.raw) != len(disc.raw) or final.files() != table:
                raise ValueError('Disc length or filesystem changed')
            # Every final sector is compared to its precomputed exact value.
            for lba in range(len(disc.raw)//2352):
                start = lba*2352
                expected = plan.get(lba, disc.raw[start:start+2352])
                if final.raw[start:start+2352] != expected:
                    raise ValueError(f'Unexplained full-image diff: LBA {lba}')
            f = table['SCN/DG.SCN']
            if final.read(f['lba'], f['size']) != changed:
                raise ValueError('Final ISO DG re-extraction differs')
            if final.read(mf['lba'], mf['size']) != changed[0x800:0x800+len(mirror)]:
                raise ValueError('Final ISO MAPHEAD mirror differs')
            for lba in plan:
                if regenerate(final.sector(lba)) != final.sector(lba):
                    raise ValueError('Final EDC/ECC failed')
            report = {'status': 'development-only', 'purpose': manifest.get('purpose', 'text reinsertion'),
                      'requested_text_units': len(manifest['edits']),
                      'verified_input_payload_bytes': sum(len(bytes.fromhex(e['expected_hex'])) for e in manifest['edits']),
                      'source_sha256': SOURCES['kor'][1], 'output_sha256': sha(final.raw),
                      'dg_sha256': sha(changed), 'edits_manifest_sha256': sha(edits_path.read_bytes()),
                      'character_map_sha256': sha(map_path.read_bytes()),
                      'writes': writes, 'sectors': [
                          {'lba': lba, 'raw_sector_offset': lba*2352,
                           'before_sha256': sha(disc.sector(lba)), 'after_sha256': sha(sector)}
                          for lba, sector in sorted(plan.items())],
                      'full_image_diff_verified': True, 'filesystem_unchanged': True,
                      'reextraction_verified': True, 'gameplay_runtime_verified': False,
                      'release_eligible': False, 'relocation_supported': False}
        finally:
            final.close()
        (output/'dg-dev.cue').write_text('FILE "dg-dev.iso" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
        (output/'edits.json').write_bytes(edits_path.read_bytes())
        write_json(output/'build.json', report)
        return report
    finally:
        disc.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--edits', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--alignment-repair', action='store_true')
    args = p.parse_args()
    print(json.dumps(build(args.edits, args.output, args.alignment_repair), ensure_ascii=False, indent=2))
