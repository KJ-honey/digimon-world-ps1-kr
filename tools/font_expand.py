#!/usr/bin/env python3
"""Lossless 3/4/4-row dictionary font provider in the original EXE font slot.

The legacy code table, symbols and fallback retain identity. Hangul uses the
user-selected Mona12 Text KR profile for both legacy and added syllables.
New KS X 1001 syllables use F040..F7FC, trail 7F excluded. Development profile;
this is not a claim of complete text-population or name-entry coverage.
"""
import os
from pathlib import Path
import shutil
import struct
import subprocess

from PIL import Image, ImageDraw, ImageFont, __version__ as PIL_VERSION
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
from match_gulim import render_rows
from survey import ROOT, sha, write_json

START, END = 0x98D38, 0x9E278
RAM_BASE = 0x80090000
HOOK = 0x157F0
HOOK_BEFORE = bytes.fromhex('3e00a2971380013c368d22a42400a0af')
WIDTHS = (3, 4, 4)
CODE_BYTES = 512
SCRATCH_OFFSET = CODE_BYTES
DESCRIPTORS_OFFSET = SCRATCH_OFFSET + 24
INDEX_OFFSET = DESCRIPTORS_OFFSET + 60
FONT_PROFILE = 'ksx1001-mona12-v1'
DEFAULT_FONT = ROOT / 'work/font-compare/Mona12TextKR.ttf'
FONT_SHA256 = 'ce94906004a3280d658946c8816093895897792363973ede9498d746b7155336'


def checked_rows(bitmap, char):
    """Reject empty/cropped glyphs before serializing the fixed 12x11 cell."""
    canvas = Image.new('1', (40, 40))
    ImageDraw.Draw(canvas).text((8, 8), char, font=bitmap, fill=1, anchor='lt')
    bounds = canvas.getbbox()
    if not bounds:
        raise ValueError(f'Empty glyph: {char}')
    if bounds[0] < 8 or bounds[1] < 8 or bounds[2] > 20 or bounds[3] > 19:
        raise ValueError(f'Clipped glyph: {char}: {bounds}')
    return render_rows(bitmap, char)


def ks_syllables():
    chars = [bytes((hi, lo)).decode('euc_kr')
             for hi in range(0xB0, 0xC9) for lo in range(0xA1, 0xFF)]
    if len(set(chars)) != 2350 or any(len(c) != 1 or not '가' <= c <= '힣' for c in chars):
        raise ValueError('KS X 1001 codec repertoire differs')
    return set(chars)


def extra_code(index):
    if not 0 <= index < 8*188:
        raise ValueError('Extension code space overflow')
    lead, trail = divmod(index, 188)
    trail += 0x40
    if trail >= 0x7F:
        trail += 1
    return f'{0xF000 + lead*256 + trail:04X}'


def pack(rows):
    """Independent segment dictionaries, 13 bits per complete 16-bit row.

    Low nibble is either 0 or F on this revision; preserve it explicitly.
    One u32 per glyph selects the three segments with derived bit widths.
    """
    if not rows or any(len(r) != 11 for r in rows):
        raise ValueError('Expected nonempty 12x11 glyph population')
    tables, descriptors, indices = [], [], [0]*len(rows)
    row_at = bit_at = 0
    for width in WIDTHS:
        unique = sorted({tuple(r[row_at:row_at+width]) for r in rows})
        bits = max(1, (len(unique)-1).bit_length())
        lookup = {r: i for i, r in enumerate(unique)}
        stride = (width*13+7)//8
        table = bytearray()
        for segment in unique:
            value = 0
            for n, row in enumerate(segment):
                if not 0 <= row <= 65535 or row & 15 not in (0, 15):
                    raise ValueError('Unsupported source row; no lossy conversion')
                value |= ((row >> 4) | (bool(row & 15) << 12)) << (13*n)
            table.extend(value.to_bytes(stride, 'little'))
        for i, r in enumerate(rows):
            indices[i] |= lookup[tuple(r[row_at:row_at+width])] << bit_at
        tables.append(bytes(table))
        descriptors.append({'count': len(unique), 'bits': bits, 'rows': width, 'stride': stride})
        row_at += width
        bit_at += bits
    if bit_at > 32:
        raise ValueError('Glyph dictionary index overflow')
    return struct.pack('<'+'I'*len(indices), *indices), tables, descriptors


