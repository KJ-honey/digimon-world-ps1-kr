#!/usr/bin/env python3
"""Execute installed script selection against original-extent DG and MAPHEAD.

CD transfers are stubs. This proves selection, offsets, loaded bytes and the
existing one-script cache, not seek timing or visible gameplay.
"""
import argparse
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *
from dg_analyze import read_source
from dg_script import decode
from survey import Disc, sha, write_json


def verify(build):
    report=json.loads((build/'build.json').read_text())
    if not report.get('disk_layout'):
        raise ValueError('This check requires the original-extent layout')
    original=read_source('kor')
    parsed=decode(original['SCN/DG.SCN'])
    with_disc=Disc(build/'dg-expanded.iso')
    try:
        assert sha(with_disc.raw)==report['output_sha256']
        files=with_disc.files()
        read=lambda name: with_disc.read(files[name]['lba'],files[name]['size'])
        exe,dg,mirror=[read(name) for name in ('SLPS_017.97','SCN/DG.SCN','SCN/MAPHEAD.SCN')]
    finally:
        with_disc.close()
    assert exe[0x60010:0x60104]==original['SLPS_017.97'][0x60010:0x60104]
    assert exe[0x60988:0x60a4c]==original['SLPS_017.97'][0x60988:0x60a4c]
    assert dg[:0x800]==original['SCN/DG.SCN'][:0x800]
    c=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN)
    c.mem_map(0,0x200000)
    c.mem_write(0x90800,exe[0x800:])
    gp=0x80150000
    def word(addr,n):c.mem_write(addr&0x1fffff,struct.pack('<I',n))
    # The same buffers initialized by the source game's 800F0010 routine.
    for offset,value in [(-0x6cf8,0x80159784),(-0x6cf4,0x8015f784),(-0x6cf0,0x80161784)]:
        word(gp+offset,value)
    c.mem_write((gp-0x6cd4)&0x1fffff,b'\xff\xff')
    c.mem_write(0x159784,mirror)
    c.mem_write(0x15f784,dg[:0x2000])
    directory=bytes(c.mem_read(0x15f784,0x2000))
    reads=[]
    def cd(cpu,pc,size,_):
        if pc!=0x800ec21c:return
        path,dest,at,count=[cpu.reg_read(r) for r in
                          (UC_MIPS_REG_A0,UC_MIPS_REG_A1,UC_MIPS_REG_A2,UC_MIPS_REG_A3)]
        assert path==0x80136bac and dest==0x80161784
        assert at%2048==0 and count%2048==0 and 0<count<=8192
        assert at>=parsed['scripts'][1]['base']
        cpu.mem_write(dest&0x1fffff,dg[at:at+count])
        reads.append(dict(file_offset=at,size=count,iso_lba=files['SCN/DG.SCN']['lba']+at//2048))
        cpu.reg_write(UC_MIPS_REG_PC,cpu.reg_read(UC_MIPS_REG_RA))
    c.hook_add(UC_HOOK_CODE,cd)
    tested=[]
    # Include repeated hits, script-0 interleaving, cross-script calls and returns.
    sequence=[0]+list(range(1,len(parsed['scripts'])))+[149,178,149,150,178,150,104,0,104]
    cached=65535
    for sid in sequence:
        for repeat in range(2):
            before=len(reads)
            c.mem_write(0x163784,b'\xa5'*32)
            preserved={r:0x12340000+r for r in (UC_MIPS_REG_S0,UC_MIPS_REG_S1,UC_MIPS_REG_S2)}
            for r,v in {UC_MIPS_REG_GP:gp,UC_MIPS_REG_SP:0x801f0000,
                        UC_MIPS_REG_RA:0x80040000,UC_MIPS_REG_A0:sid,**preserved}.items():c.reg_write(r,v)
            c.emu_start(0x800f0988,0x80040000,count=10000)
            assert c.reg_read(UC_MIPS_REG_PC)==0x80040000
            assert c.reg_read(UC_MIPS_REG_SP)==0x801f0000
            assert all(c.reg_read(r)==v for r,v in preserved.items())
            assert c.reg_read(UC_MIPS_REG_V0)==(0x80159784 if sid==0 else 0x80161784)
            expected_reads=int(sid!=0 and sid!=cached)
            assert len(reads)-before==expected_reads
            if sid:
                s=parsed['scripts'][sid]
                assert bytes(c.mem_read(0x161784,s['limit']-s['base']))==dg[s['base']:s['limit']]
                cached=sid
            else:
                assert bytes(c.mem_read(0x159784,len(mirror)))==mirror
            assert struct.unpack('<H',c.mem_read((gp-0x6cd4)&0x1fffff,2))[0]==cached
            assert bytes(c.mem_read(0x15f784,0x2000))==directory
            assert bytes(c.mem_read(0x163784,32))==b'\xa5'*32
            tested.append(dict(script=sid,repeat=repeat,cd_reads=expected_reads))
    result=dict(disc_sha256=report['output_sha256'],script_count=len(parsed['scripts']),
        loader_cases=len(tested),reads=reads,cases=tested,original_loader_unchanged=True,
        maphead_script_zero_preserved=True,directory_and_vm_guard_preserved=True,
        cache_hit_reads=0,cd_stubbed=True,gameplay_runtime_verified=False)
    write_json(build/'bank/loader-verification.json',result)
    return {k:v for k,v in result.items() if k not in ('reads','cases')}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('build',type=Path)
    print(json.dumps(verify(p.parse_args().build),indent=2))
