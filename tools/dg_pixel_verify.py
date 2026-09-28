#!/usr/bin/env python3
"""Execute patched DG rows and generic glyph uploads against a pixel oracle.
GPU calls are modelled; emulator screenshots verify the actual device separately.
"""
import argparse
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *
from dg_spacing_verify import RowRenderer
from dg_analyze import read_source
from survey import Disc, sha, write_json

class PixelRenderer:
    def __init__(self,exe):
        self.cpu=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN)
        self.cpu.mem_map(0,0x200000)
        self.cpu.mem_write(0x90800,exe[0x800:])
        self.cpu.hook_add(UC_HOOK_CODE,self.call)
        self.uploads=[]
        self.syncs=0
    def call(self,c,address,size,_):
        if address==0x8009486c:
            rect=struct.unpack('<4H',c.mem_read(c.reg_read(UC_MIPS_REG_A0)&0x1fffff,8))
            pixels=bytes(c.mem_read(c.reg_read(UC_MIPS_REG_A1)&0x1fffff,rect[2]*rect[3]*2))
            self.uploads.append((rect,pixels))
        elif address==0x80094774:
            self.syncs+=1
        else:return
        c.reg_write(UC_MIPS_REG_PC,c.reg_read(UC_MIPS_REG_RA))
    def run(self,raw,x=0,y=24,generic=False):
        c=self.cpu;self.uploads=[];self.syncs=0
        c.mem_write(0x50000,raw)
        gp,sp=0x80150000,0x801f0000
        c.mem_write((gp-0x7950)&0x1fffff,b'\x07\x70')
        c.mem_write((gp-0x6ef0)&0x1fffff,bytes(4))
        c.mem_write(0x1ef900,b'\xa5'*0x40)
        regs=[UC_MIPS_REG_S0,UC_MIPS_REG_S1,UC_MIPS_REG_S2,UC_MIPS_REG_S3,UC_MIPS_REG_S4,UC_MIPS_REG_S5,UC_MIPS_REG_S6,UC_MIPS_REG_S7,UC_MIPS_REG_FP]
        for r in regs:c.reg_write(r,0x12345678+r)
        for r,v in [(UC_MIPS_REG_GP,gp),(UC_MIPS_REG_SP,sp),(UC_MIPS_REG_RA,0x80040000),
                    (UC_MIPS_REG_A0,int.from_bytes(raw[:2],'little') if generic else 0x80050000),
                    (UC_MIPS_REG_A1,x),(UC_MIPS_REG_A2,y)]:c.reg_write(r,v)
        c.emu_start(0x800a575c if generic else 0x800f34e4,0x80040000,count=1000000)
        assert c.reg_read(UC_MIPS_REG_PC)==0x80040000
        assert c.reg_read(UC_MIPS_REG_SP)==sp and c.reg_read(UC_MIPS_REG_GP)==gp
        assert all(c.reg_read(r)==0x12345678+r for r in regs)
        assert bytes(c.mem_read(0x1ef900,0x40))==b'\xa5'*0x40
        return self.uploads

def verify(build):
    disc=Disc(build/'dg-expanded.iso')
    try:
        f=disc.files()['SLPS_017.97'];exe=disc.read(f['lba'],f['size']);digest=sha(disc.raw)
    finally:disc.close()
    oracle=json.loads((build/'font/glyph-oracle.json').read_text())
    glyphs=dict(zip((s.lower() for s in oracle['codes']),oracle['rows']))
    model=RowRenderer(read_source('kor')['SLPS_017.97'])
    machine=PixelRenderer(exe)
    tests=[('half','81410f008141'),('full','814181408141'),('two','81410f000f008141'),
           ('adjacent_shifted','0f00814181418141'),('trailing','0f0081410f00'),
           ('colored','01010f0081410107814181408141'),('tabs','81410c0081410e008141'),
           ('empty',''),('full_width_21','8141'*21),
           ('full_width_half_spaces','0f00'*2+'8141'*20),
           ('clipped','8141'*22),('all_half','0f00'*30)]
    checks=[]
    for name,raw in tests:
        data=bytes.fromhex(raw+'0d000000')
        for origin in (0,12,120,128):
            events=model.run(data)
            expected=[[0]*256 for _ in range(12)]
            color=7
            for e in events:
                if e['kind']=='color':color=e['value']&15
                if e['kind']!='glyph':continue
                x=e['x']+origin
                if x>=244:continue
                rows=glyphs[e['code']]
                for y,r in enumerate(rows):
                    for dx in range(12):expected[y][x+dx]=0 if r&(1<<(15-dx)) else color
            uploads=machine.run(data,x=origin)
            for rect,pixels in uploads:
                rx=(rect[0]-0x2c0)*4;w=rect[2]*4
                assert rect[1]==280 and rect[3]==12
                for y in range(12):
                    for px in range(w):
                        actual=(pixels[y*(w//2)+px//2]>>(4*(px%2)))&15
                        assert actual==expected[y][rx+px],(name,origin,y,rx+px,actual,expected[y][rx+px])
            assert machine.syncs==len(uploads)
            checks.append(dict(case=name,origin=origin,uploads=len(uploads)))
    # Every supplied glyph through both word alignments; entire glyph raster,
    # colored neighbor preservation, and non-DG upload rectangle are compared.
    for code,rows in glyphs.items():
        if code=='0000':continue
        for prefix in ('','0f00'):
            raw=bytes.fromhex(prefix+code+code+'0d000000')
            uploads=machine.run(raw)
            rect,pixels=uploads[0];w=rect[2]*4;x=6 if prefix else 0
            for y,row in enumerate(rows):
                for dx in range(24):
                    px=x+dx
                    got=(pixels[y*(w//2)+px//2]>>(4*(px%2)))&15
                    want=0 if row&(1<<(15-dx%12)) else 7
                    assert got==want,(code,prefix,y,dx)
        uploads=machine.run(bytes.fromhex(code),x=24,generic=True)
        assert uploads[0][0]==(710,280,3,11) and machine.syncs==0
        expected=bytes((0 if row&(1<<(15-x)) else 7)|(0 if row&(1<<(14-x)) else 0x70)
                       for row in rows for x in range(0,12,2))
        assert uploads[0][1]==expected,(code,'generic raster')
    report=dict(disc_sha256=digest,exe_sha256=sha(exe),cases=checks,glyphs=len(glyphs)-1,
                all_pixel_nibbles_match=True,abi_and_stack_canary=True,
                generic_upload_unchanged=True,gpu_stubbed=True)
    write_json(build/'pixel-row/cpu-verification.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('build',type=Path);verify(p.parse_args().build)
