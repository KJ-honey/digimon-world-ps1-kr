#!/usr/bin/env python3
"""CPU verification of the installed bank wrapper and original text consumer.

Disc I/O and BIOS strcpy/strlen are explicitly stubbed. This is NOT evidence
of real CD timing/streaming, BIOS behavior, or gameplay.
"""
import argparse
import json
import struct
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn.mips_const import (UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2,
    UC_MIPS_REG_A3, UC_MIPS_REG_RA, UC_MIPS_REG_PC, UC_MIPS_REG_V0,
    UC_MIPS_REG_SP, UC_MIPS_REG_S0, UC_MIPS_REG_S1, UC_MIPS_REG_S2, UC_MIPS_REG_T1)
from dg_cpu_verify import Consumer
from dg_analyze import read_source
from dg_expand import CODE_RAM, SCRATCH_RAM
from survey import ROOT, Disc, sha, write_json


def bios_strings(consumer):
    c=consumer.cpu
    # Use maximum-length names, rather than empty uninitialized RAM strings.
    for address in (0x13a924,0x16b0ec):
        c.mem_write(address,bytes.fromhex('8141')*6+b'\0')
    calls=[]
    def bios(cpu,address,size,user):
        if address != 0xa0:
            return
        service=cpu.reg_read(UC_MIPS_REG_T1)
        a0,a1=cpu.reg_read(UC_MIPS_REG_A0),cpu.reg_read(UC_MIPS_REG_A1)
        if service not in (0x19,0x1b):
            raise ValueError(f'Unexpected BIOS service {service:x}')
        source=a1 if service==0x19 else a0
        raw=bytearray()
        for i in range(256):
            value=bytes(cpu.mem_read((source+i)&0x1fffff,1))
            if value==b'\0':
                break
            raw+=value
        else:
            raise ValueError('Unbounded BIOS string fixture')
        if service==0x19:
            cpu.mem_write(a0&0x1fffff,bytes(raw)+b'\0')
        cpu.reg_write(UC_MIPS_REG_V0,a0 if service==0x19 else len(raw))
        calls.append(service)
        cpu.reg_write(UC_MIPS_REG_PC,cpu.reg_read(UC_MIPS_REG_RA))
    c.hook_add(UC_HOOK_CODE,bios)
    return calls


