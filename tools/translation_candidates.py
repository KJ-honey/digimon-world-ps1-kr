#!/usr/bin/env python3
"""Unverified DG text candidates as a separate wording-review family.

Not a reinsertion manifest. Every former byte-search candidate outside the
consumer-verified set is classified; only text that is not a byte copy of a
verified unit becomes a review row. Offsets are logical DG file offsets.

python3 tools/translation_review.py prepare-candidates
"""
import bisect
from collections import Counter
import json

from survey import ROOT, SOURCES, sha
from translation_review import digest, render_tokens

DG = 'SCN/DG.SCN'
MAPHEAD_END = 0x6236
# Handler evidence for the four former 6B stops (RAM addresses, JP = KR bytes).
VM_EVIDENCE = (
    dict(ram_address=0x8011B3BC, purpose='64..7E jump table entry for 6B -> 800EEB38'),
    dict(ram_address=0x800EEB38, purpose='6B handler: no argument read; b 800EF318 (longjmp 1, next opcode)'),
    dict(ram_address=0x800F08A4, purpose='opcodes 00..0F etc.: error flag gp-0x6CB0 then longjmp 2'),
    dict(ram_address=0x800F0910, purpose='longjmp 2 with error flag -> 800F3114 script stop'),
)
CONTEXT = {
    'unreferenced_block': ('미확인 후보: 섹션 진입점·분기·선택지·native 표 어디에서도 도달하지 않는 블록. '
                           'DG 안의 u16 상대 offset, EXE·overlay의 절대 포인터 참조도 찾지 못함. '
                           '실제 표시 여부 미확인 — 미사용 문장일 수 있음.'),
    'allocation_tail': ('미확인 후보: 할당 영역의 마지막 도달 명령 뒤 tail. tail은 다른 위치 바이트의 '
                        '복사본이 대부분이며 이 문장은 확인된 단위와 원문이 다름. 실제 표시 여부 미확인.'),
}


def code_gaps(script, nodes):
    """Byte spans between reached instructions, before the last reached end."""
    gaps, cursor = [], script['header_end']
    for node in nodes:
        if node['offset'] > cursor:
            gaps.append((cursor, node['offset']))
        cursor = max(cursor, node['end'])
    return gaps, cursor


