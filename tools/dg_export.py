#!/usr/bin/env python3
"""Export selected consumer-verified DG text into a guarded edit manifest."""
import argparse
import json
from pathlib import Path

from dg_analyze import read_source, verified_texts
from dg_script import decode
from restore_text import LegacyCodec
from survey import ROOT, SOURCES, sha, write_json


def export(ids, output, map_path):
    if output.exists() or not output.resolve().is_relative_to((ROOT/'work').resolve()):
        raise ValueError('Choose a new manifest under work/')
    data = read_source('kor')['SCN/DG.SCN']
    texts = verified_texts(decode(data))
    mapping = json.loads(map_path.read_text())
    if mapping['source']['dg_sha256']['kor'] != sha(data):
        raise ValueError('Stale character-map source')
    codec = LegacyCodec({e['code']:e['character'] for e in mapping['entries']})
    edits = []
    for key in ids:
        if key not in texts:
            raise ValueError(f'Not a consumer-verified text ID: {key}')
        t = texts[key]
        payload = data[t['payload']:t['end']-2]
        edits.append({'id': key, 'expected_hex': payload.hex(), 'text': codec.decode(payload)})
    manifest = {'format': 1, 'purpose': 'development text edits; prose requires review',
                'source_disc_sha256': SOURCES['kor'][1], 'source_dg_sha256': sha(data),
                'character_map_sha256': sha(map_path.read_bytes()), 'edits': edits}
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, manifest)
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--id', action='append', default=[], help='Repeat for each dg-text-XXXXXX ID; none exports a no-op manifest')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--character-map', type=Path, default=ROOT/'work/text/character-map.json')
    args = p.parse_args()
    print(export(args.id, args.output, args.character_map))
