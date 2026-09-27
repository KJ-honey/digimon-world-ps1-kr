#!/usr/bin/env python3
"""Execute the original JP/KR text consumer in Unicorn, without patched code.

This isolated CPU harness proves pointer advancement for its fixtures, NOT
PS1 gameplay, video layout, load-delay timing, saves, or scene reachability.
Requires optional unicorn==2.1.4; the product builder does not require it.
"""
import argparse
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, __version__
from unicorn.mips_const import (UC_MIPS_REG_GP, UC_MIPS_REG_SP, UC_MIPS_REG_A0,
                                UC_MIPS_REG_A1, UC_MIPS_REG_RA, UC_MIPS_REG_PC)
from dg_analyze import read_source, verified_texts
from dg_script import decode
from survey import ROOT, sha, write_json

SIMPLE_CONTROLS = {0, 1, 2, 3, 12, 13, 14, 15}


class Consumer:
    def __init__(self, exe):
        self.cpu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN)
        self.cpu.mem_map(0, 0x200000)
        self.cpu.mem_write(0x90800, exe[0x800:])
        # A synthetic GP is sufficient; every GP-relative consumer field below
        # is initialized. No game savestate or existing emulator is modified.
        self.gp = 0x80150000

    def run(self, payload):
        c = self.cpu
        c.mem_write(0x50000, payload+b'\xfe\x00')
        c.mem_write(0x60000, bytes(0x8000))
        c.mem_write(0x1640b8, bytes(0x100))
        def word(addr, value):
            c.mem_write(addr & 0x1fffff, struct.pack('<I', value))
        word(self.gp-0x6cc8, 0x80050000)
        word(self.gp-0x6ce8, 0x80060000)
        for reg, value in ((UC_MIPS_REG_GP, self.gp), (UC_MIPS_REG_SP, 0x801f0000),
                           (UC_MIPS_REG_A0, 0), (UC_MIPS_REG_A1, 255),
                           (UC_MIPS_REG_RA, 0x80040000)):
            c.reg_write(reg, value)
        c.emu_start(0x800f4200, 0x80040000, count=100000)
        cursor = struct.unpack('<I', c.mem_read((self.gp-0x6cc8)&0x1fffff, 4))[0]
        if c.reg_read(UC_MIPS_REG_PC) != 0x80040000 or cursor != 0x80050000+len(payload):
            raise ValueError(f'Actual MIPS consumer disagrees: cursor={cursor:#x}, expected={0x80050000+len(payload):#x}')
        return cursor


def verify(output, build_dir=None):
    if not output.resolve().is_relative_to((ROOT/'work').resolve()):
        raise ValueError('Evidence must stay under work/')
    report = {'unicorn_version': __version__, 'entry_ram': '0x800F4200',
              'isolated_cpu_only': True, 'gameplay_runtime_verified': False, 'sources': {}}
    for label in ('jpn', 'kor'):
        files = read_source(label)
        data = files['SCN/DG.SCN']
        exe = files['SLPS_017.97']
        consumer = Consumer(exe)
        tested, skipped = [], []
        for t in verified_texts(decode(data)).values():
            if any(tok['kind'] == 'control' and int(tok['raw'][:2],16) not in SIMPLE_CONTROLS
                   for tok in t['tokens']):
                skipped.append(t['id'])
                continue
            consumer.run(data[t['payload']:t['end']])
            tested.append(t['id'])
        # Deliberately includes 0000 as 03 arguments and as a non-terminating
        # standalone pair; the old two-byte scan would stop early.
        fixtures = ['0300000081400d000000', '8140000081410d000000',
                    '81400d0081410d000000']
        for raw in fixtures:
            consumer.run(bytes.fromhex(raw))
        report['sources'][label] = {'exe_sha256': sha(exe), 'dg_sha256': sha(data),
                                     'text_units_executed': len(tested), 'tested_ids': tested,
                                     'dynamic_control_units_skipped': len(skipped),
                                     'synthetic_boundary_fixtures': fixtures}
    if build_dir:
        from survey import Disc
        disc = Disc(build_dir/'dg-dev.iso')
        try:
            table = disc.files()
            b = lambda name: disc.read(table[name]['lba'], table[name]['size'])
            data, exe = b('SCN/DG.SCN'), b('SLPS_017.97')
            consumer = Consumer(exe)
            parsed = verified_texts(decode(data))
            tested = []
            manifest = json.loads((build_dir/'edits.json').read_text())
            for edit in manifest['edits']:
                t = parsed[edit['id']]
                if any(tok['kind']=='control' and int(tok['raw'][:2],16) not in SIMPLE_CONTROLS for tok in t['tokens']):
                    raise ValueError('Build fixture needs dynamic control environment')
                consumer.run(data[t['payload']:t['end']])
                tested.append(t['id'])
            report['build'] = {'disc_sha256': sha(disc.raw), 'edited_ids_executed': tested}
        finally:
            disc.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, report)
    return {label: {k:v for k,v in r.items() if k != 'tested_ids'} for label,r in report['sources'].items()}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT/'work/dg/cpu-verification.json')
    p.add_argument('--build', type=Path)
    args = p.parse_args()
    print(json.dumps(verify(args.output, args.build), indent=2))
