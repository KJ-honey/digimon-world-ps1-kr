#!/usr/bin/env python3
"""Revision-bound non-DG wording catalog. Does not write game files.

Offsets are logical SLPS_017.97 offsets; pointers are RAM addresses. Counts
are the declared tables for these exact disc revisions, not the whole game.
"""
from collections import Counter
import json
import struct

from glyph_review import atomic_json
from survey import ROOT, SOURCES, sha
from translation_review import digest, render_tokens

EXE = 'SLPS_017.97'
RAM_BASE = 0x80090000
TABLES = (
    ('location_name', 0xA5304, 70, 4, True),
    ('item_name', 0xA2D60, 128, 32, False),
    ('item_description', 0xA3D60, 128, 4, True),
    ('digimon_name', 0xAA924, 180, 52, False),
)
# Exact instruction hashes are checked in both supported revisions.
CONSUMERS = (
    (0x645E8, 0x64640, 'entity index * 52 -> name copy/length', '9f818b732387af779ed3e21e033a95740d1bff956c83baeac8069223425a59b7'),
    (0x53F34, 0x53F70, 'location pointer -> general text renderer', '749d678ce57a27a73fd3b15e6b42898e2a365d5728b8e88303405f68f27d2fb0'),
    (0x64720, 0x64758, 'item index * 32 -> string copy/length', '544f72ec8d669bccb42a82fcc692983cfaa3ea8ab5795b51451317be9d8c8e9a'),
    (0x58548, 0x58584, 'item description pointer -> general text renderer', '66dc880e2884cf10aa6311c88d6cf65bf28cdcab06189dc72e0e3f954a823d40'),
    (0x15B48, 0x15BCC, 'two-byte glyphs; zero first byte terminates', 'ca75f88678326d8eecd70682b9309d4407f231f633635a40dc583f541b775d59'),
)


def read_string(exe, offset, limit):
    """Follow the general consumer's two-byte advance and byte NUL check."""
    if not 0x800 <= offset < limit <= len(exe):
        raise ValueError('String address outside supported EXE payload')
    at = offset
    tokens = []
    while at < limit:
        if exe[at] == 0:
            return exe[offset:at + 1], tokens
        if at + 1 >= limit or exe[at + 1] == 0:
            raise ValueError('Truncated glyph or embedded byte NUL')
        tokens.append({'kind': 'glyph', 'raw': exe[at:at + 2].hex()})
        at += 2
    raise ValueError('Unterminated string within declared field')


def decode_reversible(tokens, mapping):
    # Keep ambiguous aliases as raw glyphs so Unicode round trips exactly.
    counts = Counter(c for c in mapping.values() if c is not None)
    safe = {code: c for code, c in mapping.items() if c is not None and counts[c] == 1}
    text = render_tokens(tokens, safe)
    reverse = {c: bytes.fromhex(code) for code, c in safe.items()}
    from translation_review import TOKEN
    rebuilt = bytearray()
    at = 0
    for match in TOKEN.finditer(text):
        for char in text[at:match.start()]:
            rebuilt.extend(reverse[char])
        rebuilt.extend(bytes.fromhex(match.group()[3:-1]))
        at = match.end()
    for char in text[at:]:
        rebuilt.extend(reverse[char])
    if rebuilt != b''.join(bytes.fromhex(t['raw']) for t in tokens):
        raise ValueError('Catalog Unicode round trip failed')
    return text


