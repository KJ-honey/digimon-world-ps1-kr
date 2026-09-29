"""Compile DG-only pixel row staging into the reclaimed expanded-font extent."""
import struct
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
from capstone.mips import MIPS_OP_REG, MIPS_OP_MEM
from font_expand import START, END, RAM_BASE, assemble
from survey import ROOT, write_json


def compile_pixel_row(exe, font_writes, font_report, output):
    output.mkdir(parents=True)
    offset = (START + font_report['glyph_bytes'] + 3) & ~3
    base = RAM_BASE + offset
    if (base >> 16) != ((base+0x200) >> 16):
        raise ValueError('Row code address crosses immediate page')
    source = f'.equ BASE_HI, {base>>16}\n.equ TRAMP_LO, {(base+0x200)&65535}\n'
    code = assemble(source+(ROOT/'tools/dg_pixel_row.s').read_text(), output, 'row')
    resident_offset = (len(code)+3)&~3
    resident = assemble((ROOT/'tools/catalog_resident.s').read_text(), output, 'catalog-resident')
    from catalog_insert import verify_machine_code
    verify_machine_code(resident, base+resident_offset, output/'catalog-resident.asm')
    if offset+len(code)>END:
        raise ValueError('Row renderer exceeds reclaimed font extent')
    decoder = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
    decoder.detail = True
    ins = list(decoder.disasm(code,base))
    for i,n in zip(ins,ins[1:]):
        if i.mnemonic in ('lw','lh','lhu','lb','lbu'):
            dest=i.operands[0].reg
            sources=list(n.operands[1:])
            if n.mnemonic.startswith('b') or n.mnemonic in ('jr','jalr','multu','sw','sh','sb'):
                sources=list(n.operands)
            if any((p.type==MIPS_OP_REG and p.reg==dest) or (p.type==MIPS_OP_MEM and p.mem.base==dest) for p in sources):
                raise ValueError(f'Row load delay hazard at {i.address:x}')
        if i.mnemonic.startswith('b') or i.mnemonic in ('j','jal','jr','jalr'):
            if n.mnemonic!='nop':
                raise ValueError(f'Row branch delay occupied at {i.address:x}')
    (output/'row.asm').write_text('\n'.join(f'{i.address:08x} {i.mnemonic} {i.op_str}' for i in ins)+'\n')
    code = code.ljust(resident_offset,b'\0') + resident
    if offset+len(code)>END:
        raise ValueError('Resident catalog code exceeds reclaimed font extent')
    # This range has already been reclaimed by the dictionary font provider.
    # Merge into that one writer, so the sector planner sees no overlap.
    font_write=next(w for w in font_writes if w['id']=='compressed-expanded-font')
    data=bytearray.fromhex(font_write['after'])
    assert not any(data[offset-START:offset-START+len(code)])
    data[offset-START:offset-START+len(code)]=code
    font_write['after']=data.hex()
    hooks=[]
    def patch(at, expected, dest, link=False):
        before=bytes.fromhex(expected)
        if exe[at:at+len(before)]!=before:
            raise ValueError(f'Pixel row hook revision differs at EXE {at:x}')
        raw=struct.pack('<I',(0x0c000000 if link else 0x08000000)|((dest>>2)&0x3ffffff))
        if len(before)==8: raw+=bytes(4)
        decoded=list(decoder.disasm(raw,RAM_BASE+at))
        if decoded[0].mnemonic!=('jal' if link else 'j') or decoded[0].operands[0].imm!=dest:
            raise ValueError('Pixel hook target did not decode exactly')
        hooks.append(dict(id=f'pixel-row-{at:06x}',file='SLPS_017.97',file_offset=at,before=before.hex(),after=raw.hex()))
    patch(0x634e4,'d0ffbd271c00bfaf',base)
    patch(0x6384c,'1c00bf8f1800b28f',base+0x220)
    for at in (0x63660,0x63714,0x63774,0x6380c):
        patch(at,'a695020c',base+0x240,True)
    patch(0x15b24,'1b52020c',base+0x260,True)
    report=dict(code_exe_offset=offset,code_ram=base,code_bytes=len(code),stack_bytes=0x650,
                catalog_dispatch_ram=base+resident_offset,
                catalog_width_ram=base+resident_offset+0x40,
                staging_pixels=[256,12],upload_sync_ram='0x80094774',
                scope='DG row renderer only; generic glyph uploads retain original path',
                half_pixels=6,full_pixels=12,extra_resident_ram=0)
    write_json(output/'row.json',report)
    return hooks,report
