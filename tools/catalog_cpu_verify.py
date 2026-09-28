#!/usr/bin/env python3
"""Execute catalog pointers, NUL rendering and DG name copies in installed code.

CD, GPU, DrawSync and BIOS calls are modelled. This is CPU/pixel evidence,
not actual game/streaming/window-size verification.
"""
import argparse
import json
import struct
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn.mips_const import *
from catalog_insert import HALF_SPACE, RAM_BASE, pixel_width
from dg_pixel_verify import PixelRenderer
from dg_cpu_verify import Consumer
from dg_bank_verify import bios_strings
from survey import Disc, ROOT, sha, write_json


class CatalogRenderer(PixelRenderer):
    def __init__(self,exe,dg):
        super().__init__(exe)
        self.dg=dg
        self.cpu.mem_write(0x15f784,dg[:0x2000])
        self.reads=[]
        self.cpu.hook_add(UC_HOOK_CODE,self.cd)

    def cd(self,c,address,size,_):
        if address!=0x800ec21c:return
        path,dest,offset,count=[c.reg_read(r) for r in
            (UC_MIPS_REG_A0,UC_MIPS_REG_A1,UC_MIPS_REG_A2,UC_MIPS_REG_A3)]
        assert path==0x80136bac and offset%2048==0 and count==2048
        assert 0x801ee000<=dest<0x801f0000 and dest%4==0
        raw=self.dg[offset:offset+count]
        assert len(raw)==count
        c.mem_write(dest&0x1fffff,raw)
        self.reads.append(offset)
        c.reg_write(UC_MIPS_REG_PC,c.reg_read(UC_MIPS_REG_RA))

    def render(self,pointer,x=0,y=24):
        c=self.cpu;self.uploads=[];self.syncs=0;self.reads=[]
        gp,sp=0x80150000,0x801f0000
        c.mem_write((gp-0x7950)&0x1fffff,b'\x07\x70')
        c.mem_write((gp-0x6ef0)&0x1fffff,bytes(4))
        for at in (0x1ee000,0x1f0040):c.mem_write(at,b'\xa5'*64)
        regs=[UC_MIPS_REG_S0,UC_MIPS_REG_S1,UC_MIPS_REG_S2,UC_MIPS_REG_S3,
              UC_MIPS_REG_S4,UC_MIPS_REG_S5,UC_MIPS_REG_S6,UC_MIPS_REG_S7,UC_MIPS_REG_FP]
        for r in regs:c.reg_write(r,0x12345678+r)
        for r,v in [(UC_MIPS_REG_GP,gp),(UC_MIPS_REG_SP,sp),(UC_MIPS_REG_RA,0x80040000),
                    (UC_MIPS_REG_A0,pointer),(UC_MIPS_REG_A1,x),(UC_MIPS_REG_A2,y)]:c.reg_write(r,v)
        c.emu_start(0x800a5b48,0x80040000,count=1000000)
        assert c.reg_read(UC_MIPS_REG_PC)==0x80040000
        assert c.reg_read(UC_MIPS_REG_SP)==sp and c.reg_read(UC_MIPS_REG_GP)==gp
        assert c.reg_read(UC_MIPS_REG_V0)==0
        assert all(c.reg_read(r)==0x12345678+r for r in regs)
        for at in (0x1ee000,0x1f0040):assert bytes(c.mem_read(at,64))==b'\xa5'*64
        return self.uploads


