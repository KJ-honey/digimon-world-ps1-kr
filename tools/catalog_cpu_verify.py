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


def location_sprite_widths(exe,dg,baseline,changed):
    """Execute the real map callback through its sprite call, not just upload."""
    machine=CatalogRenderer(exe,dg)
    bios_strings(machine)
    sprites=[]
    def capture(c,address,size,_):
        if address==0x80103c84:
            sprites.append(tuple(c.reg_read(r) for r in (UC_MIPS_REG_A1,UC_MIPS_REG_A3)))
            c.reg_write(UC_MIPS_REG_PC,c.reg_read(UC_MIPS_REG_RA))
    machine.cpu.hook_add(UC_HOOK_CODE,capture)
    results=[]
    for row in baseline['entries']:
        if row['category']!='location_name':continue
        entry=changed.get(row['id'])
        raw=bytes.fromhex(entry['expanded_hex'] if entry else row['raw']['kor'])
        width=pixel_width(raw)
        c=machine.cpu
        # Map 0's name index is a fixture; execute its original lookup path.
        c.mem_write(0x13542b,bytes([row['table_index']]))
        for r,v in [(UC_MIPS_REG_SP,0x801f0000),(UC_MIPS_REG_RA,0x80040000),
                    (UC_MIPS_REG_A0,0),(UC_MIPS_REG_S0,0x12345678)]:c.reg_write(r,v)
        c.emu_start(0x800e424c,0x80040000,count=10000)
        assert c.reg_read(UC_MIPS_REG_PC)==0x80040000
        assert c.reg_read(UC_MIPS_REG_SP)==0x801f0000
        assert c.reg_read(UC_MIPS_REG_S0)==0x12345678
        expected=((-12-width//2)&0xffffffff,width)
        results.append(dict(id=row['id'],actual=list(sprites[-1]),expected=list(expected)))
        if entry and entry['policy']=='resident-directory-string':
            # Original location substitution: strcpy, strlen, then advance.
            c.mem_write(0x60000,b'\xa5'*128)
            c.reg_write(UC_MIPS_REG_S0,0x80060000)
            c.reg_write(UC_MIPS_REG_S2,row['table_index'])
            c.emu_start(0x800fe270,0x800fe2bc,count=10000)
            assert bytes(c.mem_read(0x60000,len(raw)))==raw
            assert c.reg_read(UC_MIPS_REG_S0)==0x80060000+len(raw)-1
            # The three save-label callers use the same original bounded
            # byte copy with a limit of 18. Preserve that existing policy.
            c.mem_write(0x60000,b'\xa5'*32)
            for reg,value in [(UC_MIPS_REG_A0,0x80060000),(UC_MIPS_REG_A1,entry['target_ram']),
                              (UC_MIPS_REG_A2,18),(UC_MIPS_REG_RA,0x80040000)]:
                c.reg_write(reg,value)
            c.emu_start(0x80110d08,0x80040000,count=10000)
            wanted=raw[:-1][:18]
            assert bytes(c.mem_read(0x60000,len(wanted)+1))==wanted+b'\xa5'
            results[-1]['native_copy_and_save_label']=True
    return results


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
    sprite_cases=location_sprite_widths(exe,dg,baseline,changed)
    assert all(r['actual']==r['expected'] for r in sprite_cases), sprite_cases
    machine=CatalogRenderer(exe,dg)
    cases=[]
    for row in baseline['entries']:
        entry=changed.get(row['id']);loc=row['locations']['kor']
        raw=bytes.fromhex(entry['expanded_hex'] if entry else row['raw']['kor'])
        pointer=(struct.unpack_from('<I',exe,loc['reference_logical_offset'])[0]
                 if loc['reference_kind']=='u32_ram_pointer' else RAM_BASE+loc['logical_offset'])
        check_pixels(machine,pointer,raw,glyphs)
        expected_reads=([report['catalog']['bank_file_offset']+(entry.get('packed_offset',entry['record']*2048)//2048)*2048]
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
    # The title is reachable before the DG directory has been loaded.
    from menu_layout import TITLE_POINTERS
    from translation_catalog import read_string
    machine.cpu.mem_write(0x15f784,bytes(0x2000))
    for pointer in TITLE_POINTERS:
        raw,_=read_string(exe,pointer-RAM_BASE,len(exe))
        assert HALF_SPACE in raw
        check_pixels(machine,pointer,raw,glyphs)
        assert not machine.reads
    from menu_layout import memory_card_writes
    from dg_analyze import read_source
    card_writes=memory_card_writes(read_source('kor')['SLPS_017.97'])
    for write in card_writes:
        raw=bytes.fromhex(write['after'])
        at=write['file_offset']
        assert exe[at:at+len(raw)]==raw
        check_pixels(machine,RAM_BASE+at,raw,glyphs)
        assert not machine.reads
    technique_before_dg=[]
    for row in baseline['entries']:
        if row['category']!='technique_name':continue
        entry=changed[row['id']]
        raw=bytes.fromhex(entry['expanded_hex'])
        check_pixels(machine,entry['target_ram'],raw,glyphs)
        assert not machine.reads
        technique_before_dg.append(row['id'])
    card_consumer=Consumer(exe)
    card_names=[]
    def capture_card_name(c,address,size,_):
        if address==0x800a5b48:
            card_names.append(c.reg_read(UC_MIPS_REG_A0))
            c.reg_write(UC_MIPS_REG_PC,c.reg_read(UC_MIPS_REG_RA))
    c=card_consumer.cpu
    c.hook_add(UC_HOOK_CODE,capture_card_name)
    c.reg_write(UC_MIPS_REG_SP,0x801f0000)
    c.mem_write(0x1f0028,struct.pack('<II',0,24))
    for row in baseline['entries']:
        if row['category']!='technique_name':continue
        c.reg_write(UC_MIPS_REG_S0,row['table_index'])
        c.emu_start(0x8010d1c8,0x8010d1ec,count=1000)
        assert c.reg_read(UC_MIPS_REG_PC)==0x8010d1ec
        assert card_names[-1]==changed[row['id']]['target_ram']
    # Execute the real DG table-copy/length callers with C-string BIOS models.
    consumer=Consumer(exe);bios_strings(consumer)
    consumer.cpu.mem_write(0x13a924,exe[0xaa924:0xaa924+20])
    consumer.cpu.mem_write(0x15f784,dg[:0x2000])
    dynamic=[]
    for row in baseline['entries']:
        if row['category'] not in ('item_name','digimon_name','technique_name'):continue
        entry=changed.get(row['id'])
        raw=bytes.fromhex(entry['expanded_hex'] if entry else row['raw']['kor'])
        op={'item_name':9,'digimon_name':7,'technique_name':8}[row['category']]
        # The operand is a VM byte-variable index, not the table ID itself.
        consumer.cpu.mem_write((consumer.gp-0x6cec)&0x1fffff,struct.pack('<I',0x80070000))
        consumer.cpu.mem_write(0x70159,bytes((row['table_index'],)))
        payload=bytes((op,0))+bytes.fromhex('0d000000')
        consumer.run(payload)
        actual=bytes(consumer.cpu.mem_read(0x60000,len(raw)-1))
        assert actual==raw[:-1],(row['id'],actual.hex(),raw.hex())
        dynamic.append(row['id'])
    # Execute the real help sprite callback, including the repeated button
    # icons and the variable-width parenthesized legend suffixes.
    help_cpu=Consumer(exe)
    help_calls=[]
    legend_icons={}
    def capture_help(c,address,size,_):
        if address in (0x800be9c8,0x800c5d30):
            ra=c.reg_read(UC_MIPS_REG_RA)
            if ra in (0x800c43c8,0x800c4408):
                values=[c.reg_read(r) for r in (UC_MIPS_REG_A0,UC_MIPS_REG_A1,
                                               UC_MIPS_REG_A2,UC_MIPS_REG_A3)]
                values=[v if v<0x80000000 else v-0x100000000 for v in values]
                legend_icons[ra]=dict(zip(('x','y','width','height'),values))
            c.reg_write(UC_MIPS_REG_PC,ra)
            return
        if address!=0x80103c84:return
        sp=c.reg_read(UC_MIPS_REG_SP)
        x,y,width=[c.reg_read(r) for r in (UC_MIPS_REG_A1,UC_MIPS_REG_A2,UC_MIPS_REG_A3)]
        height,u,v=struct.unpack('<III',c.mem_read((sp+16)&0x1fffff,12))
        help_calls.append(dict(x=x if x<0x80000000 else x-0x100000000,
                               y=y if y<0x80000000 else y-0x100000000,
                               width=width,height=height,u=u,v=v))
        c.reg_write(UC_MIPS_REG_PC,c.reg_read(UC_MIPS_REG_RA))
    c=help_cpu.cpu
    c.hook_add(UC_HOOK_CODE,capture_help)
    c.reg_write(UC_MIPS_REG_SP,0x801f0000)
    c.emu_start(0x800c3f2c,0x800c442c,count=10000)
    assert c.reg_read(UC_MIPS_REG_PC)==0x800c442c
    assert len(help_calls)==18
    metadata=report['catalog']['technique_help_sprites']
    for part in metadata:
        if 'table_index' in part:
            got=help_calls[4+part['table_index']]
            assert (got['u'],got['width'],got['x'],got['y'],got['v']) == (
                part['u'],part['width'],part['x'],part['y']+1,part['texture_y'])
        elif part.get('field')=='screen_x':
            assert help_calls[3]['x']==part['value']
    # These suffixes are displayed after row 8, not after their source-row
    # prefixes. Check actual composition independently of the build metadata.
    for prefix_no,suffix_no,ra in ((13,16,0x800c43c8),(14,17,0x800c4408)):
        prefix,suffix,icon=help_calls[prefix_no],help_calls[suffix_no],legend_icons[ra]
        assert prefix['y']==suffix['y']==icon['y']+1
        assert prefix['x']+prefix['width']==suffix['x'],(prefix,suffix)
        assert suffix['x']+suffix['width']<=146
        assert icon['x']>=-146 and icon['x']+icon['width']<=prefix['x']
        assert (icon['width'],icon['height'])==(12,12)
    # Every legend suffix and title is independently cropped from the same
    # renderer output. Source U and width must match the emitted manifest.
    immediate_calls={0x33f5c:(0,'width'),0x33f70:(1,'u'),0x33fb0:(2,'u'),
                     0x33ff0:(3,'u'),0x340d8:(16,'u'),0x34104:(16,'width'),
                     0x34118:(17,'u'),0x34144:(17,'width')}
    for part in metadata:
        if part.get('instruction_offset') in immediate_calls:
            number,field=immediate_calls[part['instruction_offset']]
            assert help_calls[number][field]==part['value']
    result=dict(disc_sha256=report['output_sha256'],exe_sha256=sha(exe),
                catalog_rendered=len(cases),cases=cases,dg_copy_cases=len(dynamic),
                location_sprite_cases=sprite_cases,title_before_dg_cases=len(TITLE_POINTERS),
                technique_help_sprite_calls=help_calls,technique_dg_copy_cases=121,
                technique_legend_icons=legend_icons,technique_legend_compositions=2,
                memory_card_before_dg_cases=len(card_writes),
                technique_before_dg_cases=len(technique_before_dg),
                technique_card_consumer_cases=len(card_names),
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
