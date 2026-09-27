#!/usr/bin/env python3
"""Exhaustive isolated MIPS font provider + original 4bpp conversion verification.
Unicorn does not emulate PS1 GPU or R3000A load delays; game proof is separate.
"""
import argparse
import json
from pathlib import Path
import struct
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE, __version__
from unicorn.mips_const import *
from font_expand import START, SCRATCH_OFFSET
from survey import Disc, ROOT, sha, write_json


def verify(build_dir):
    disc=Disc(build_dir/'dg-dev.iso')
    try:
        ef=disc.files()['SLPS_017.97']; exe=disc.read(ef['lba'],ef['size']); digest=sha(disc.raw)
    finally: disc.close()
    oracle=json.loads((build_dir/'font/glyph-oracle.json').read_text())
    c=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN)
    c.mem_map(0,0x200000);c.mem_write(0x90800,exe[0x800:])
    c.hook_add(UC_HOOK_CODE, lambda cpu, address, size, _: cpu.emu_stop(), begin=0x800a5b24, end=0x800a5b24)
    gp,sp=0x80150000,0x801f0000
    c.mem_write((gp-0x7950)&0x1fffff,bytes([0xA0,0x0B]))
    def run(code, rows):
        c.mem_write((gp-0x6ef0)&0x1fffff,bytes(4))
        c.mem_write(0x140ed0,bytes([0xCC])*1512)
        for reg,value in [(UC_MIPS_REG_GP,gp),(UC_MIPS_REG_SP,sp),(UC_MIPS_REG_A0,int.from_bytes(bytes.fromhex(code),'little')),
                          (UC_MIPS_REG_A1,24),(UC_MIPS_REG_A2,36),(UC_MIPS_REG_RA,0x80040000)]:c.reg_write(reg,value)
        c.emu_start(0x800a575c,0x80040000,count=100000)
        if c.reg_read(UC_MIPS_REG_PC)!=0x800a5b24:raise ValueError('Did not reach GPU upload: '+code+' PC='+hex(c.reg_read(UC_MIPS_REG_PC)))
        actual=bytes(c.mem_read(0x90000+START+SCRATCH_OFFSET,22))
        if actual!=struct.pack('<11H',*rows):raise ValueError('Glyph mismatch: '+code)
        target=c.reg_read(UC_MIPS_REG_A1)&0x1fffff
        pixels=bytes(c.mem_read(target,66))
        expected=bytes((0 if r&(1<<(15-x)) else 0xA0)|(0 if r&(1<<(14-x)) else 0x0B)
                       for r in rows for x in range(0,12,2))
        if pixels!=expected:raise ValueError('4bpp mismatch: '+code)
        rect=c.reg_read(UC_MIPS_REG_A0)&0x1fffff
        if bytes(c.mem_read(rect,8))!=struct.pack('<4H',0x2c0+6,0x100+36,3,11):raise ValueError('Upload rectangle mismatch')
    for code,rows in zip(oracle['codes'],oracle['rows']):run(code,rows)
    missing=['F03F','F07F','F0FD','F0FF','F7FC','F840','FEFE']
    for code in missing:run(code,oracle['rows'][991])
    # Original GPU function is outside this isolated check; skip call and finish
    # original epilogue to verify frame/callee-saved restoration.
    c.emu_start(0x800a5b2c,0x80040000,count=100)
    if c.reg_read(UC_MIPS_REG_SP)!=sp:raise ValueError('Stack restoration mismatch')
    report={'disc_sha256':digest,'exe_sha256':sha(exe),'unicorn_version':__version__,
            'glyphs_executed':len(oracle['rows']),'all_22_byte_glyphs_match':True,
            'all_66_byte_4bpp_uploads_match':True,'invalid_code_fallbacks':missing,
            'stack_restored':True,'ps1_gameplay_verified':False,'load_delay_timing_verified':False}
    write_json(build_dir/'font/cpu-verification.json',report)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('build',type=Path)
    print(json.dumps(verify(p.parse_args().build),indent=2))
