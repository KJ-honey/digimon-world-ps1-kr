"""Read-only speaker metadata from verified DG instructions and original names.

All offsets in evidence are logical file offsets, never ISO sector offsets.
Unknown entry/call state is deliberately retained at control-flow joins.
"""
from collections import deque
import re
import struct

HEADER = re.compile(r'^⟦01[0-9A-F]{2}⟧(.+?)⟦0101⟧[ 　]*⟦0D00⟧')


def inline_name(text):
    match = HEADER.match(text)
    return match.group(1).strip() if match else None


def speakers_for(rows, parsed, fixed_names, npc_names=None):
    npc_names = npc_names or {}
    nodes = {n['offset']: n for n in parsed['nodes']}
    states = {p: set() for p in nodes}
    queue = deque()

    def offer(p, values):
        if p in states and not values <= states[p]:
            states[p].update(values)
            queue.append(p)

    for script in parsed['scripts']:
        for section in script['sections']:
            offer(section['target'], {None})
    for ref in parsed.get('native_text_references', []):
        offer(ref['target'], {None})
    while queue:
        pos = queue.popleft()
        node = nodes[pos]
        op = node['opcode']
        values = states[pos]
        if op == 0x1b:
            values = {bytes.fromhex(node['raw'])[1]}
        elif op == 0x26:
            # This textbox mode suppresses the name until another mode change.
            # Keep unknown rather than inventing persistence of a visible name.
            values = {None}
        # Subroutine/native calls may change the global speaker. Do not carry
        # a caller's speaker past a call without a verified return summary.
        if node['fallthrough']:
            offer(node['end'], {None} if op in (0x13, 0x14, 0x49, 0xfb) else values)
        for ref in node['references']:
            if ref['kind'] in ('script_relative_u16', 'script_section_u16') and 'target' in ref:
                offer(ref['target'], values)
            elif ref['kind'] == 'script_section_u16':
                target_script = parsed['scripts'][ref['script']]
                section = next((s for s in target_script['sections'] if s['id'] == ref['section']), None)
                if section:
                    offer(section['target'], values)

    def describe(value, script):
        if value is None:
            return dict(id='unknown', label='화자 미확인')
        if value == 0xff:
            return dict(id='none', label='화자 표시 없음')
        if value in (0xfd, 0xfc):
            return dict(id='player' if value == 0xfd else 'partner',
                        label='주인공' if value == 0xfd else '파트너 디지몬')
        if value in fixed_names:
            jp, kr = fixed_names[value]
            return dict(id='name:'+jp, label=f'{kr} / {jp}')
        return dict(id=f'actor:{script}:{value:02x}',
                    label=f'NPC 0x{value:02X} (script {script} · 이름 미확인)')

    result = {}
    for row in rows:
        node = nodes.get(row.get('instruction'))
        source_name = inline_name(row['source'])
        if source_name:
            kr = inline_name(row['existing'])
            if source_name in ('⟦0500⟧', '⟦0600⟧'):
                item = describe(0xfd if source_name == '⟦0500⟧' else 0xfc, row['script'])
            else:
                item = dict(id='name:'+source_name, label=f'{kr or source_name} / {source_name}')
            candidates = [item]
            evidence = '원문 첫 줄의 명시적 화자명'
        else:
            values = states.get(row.get('instruction')) or {None}
            candidates = []
            for value in sorted(values, key=lambda v: -1 if v is None else v):
                candidates.extend(npc_names.get((row['script'], value), [describe(value, row['script'])]))
            candidates = list({c['id']: c for c in candidates}.values())
            evidence = 'VM 1B → 로드된 맵의 NPC 배치 → 디지몬 종류 → 게임 이름 테이블'
        result[row['id']] = dict(candidates=candidates,
            label=' / '.join(c['label'] for c in candidates),
            ambiguous=len(candidates) > 1, evidence=evidence,
            is_choice=bool(node and node['opcode'] == 0x10),
            instruction_logical_offset=row.get('instruction'))
    return result


def load_speakers(baseline):
    from dg_analyze import read_source, verified_texts
    from dg_script import decode
    from translation_catalog import read_string
    from translation_review import render_tokens
    from survey import ROOT, sha
    import json
    inputs = {lang: read_source(lang) for lang in ('jpn', 'kor')}
    parsed = decode(inputs['jpn']['SCN/DG.SCN'])
    texts = verified_texts(parsed)
    rows = baseline['entries']
    for row in rows:
        t = texts.get(row['id'])
        if not t or t['instruction'] != row['instruction']:
            raise ValueError('Speaker metadata baseline boundary mismatch')
        for lang in inputs:
            if inputs[lang]['SCN/DG.SCN'][t['payload']:t['end']].hex() != row['raw'][lang]:
                raise ValueError('Speaker metadata baseline bytes mismatch')
    cmap_path = ROOT / 'work/text/character-map.json'
    if sha(cmap_path.read_bytes()) != baseline['character_map_sha256']:
        raise ValueError('Speaker character map mismatch')
    mapping = {e['code']: e['character'] for e in json.loads(cmap_path.read_text())['entries']}
    fixed = {}
    values = {bytes.fromhex(n['raw'])[1] for n in parsed['nodes'] if n['opcode'] == 0x1b}
    for value in sorted(values & set(range(0xc8, 0xfc))):
        names = []
        for lang in ('jpn', 'kor'):
            exe = inputs[lang]['SLPS_017.97']
            pointer = struct.unpack_from('<I', exe, 0xa6c74 + (value-0xc8)*4)[0]
            _, tokens = read_string(exe, pointer - 0x80090000, len(exe))
            table = mapping if lang == 'kor' else {t['raw'].upper(): bytes.fromhex(t['raw']).decode('shift_jis') for t in tokens}
            names.append(render_tokens(tokens, table))
        fixed[value] = names
    from translation_npcs import load_npcs
    return speakers_for(rows, parsed, fixed, load_npcs(parsed, inputs, mapping))
