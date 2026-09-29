"""Source-bound audit of the DG 12 tournament-name pointer table."""
import hashlib
import struct

from dg_analyze import read_source

TABLE_OFFSET = 0xA78C4  # SLPS_017.97 logical file offset, RAM 0x801378C4.
JUMP_TABLE_OFFSET = 0x8B44C
OPCODE = 0x12
OPCODE_HANDLER_RAM = 0x800F4948
RAM_DELTA = 0x80090000
ENTRY_COUNT = 46  # 23 full names followed by 23 abbreviated names.
EXPECTED = {
    'kor': ('bf701939eb22766e7b47a9dc4386f44a39b27cdb833fa966a6dcd02d07611a85', 5),
    'jpn': ('d9db5924ac7f45bf0473f4561c7b9d0d39007f93f3454d52fdea9e2f2a2f2817', 11),
}


def audit(exe, language):
    """Hash table and pointed strings; reject changed or malformed names."""
    if language not in EXPECTED:
        raise ValueError('Unsupported tournament table language')
    handler, = struct.unpack_from('<I', exe, JUMP_TABLE_OFFSET + OPCODE * 4)
    if handler != OPCODE_HANDLER_RAM:
        raise ValueError('DG 12 no longer selects the tournament-name handler')
    table = exe[TABLE_OFFSET:TABLE_OFFSET + ENTRY_COUNT * 4]
    if len(table) != ENTRY_COUNT * 4:
        raise ValueError('Truncated tournament pointer table')
    bound = bytearray(table)
    lengths = []
    for index in range(ENTRY_COUNT):
        pointer, = struct.unpack_from('<I', table, index * 4)
        at = pointer - RAM_DELTA
        if not 0x800 <= at < len(exe):
            raise ValueError(f'Tournament pointer {index} outside EXE')
        start = at
        while at + 1 < len(exe) and at - start <= 64:
            if exe[at] == 0:
                break
            if exe[at + 1] == 0:
                raise ValueError(f'Tournament name {index} has embedded byte NUL')
            at += 2
        else:
            raise ValueError(f'Tournament name {index} is unterminated')
        raw = exe[start:at + 1]
        bound.extend(raw)
        lengths.append((len(raw) - 1) // 2)
    digest = hashlib.sha256(bound).hexdigest()
    expected_hash, expected_max = EXPECTED[language]
    if digest != expected_hash or max(lengths) != expected_max:
        raise ValueError(f'{language} tournament names changed; reassess DG 12 width')
    return {'language': language, 'opcode': f'{OPCODE:02X}',
            'handler_ram': f'{handler:08X}', 'pointer_table_file_offset': TABLE_OFFSET,
            'entries': ENTRY_COUNT,
            'full_name_max': max(lengths[:23]),
            'abbreviation_max': max(lengths[23:]),
            'max_characters': max(lengths), 'table_and_strings_sha256': digest}


if __name__ == '__main__':
    import json
    print(json.dumps({lang: audit(read_source(lang)['SLPS_017.97'], lang)
                      for lang in EXPECTED}, ensure_ascii=False, indent=2))
