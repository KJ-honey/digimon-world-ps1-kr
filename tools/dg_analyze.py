#!/usr/bin/env python3
"""Extract DG instructions and text with revision-bound evidence and round trips."""
import argparse
import json
from pathlib import Path
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN

from dg_script import decode, partition, reassemble
from recover_assets import scan_dialogue
from restore_text import LegacyCodec
from survey import ROOT, SOURCES, Disc, sha, write_json

FILES = ('SLPS_017.97', 'SCN/DG.SCN', 'SCN/MAPHEAD.SCN')
EVIDENCE_RANGES = ((0x5c404, 0x657a4, 'VM and text consumers'),
                   (0x8b0f8, 0x8b4a4, 'dispatch tables'),
                   (0x6a2c0, 0x6a474, 'common native text accessor'),
                   (0x75524, 0x755ec, 'current-script indexed accessor'))


def read_source(label):
    disc = Disc(ROOT / SOURCES[label][0])
    try:
        if sha(disc.raw) != SOURCES[label][1]:
            raise ValueError(f'Unsupported {label} source')
        table = disc.files()
        return {f: disc.read(table[f]['lba'], table[f]['size']) for f in FILES}
    finally:
        disc.close()


def verified_texts(parsed):
    return {t['id']: dict(t, script=n['script'], instruction=n['offset'])
            for n in parsed['nodes'] for t in n['texts']}


def analyze(out, map_path):
    if not out.resolve().is_relative_to((ROOT / 'work').resolve()):
        raise ValueError('Outputs must stay under work/')
    inputs = {label: read_source(label) for label in SOURCES}
    out.mkdir(parents=True, exist_ok=True)
    cs = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
    evidence = []
    for start, end, purpose in EVIDENCE_RANGES:
        raw = inputs['jpn']['SLPS_017.97'][start:end]
        if raw != inputs['kor']['SLPS_017.97'][start:end]:
            raise ValueError('JP/KR consumer code differs')
        evidence.append({'purpose': purpose, 'exe_file_offset': start, 'size': end-start,
                         'ram_start': hex(0x80090000+start), 'sha256': sha(raw)})
        if purpose != 'dispatch tables':
            (out/f'consumer-{start:06x}.asm').write_text('\n'.join(
                f'{i.address:08X} {i.mnemonic} {i.op_str}'
                for i in cs.disasm(raw, 0x80090000+start))+'\n')
    write_json(out/'consumer-evidence.json', evidence)
    mapping = json.loads(map_path.read_text())
    codec = LegacyCodec({e['code']: e['character'] for e in mapping['entries']})
    parsed, texts, summary = {}, {}, {}
    for label, files in inputs.items():
        data = files['SCN/DG.SCN']
        if mapping['source']['dg_sha256'][label] != sha(data):
            raise ValueError('Character map DG binding differs')
        mirror = files['SCN/MAPHEAD.SCN']
        if data[0x800:0x800+len(mirror)] != mirror:
            raise ValueError('MAPHEAD is not the expected DG allocation-0 mirror')
        parsed[label] = decode(data)
        texts[label] = verified_texts(parsed[label])
        parts = partition(data, parsed[label])
        # Serialize and deserialize before reassembly, not just slice/concatenate.
        write_json(out / f'{label}-parts.json', parts)
        rebuilt = reassemble(json.loads((out / f'{label}-parts.json').read_text()))
        if rebuilt != data:
            raise ValueError('DG serialized round trip failed')
        (out / f'{label}-roundtrip.scn').write_bytes(rebuilt)
        write_json(out / f'{label}-vm.json', parsed[label])
        candidates = scan_dialogue(data)
        headers = {t['header'] for t in texts[label].values()}
        payloads = {data[t['payload']:t['end']-2] for t in texts[label].values()}
        classified = []
        for header, raw in candidates.items():
            t = texts[label].get(f'dg-text-{header:06x}')
            classified.append({'header': header, 'state': 'consumer_boundary' if t else 'unresolved',
                               'same_payload_end': t['end']-2 == header+2+len(raw) if t else None,
                               'payload_duplicates_verified_unit': raw in payloads if not t else None})
        write_json(out / f'{label}-candidate-audit.json', classified)
        summary[label] = {
            'file_sha256': {f: sha(b) for f, b in files.items()},
            'allocations_roundtrip': 225, 'roundtrip_bytes': len(data),
            'roundtrip_sha256': sha(rebuilt),
            'section_references': sum(len(s['sections']) for s in parsed[label]['scripts']),
            'decoded_instructions': len(parsed[label]['nodes']),
            'decoded_instruction_bytes': sum(n['end']-n['offset'] for n in parsed[label]['nodes']),
            'text_units': len(texts[label]),
            'candidate_matches': len(headers & candidates.keys()),
            'unresolved_candidates': len(candidates.keys()-headers),
            'unresolved_payloads_matching_verified_units': sum(raw in payloads for h,raw in candidates.items() if h not in headers),
            'new_text_units_outside_search': len(headers-candidates.keys()),
            'errors': parsed[label]['errors'], 'overlaps': parsed[label]['overlaps'],
            'unresolved_explicit_references': [r for r in parsed[label]['references'] if not r['resolved']],
            'native_table_references': len(parsed[label]['native_text_references']),
        }
    a, b = parsed['jpn'], parsed['kor']
    skeleton = lambda p: [(n['offset'], n['end'], n['opcode'], n['references']) for n in p['nodes']]
    if skeleton(a) != skeleton(b):
        raise ValueError('JP/KR instruction skeletons differ')
    rows = []
    for key, t in texts['kor'].items():
        jp = texts['jpn'][key]
        t = dict(t, korean=codec.decode(inputs['kor']['SCN/DG.SCN'][t['payload']:t['end']-2]),
                 japanese_raw=inputs['jpn']['SCN/DG.SCN'][jp['payload']:jp['end']-2].hex(),
                 boundary_evidence='JP EXE consumer + section/branch graph',
                 reinsert_policy='exact_length_and_protected_token_positions',
                 release_eligible=False)
        rows.append(t)
    (out / 'texts.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False)+'\n' for t in rows))
    summary.update(format=1, source_disc_sha256={l: v[1] for l, v in SOURCES.items()},
                   character_map_sha256=sha(map_path.read_bytes()),
                   same_jp_kr_skeleton=True, complete_vm=False, complete_reference_catalog=False,
                   opaque_bytes_preserved=True, gameplay_runtime_verified=False,
                   relocation_supported=False)
    write_json(out / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT/'work/dg/analysis')
    p.add_argument('--character-map', type=Path, default=ROOT/'work/text/character-map.json')
    args = p.parse_args()
    print(json.dumps(analyze(args.output, args.character_map), ensure_ascii=False, indent=2))
