"""Revision-bound title spacing and map-name sprite width fixes."""
import struct
from catalog_insert import HALF_SPACE, compile_renderer, verify_machine_code
from font_expand import assemble
from survey import sha
from translation_catalog import RAM_BASE, read_string

TITLE_POINTERS = (0x80139a68,0x80139a80,0x80139a94,0x80139aa5,
                  0x80139abb,0x80139ad2,0x80139aec,0x80139b08)
WIDTH_START, WIDTH_END = 0x54290, 0x5430c
WIDTH_SHA = '62199deeae28d48e8c60432a2d0e4ba54ae7626548c4e619b8920126529b6026'


def title_writes(exe):
    if struct.unpack_from('<8I',exe,0xaa350)!=TITLE_POINTERS:
        raise ValueError('Title menu pointer revision differs')
    writes=[]
    for index,pointer in enumerate(TITLE_POINTERS):
        at=pointer-RAM_BASE
        raw,_=read_string(exe,at,len(exe))
        new=bytearray(raw)
        # The two leading cells are the cursor margin. Only word separators
        # change; byte length, aliases into this text and NUL remain valid.
        started=False
        for i in range(0,len(raw)-1,2):
            if raw[i:i+2]!=b'\x81\x40':started=True
            elif started:new[i:i+2]=HALF_SPACE
        if new!=raw:
            writes.append(dict(id=f'title-spacing-{index:03d}',file='SLPS_017.97',
                               file_offset=at,before=raw.hex(),after=new.hex()))
    return writes


def compile_layout(exe,pixel_report,output):
    writes=[compile_renderer(exe,pixel_report['catalog_dispatch_ram'],output)]
    writes.extend(title_writes(exe))
    if sha(exe[WIDTH_START:WIDTH_END])!=WIDTH_SHA:
        raise ValueError('Location sprite width consumer revision differs')
    source=f'''.set noreorder
.set noat
.text
    jal {pixel_report['catalog_width_ram']}
    nop
    move $s0,$v0
    addiu $v0,$zero,12
    sw $v0,16($sp)
    sw $zero,20($sp)
    sw $zero,24($sp)
    sw $zero,28($sp)
    sw $zero,32($sp)
    srl $v1,$s0,1
    addiu $v0,$zero,-12
    subu $a1,$v0,$v1
    move $a3,$s0
    move $a0,$zero
    addiu $a2,$zero,-6
    jal 0x80103c84
    nop
'''
    code=assemble(source,output,'location-width')
    if len(code)>WIDTH_END-WIDTH_START:raise ValueError('Location width code overflow')
    code=code.ljust(WIDTH_END-WIDTH_START,b'\0')
    verify_machine_code(code,RAM_BASE+WIDTH_START,output/'location-width.asm')
    writes.append(dict(id='location-sprite-width',file='SLPS_017.97',file_offset=WIDTH_START,
                       before=exe[WIDTH_START:WIDTH_END].hex(),after=code.hex()))
    return writes
