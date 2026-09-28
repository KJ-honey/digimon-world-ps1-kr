"""Map NPC records consumed by JP 800BAE54; read-only speaker name links."""
from collections import defaultdict
import struct

MAP_TABLE = 0xa541c


def map_npcs(data, descriptor):
    # 800DF830..800DFA24 selects this relative pointer; 800AC5C8 skips
    # the player's 0x78-byte map entry block before calling 800BAE54.
    if not descriptor[12] & 0x80:
        return []
    a, b = descriptor[10:12]
    pointer_offset = 4 * (1 + a + b + bool(a or b))
    if pointer_offset + 4 > len(data):
        raise ValueError('Truncated map pointer table')
    offset = struct.unpack_from('<I', data, pointer_offset)[0] + 0x78
    if offset + 2 > len(data):
        raise ValueError('Truncated NPC count')
    count = struct.unpack_from('<H', data, offset)[0]
    if count > 8:
        raise ValueError('Map NPC count exceeds eight entity slots')
    cursor = offset + 2
    records = []
    for slot in range(count):
        if cursor + 84 > len(data):
            raise ValueError('Truncated NPC record')
        words = struct.unpack_from('<42H', data, cursor)
        # 33 fixed fields, patrol count, eight extra fields, then XYZ triplets.
        end = cursor + 84 + 6 * words[33]
        if end > len(data) or words[0] >= 180 or words[10] >= 200:
            raise ValueError('Invalid map NPC record')
        records.append(dict(slot=slot, type_id=words[0], actor_id=words[10],
                            logical_offset=cursor, end=end,
                            pointer_logical_offset=pointer_offset))
        cursor = end
    return records


def script_maps(parsed):
    direct = defaultdict(set)
    for ref in parsed['references']:
        if ref['kind'] == 'map_script_u16':
            direct[ref['script']].add(ref['map'])
    result = {s['index']: set(direct[s['index']]) for s in parsed['scripts']}
    # Shared event scripts inherit the caller's loaded map; the map itself is
    # not replaced by a 14/17 script call. Keep alternatives, never pick first.
    changed = True
    while changed:
        changed = False
        for ref in parsed['references']:
            if ref['kind'] != 'script_section_u16' or direct[ref['script']]:
                continue
            target = result[ref['script']]
            previous = len(target)
            target.update(result[ref['source_script']])
            changed |= len(target) != previous
    return result


def load_npcs(parsed, inputs, mapping):
    from survey import Disc, ROOT, SOURCES
    from translation_catalog import read_string
    from translation_review import render_tokens
    for start, end in ((0x2ae54, 0x2b518), (0x1c588, 0x1c7c4),
                       (0x4f7d0, 0x4fa2c), (0x64dbc, 0x64f44), (0x650a8, 0x65184)):
        if inputs['jpn']['SLPS_017.97'][start:end] != inputs['kor']['SLPS_017.97'][start:end]:
            raise ValueError('NPC/name consumer differs between languages')
    maps = script_maps(parsed)
    records = {}
    # Read both supported sources so differing placement data cannot silently
    # attach a JP character to the KR dialogue.
    discs = {lang: Disc(ROOT / SOURCES[lang][0]) for lang in inputs}
    try:
        tables = {lang: disc.files() for lang, disc in discs.items()}
        for map_id in sorted(set().union(*maps.values())):
            offset = MAP_TABLE + map_id * 16
            desc = inputs['jpn']['SLPS_017.97'][offset:offset+16]
            if len(desc) != 16 or desc != inputs['kor']['SLPS_017.97'][offset:offset+16]:
                raise ValueError('Map descriptor differs between languages')
            name = desc[:8].split(b'\0')[0].decode('ascii')
            filename = f'MAP/MAP{map_id//15+1}/{name}.MAP'
            if any(filename not in tables[lang] for lang in discs):
                records[map_id] = []
                continue
            parsed_maps = {}
            for lang, disc in discs.items():
                f = tables[lang][filename]
                raw = disc.read(f['lba'], f['size'])
                parsed_maps[lang] = map_npcs(raw, desc)
            if parsed_maps['jpn'] != parsed_maps['kor']:
                raise ValueError('NPC placement differs between languages')
            records[map_id] = [dict(r, map_id=map_id, file=filename,
                                    descriptor_logical_offset=offset) for r in parsed_maps['jpn']]
    finally:
        for disc in discs.values():
            disc.close()
    names = {}
    for type_id in sorted({r['type_id'] for rs in records.values() for r in rs}):
        pair = []
        for lang, files in inputs.items():
            exe = files['SLPS_017.97']
            offset = 0xaa924 + type_id * 52
            _, tokens = read_string(exe, offset, offset + 20)
            table = mapping if lang == 'kor' else {t['raw'].upper(): bytes.fromhex(t['raw']).decode('shift_jis') for t in tokens}
            pair.append(render_tokens(tokens, table).strip())
        names[type_id] = pair
    linked = {}
    for script, map_ids in maps.items():
        actors = defaultdict(list)
        for map_id in sorted(map_ids):
            for record in records[map_id]:
                jp, kr = names[record['type_id']]
                actors[record['actor_id']].append(dict(id='name:'+jp, label=f'{kr} / {jp}',
                    source_name=jp, existing_name=kr, origin=record))
        for actor, options in actors.items():
            grouped = {}
            for option in options:
                key = option['id']
                if key not in grouped:
                    grouped[key] = {k: v for k, v in option.items() if k != 'origin'}
                    grouped[key]['origins'] = []
                grouped[key]['origins'].append(option['origin'])
            linked[script, actor] = list(grouped.values())
    return linked
