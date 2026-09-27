#!/usr/bin/env python3
"""Revision-specific DG control-flow decoder, with opaque bytes preserved.

Specification/evidence: docs/dg-script.md. Addresses are logical file offsets.
Unknown instructions stop a path; no byte scanning is used to recover it.
"""
import struct
from collections import Counter


def u16(data, pos):
    return struct.unpack_from('<H', data, pos)[0]


# Total instruction widths, derived from the JP EXE's argument-reader calls.
# FE/FF consume one opcode byte then unwind; the following zero is not executed.
WIDTHS = {}
for width, codes in {
    1: '11 12 FE FF',
    2: '15 1B 21 22 23 25 27 2D 2E 2F 30 37 3D 3E 46 48 49 4A 54 58 5B 5C 5D 5E 5F 64 65 66 69 76 78 79 7B',
    4: '13 16 1C 1D 1E 1F 20 24 26 28 29 31 32 33 34 35 36 3A 3B 3C 3F 47 4B 4C 4D 50 51 53 56 57 5A 67 68 6A 6D 6F 70 7A 7E',
    6: '14 17 2A 2B 38 39 4F 72 73 74 77 FB',
    8: '4E 52 55 6C 6E 7C',
    10: '2C 71 7D',
    12: '75',
}.items():
    WIDTHS.update({int(code, 16): width for code in codes.split()})


def require(data, pos, size, limit):
    if pos < 0 or size < 0 or pos + size > min(limit, len(data)):
        raise ValueError(f'truncated instruction/token at {pos:#x}, needs {size}')


def text_tokens(data, pos, limit):
    """800F4424: byte dispatch; 03 takes four bytes, others take two.

    800F4A94 tests the byte AFTER a 0D pair for zero, then consumes two.
    An arbitrary 0000 elsewhere is NOT a termination signal.
    """
    result = []
    while True:
        require(data, pos, 2, limit)
        first = data[pos]
        width = 4 if first == 3 else 2
        require(data, pos, width, limit)
        kind = 'glyph' if first >= 0x16 else 'control'
        result.append({'offset': pos, 'kind': kind, 'raw': data[pos:pos+width].hex()})
        pos += width
        if first == 0x0d:
            require(data, pos, 2, limit)
            if data[pos] == 0:
                result.append({'offset': pos, 'kind': 'terminator',
                               'raw': data[pos:pos+2].hex()})
                return pos + 2, result


def instruction(data, pos, base, limit):
    require(data, pos, 1, limit)
    op = data[pos]
    refs, texts = [], []
    fallthrough = op not in (0x15, 0x16, 0x17, 0x18, 0xfe, 0xff)

    def local(storage):
        require(data, storage, 2, limit)
        refs.append({'storage': storage, 'target': base + u16(data, storage),
                     'kind': 'script_relative_u16'})

    def text(header):
        require(data, header, 2, limit)
        if data[header:header+2] != b'\x1a\x00':
            raise ValueError(f'unsupported text header at {header:#x}')
        end, tokens = text_tokens(data, header + 2, limit)
        texts.append({'id': f'dg-text-{header:06x}', 'header': header,
                      'payload': header + 2, 'end': end, 'tokens': tokens})
        return end

    if op == 0x1a:
        end = text(pos)
    elif op == 0x10:
        require(data, pos, 2, limit)
        count = data[pos+1]
        if not count:
            raise ValueError(f'zero selection count at {pos:#x}')
        for storage in range(pos+2, pos+2+count*2, 2):
            local(storage)
        # The selection handler skips the embedded 1A00 and consumes its text.
        end = text(pos + 2 + count*2)
        fallthrough = False
    elif op == 0x18:
        require(data, pos, 4, limit)
        count = u16(data, pos+2)
        if not count:
            raise ValueError(f'zero switch count at {pos:#x}')
        end = pos + 4 + 2*count
        for storage in range(pos+4, end, 2):
            local(storage)
    elif op == 0x19:
        # The predicate sub-VM runs until 19 xx yields to the main dispatcher.
        cursor = pos + 2
        while True:
            require(data, cursor, 2, limit)
            code = data[cursor]
            if code == 0x19:
                end = cursor + 2
                break
            family = code & 0x38
            if family in (0, 8):
                size = 4
            elif family in (0x10, 0x18):
                size = 4
                local(cursor+2)
            elif family == 0x20 and (code & 7) <= 5:
                size = (6, 6, 4, 4, 6, 8)[code & 7]
            else:
                raise ValueError(f'unsupported predicate {code:02x} at {cursor:#x}')
            require(data, cursor, size, limit)
            cursor += size
    elif op in WIDTHS:
        end = pos + WIDTHS[op]
        require(data, pos, WIDTHS[op], limit)
        if op in (0x13, 0x16):
            local(pos+2)
        elif op == 0xfb:
            refs.append({'storage': pos+2, 'script': u16(data, pos+2),
                         'map': u16(data, pos+4), 'kind': 'map_script_u16'})
        elif op in (0x14, 0x17):
            refs.append({'storage': pos+2, 'script': u16(data, pos+2),
                         'section': u16(data, pos+4), 'kind': 'script_section_u16'})
    else:
        raise ValueError(f'unsupported opcode {op:02x} at {pos:#x}')
    require(data, pos, end-pos, limit)
    return {'offset': pos, 'end': end, 'opcode': op, 'raw': data[pos:end].hex(),
            'references': refs, 'texts': texts, 'fallthrough': fallthrough}


