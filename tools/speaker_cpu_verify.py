#!/usr/bin/env python3
"""Verify map NPC decoding and speaker lookup against original MIPS functions.

Isolated CPU only. Entity activation is a fixture; BIOS strcpy/strlen stubbed.
No emulator/game session, image, translation, or save file is modified.
"""
import json
import struct
from unicorn.mips_const import *
from dg_analyze import read_source
from dg_script import decode
from dg_cpu_verify import Consumer
from dg_bank_verify import bios_strings
from translation_npcs import MAP_TABLE, map_npcs, script_maps
from survey import Disc, ROOT, SOURCES, sha


def verify():
    result = dict(isolated_cpu_only=True, gameplay_verified=False,
                  bios_stubbed=['strcpy', 'strlen'], entity_activation='fixture', languages={})
    for lang in ('jpn', 'kor'):
        files = read_source(lang)
        exe = files['SLPS_017.97']
        maps = sorted(set().union(*script_maps(decode(files['SCN/DG.SCN'])).values()))
        machine = Consumer(exe)
        bios_strings(machine)
        c = machine.cpu
        tested = []
        missing = []
        disc = Disc(ROOT / SOURCES[lang][0])
        try:
            table = disc.files()
            for map_id in maps:
                desc = exe[MAP_TABLE+map_id*16:MAP_TABLE+(map_id+1)*16]
                name = desc[:8].split(b'\0')[0].decode()
                path = f'MAP/MAP{map_id//15+1}/{name}.MAP'
                if path not in table:
                    missing.append(dict(map_id=map_id, file=path))
                    continue
                entry = table[path]
                raw = disc.read(entry['lba'], entry['size'])
                records = map_npcs(raw, desc)
                if not records:
                    continue
                start = records[0]['logical_offset']-2
                payload = raw[start:records[-1]['end']]
                c.mem_write(0x40000, payload)
                c.mem_write(0x145608, bytes(196*8))
                c.mem_write(0x16b104, bytes(104*8))
                def run(pc, a0, a1):
                    for reg, val in [(UC_MIPS_REG_A0,a0),(UC_MIPS_REG_A1,a1),
                                     (UC_MIPS_REG_GP,machine.gp),(UC_MIPS_REG_SP,0x801f0000),
                                     (UC_MIPS_REG_RA,0x80030000)]:c.reg_write(reg,val)
                    c.emu_start(pc,0x80030000,count=100000)
                    assert c.reg_read(UC_MIPS_REG_PC)==0x80030000
                run(0x800bae54,0x80040000,map_id)
                for record in records:
                    slot = record['slot']
                    actual_type = struct.unpack('<H',c.mem_read(0x145608+slot*196,2))[0]
                    actual_actor = c.mem_read(0x16b104+slot*104+0x65,1)[0]
                    assert (actual_type,actual_actor)==(record['type_id'],record['actor_id'])
                    # Activate one slot at a time, as multiple alternative
                    # occupants can share a script actor number on one map.
                    c.mem_write(0x13cdb4,bytes(40))
                    entity = 0x8016b104+slot*104
                    c.mem_write(0x13cdb4+(slot+2)*4,struct.pack('<I',entity))
                    c.mem_write(entity&0x1fffff,struct.pack('<I',actual_type))
                    c.mem_write(0x50000,b'\xa5'*64)
                    run(0x800f4dbc,actual_actor,0x80050000)
                    length = c.reg_read(UC_MIPS_REG_V0)
                    expected_start=0xaa924+actual_type*52
                    expected=exe[expected_start:expected_start+20].split(b'\0')[0]
                    assert bytes(c.mem_read(0x50000,length+1))==expected+b'\0'
                tested.append(dict(map_id=map_id,file=path,records=len(records),sha256=sha(raw)))
        finally:disc.close()
        result['languages'][lang]=dict(maps=tested,missing_map_files=missing,
            records=sum(m['records'] for m in tested),exe_sha256=sha(exe))
    path=ROOT/'work/speakers/cpu-verification.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({lang:{'maps':len(v['maps']),'records':v['records'],'missing':v['missing_map_files']}
                      for lang,v in result['languages'].items()},ensure_ascii=False))


if __name__=='__main__':verify()
