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


def memory_card_writes(exe):
    """Spacing only; these prompts are deliberately not translation targets.

    Use the declared pointer table and direct a0 references in the verified
    card-dialogue consumer, never a scan for Shift-JIS-looking data.
    """
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
    if sha(exe[0x7BDEC:0x7CEC4]) != '7ca2b0370c7839017c88d6a2ebe6e3224bf4229296b262994f49f70e14644ef7':
        raise ValueError('Memory-card consumer revision differs')
    if sha(exe[0xAA370:0xAA3D0]) != 'ad5ab80b889fa5eae63487d9a8ef93fa231d09c76f79c95d53f868dffe02b5f3':
        raise ValueError('Memory-card pointer revision differs')
    pointers = set(struct.unpack_from('<24I', exe, 0xAA370))
    cs = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    instructions = list(cs.disasm(exe[0x7BDEC:0x7CEC4], 0x8010BDEC))
    direct = set()
    for first, second in zip(instructions, instructions[1:]):
        if (first.mnemonic == 'lui' and first.op_str == '$a0, 0x8014' and
                second.mnemonic == 'addiu' and second.op_str.startswith('$a0, $a0, ')):
            pointer = 0x80140000 + int(second.op_str.split(', ')[-1], 0)
            if 0x80139D18 <= pointer < 0x8013A0EC:
                direct.add(pointer)
    if len(direct) != 31:
        raise ValueError('Memory-card direct reference count differs')
    pointers.update(direct)
    title_ranges = []
    for pointer in TITLE_POINTERS:
        raw, _ = read_string(exe, pointer-RAM_BASE, len(exe))
        title_ranges.append((pointer, pointer+len(raw)))
    writes = []
    for pointer in sorted(pointers):
        # The card-battle heading aliases the title text. Its writer owns it.
        if any(start <= pointer < end for start, end in title_ranges):
            continue
        at = pointer-RAM_BASE
        raw, _ = read_string(exe, at, len(exe))
        units = [raw[i:i+2] for i in range(0, len(raw)-1, 2)]
        nonspace = [i for i, unit in enumerate(units) if unit != b'\x81\x40']
        if not nonspace:
            continue
        for i in range(nonspace[0], nonspace[-1]):
            if units[i] == b'\x81\x40':
                units[i] = HALF_SPACE
        new = b''.join(units)+b'\0'
        if new != raw:
            writes.append(dict(id=f'memory-card-spacing-{at:06x}',file='SLPS_017.97',
                               file_offset=at,before=raw.hex(),after=new.hex()))
    return writes


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
    writes.extend(memory_card_writes(exe))
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