def unpack(index_data, tables, descriptors, index):
    """Artifact oracle: unpack each segment as one integer, not runtime stream loop."""
    value, = struct.unpack_from('<I', index_data, index*4)
    result = []
    for table, d in zip(tables, descriptors):
        which = value & ((1 << d['bits'])-1)
        value >>= d['bits']
        if which >= d['count']:
            raise ValueError('Invalid segment index')
        start = which*d['stride']
        packed = int.from_bytes(table[start:start+d['stride']], 'little')
        for n in range(d['rows']):
            word = (packed >> (13*n)) & 8191
            result.append(((word & 4095) << 4) | (15 if word & 4096 else 0))
    if value:
        raise ValueError('Unexpected index high bits')
    return tuple(result)


def llvm_tool(name):
    path = shutil.which(name)
    if not path:
        homebrew = shutil.which('brew')
        prefix = subprocess.check_output([homebrew, '--prefix', 'llvm'], text=True).strip() if homebrew else ''
        path = str(Path(os.environ.get('LLVM_BIN', prefix+'/bin'))/name)
    if not Path(path).is_file():
        raise ValueError(f'{name} required; set LLVM_BIN or PATH')
    return path


def assemble(source, out, name):
    mc, objcopy = llvm_tool('llvm-mc'), llvm_tool('llvm-objcopy')
    asm, obj, binary = (out/(name+ext) for ext in ('.s', '.o', '.bin'))
    asm.write_text(source)
    subprocess.run([mc, '-triple=mipsel', '-mcpu=mips1', '-filetype=obj', str(asm), '-o', str(obj)], check=True)
    from elftools.elf.elffile import ELFFile
    with obj.open('rb') as f:
        elf = ELFFile(f)
        if any(s.header['sh_type'] in ('SHT_REL', 'SHT_RELA') and s.num_relocations() for s in elf.iter_sections()):
            raise ValueError('Unresolved machine-code relocation')
    subprocess.run([objcopy, '-O', 'binary', '--only-section=.text', str(obj), str(binary)], check=True)
    data = binary.read_bytes()
    # LLVM's full MIPS I parser/decoder is the ISA authority; independent Capstone
    # checks final instruction boundaries and branch/load delay hazards below.
    dis = subprocess.run([mc, '-triple=mipsel', '-mcpu=mips1', '--disassemble'],
                         input=' '.join(f'0x{x:02x}' for x in data), text=True, capture_output=True, check=True)
    if 'warning:' in dis.stderr or 'invalid' in dis.stderr:
        raise ValueError('MIPS I disassembly failed: '+dis.stderr)
    rt = out/(name+'-roundtrip.s')
    decoder = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    decoder.detail = True
    decoded = list(decoder.disasm(data, 0))
    if len(decoded)*4 != len(data):
        raise ValueError('Independent MIPS decode incomplete')
    # LLVM prints branch displacement from PC, while its parser applies PC+4.
    # Normalize decoded branch targets to local labels before reassembly.
    lines = []
    for ins in decoded:
        operands = ins.op_str
        if ins.mnemonic in ('b', 'beq', 'beqz', 'bne', 'bnez', 'bgez', 'bltz', 'blez', 'bgtz'):
            target = ins.operands[-1].imm
            parts = operands.rsplit(',', 1)
            operands = (parts[0]+', ' if len(parts)>1 else '')+f'L{target:08x}'
        lines.append(f'L{ins.address:08x}: {ins.mnemonic} {operands}')
    rt.write_text('.set noreorder\n.set noat\n.text\n'+'\n'.join(lines)+'\n')
    rt_obj = out/(name+'-roundtrip.o')
    subprocess.run([mc, '-triple=mipsel', '-mcpu=mips1', '-filetype=obj', str(rt), '-o', str(rt_obj)], check=True)
    rt_bin = out/(name+'-roundtrip.bin')
    subprocess.run([objcopy, '-O', 'binary', '--only-section=.text', str(rt_obj), str(rt_bin)], check=True)
    if rt_bin.read_bytes() != data:
        raise ValueError('Assembler/disassembler round trip failed')
    return data