def verify(build_dir):
    report = json.loads((build_dir/'build.json').read_text())
    source = read_source('kor')
    following=[0,0xfe]
    def source_lookahead(cpu,address,size,user):
        if address==0x800f4200:
            cpu.mem_write(0x50000+following[0],bytes((following[1],)))
    disc = Disc(build_dir/'dg-expanded.iso')
    try:
        if sha(disc.raw) != report['output_sha256']:
            raise ValueError('Build evidence binding mismatch')
        files = disc.files()
        read = lambda name: disc.read(files[name]['lba'],files[name]['size'])
        dg,exe = read('SCN/DG.SCN'),read('SLPS_017.97')
        # Keep all current name/pointer tables, including repacked techniques.
        # Only restore the original consumer prologue in the oracle.
        oracle_exe=bytearray(exe)
        oracle_exe[0x64200:0x64208]=source['SLPS_017.97'][0x64200:0x64208]
        original=Consumer(bytes(oracle_exe))
        original_bios=bios_strings(original)
        original.cpu.hook_add(UC_HOOK_CODE,source_lookahead)
        bank = Consumer(exe)
        bank_bios=bios_strings(bank)
        c = bank.cpu
        c.mem_write(CODE_RAM&0x1fffff,dg[0x800:0x1000])
        # All installed hook and original consumer instructions execute.
        resident=report.get('resident_dialogue')
        if resident:
            c.mem_write(SCRATCH_RAM&0x1fffff,dg[0x1000:0x1800])
        reads = []
        def io(cpu, address, size, user):
            if address != 0x800ec21c:
                return
            path,dest,offset,count = [cpu.reg_read(r) for r in
                (UC_MIPS_REG_A0,UC_MIPS_REG_A1,UC_MIPS_REG_A2,UC_MIPS_REG_A3)]
            if path!=0x80136bac or dest!=SCRATCH_RAM or offset%2048 or count!=2048:
                raise ValueError('Unexpected disc read ABI')
            raw = dg[offset:offset+count]
            if len(raw)!=count:
                raise ValueError('Disc read outside bank')
            cpu.mem_write(dest&0x1fffff,raw)
            reads.append({'file_offset':offset,'size':count,'destination_ram':dest})
            cpu.reg_write(UC_MIPS_REG_PC,cpu.reg_read(UC_MIPS_REG_RA))
        c.hook_add(UC_HOOK_CODE,io)
        tested=[]
        from dg_script import decode
        parsed=decode(source['SCN/DG.SCN'])
        for entry in report['entries']:
            payload=bytes.fromhex(entry['expanded_hex'])
            next_opcode=source['SCN/DG.SCN'][entry['source_end']]
            following[:]=[len(payload),next_opcode]
            try:
                original.run(payload)
            except Exception as exc:
                raise ValueError(f"Original consumer fixture failed: {entry['id']}") from exc
            expected=bytes(original.cpu.mem_read(0x60000,0x1000))
            expected_width=original.cpu.reg_read(UC_MIPS_REG_V0)
            expected_state=bytes(original.cpu.mem_read(0x1640b8,0x100))
            script=parsed['scripts'][entry['script']]
            base=0x80159784 if entry['script']==0 else 0x80161784
            pointer=base+entry['source_payload']-script['base']
            # Initialize through the existing harness without running the bank.
            # run() calls legacy text outside the redirect address range.
            bank.run(bytes.fromhex('81400d000000'))
            c.mem_write(0x60000,bytes(0x8000))
            c.mem_write(0x1640b8,bytes(0x100))
            if resident:
                shift=report['script_file_offset_shift']
                c.mem_write(base&0x1fffff,dg[script['base']+shift:script['limit']+shift])
            descriptor=dg[entry['source_payload']+report['script_file_offset_shift']:
                          entry['source_payload']+report['script_file_offset_shift']+4]
            continuation=pointer+entry['old_bytes']
            c.mem_write(pointer&0x1fffff,descriptor)
            c.mem_write(continuation&0x1fffff,bytes((next_opcode,0)))
            c.mem_write((bank.gp-0x6cc8)&0x1fffff,struct.pack('<I',pointer))
            guard=b'\xa5'*32
            if not resident:
                c.mem_write((SCRATCH_RAM-32)&0x1fffff,guard)
            c.mem_write((SCRATCH_RAM+2048)&0x1fffff,guard)
            for reg,value in ((UC_MIPS_REG_A0,0),(UC_MIPS_REG_A1,255),
                              (UC_MIPS_REG_RA,0x80040000),(UC_MIPS_REG_SP,0x801f0000),
                              (UC_MIPS_REG_S0,0x11223344),(UC_MIPS_REG_S1,0x22334455),
                              (UC_MIPS_REG_S2,0x33445566)):
                c.reg_write(reg,value)
            before=len(reads)
            c.emu_start(0x800f4200,0x80040000,count=100000)
            cursor=struct.unpack('<I',c.mem_read((bank.gp-0x6cc8)&0x1fffff,4))[0]
            if c.reg_read(UC_MIPS_REG_PC)!=0x80040000 or cursor!=continuation:
                raise ValueError('Original continuation was not restored')
            if bytes(c.mem_read(0x60000,0x1000))!=expected or c.reg_read(UC_MIPS_REG_V0)!=expected_width:
                raise ValueError(f"Expanded output/width differs: {entry['id']}, scratch={bytes(c.mem_read(SCRATCH_RAM&0x1fffff,len(payload)+2)).hex()}, expected={payload.hex()}, width={c.reg_read(UC_MIPS_REG_V0)}/{expected_width}")
            if bytes(c.mem_read(0x1640b8,0x100))!=expected_state:
                raise ValueError('Textbox/page state differs from original consumer oracle')
            for reg,value in ((UC_MIPS_REG_SP,0x801f0000),(UC_MIPS_REG_S0,0x11223344),
                              (UC_MIPS_REG_S1,0x22334455),(UC_MIPS_REG_S2,0x33445566)):
                if c.reg_read(reg)!=value:
                    raise ValueError('Callee-saved state changed')
            guards=(SCRATCH_RAM+2048,) if resident else (SCRATCH_RAM-32,SCRATCH_RAM+2048)
            if any(bytes(c.mem_read(a&0x1fffff,32))!=guard for a in guards):
                raise ValueError('Scratch bounds overwritten')
            if resident:
                start=resident['resident_start']
                if bytes(c.mem_read((SCRATCH_RAM+start)&0x1fffff,2048-start))!=dg[0x1000+start:0x1800]:
                    raise ValueError('Resident tail overwritten')
                if bytes(c.mem_read(CODE_RAM&0x1fffff,2048))!=dg[0x800:0x1000]:
                    raise ValueError('Resident code/dictionary overwritten')
            if len(reads)!=before+(0 if resident else 1):
                raise ValueError('Unexpected I/O count')
            tested.append(dict(entry,expected_continuation_ram=continuation,next_opcode=next_opcode))
        result={'isolated_cpu_only':True,'disc_io_stubbed':True,
                'bios_services_stubbed':['A0:19 strcpy','A0:1B strlen'],
                'bios_call_counts':{'original':len(original_bios),'bank':len(bank_bios)},
                'six_character_name_fixtures':True,
                'dialogue_disc_read_count':len(reads),
                'resident_pool_verified':bool(resident),
                'gameplay_runtime_verified':False,'disc_sha256':report['output_sha256'],
                'helper_sha256':sha(dg[0x800:0x1000]),'tested':tested,'disc_reads':reads,
                'output_and_width_match_original_consumer':True,
                'textbox_state_and_next_opcode_match':True,
                'consecutive_text_cases':sum(e['next_opcode']==0x1a for e in tested),
                'original_continuations_restored':True,'callee_saved_and_bounds_verified':True}
        write_json(build_dir/'bank/cpu-verification.json',result)
        return {k:v for k,v in result.items() if k not in ('tested','disc_reads')}
    finally:
        disc.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(verify(a.build),indent=2))