def check_pixels(machine,pointer,raw,glyphs,x=0):
    expected=[[0]*256 for _ in range(12)]
    cursor=x
    for at in range(0,len(raw)-1,2):
        unit=raw[at:at+2]
        if unit==HALF_SPACE:cursor+=6;continue
        if unit!=b'\x81\x40' and cursor<244:
            # Original 9860 has no supplied glyph. Verify its existing fallback
            # behavior explicitly; this is not new-character support.
            for y,row in enumerate(glyphs.get(unit.hex(),glyphs['0000'])):
                for dx in range(12):expected[y][cursor+dx]=0 if row&(1<<(15-dx)) else 7
        cursor+=12
    actual=[[0]*256 for _ in range(12)]
    for rect,pixels in machine.render(pointer,x):
        origin=(rect[0]-0x2c0)*4;width=rect[2]*4
        assert rect[1]==280 and 0<=origin<=256-width and rect[3] in (11,12)
        for y in range(rect[3]):
            for dx in range(width):actual[y][origin+dx]=(pixels[y*(width//2)+dx//2]>>(4*(dx%2)))&15
    assert actual==expected,('pixel mismatch',hex(pointer),raw.hex(),x)


def verify(build):
    report=json.loads((build/'build.json').read_text())
    disc=Disc(build/'dg-expanded.iso')
    try:
        assert sha(disc.raw)==report['output_sha256']
        files=disc.files()
        read=lambda name:disc.read(files[name]['lba'],files[name]['size'])
        exe,dg=read('SLPS_017.97'),read('SCN/DG.SCN')
    finally:disc.close()
    oracle=json.loads((build/'font/glyph-oracle.json').read_text())
    glyphs=dict(zip((s.lower() for s in oracle['codes']),oracle['rows']))
    baseline=json.loads((ROOT/'work/translation/catalog/baseline.json').read_text())
    changed={e['id']:e for e in report['catalog']['entries']}
    machine=CatalogRenderer(exe,dg)
    cases=[]
    for row in baseline['entries']:
        entry=changed.get(row['id']);loc=row['locations']['kor']
        raw=bytes.fromhex(entry['expanded_hex'] if entry else row['raw']['kor'])
        pointer=(struct.unpack_from('<I',exe,loc['reference_logical_offset'])[0]
                 if loc['reference_kind']=='u32_ram_pointer' else RAM_BASE+loc['logical_offset'])
        check_pixels(machine,pointer,raw,glyphs)
        expected_reads=([report['catalog']['bank_file_offset']+entry['record']*2048]
                        if entry and entry['policy']=='independent-CD-record' else [])
        assert machine.reads==expected_reads
        cases.append(dict(id=row['id'],pointer=pointer,bytes=len(raw),pixels=pixel_width(raw)))
    # Exact half-space, full-space, consecutive, leading/trailing and maximum
    # rows; odd source pointers exercise the previous unaligned-load failure.
    fixtures=['0f01814181410f018141','81410f010f01814181408141','81410f01',
              '0f01'*42,'8141'*21,'0f01'*2+'8141'*20,'']
    for raw_hex in fixtures:
        raw=bytes.fromhex(raw_hex)+b'\0'
        machine.cpu.mem_write(0x50001,raw)
        check_pixels(machine,0x80050001,raw,glyphs)
    for x in (4,12,120,128):
        raw=bytes.fromhex('81410f0181410f01814100')
        machine.cpu.mem_write(0x50001,raw)
        check_pixels(machine,0x80050001,raw,glyphs,x)
    # Execute the real DG table-copy/length callers with C-string BIOS models.
    consumer=Consumer(exe);bios_strings(consumer)
    consumer.cpu.mem_write(0x13a924,exe[0xaa924:0xaa924+20])
    consumer.cpu.mem_write(0x15f784,dg[:0x2000])
    dynamic=[]
    for row in baseline['entries']:
        if row['category'] not in ('item_name','digimon_name'):continue
        entry=changed.get(row['id'])
        raw=bytes.fromhex(entry['expanded_hex'] if entry else row['raw']['kor'])
        op=9 if row['category']=='item_name' else 7
        # The operand is a VM byte-variable index, not the table ID itself.
        consumer.cpu.mem_write((consumer.gp-0x6cec)&0x1fffff,struct.pack('<I',0x80070000))
        consumer.cpu.mem_write(0x70159,bytes((row['table_index'],)))
        payload=bytes((op,0))+bytes.fromhex('0d000000')
        consumer.run(payload)
        actual=bytes(consumer.cpu.mem_read(0x60000,len(raw)-1))
        assert actual==raw[:-1],(row['id'],actual.hex(),raw.hex())
        dynamic.append(row['id'])
    result=dict(disc_sha256=report['output_sha256'],exe_sha256=sha(exe),
                catalog_rendered=len(cases),cases=cases,dg_copy_cases=len(dynamic),
                fixtures=len(fixtures)+4,all_pixels_match=True,abi_and_canaries=True,
                existing_unsupplied_glyphs=sorted({bytes.fromhex(r['raw']['kor'])[i:i+2].hex()
                    for r in baseline['entries'] for i in range(0,len(bytes.fromhex(r['raw']['kor']))-1,2)
                    if bytes.fromhex(r['raw']['kor'])[i:i+2].hex() not in glyphs
                    and bytes.fromhex(r['raw']['kor'])[i:i+2]!=b'\x81\x40'}),
                cd_gpu_bios_stubbed=True,gameplay_runtime_verified=False)
    write_json(build/'catalog/cpu-verification.json',result)
    return {k:v for k,v in result.items() if k!='cases'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('build',type=Path)
    print(json.dumps(verify(p.parse_args().build),indent=2))