def decode(data):
    if len(data) != 0xa9000:
        raise ValueError('Unsupported DG file size')
    bounds = list(struct.unpack_from('<226I', data))
    if bounds[0] != 0x800 or bounds[-1] != len(data) or any(
            a >= b or a % 2048 or b % 2048 for a, b in zip(bounds, bounds[1:])):
        raise ValueError('Invalid 225 allocation boundaries')
    scripts, nodes, errors, references = [], {}, [], []
    for index, (base, limit) in enumerate(zip(bounds, bounds[1:])):
        header_end = base + u16(data, base)
        if not base+4 <= header_end <= limit or (header_end-base) % 4:
            raise ValueError(f'Invalid section header in script {index}')
        sections = []
        for pos in range(base+2, header_end-2, 4):
            sid, offset = struct.unpack_from('<HH', data, pos)
            if sid == 0xffff or not header_end <= base+offset < limit or offset % 2:
                raise ValueError(f'Invalid section reference at {pos:#x}')
            sections.append({'id': sid, 'storage': pos+2, 'target': base+offset})
        if data[header_end-2:header_end] != b'\xff\xff':
            raise ValueError(f'Missing section sentinel in script {index}')
        script = {'index': index, 'base': base, 'limit': limit, 'header_end': header_end,
                  'sections': sections}
        scripts.append(script)
        pending = [s['target'] for s in sections]
        attempted = set()
        while pending:
            pos = pending.pop()
            if pos in attempted:
                continue
            attempted.add(pos)
            if not header_end <= pos < limit or pos % 2:
                errors.append({'script': index, 'offset': pos, 'error': 'invalid entry target'})
                continue
            try:
                node = instruction(data, pos, base, limit)
            except ValueError as exc:
                errors.append({'script': index, 'offset': pos, 'error': str(exc)})
                continue
            node['script'] = index
            nodes[pos] = node
            for ref in node['references']:
                references.append(dict(ref, source=pos, source_script=index))
                if ref['kind'] == 'script_relative_u16':
                    pending.append(ref['target'])
            if node['fallthrough']:
                pending.append(node['end'])
    # Overlaps are explicit, never silently accepted as independent strings.
    ordered = sorted(nodes.values(), key=lambda n: n['offset'])
    overlaps = []
    previous = None
    for node in ordered:
        if previous and node['offset'] < previous['end']:
            overlaps.append([previous['offset'], node['offset']])
        if previous is None or node['end'] > previous['end']:
            previous = node
    for ref in references:
        if ref['kind'] == 'script_relative_u16':
            ref['resolved'] = ref['target'] in nodes
        elif ref['kind'] == 'map_script_u16':
            ref['resolved'] = ref['script'] < len(scripts)
        else:
            target_script = ref['script']
            found = [s for s in scripts[target_script]['sections'] if s['id'] == ref['section']] if target_script < len(scripts) else []
            ref['resolved'] = bool(found) and found[0]['target'] in nodes
            if found:
                ref['target'] = found[0]['target']
    # Fixed, reviewed native accessor catalog. This is NOT inferred by searching
    # for 1600: 800FA2C0 chooses IDs 1220..1230, 800FA3F8 indexes four bytes.
    native = []
    for sid in range(1220, 1231):
        section = next(s for s in scripts[0]['sections'] if s['id'] == sid)
        for index in range(14):
            storage = section['target'] + 4*index + 2
            if data[storage-2:storage] != b'\x16\x00':
                raise ValueError('Native table catalog mismatch')
            target = scripts[0]['base'] + u16(data, storage)
            if target not in nodes or nodes[target]['opcode'] != 0x1a:
                raise ValueError('Native table target is not decoded text')
            native.append({'section': sid, 'index': index, 'storage': storage,
                           'target': target, 'payload': target+2})
    return {'scripts': scripts, 'nodes': ordered, 'references': references,
            'native_text_references': native,
            'errors': errors, 'overlaps': overlaps,
            'opcode_counts': dict(Counter(f'{n["opcode"]:02X}' for n in ordered))}


def partition(data, parsed):
    """All bytes, including headers, unreachable code and opaque allocation tails.

    A byte-identical reconstruction does not turn opaque bytes into decoded VM.
    """
    edges = {0, len(data)}
    for s in parsed['scripts']:
        edges.update((s['base'], s['header_end'], s['limit']))
    for n in parsed['nodes']:
        edges.update((n['offset'], n['end']))
    edges = sorted(edges)
    return [{'offset': a, 'raw': data[a:b].hex()} for a, b in zip(edges, edges[1:])]


def reassemble(parts):
    result = bytearray()
    for part in parts:
        if part['offset'] != len(result):
            raise ValueError('Non-contiguous/overlapping DG parts')
        result.extend(bytes.fromhex(part['raw']))
    return bytes(result)
