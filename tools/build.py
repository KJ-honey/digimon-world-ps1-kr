#!/usr/bin/env python3
"""Build a development-only alignment repair from the immutable Korean ISO.

This is not the requested finished font/name/translation upgrade. The fixed
four-instruction MIPS I byte specification changes no branches or placement.
"""
import argparse
import json
from pathlib import Path

from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
from cd_sector import regenerate
from survey import Disc, SOURCES, ROOT, sha

OFFSET = 0x15B78
BEFORE = bytes.fromhex('0000429400000000ffff523021204002')
AFTER = bytes.fromhex('01004390000042900092030025204202')
DECODED = [('lbu', '$v1, 1($v0)'), ('lbu', '$v0, ($v0)'),
           ('sll', '$s2, $v1, 8'), ('or', '$a0, $s2, $v0')]


def build(source, output):
    if output.exists():
        raise ValueError('Output already exists; choose a new output directory')
    disc = Disc(source)
    try:
        if sha(disc.raw) != SOURCES['kor'][1]:
            raise ValueError('Unsupported source SHA-256')
        file = disc.files()['SLPS_017.97']
        exe = disc.read(file['lba'], file['size'])
        if exe[OFFSET:OFFSET + len(BEFORE)] != BEFORE:
            raise ValueError('Instruction precondition mismatch')
        cs = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
        instructions = list(cs.disasm(AFTER, 0x80090000 + OFFSET))
        if [(i.mnemonic, i.op_str) for i in instructions] != DECODED:
            raise ValueError('Independent instruction decoding mismatch')
        # Verify all EXE sectors against their existing EDC/P/Q before trusting
        # this encoder for the changed sector. The originals are the oracle.
        for n in range((file['size'] + 2047) // 2048):
            s = disc.sector(file['lba'] + n)
            if regenerate(s) != s:
                raise ValueError(f'Original sector parity mismatch: {n}')
        lba = file['lba'] + OFFSET // 2048
        within = 24 + OFFSET % 2048
        old_sector = disc.sector(lba)
        candidate = bytearray(old_sector)
        candidate[within:within + len(AFTER)] = AFTER
        new_sector = regenerate(candidate)
        allowed = set(range(within, within + len(AFTER))) | set(range(2072, 2352))
        if any(a != b and i not in allowed for i, (a, b) in enumerate(zip(old_sector, new_sector))):
            raise ValueError('Protected sector bytes changed')
        raw_offset = lba * 2352
        plan = {'writer': 'unaligned-text-reader', 'purpose': 'Read two-byte text at either address parity',
                'raw_offset': raw_offset, 'lba': lba, 'file_offset': OFFSET,
                'before_sha256': sha(old_sector), 'after_sha256': sha(new_sector),
                'instruction_before': BEFORE.hex(), 'instruction_after': AFTER.hex(),
                'derived_ranges': ['Mode2 Form1 EDC 2072:2076', 'P/Q 2076:2352']}
        output.mkdir(parents=True)
        image = output / 'alignment-dev.iso'
        with image.open('xb') as f:
            f.write(disc.raw[:raw_offset])
            f.write(new_sector)
            f.write(disc.raw[raw_offset + 2352:])
        final = Disc(image)
        try:
            if len(final.raw) != len(disc.raw):
                raise ValueError('Unexpected output length')
            # Full-image final diff explained by the single precomputed write.
            for start in range(0, len(disc.raw), 2352 * 512):
                end = min(start + 2352 * 512, len(disc.raw))
                expected = bytearray(disc.raw[start:end])
                if start <= raw_offset < end:
                    p = raw_offset - start
                    expected[p:p + 2352] = new_sector
                if final.raw[start:end] != expected:
                    raise ValueError('Unexplained final image difference')
            report = {'status': 'development-only', 'source_sha256': sha(disc.raw),
                      'output_sha256': sha(final.raw), 'expected_writes': [plan],
                      'exe_sectors_parity_checked': (file['size'] + 2047) // 2048,
                      'runtime_verified': False}
        finally:
            final.close()
        (output / 'alignment-dev.cue').write_text('FILE "alignment-dev.iso" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
        (output / 'build.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
    finally:
        disc.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=ROOT / SOURCES['kor'][0])
    p.add_argument('--output', type=Path, default=ROOT / 'work/build/alignment-dev')
    args = p.parse_args()
    build(args.source, args.output)
