#!/usr/bin/env python3
"""Execute native DG renderer; record glyph origins and cleared rectangles.

GPU/font calls are stubbed here. Real PS1 framebuffer evidence is separate.
"""
import argparse
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *
from dg_analyze import read_source
from dg_cpu_verify import Consumer
from survey import ROOT, sha, write_json


class RowRenderer:
    def __init__(self, exe):
        self.cpu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN)
        self.cpu.mem_map(0, 0x200000)
        self.cpu.mem_write(0x90800, exe[0x800:])
        self.events = []
        self.cpu.hook_add(UC_HOOK_CODE, self.call)

    def call(self, cpu, address, size, _):
        if address not in (0x800a575c, 0x800a5698, 0x800a5728):
            return
        a0, a1, a2 = [cpu.reg_read(r) for r in (UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2)]
        if address == 0x800a575c:
            self.events.append(dict(kind='glyph', code=a0.to_bytes(2,'little').hex(), x=a1, y=a2))
        elif address == 0x800a5698:
            rect = struct.unpack('<4h', cpu.mem_read(a0&0x1fffff, 8))
            self.events.append(dict(kind='clear', rect=rect))
        else:
            self.events.append(dict(kind='color', value=a0))
        cpu.reg_write(UC_MIPS_REG_PC, cpu.reg_read(UC_MIPS_REG_RA))

    def run(self, raw):
        c = self.cpu
        self.events = []
        c.mem_write(0x50000, raw)
        for reg, value in [(UC_MIPS_REG_SP,0x801f0000), (UC_MIPS_REG_RA,0x80040000),
                           (UC_MIPS_REG_A0,0x80050000), (UC_MIPS_REG_A1,0), (UC_MIPS_REG_A2,24),
                           (UC_MIPS_REG_S0,0x1234), (UC_MIPS_REG_S1,0x2345), (UC_MIPS_REG_S2,0x3456)]:
            c.reg_write(reg,value)
        c.emu_start(0x800f34e4,0x80040000,count=100000)
        if c.reg_read(UC_MIPS_REG_PC)!=0x80040000:
            raise ValueError('Renderer did not return')
        for reg,value in [(UC_MIPS_REG_SP,0x801f0000),(UC_MIPS_REG_S0,0x1234),
                           (UC_MIPS_REG_S1,0x2345),(UC_MIPS_REG_S2,0x3456)]:
            if c.reg_read(reg)!=value:
                raise ValueError('Renderer ABI changed')
        return self.events


def verify(output):
    results = {}
    for lang in ('jpn','kor'):
        exe = read_source(lang)['SLPS_017.97']
        renderer, consumer = RowRenderer(exe), Consumer(exe)
        tests = [
            ('half', '81410f0081410d000000', [0,18], [6]),
            ('full', '8141814081410d000000', [0,24], [12]),
            ('two_halves', '81410f000f0081410d000000', [0,24], [6,6]),
            ('punctuation', '81418141814981410d000000', [0,12,24,36], []),
            ('mixed', '01070f00814081410f00814101010d000000', [18,36], [6,12,6]),
        ]
        evidence=[]
        for name, rawhex, xs, clears in tests:
            raw = bytes.fromhex(rawhex)
            consumer.run(raw)
            out = bytes(consumer.cpu.mem_read(0x60000,len(raw)))
            events = renderer.run(out)
            if [e['x'] for e in events if e['kind']=='glyph'] != xs:
                raise ValueError(name+' glyph origins differ')
            if [e['rect'][2] for e in events if e['kind']=='clear'] != clears:
                raise ValueError(name+' clear widths differ')
            evidence.append(dict(name=name, input=rawhex, output=out.hex(), events=events))
        results[lang] = dict(exe_sha256=sha(exe), cases=evidence)
    report = dict(native_code_unchanged=True, bytes_per_space=2, half_pixels=6, full_pixels=12,
                  consumer_ram='0x800F4200', renderer_ram='0x800F34E4',
                  gpu_and_glyph_calls_stubbed=True, ps1_gameplay_verified=False, results=results)
    write_json(output,report)
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'work/spacing/native-cpu.json')
    verify(p.parse_args().output)
