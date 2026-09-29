"""Lossless resident dialogue pools; only verified replaced payloads are owned.

Tokens 00..FC expand to a dictionary pair, FD carries a literal pair, FE jumps
within the current script (or to the initial directory's scratch tail), FF ends
one record. Every record expands to old_length:u16 + the exact text bytes.
"""
from collections import Counter, defaultdict
import struct

BLOCK = 2048
DICTIONARY_OFFSET = 0x600


def prepare(data, parsed, entries):
    if not entries:
        raise ValueError('Resident dialogue requires changed entries')
    dictionary = [p for p, _ in Counter(
        bytes.fromhex(e['expanded_hex'])[i:i+2]
        for e in entries for i in range(0, e['new_bytes'], 2)).most_common(253)]
    dictionary += [b'\0\0'] * (253-len(dictionary))
    codes = {p: i for i, p in reversed(list(enumerate(dictionary)))}
    scratch_used = max(e['new_bytes'] for e in entries) + 3
    resident_start = (scratch_used + 3) & ~3
    tail = bytearray(BLOCK)
    tail_at = resident_start
    changed = bytearray(data)
    groups = defaultdict(list)
    for e in entries:
        groups[e['script']].append(e)
    reports = []
    for sid, group in sorted(groups.items()):
        base = parsed['scripts'][sid]['base']
        # A slot needs one maximum-sized token and a three-byte link.
        slots = sorted([(e['source_payload']+4, e['source_end']) for e in group
                        if e['old_bytes'] >= 10], key=lambda x: (-(x[1]-x[0]), x[0]))
        slots = iter(slots)
        at, end = next(slots, (0, 0))
        in_tail = not end
        if in_tail:
            at, end = tail_at, BLOCK
        def pointer():
            return 0x8000 | at if in_tail else at-base
        def put(raw):
            nonlocal at
            if at+len(raw)>end:
                raise ValueError('Resident dialogue directory capacity exceeded; no CD fallback')
            if in_tail:
                tail[at:at+len(raw)] = raw
            else:
                changed[at:at+len(raw)] = raw
            at += len(raw)
        def room(size):
            nonlocal at, end, in_tail
            if at+size+3 <= end or in_tail:
                return
            new_at, new_end = next(slots, (tail_at, BLOCK))
            new_tail = new_end == BLOCK
            target = (0x8000 | new_at) if new_tail else new_at-base
            put(b'\xfe'+struct.pack('<H', target))
            at, end, in_tail = new_at, new_end, new_tail
        started = tail_at
        for e in group:
            raw = struct.pack('<H', e['old_bytes']) + bytes.fromhex(e['expanded_hex'])
            tokens = [bytes((codes[raw[i:i+2]],)) if raw[i:i+2] in codes
                      else b'\xfd'+raw[i:i+2] for i in range(0,len(raw),2)] + [b'\xff']
            room(len(tokens[0]))
            address = pointer()
            if not 0 <= address <= 65535:
                raise ValueError('Resident script address overflow')
            e['resident_pointer'] = address
            e['storage'] = 'resident-pair-pool'
            p = e['source_payload']
            changed[p:p+4] = b'\x15\xd7'+struct.pack('<H',address)
            for token in tokens:
                room(len(token))
                put(token)
        if in_tail:
            tail_at = at
        reports.append({'script': sid, 'entries': len(group), 'directory_bytes': tail_at-started})
    # Validate every byte touched belongs to a replaced, verified payload.
    restored = bytearray(changed)
    for e in entries:
        a,b=e['source_payload'],e['source_end']
        restored[a:b]=data[a:b]
    if restored != data:
        raise ValueError('Resident pool changed non-text script data')
    result = {'format': 'resident-pair-pool-v1', 'dictionary_offset': DICTIONARY_OFFSET,
              'scratch_output_bytes': scratch_used, 'resident_start': resident_start,
              'resident_end': tail_at, 'directory_capacity': BLOCK,
              'per_dialogue_cd_reads': 0, 'scripts': reports}
    packed = bytes(changed)
    for e in entries:
        actual = unpack(packed, parsed['scripts'][e['script']]['base'], tail,
                        dictionary, e['resident_pointer'])
        expected = struct.pack('<H', e['old_bytes']) + bytes.fromhex(e['expanded_hex'])
        if actual != expected:
            raise ValueError('Resident dialogue round trip differs: '+e['id'])
    return packed, bytes(tail), b''.join(dictionary), result


def unpack(data, base, tail, dictionary, pointer):
    """Independent bounded decoder used by the build's byte round trip."""
    output = bytearray()
    seen = set()
    for _ in range(8192):
        if pointer in seen:
            raise ValueError('Resident pool cycle')
        seen.add(pointer)
        buf, at = (tail, pointer & 0x7fff) if pointer & 0x8000 else (data, base+pointer)
        token = buf[at]
        if token == 255:
            return bytes(output)
        if token == 254:
            pointer = struct.unpack_from('<H',buf,at+1)[0]
            continue
        if token == 253:
            output += buf[at+1:at+3]
            pointer += 3
        else:
            output += dictionary[token]
            pointer += 1
        if len(output)>BLOCK-1:
            raise ValueError('Resident output overflow')
    raise ValueError('Unterminated resident record')
