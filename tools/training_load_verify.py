#!/usr/bin/env python3
"""Execute training dispatch, RAM lookup, queue insertion and queue ticks.

BIOS strings and low-level CD operations are stubs: this proves request/state
equivalence and removal of CdSearchFile calls, not frame-time improvement.
"""
import argparse
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *
from survey import Disc, sha, write_json
from training_load import HOOK, jal

GP=0x80150000
QUEUE=0x80167BE0
STOP=0x80040000
STATUS=GP-0x6D57


def loc(lba):
    minutes,rem=divmod(lba+150,4500)
    seconds,frames=divmod(rem,75)
    return bytes((n//10*16+n%10 for n in (minutes,seconds,frames)))+b'\0'


class Machine:
    def __init__(self,exe,dg,files):
        self.cpu=c=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN)
        c.mem_map(0,0x200000)
        c.mem_write(0x90800,exe[0x800:])
        c.mem_write(0x15F784,dg[:0x2000])
        self.files=files
        self.calls=[]
        self.sync=[]
        self.control=[]
        self.read=[]
        self.instructions=0
        self.put(GP-0x7648,b';1\0')
        c.hook_add(UC_HOOK_CODE,self.hook)

    def put(self,p,raw):self.cpu.mem_write(p&0x1FFFFF,raw)
    def get(self,p,n):return bytes(self.cpu.mem_read(p&0x1FFFFF,n))
    def word(self,p,n):self.put(p,struct.pack('<I',n&0xFFFFFFFF))
    def number(self,p):return struct.unpack('<I',self.get(p,4))[0]
    def string(self,p):return self.get(p,256).split(b'\0',1)[0]

    def hook(self,c,pc,size,_):
        self.instructions+=1
        args=[c.reg_read(r) for r in (UC_MIPS_REG_A0,UC_MIPS_REG_A1,UC_MIPS_REG_A2)]
        a,b,d=args
        if pc==0xA0:
            service=c.reg_read(UC_MIPS_REG_T1)
            if service==0x1F:  # strrchr
                at=self.string(a).rfind(bytes((b,)))
                result=0 if at<0 else a+at
            elif service==0x17:  # strcmp
                x,y=self.string(a),self.string(b)
                result=(x>y)-(x<y)
            elif service in (0x15,0x19):  # strcat, strcpy
                offset=len(self.string(a)) if service==0x15 else 0
                self.put(a+offset,self.string(b)+b'\0')
                result=a
            else:raise AssertionError(f'Unexpected BIOS service {service:x}')
        elif pc==0x800B6964:
            name=self.string(b).decode().strip('\\').split(';')[0]
            f=self.files[name]
            self.put(a,loc(f['lba'])+struct.pack('<I',f['size']))
            self.calls.append(('search',name))
            result=a
        elif pc==0x800B45B4:
            assert a==2 and d==0
            self.calls.append(('setloc',self.get(b,3).hex()))
            result=self.control.pop(0) if self.control else 1
        elif pc==0x800B7170:
            self.calls.append(('read',a,b,d))
            result=self.read.pop(0) if self.read else 1
        elif pc==0x800B7270:
            assert a==1 and b==0  # Polling must remain nonblocking.
            result=self.sync.pop(0) if self.sync else 0
            self.calls.append(('poll',result))
        else:return
        c.reg_write(UC_MIPS_REG_V0,result&0xFFFFFFFF)
        c.reg_write(UC_MIPS_REG_PC,c.reg_read(UC_MIPS_REG_RA))

    def run(self,start,stop=STOP):
        c=self.cpu
        preserved={r:0x12340000+r for r in (UC_MIPS_REG_S0,UC_MIPS_REG_S1,
                  UC_MIPS_REG_S2,UC_MIPS_REG_S3,UC_MIPS_REG_S4,UC_MIPS_REG_S5,
                  UC_MIPS_REG_S6,UC_MIPS_REG_S7,UC_MIPS_REG_FP)}
        for r,v in {UC_MIPS_REG_GP:GP,UC_MIPS_REG_SP:0x801F0000,
                    UC_MIPS_REG_RA:STOP,**preserved}.items():c.reg_write(r,v)
        c.emu_start(start,stop,count=500000)
        assert c.reg_read(UC_MIPS_REG_PC)==stop
        assert c.reg_read(UC_MIPS_REG_SP)==0x801F0000
        assert c.reg_read(UC_MIPS_REG_GP)==GP
        assert all(c.reg_read(r)==v for r,v in preserved.items())

    def reset(self):
        self.put(QUEUE,bytes(32*0x44))
        for i in range(32):self.put(QUEUE+i*0x44+0x1C,b'\xff')
        self.word(GP-0x6C18,0)
        self.word(GP-0x6C14,0)
        self.put(STATUS,b'\x7a')
        self.word(GP-0x6E98,0x55555555)
        self.calls=[]

    def command(self,map_id):
        self.put(GP-0x6CA6,struct.pack('<H',map_id))
        self.run(0x800EE458,0x800EE464)  # Execute the installed call and return.
        assert self.number(GP-0x6E98)==0

    def tick(self):self.run(0x801008C0)


def verify(build):
    report=json.loads((build/'build.json').read_text())
    assert report['training_load']
    disc=Disc(build/'dg-expanded.iso')
    try:
        assert sha(disc.raw)==report['output_sha256']
        files=disc.files()
        read=lambda n:disc.read(files[n]['lba'],files[n]['size'])
        exe,dg=read('SLPS_017.97'),read('SCN/DG.SCN')
    finally:disc.close()
    oracle=bytearray(exe)
    oracle[HOOK:HOOK+4]=jal(0x800E43C4)
    old,new=Machine(bytes(oracle),dg,files),Machine(exe,dg,files)
    guard=new.get(0x15F784,0x4000)
    cases=[]
    selected={0x70:10,0x4E:10,0x77:10,0x6B:13,0x6C:13,0xA5:13,0x63:13}
    for map_id in range(256):
        for m in (old,new):m.reset();m.command(map_id)
        assert old.get(QUEUE,0x3A)==new.get(QUEUE,0x3A)
        assert old.get(STATUS,1)==new.get(STATUS,1)
        if map_id not in selected:
            assert new.number(GP-0x6C18)==0
            continue
        assert new.get(STATUS,1)==b'\1'
        name='TRN_REL.BIN' if selected[map_id]==10 else 'TRN2_REL.BIN'
        f=files[name]
        assert new.number(QUEUE+0x40)==f['size']
        assert new.get(QUEUE+0x3A,4)==loc(f['lba'])
        assert old.number(QUEUE+0x40)==0xFFFFFFFF
        for m in (old,new):
            m.control=[0,1]  # Preserve busy Setloc and failed Read retry.
            m.read=[0,1]
            m.tick()
            assert m.get(QUEUE+0x1C,1)==b'\1'
            assert m.get(STATUS,1)==b'\1'
            m.sync=[2,-1]  # Busy poll, then read error and retry.
            m.tick();m.tick()
            assert m.get(QUEUE+0x1C,1)==b'\2'
            m.tick();m.tick()
            assert m.get(STATUS,1)==b'\0'
            m.tick()
            assert m.number(GP-0x6C18)==m.number(GP-0x6C14)==0
        assert [x for x in old.calls if x[0]!='search']==new.calls
        assert [x for x in old.calls if x[0]=='search']==[('search',name)]
        assert new.get(QUEUE,0x3D)==old.get(QUEUE,0x3D)
        cases.append(dict(map_id=map_id,file=name,old_searches=1,new_searches=0,
                          sector_count=(f['size']+2047)//2048,retry_and_status_equal=True))
    # Missing cached name preserves the original slow path, never drops a load.
    for offset,map_id in ((0x98428,0x70),(0x98434,0x6B)):
        pointer=struct.unpack_from('<I',exe,offset+8)[0]
        new.word(0x80090000+offset+8,0x80050000)
        new.put(0x80050000,b'MISSING.BIN\0')
        new.reset();new.command(map_id)
        assert new.number(QUEUE+0x40)==0xFFFFFFFF
        new.tick();new.tick();new.tick()
        assert sum(x[0]=='search' for x in new.calls)==1
        assert new.get(STATUS,1)==b'\0'
        new.word(0x80090000+offset+8,pointer)
    # Two queued requests must retain their links and drain in the same order.
    for m in (old,new):
        m.reset();m.command(0x70);m.command(0x6B)
        assert m.number(QUEUE)==QUEUE+0x44
        for _ in range(5):m.tick()
        assert m.number(GP-0x6C18)==0
    assert [x for x in old.calls if x[0]!='search']==new.calls
    assert new.get(0x15F784,0x4000)==guard
    result=dict(disc_sha256=report['output_sha256'],map_selection_cases=256,
                selected_cases=cases,missing_table_fallback_cases=2,
                queue_order_preserved=True,abi_and_resident_guard_preserved=True,
                cd_and_bios_stubbed=True,gameplay_runtime_verified=False)
    write_json(build/'bank/training-load-verification.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('build',type=Path)
    print(json.dumps(verify(p.parse_args().build),indent=2))
