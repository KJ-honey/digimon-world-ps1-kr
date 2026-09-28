#!/usr/bin/env python3
"""Run final installed MIPS editor code, not a host-language input simulation."""
import argparse,json,struct,time
from pathlib import Path
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS32,UC_MODE_LITTLE_ENDIAN,UC_HOOK_MEM_WRITE
from unicorn.mips_const import *
from survey import Disc,sha,write_json
from name_entry import INITIALS,MEDIALS,FINALS

VP={'ㅘ':'ㅗㅏ','ㅙ':'ㅗㅐ','ㅚ':'ㅗㅣ','ㅝ':'ㅜㅓ','ㅞ':'ㅜㅔ','ㅟ':'ㅜㅣ','ㅢ':'ㅡㅣ'}
TP={'ㄳ':'ㄱㅅ','ㄵ':'ㄴㅈ','ㄶ':'ㄴㅎ','ㄺ':'ㄹㄱ','ㄻ':'ㄹㅁ','ㄼ':'ㄹㅂ','ㄽ':'ㄹㅅ','ㄾ':'ㄹㅌ','ㄿ':'ㄹㅍ','ㅀ':'ㄹㅎ','ㅄ':'ㅂㅅ'}

def verify(build):
    report=json.loads((build/'name/name.json').read_text());sym=report['symbols']
    oracle=json.loads((build/'name/canonical.json').read_text())
    disc=Disc(build/'dg-expanded.iso')
    files=disc.files();read=lambda n:disc.read(files[n]['lba'],files[n]['size'])
    exe,shop=read('SLPS_017.97'),read('SHOP_REL.BIN');digest=sha(disc.raw);disc.close()
    c=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN);c.mem_map(0,0x200000)
    c.mem_write(0x90800,exe[0x800:]);c.mem_write(0x80800,shop)
    state=sym['edit']&0x1fffff
    allowed=[(0x1ef000,0x1f0000),(state,state+7),(0x167bcc,0x167bd9),(0x144e0c-0x6c3a,0x144e0c-0x6c3a+1),(0x144e0c-0x6caa,0x144e0c-0x6caa+2)]
    def check_write(cpu,access,address,size,value,user):
        at=address&0x1fffff
        assert any(lo<=at and at+size<=hi for lo,hi in allowed),(hex(address),size,hex(cpu.reg_read(UC_MIPS_REG_PC)))
    c.hook_add(UC_HOOK_MEM_WRITE,check_write)
    saved_regs=[UC_MIPS_REG_S0,UC_MIPS_REG_S1,UC_MIPS_REG_S2,UC_MIPS_REG_S3,UC_MIPS_REG_S4,UC_MIPS_REG_S5,UC_MIPS_REG_S6,UC_MIPS_REG_S7,UC_MIPS_REG_FP]
    def call(name,*args):
        for i,reg in enumerate(saved_regs):c.reg_write(reg,0x12340000+i)
        for reg,v in zip((UC_MIPS_REG_A0,UC_MIPS_REG_A1,UC_MIPS_REG_A2),args):c.reg_write(reg,v)
        c.reg_write(UC_MIPS_REG_RA,0x80040000);c.reg_write(UC_MIPS_REG_SP,0x801f0000);c.reg_write(UC_MIPS_REG_GP,0x80144e0c)
        c.emu_start(sym[name],0x80040000,count=200000)
        assert c.reg_read(UC_MIPS_REG_PC)==0x80040000,(name,hex(c.reg_read(UC_MIPS_REG_PC)))
        assert c.reg_read(UC_MIPS_REG_SP)==0x801f0000
        assert c.reg_read(UC_MIPS_REG_GP)==0x80144e0c
        assert [c.reg_read(r) for r in saved_regs]==[0x12340000+i for i in range(len(saved_regs))]
        return c.reg_read(UC_MIPS_REG_V0)
    def init(prefix=b''):
        c.mem_write(state,bytes([255,255,0,0,len(prefix)//2,0,0]));c.mem_write(0x167bcb,b'\xa5'+prefix+bytes(13-len(prefix))+b'\x5a')
        c.mem_write(0x144e0c-0x6caa,b'\x00\x00')
    def action(a):return call('name_action',ord(a)-0x3131 if isinstance(a,str) else a)
    def record():return bytes(c.mem_read(0x167bcc,13))
    def guards():
        assert bytes(c.mem_read(0x167bcb,1))==b'\xa5'
        assert bytes(c.mem_read(0x167bd9,1))==b'\x5a'
    def sequence(text):
        for ch in text:
            n=ord(ch)-0xac00;l=n//588;v=n//28%21;t=n%28
            for key in INITIALS[l]+VP.get(MEDIALS[v],MEDIALS[v])+(TP.get(FINALS[t],FINALS[t]) if t else ''):
                assert action(key),(text,ch,key,list(c.mem_read(state,7)))
    t0=time.time()
    for n in range(11172):
        actual=call('name_lookup',n//588,n//28%21,n%28)
        assert actual==int(oracle.get(chr(0xac00+n),'0'),16),hex(n)
    for args in [(19,0,0),(0,21,0),(0,0,28),(255,255,0),(0xffffffff,0,0)]:assert call('name_lookup',*args)==0
    print('lookup: all 11,172 combinations checked',flush=True)
    # Each supported syllable is entered from actual two-set keyboard keys in
    # every slot, with existing preceding records and surrounding byte guards.
    for slot in range(6):
        prefix=bytes.fromhex(oracle['가'])*slot
        for ch,code in oracle.items():
            init(prefix);sequence(ch);assert action(52)
            expected=prefix+bytes.fromhex(code)+bytes(11-len(prefix))
            assert record()==expected,(slot,ch,record().hex(),expected.hex())
            assert bytes(c.mem_read(0x144e0c-0x6caa,2))==b'\x15\x00';guards()
        print('all supported syllables in slot',slot+1,flush=True)
    cases={'ㄱㅏㄴㅏ':'가나','ㄷㅏㄹㄱㅏ':'달가','ㅂㅏㄲㅏ':'바까','ㄱㅗㅏㄴ':'관','ㅇㅏㄴㅈㅏ':'안자','ㄱㅏㅂㅅㅏ':'갑사',
           'ㅎㅏㄴㄱㅡㄹ':'한글','ㄱㅏㄱㅏㄱㅏㄱㅏㄱㅏㄱㅏ':'가가가가가가'}
    for keys,text in cases.items():
        init()
        for k in keys:assert action(k),(keys,k)
        assert action(52)
        expected=b''.join(bytes.fromhex(oracle[ch]) for ch in text)
        assert record()[:len(expected)+1]==expected+b'\0',(keys,record().hex())
        guards()
    # Deletion unfolds compound final, medial and initial before committed text.
    init()
    for k in 'ㄱㅗㅏㄹㄱ':assert action(k)
    for wanted in [(0,9,8),(0,9,0),(0,8,0),(0,255,0),(255,255,0)]:
        assert action(51);assert tuple(c.mem_read(state,3))==wanted
    # Unfinished and unsupported commits are rejected atomically.
    rejected=0
    for n in range(11172):
        ch=chr(0xac00+n)
        if ch in oracle:continue
        init();c.mem_write(state,bytes([n//588,n//28%21,n%28,0,0,0,0]))
        before=record();assert not action(52);assert record()==before;guards();rejected+=1
    for partial in [(255,255,0),(0,255,0),(255,0,0)]:
        init();c.mem_write(state,bytes(partial));before=record();assert not action(52);assert record()==before
    init(bytes.fromhex(oracle['가'])*6)
    for a in list(range(51))+[53,255,0xffffffff]:
        before=record();assert not action(a);assert record()==before;guards()
    assert action(51);assert record()==bytes.fromhex(oracle['가'])*5+bytes(3)
    result=dict(disc_sha256=digest,lookup_combinations=11172,supported_syllables=2350,slot_positions=6,
        accepted_keyboard_paths=14100,unsupported_commit_rejections=rejected,sequence_cases=cases,
        byte_guards=True,all_cpu_writes_bounded=True,callee_saved_restored=True,stack_restored=True,seconds=round(time.time()-t0,2),
        ps1_runtime=False,persistence_verified=False)
    write_json(build/'name/cpu-verification.json',result);return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('build',type=Path);print(json.dumps(verify(p.parse_args().build),ensure_ascii=False,indent=2))
