"""Compile the SHOP name editor into replaced name-only routines and font tail.

No overlay growth or persistent representation change. All output writes bind to
immutable source bytes. MIPS I code is linked by LLD and independently decoded.
"""
import json, os, shutil, struct, subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
from font_expand import START, END, RAM_BASE, llvm_tool, ks_syllables
from survey import ROOT, sha, write_json

BASE, LIMIT = 0x800849e0, 0x80086504
SHOP_BASE = 0x80080800
SHOP_SHA = '98ad95d164046d447dbf9429f2d9a21d27da90d0965adf18bf52a56eeda38ce4'
INITIALS='ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
MEDIALS='ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
FINALS='−ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ'

def compile_names(shop, mapping, font_writes, font_report, pixel_report, output):
    if sha(shop)!=SHOP_SHA: raise ValueError('Unsupported SHOP revision')
    output.mkdir(parents=True)
    entries=mapping['entries']
    codes={};indices={}
    for e in entries:
        if e['character'] and e['character'] not in codes:
            codes[e['character']]=int(e['code'],16);indices[e['character']]=e['index']
    # Legacy duplicate 늪 is resolved explicitly to its first verified slot.
    if codes.get('늪')!=0x88c0:raise ValueError('Canonical duplicate changed')
    bits=bytearray(1397);legacy=bytearray(294);packed=0;legacy_count=0
    chars=sorted(ks_syllables())
    for rank,ch in enumerate(chars):
        n=ord(ch)-0xac00;bits[n//8]|=1<<(n%8)
        if indices[ch]<991:
            legacy[rank//8]|=1<<(rank%8)
            packed|=indices[ch]<<(legacy_count*10);legacy_count+=1
    if legacy_count!=912:raise ValueError('Legacy Hangul count changed')
    data=bytes(bits)+bytes(legacy)+packed.to_bytes((legacy_count*10+7)//8,'little')+b'\0'
    # KS membership + legacy membership + packed 10-bit original glyph indices.
    tail=(START+font_report['glyph_bytes']+3)&~3
    if pixel_report:tail=max(tail,pixel_report['code_exe_offset']+pixel_report['code_bytes'])
    tail=(tail+3)&~3; capacity=END-tail
    if capacity<=0:raise ValueError('No reclaimed font tail for name lookup')
    split=min(capacity,len(data))
    # Put the front in the resident font extent and the rest after editor code.
    # DATA_B assigned by the linker, without hand-maintained function offsets.
    def array(name,s):
        vals=[]
        for c in s:
            if c not in codes: raise ValueError('Missing name UI glyph: '+c)
            vals.append(codes[c])
        return 'static const u16 '+name+'[]={'+','.join(map(str,vals))+',0};\n'
    labels=['주인공 이름','디지몬 이름','입력 중','입력할 수 없는 조합','○ 입력 ｘ 삭제','시작 완료 Ｌ１ 쌍자음','한글 두벌식']
    # Use verified full-width symbols and an explicit source-bound space.
    codes[' ']=0x8140
    header=f'#define DATA_A {RAM_BASE+tail}u\n#define DATA_SPLIT {split}u\nextern const u8 name_data[];\n#define DATA_B name_data\n'
    header+=array('initials',INITIALS)+array('medials',MEDIALS)+array('finals',FINALS)
    header+=array('jamo_glyphs',''.join(chr(c) for c in range(0x3131,0x3164)))
    keys='ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔㅁㄴㅇㄹㅎㅗㅓㅏㅣㅋㅌㅊㅍㅠㅜㅡ'
    shift='ㅃㅉㄸㄲㅆㅛㅕㅑㅒㅖ'
    def raw(name,values):return 'static const u8 '+name+'[]={'+','.join(map(str,values))+'};\n'
    header+=raw('keys',[ord(c)-0x3131 for c in keys])+raw('shiftkeys',[ord(c)-0x3131 for c in shift])
    header+=raw('to_l',[INITIALS.index(chr(c)) if chr(c) in INITIALS else 255 for c in range(0x3131,0x3164)])
    header+=raw('to_t',[FINALS.index(chr(c)) if chr(c) in FINALS else 0 for c in range(0x3131,0x3164)])
    header+=raw('t_to_l',[INITIALS.index(c) if c in INITIALS else 255 for c in FINALS])
    for i,s in enumerate(labels):header+=array('label'+str(i),s)
    header+='static const u16 *const labels[]={'+','.join('label'+str(i) for i in range(len(labels)))+'};\n'
    (output/'name_data.h').write_text(header)
    cc=str(Path(llvm_tool('llvm-mc')).with_name('clang'))
    lld=os.environ.get('LLD') or shutil.which('ld.lld')
    if not lld:
        found=list((Path.home()/'.rustup/toolchains').glob('*/lib/rustlib/*/bin/rust-lld'))
        if found:lld=str(found[0])
    if not lld:raise ValueError('LLD ELF linker required (LLD env or rust-lld)')
    args=[cc,'-target','mipsel-none-elf','-march=mips1','-mabi=32','-msoft-float','-mno-abicalls','-fno-pic','-mllvm','-mno-check-zero-division','-G0','-Oz','-ffreestanding','-fno-builtin','-fno-stack-protector','-fomit-frame-pointer','-I',str(output),'-c',str(ROOT/'tools/name_entry.c'),'-o',str(output/'editor.o')]
    subprocess.run(args,check=True)
    (output/'data.s').write_text('.section .name_data,"a"\n.globl name_data\nname_data:\n.byte '+','.join(map(str,data[split:]))+'\n')
    subprocess.run([cc,'-target','mipsel-none-elf','-march=mips1','-msoft-float','-mno-abicalls','-fno-pic','-c',str(output/'data.s'),'-o',str(output/'data.o')],check=True)
    script=f'''ENTRY(name_input)
SECTIONS {{
 . = 0x{BASE:x};
 .text : {{ FILL(0); *(.text*) }} =0
 .rodata : {{ *(.rodata*) }}
 .data : {{ *(.data*) *(.sdata*) }}
 .state : {{ *(.state) }}
 .name_data : {{ *(.name_data) }}
 /DISCARD/ : {{ *(.MIPS.abiflags) *(.reginfo) *(.pdr) *(.comment) *(.note*) *(.eh_frame*) }}
}}
'''
    (output/'editor.ld').write_text(script)
    cmd=[lld]+(['-flavor','gnu'] if Path(lld).name=='rust-lld' else [])
    subprocess.run(cmd+['-m','elf32ltsmip','-T',str(output/'editor.ld'),str(output/'editor.o'),str(output/'data.o'),'-o',str(output/'editor.elf')],check=True)
    with (output/'editor.elf').open('rb') as f:
        elf=ELFFile(f);sym={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        sections=[s for s in elf.iter_sections() if s['sh_flags']&2]
        end=max(s['sh_addr']+s['sh_size'] for s in sections)
        if end>LIMIT:raise ValueError(f'Name editor overflow: {end-BASE} > {LIMIT-BASE}; tail {split}')
        payload=bytearray(LIMIT-BASE)
        for sec in sections:payload[sec['sh_addr']-BASE:sec['sh_addr']-BASE+sec['sh_size']]=sec.data()
        code=elf.get_section_by_name('.text').data()
    # LLVM full MIPS I decoder rejects out-of-profile code. Linker applies all
    # HI16/LO16/call relocations before independent final-address inspection.
    dis=subprocess.run([llvm_tool('llvm-mc'),'-triple=mipsel','-mcpu=mips1','--disassemble'],input=' '.join(f'0x{x:02x}' for x in code),text=True,capture_output=True,check=True)
    if dis.stderr:raise ValueError(dis.stderr.splitlines()[0])
    dec=Cs(CS_ARCH_MIPS,CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN);dec.detail=True
    ins=list(dec.disasm(code,BASE))
    if len(ins)*4!=len(code):raise ValueError('Incomplete MIPS decode')
    # Verify final code through a second assemble/decode round trip. No data
    # is sent to the ISA decoder; text padding is explicitly zero-filled.
    from font_expand import assemble
    branches=('b','beq','beqz','bne','bnez','bgez','bltz','blez','bgtz')
    zero_ins=list(dec.disasm(code,0));lines=[]
    for i in zero_ins:
        ops=i.op_str
        if i.mnemonic in branches:
            target=i.operands[-1].imm
            if target%4 or not 0<=target<len(code):raise ValueError('Branch leaves editor text')
            parts=ops.rsplit(',',1)
            ops=(parts[0]+', ' if len(parts)>1 else '')+f'L{target:08x}'
        lines.append(f'L{i.address:08x}: {i.mnemonic} {ops}')
    rebuilt=assemble('.set noreorder\n.set noat\n.text\n'+'\n'.join(lines)+'\n',output,'editor-verified')
    if rebuilt!=code:raise ValueError('Final linked code round trip differs')
    from capstone.mips import MIPS_OP_REG,MIPS_OP_MEM
    for i,n in zip(ins,ins[1:]):
        if i.mnemonic in ('lw','lh','lhu','lb','lbu'):
            dest=i.operands[0].reg;sources=list(n.operands[1:])
            if n.mnemonic in branches or n.mnemonic in ('jr','jalr','mult','multu','div','divu','sw','sh','sb'):
                sources=list(n.operands)
            if any((p.type==MIPS_OP_REG and p.reg==dest) or (p.type==MIPS_OP_MEM and p.mem.base==dest) for p in sources):
                raise ValueError(f'Name load delay hazard {i.address:x}')
        if i.mnemonic in branches or i.mnemonic in ('j','jal','jr','jalr'):
            if n.mnemonic in branches or n.mnemonic in ('j','jal','jr','jalr'):
                raise ValueError('Control transfer in delay slot')
    (output/'editor.asm').write_text('\n'.join(f'{i.address:08x} {i.mnemonic} {i.op_str}' for i in ins)+'\n')
    (output/'editor.bin').write_bytes(payload)
    (output/'lookup.bin').write_bytes(data)
    fw=next(w for w in font_writes if w['id']=='compressed-expanded-font')
    fdata=bytearray.fromhex(fw['after']);at=tail-START
    if any(fdata[at:at+split]):raise ValueError('Name data overlaps font/pixel code')
    fdata[at:at+split]=data[:split];fw['after']=fdata.hex()
    writes=[dict(id='compositional-name-editor',file='SHOP_REL.BIN',file_offset=BASE-SHOP_BASE,before=shop[BASE-SHOP_BASE:LIMIT-SHOP_BASE].hex(),after=payload.hex())]
    def patch(at,value):
        writes.append(dict(id=f'name-hook-{at:x}',file='SHOP_REL.BIN',file_offset=at,before=shop[at:at+len(value)].hex(),after=value.hex()))
    # The four incoming edges from the unchanged name-window constructors.
    # Two callback immediate addresses and two direct init/refresh calls.
    for address,name in [(0x800847e4,'name_input'),(0x800847f0,'name_draw'),(0x80084948,'name_field')]:
        value=sym[name]
        if (value+0x8000)>>16!=0x8008:raise ValueError('Callback immediate page changed')
        before=struct.unpack_from('<I',shop,address-SHOP_BASE)[0]
        patch(address-SHOP_BASE,struct.pack('<I',(before&0xffff0000)|(value&65535)))
    for address,name in [(0x80084834,'name_init'),(0x800849c0,'name_init')]:
        patch(address-SHOP_BASE,struct.pack('<I',0x0c000000|((sym[name]>>2)&0x3ffffff)))
    report=dict(format=1,source_shop_sha256=sha(shop),code_ram=BASE,code_bytes=len(code),end_ram=end,capacity=LIMIT-BASE,
                data_bytes=len(data),data_a_ram=RAM_BASE+tail,data_a_bytes=split,data_b_ram=sym['name_data'],
                symbols={k:v for k,v in sym.items() if v and (k.startswith('name_') or k=='edit')},
                max_characters=6,hangul_syllables=2350,save_format='original two-byte codes + single NUL',
                compiler=subprocess.check_output([cc,'--version'],text=True).splitlines()[0],
                linker=subprocess.check_output(cmd+['--version'],text=True).strip(),
                runtime_verified=False)
    write_json(output/'name.json',report)
    write_json(output/'canonical.json',{ch:f'{codes[ch]:04X}' for ch in chars})
    return writes,report