def extract(inputs, cmap, map_hash):
    from restore_text import RAW_GLYPH_INDICES
    if cmap['source']['disc_sha256'] != {k: v[1] for k, v in SOURCES.items()}:
        raise ValueError('Character map source discs differ')
    maps = {'kor': {e['code']: e['character'] for e in cmap['entries']}, 'jpn': {}}
    for e in cmap['entries']:
        maps['jpn'][e['code']] = (None if e['index'] in RAW_GLYPH_INDICES
                                  else bytes.fromhex(e['code']).decode('shift_jis'))
    evidence = []
    for start, end, purpose, expected in CONSUMERS:
        for exe in inputs.values():
            if sha(exe[start:end]) != expected:
                raise ValueError('Unsupported catalog consumer: '+hex(start))
        evidence.append(dict(logical_offset=start, ram_address=RAM_BASE + start,
                             size=end-start, sha256=expected, purpose=purpose))
    entries = []
    for category, base, count, stride, pointer in TABLES:
        for index in range(count):
            ref = base + index * stride
            row = dict(id=f'{category}-{index:03d}', category=category, table_index=index,
                       file=EXE, script=None, text_format='nul_glyph_string',
                       boundary='consumer_verified', product_eligible=False,
                       layout_verified=False, runtime_verified=False,
                       context='동일 테이블의 인덱스 순서. 실제 화면·등장 순서는 미검증.',
                       raw={}, tokens={}, locations={})
            for lang, exe in inputs.items():
                offset = struct.unpack_from('<I', exe, ref)[0] - RAM_BASE if pointer else ref
                # Bound inline names before the numeric record fields.
                limit = len(exe) if pointer else ref + 20
                raw, tokens = read_string(exe, offset, limit)
                if not tokens:
                    raise ValueError('Unexpected empty catalog entry')
                row['raw'][lang] = raw.hex()
                row['tokens'][lang] = tokens + [{'kind': 'terminator', 'raw': '00'}]
                row['source' if lang == 'jpn' else 'existing'] = decode_reversible(tokens, maps[lang])
                row['locations'][lang] = dict(logical_offset=offset, ram_address=RAM_BASE + offset,
                    reference_logical_offset=ref, reference_kind='u32_ram_pointer' if pointer else 'record',
                    reference_raw=exe[ref:ref + (4 if pointer else stride)].hex(),
                    byte_length_with_nul=len(raw))
            row['logical_offset'] = row['locations']['kor']['logical_offset']
            row['baseline_sha256'] = digest(row)
            entries.append(row)
    return dict(format=1, source_disc_sha256={k: v[1] for k, v in SOURCES.items()},
                source_file_sha256={k: sha(v) for k, v in inputs.items()},
                character_map_sha256=map_hash, entries=entries, consumer_evidence=evidence,
                scope=dict(confirmed_catalog_units=len(entries),
                           categories=dict(Counter(r['category'] for r in entries)),
                           complete_game_extraction=False,
                           unresolved=['other UI/module tables', 'card/move/song/tournament names',
                                       'all references and reinsertion capacity', 'runtime screens']),
                purpose='wording_review_only; not a reinsertion manifest')


def prepare(directory):
    from dg_analyze import read_source
    inputs = {lang: read_source(lang)[EXE] for lang in SOURCES}
    map_path = ROOT / 'work/text/character-map.json'
    baseline = extract(inputs, json.loads(map_path.read_text()), sha(map_path.read_bytes()))
    directory.mkdir(parents=True, exist_ok=True)
    # Same lock as reviewers; regeneration never overwrites authored decisions.
    import fcntl
    with (directory / '.write.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        install_baseline(directory, baseline)
    print(json.dumps({'catalog': str(directory), 'scope': baseline['scope']}, ensure_ascii=False))


def install_baseline(directory, baseline):
    """Called under the review lock; allow only an additive source extension."""
    path, review_path = directory / 'baseline.json', directory / 'reviews.json'
    previous = json.loads(path.read_text()) if path.exists() else None
    reviews = json.loads(review_path.read_text()) if review_path.exists() else None
    if reviews and (previous is None or reviews['baseline_sha256'] != digest(previous)):
        raise ValueError('Catalog review baseline mismatch')
    if previous is not None and previous != baseline:
        for field in ('source_disc_sha256', 'source_file_sha256', 'character_map_sha256'):
            if previous[field] != baseline[field]:
                raise ValueError('Catalog input changed; migration required')
        new_rows = {r['id']: r for r in baseline['entries']}
        if (len(new_rows) != len(baseline['entries']) or
                any(new_rows.get(r['id']) != r for r in previous['entries'])):
            raise ValueError('Existing catalog entries changed; migration required')
        if not all(e in baseline['consumer_evidence'] for e in previous['consumer_evidence']):
            raise ValueError('Existing consumer evidence changed')
        backup = directory / 'history' / digest(previous)
        backup.mkdir(parents=True, exist_ok=True)
        atomic_json(backup / 'baseline.json', previous)
        if reviews is not None:
            atomic_json(backup / 'reviews.json', reviews)
    updated = dict(reviews or dict(format=1, entries={}), baseline_sha256=digest(baseline))
    atomic_json(path, baseline)
    atomic_json(review_path, updated)