def compile_font(exe, mapping, output, font_path=DEFAULT_FONT, name_entry=False):
    output.mkdir(parents=True, exist_ok=True)
    if exe[HOOK:HOOK+16] != HOOK_BEFORE:
        raise ValueError('Font hook revision mismatch')
    entries = mapping['entries']
    if len(entries) != 992:
        raise ValueError('Legacy map population changed')
    for e in entries:
        if e['index'] is not None and struct.unpack_from('<H', exe, 0x98578+2*e['index'])[0] != int(e['code'],16):
            raise ValueError('Legacy map code differs from EXE')
    old = {e['character'] for e in entries if e['character'] and '가' <= e['character'] <= '힣'}
    required = old | ks_syllables()
    additions = sorted(required-old)
    if sha(font_path.read_bytes()) != FONT_SHA256:
        raise ValueError('Mona12 font source changed; review a new profile first')
    jamo = list(chr(c) for c in range(0x3131,0x3164)) if name_entry else []
    from fontTools.ttLib import TTFont
    with TTFont(font_path, fontNumber=0) as source_font:
        cmap = source_font.getBestCmap()
        missing = sorted(c for c in required | set(jamo) if ord(c) not in cmap)
        if missing:
            raise ValueError('Font has no glyphs: '+''.join(missing))
    bitmap = ImageFont.truetype(str(font_path), 12, index=0)
    # Glyph identities still come from restore_text's Gulim comparison. The
    # selected product raster is independently bound to the Mona12 source.
    rendered = {char: checked_rows(bitmap, char) for char in sorted(required) + jamo}
    rows = [struct.unpack_from('<11H', exe, START+22*i) for i in range(992)]
    legacy_hangul = [e for e in entries if e['character'] in old]
    for e in legacy_hangul:
        rows[e['index']] = rendered[e['character']]
    new_entries = []
    for i, char in enumerate(additions + jamo):
        rows.append(rendered[char])
        new_entries.append({'id': f'expanded-{ord(char):04x}', 'index': 992+i,
                            'code': extra_code(i), 'character': char, 'evidence': 'mona12_12px_raster'})
    idx, tables, desc = pack(rows)
    for i, original in enumerate(rows):
        if unpack(idx,tables,desc,i) != tuple(original):
            raise ValueError(f'Lossless font reconstruction failed: {i}')
    base = RAM_BASE+START
    offset = INDEX_OFFSET+len(idx)
    desc_bytes = bytearray()
    for t,d in zip(tables,desc):
        d['offset'] = offset
        desc_bytes.extend(struct.pack('<5I', base+offset, (1<<d['bits'])-1, d['bits'], d['rows'], d['stride']))
        offset += len(t)
    definitions = {'EXTRA_COUNT': len(additions) + len(jamo)}
    for key, addr in {'INDEX':base+INDEX_OFFSET, 'SCRATCH':base+SCRATCH_OFFSET,
                      'DESCRIPTORS':base+DESCRIPTORS_OFFSET}.items():
        definitions[key+'_HI'], definitions[key+'_LO'] = addr>>16, addr&65535
    preamble = ''.join(f'.equ {k}, {v}\n' for k,v in definitions.items())
    code = assemble(preamble+(ROOT/'tools/font_provider.s').read_text(),output,'provider')
    if len(code)>CODE_BYTES:
        raise ValueError('Provider code slot overflow')
    hook = assemble(f'.set noreorder\n.text\nlui $v0,{base>>16}\nori $v0,$v0,{base&65535}\njr $v0\nnop\n',output,'hook')
    packed = code.ljust(CODE_BYTES,b'\0')+bytes(24)+desc_bytes+idx+b''.join(tables)
    if len(packed)>END-START:
        raise ValueError(f'Font slot overflow: {len(packed)} > {END-START}')
    cs = Cs(CS_ARCH_MIPS,CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
    cs.detail = True
    ins = list(cs.disasm(code,base))
    if sum(i.size for i in ins)!=len(code):
        raise ValueError('Independent code boundary failure')
    for i,n in zip(ins,ins[1:]):
        if i.mnemonic in ('lw','lh','lhu','lb','lbu'):
            dest = i.operands[0].reg
            from capstone.mips import MIPS_OP_REG, MIPS_OP_MEM
            # These are final generated instructions; Capstone MIPS does not
            # implement regs_access. Identify source operands explicitly.
            sources = list(n.operands[1:])
            if n.mnemonic.startswith('b') or n.mnemonic in ('jr','multu','sw','sh','sb'):
                sources = list(n.operands)
            if any((op.type == MIPS_OP_REG and op.reg == dest) or
                   (op.type == MIPS_OP_MEM and op.mem.base == dest) for op in sources):
                raise ValueError(f'Load delay hazard: {i.address:x} -> {n.address:x}')
        if i.mnemonic in ('b','beq','beqz','bne','bnez'):
            if n.mnemonic != 'nop':
                raise ValueError('Unexpected occupied branch delay')
            target=i.operands[-1].imm
            if not base<=target<base+len(code) or target%4:
                raise ValueError('Branch outside provider')
    (output/'provider.asm').write_text('\n'.join(f'{i.address:08x} {i.mnemonic} {i.op_str}' for i in ins)+'\n')
    if len({e['code'] for e in entries+new_entries}) != len(entries+new_entries):
        raise ValueError('New code collides with legacy identity')
    result_map = dict(mapping, entries=entries+new_entries, font_profile=FONT_PROFILE)
    write_json(output/'character-map.json', result_map)
    report = {'profile':FONT_PROFILE, 'hangul_before':len(old),
              'hangul_total':len(required), 'hangul_added':len(additions), 'name_jamo':len(jamo),
              'legacy_slots_preserved':991-len(legacy_hangul), 'fallback_preserved':True,
              'legacy_hangul_slots_rerendered':len(legacy_hangul),
              'font_name':'Mona12 Text KR', 'font_size_px':12, 'font_face':0,
              'raster':'Pillow 1-bit, anchor=lt, origin=(0,0), 12x11',
              'glyphs_total_with_fallback':len(rows), 'glyph_bytes':len(packed), 'capacity':END-START,
              'provider_code_bytes':len(code), 'scratch_bytes':22, 'extra_resident_ram':0,
              'font_sha256':sha(font_path.read_bytes()), 'pillow_version':PIL_VERSION,
              'llvm_version':subprocess.check_output([llvm_tool('llvm-mc'),'--version'],text=True).splitlines()[0],
              'descriptors':desc,'all_glyphs_lossless':True,'legacy_codes_unchanged':True,
              'exe_file_offset':START,'ram_address':base,'runtime_verified':False,
              'encoding_scope':'existing glyph identities + DG/general 2-byte readers; full consumer audit pending'}
    write_json(output/'font.json',report)
    write_json(output/'glyph-oracle.json', {'rows':rows, 'codes':[e['code'] for e in entries if e['index'] is not None]+['0000']+[e['code'] for e in new_entries]})
    writes=[{'id':'font-provider-hook','file':'SLPS_017.97','file_offset':HOOK,'before':exe[HOOK:HOOK+16].hex(),'after':hook.hex()},
            {'id':'compressed-expanded-font','file':'SLPS_017.97','file_offset':START,'before':exe[START:END].hex(),
             'after':packed.ljust(END-START,b'\0').hex()}]
    return result_map,writes,report
