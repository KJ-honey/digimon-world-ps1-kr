#!/usr/bin/env python3
"""Export current wording drafts for an explicitly non-release gameplay test.

Source/review files remain unchanged. Failed entries require --defer-failed;
that option preserves their original disc text and lists every deferred ID.
"""
import argparse
from collections import Counter
import json
import unicodedata
from pathlib import Path

from dg_analyze import read_source, verified_texts
from dg_expand import DYNAMIC_TABLE_MAX_CHARS, validate_text
from dg_script import decode, text_tokens
from dg_layout import (INLINE_NAME_MAX_CHARS, TOURNAMENT_NAME_MAX_CHARS,
                       MAX_LINE_PIXELS, validate_layout,
                       validate_encoded_layout)
from dg_spacing import dialogue_codec
from survey import ROOT, SOURCES, sha, write_json
from translation_review import Workspace, TOKEN, WORK


def encode_draft(text, codec):
    # Encoding aliases for the existing game's full-cell glyphs. These do not
    # edit authored wording. Keep the table explicit in the output evidence.
    aliases = {unicodedata.normalize('NFKC', char): char for char in codec.reverse
               if len(unicodedata.normalize('NFKC', char)) == 1}
    aliases.update({' ': '\u3000', ',': '、', '.': '。', '~': '〜', '·': '・', '×': 'ｘ'})
    if any(codec.mapping.get(code) == ' ' for code in ('0F00', '0F01')):
        aliases[' '] = ' '
    def glyphs(part):
        result = bytearray()
        for char in part:
            if char == '늪':
                # Both legacy slots have the reviewed identity and same pixels;
                # new occurrences use the original first slot explicitly.
                result.extend(bytes.fromhex('88C0'))
            else:
                canonical = aliases.get(char, char)
                codes = codec.reverse.get(canonical, [])
                if len(codes) != 1:
                    raise ValueError(f'Missing or ambiguous character {char!r}: {codes}')
                result.extend(bytes.fromhex(codes[0]))
        return result
    result = bytearray()
    at = 0
    for token in TOKEN.finditer(text):
        result.extend(glyphs(text[at:token.start()]))
        result.extend(bytes.fromhex(token.group()[1:-1].removeprefix('G:')))
        at = token.end()
    result.extend(glyphs(text[at:]))
    return bytes(result), aliases


def export(directory, output, font_map, defer_failed=False):
    if output.exists() or not output.resolve().is_relative_to((ROOT/'work').resolve()):
        raise ValueError('Choose a new output directory under work/')
    workspace = Workspace(directory)
    reviews = workspace.load()
    # Recheck immutable images and actual consumer boundaries, not copied IDs.
    sources = {lang: read_source(lang) for lang in SOURCES}
    texts = {lang: verified_texts(decode(source['SCN/DG.SCN']))
             for lang, source in sources.items()}
    mapping = json.loads(font_map.read_text())
    if mapping.get('font_profile') not in ('ksx1001-preserve-legacy-v1', 'ksx1001-mona12-v1'):
        raise ValueError('Expected verified expanded font map')
    codec = dialogue_codec(mapping)
    if set(workspace.rows) != set(reviews['entries']) or set(workspace.rows) != set(texts['kor']):
        raise ValueError('Incomplete review/source population')
    edits, deferred, aliases = [], [], {}
    unchanged = 0
    for key, row in workspace.rows.items():
        for lang in sources:
            unit = texts[lang][key]
            actual = sources[lang]['SCN/DG.SCN'][unit['payload']:unit['end']]
            if actual.hex() != row['raw'][lang]:
                raise ValueError('Stale source bytes: '+key)
        old = bytes.fromhex(row['raw']['kor'])
        draft = reviews['entries'][key]
        try:
            validate_layout(draft['text'])
            if draft['text'] == row['existing']:
                new = old
            else:
                encoded, aliases = encode_draft(draft['text'], codec)
                new = encoded + b'\0\0'
                validate_text(old, new, codec, entry_id=key)
            validate_encoded_layout(text_tokens(new, 0, len(new))[1])
            unchanged += new == old
            edits.append(dict(id=key, expected_hex=old[:-2].hex(), text=codec.decode(new[:-2])))
        except ValueError as exc:
            deferred.append(dict(id=key, reason=str(exc), text=draft['text'],
                                 action='preserve_original_disc_text', revision=draft['revision']))
    output.mkdir(parents=True)
    report = dict(format=1, policy='development-only; user-requested unreviewed gameplay test',
                  release_eligible=False, review_states_changed=False,
                  baseline_sha256=sha((directory/'baseline.json').read_bytes()),
                  reviews_sha256=sha((directory/'reviews.json').read_bytes()),
                  expanded_character_map_sha256=sha(font_map.read_bytes()),
                  total=len(workspace.rows), selected=len(edits), unchanged=unchanged,
                  changed=len(edits)-unchanged, deferred=deferred,
                  deferred_reason_counts=dict(Counter(e['reason'] for e in deferred)),
                  dynamic_table_max_characters=DYNAMIC_TABLE_MAX_CHARS,
                  inline_name_max_characters={'07': INLINE_NAME_MAX_CHARS,
                                              '09': INLINE_NAME_MAX_CHARS},
                  tournament_name_max_characters=TOURNAMENT_NAME_MAX_CHARS,
                  max_line_pixels=MAX_LINE_PIXELS,
                  dynamic_table_budget_basis='user-specified ceiling; not independently measured',
                  encoding_aliases=aliases, duplicate_hangul_policy='new 늪 uses 88C0; unchanged payload stays byte-identical',
                  deferral_explicitly_selected=defer_failed)
    write_json(output/'selection.json', report)
    write_json(output/'reviews-snapshot.json', reviews)
    if deferred and not defer_failed:
        raise ValueError(f'{len(deferred)} entries failed; see {output}/selection.json')
    manifest = dict(format=1, purpose='development-only unreviewed gameplay test; see selection.json',
                    source_disc_sha256=SOURCES['kor'][1],
                    source_dg_sha256=sha(sources['kor']['SCN/DG.SCN']),
                    character_map_sha256=workspace.baseline['character_map_sha256'], edits=edits)
    write_json(output/'edits.json', manifest)
    return {key: report[key] for key in ('total','selected','unchanged','changed','deferred_reason_counts')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=WORK)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font-map', type=Path, default=ROOT/'work/build/full-development/font/character-map.json')
    parser.add_argument('--defer-failed', action='store_true', help='Explicitly preserve failed entries as original disc text')
    args = parser.parse_args()
    print(json.dumps(export(args.directory,args.output,args.font_map,args.defer_failed),ensure_ascii=False,indent=2))