def classify(inputs, maps):
    from dg_analyze import verified_texts
    from dg_script import decode, instruction, text_tokens
    from recover_assets import scan_dialogue
    parsed = {lang: decode(files[DG]) for lang, files in inputs.items()}
    data = {lang: files[DG] for lang, files in inputs.items()}
    verified = verified_texts(parsed['jpn'])
    if verified.keys() != verified_texts(parsed['kor']).keys():
        raise ValueError('Different JP/KR consumer boundaries')
    covered = {}
    for key, text in verified.items():
        covered.setdefault(data['jpn'][text['payload']:text['end']], []).append(key)
    headers = {t['header'] for t in verified.values()}
    searched = {lang: scan_dialogue(data[lang]).keys() - headers for lang in data}
    if searched['jpn'] != searched['kor']:
        raise ValueError('JP/KR search candidates differ')
    scripts = parsed['jpn']['scripts']
    bases = [s['base'] for s in scripts]
    by_script = {}
    for node in parsed['jpn']['nodes']:
        by_script.setdefault(node['script'], []).append(node)
    discovered = dict.fromkeys(searched['jpn'], 'byte_search')
    blocks, tails = {}, {}
    for script in scripts:
        gaps, last = code_gaps(script, by_script.get(script['index'], []))
        tails[script['index']] = last
        for start, end in gaps:
            for at in range(start + (start & 1), end, 2):
                blocks.setdefault(at, (start, end))
                # The search required a glyph/01..0D first token; decode 1A00
                # with the consumer grammar to recover what it skipped.
                if data['jpn'][at:at+2] == b'\x1a\x00' and at not in discovered:
                    try:
                        instruction(data['jpn'], at, script['base'], script['limit'])
                        instruction(data['kor'], at, script['base'], script['limit'])
                    except ValueError:
                        continue
                    discovered[at] = 'unreferenced_block_decode'
    audit, entries = [], []
    for header in sorted(discovered):
        index = bisect.bisect_right(bases, header) - 1
        script = scripts[index]
        tokens, ends = {}, {}
        for lang in data:
            ends[lang], tokens[lang] = text_tokens(data[lang], header + 2, script['limit'])
        if ends['jpn'] != ends['kor']:
            raise ValueError(f'Different JP/KR candidate ends at {header:#x}')
        end = ends['jpn']
        kind = 'allocation_tail' if header >= tails[index] else 'unreferenced_block'
        record = dict(header=header, script=index, end=end, candidate_class=kind,
                      discovery=discovered[header],
                      covered_by=covered.get(data['jpn'][header+2:end], []))
        if kind == 'unreferenced_block':
            record['block'] = list(blocks[header])
        if not record['covered_by']:
            key = f'dg-candidate-{header:06x}'
            record['review_id'] = key
            row = dict(id=key, category='dialogue_candidate', script=index, file=DG,
                       logical_offset=header, source=render_tokens(tokens['jpn'], maps['jpn']),
                       existing=render_tokens(tokens['kor'], maps['kor']),
                       raw={lang: data[lang][header+2:end].hex() for lang in data},
                       tokens=tokens, context=CONTEXT[kind], boundary='unverified_candidate',
                       candidate_class=kind, discovery=record['discovery'],
                       product_eligible=False, layout_verified=False, runtime_verified=False)
            if index == 0 and header < MAPHEAD_END:
                row['maphead_logical_offset'] = header - 0x800
            if kind == 'unreferenced_block':
                row['block'] = record['block']
            row['baseline_sha256'] = digest(row)
            entries.append(row)
        audit.append(record)
    return entries, audit


def extract(inputs, cmap, map_hash):
    from restore_text import RAW_GLYPH_INDICES
    if cmap['source']['disc_sha256'] != {k: v[1] for k, v in SOURCES.items()}:
        raise ValueError('Character map source discs differ')
    maps = {'kor': {e['code']: e['character'] for e in cmap['entries']}, 'jpn': {}}
    for e in cmap['entries']:
        maps['jpn'][e['code']] = (None if e['index'] in RAW_GLYPH_INDICES
                                  else bytes.fromhex(e['code']).decode('shift_jis'))
    entries, audit = classify(inputs, maps)
    classes = Counter((r['candidate_class'], 'review_row' if 'review_id' in r else 'covered_by_verified')
                      for r in audit)
    return dict(format=1, source_disc_sha256={k: v[1] for k, v in SOURCES.items()},
                source_file_sha256={k: sha(v[DG]) for k, v in inputs.items()},
                character_map_sha256=map_hash, entries=entries, consumer_evidence=list(VM_EVIDENCE),
                audit=audit,
                scope=dict(candidates=len(audit), review_rows=len(entries),
                           classes={f'{a}/{b}': n for (a, b), n in sorted(classes.items())},
                           byte_search=sum(r['discovery'] == 'byte_search' for r in audit),
                           unreferenced_block_decode=sum(r['discovery'] != 'byte_search' for r in audit),
                           consumer_verified=False, complete_game_extraction=False,
                           unresolved=['dynamic/native references outside DG and declared tables',
                                       'runtime display', 'reinsertion path']),
                purpose='wording_review_only; unverified candidates; not a reinsertion manifest')


def prepare(directory):
    from dg_analyze import read_source
    from translation_catalog import install_baseline
    inputs = {lang: read_source(lang) for lang in SOURCES}
    map_path = ROOT / 'work/text/character-map.json'
    baseline = extract(inputs, json.loads(map_path.read_text()), sha(map_path.read_bytes()))
    directory.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (directory / '.write.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        install_baseline(directory, baseline)
    print(json.dumps({'candidates': str(directory), 'scope': baseline['scope']}, ensure_ascii=False))
