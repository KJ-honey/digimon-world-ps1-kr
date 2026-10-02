#!/usr/bin/env python3
"""Source-bound non-DG reinsertion, composed by dg_expand (development only).

Locations stay resident C strings; descriptions get independent CD records.
Their original strings stay intact.
Inline records retain the established 20-byte field, including byte NUL. No
numeric record data, shared original string, or authored review is overwritten.
"""
import argparse
import json
import struct
from pathlib import Path

from font_expand import assemble
from restore_text import LegacyCodec
from survey import ROOT, SOURCES, sha, write_json
from translation_catalog import EXE, RAM_BASE, extract
from translation_review import Workspace, digest

DESCRIPTOR_RAM = 0x80160F84
HELPER_OFFSET = 0x400
GENERAL_START, GENERAL_END = 0x15B48, 0x15BCC
GENERAL_SHA = 'ca75f88678326d8eecd70682b9309d4407f231f633635a40dc583f541b775d59'
HALF_SPACE = b'\x0f\x01'  # No embedded byte NUL: strcpy/strlen stay valid.
INLINE_BYTES = 20
MAX_PIXELS = 252  # Physical row capacity; individual UI windows still need QA.


def encode_text(row, text, mapping):
    from translation_playtest import encode_draft
    Workspace.validate(row, text, 'draft')
    old = bytes.fromhex(row['raw']['kor'])
    if text == row['existing']:
        return old
    values = {e['code']: e['character'] for e in mapping['entries']}
    if '0F01' in values or ' ' in values.values():
        raise ValueError('Catalog half-space alias collision')
    values['0F01'] = ' '
    encoded, _ = encode_draft(text, LegacyCodec(values))
    if not encoded or len(encoded) % 2 or 0 in encoded:
        raise ValueError('Catalog text requires complete non-NUL two-byte units')
    for at in range(0, len(encoded), 2):
        code = encoded[at:at+2].hex().upper()
        if code != '0F01' and code not in values:
            raise ValueError('Unsupported catalog glyph: '+code)
        if encoded[at] < 32 and code != '0F01':
            raise ValueError('DG/control bytes are not catalog glyphs')
    from technique_insert import encode_layout
    return encode_layout(row, encoded + b'\0')


def pixel_width(raw):
    if not raw or raw[-1:] != b'\0' or len(raw) % 2 != 1 or 0 in raw[:-1]:
        raise ValueError('Invalid byte-NUL catalog payload')
    return sum(6 if raw[i:i+2] == HALF_SPACE else 12 for i in range(0,len(raw)-1,2))


def validate_manifest(manifest, baseline):
    fields = {'format','purpose','source_disc_sha256','source_exe_sha256',
              'baseline_sha256','character_map_sha256','edits'}
    if not isinstance(manifest,dict) or set(manifest) != fields:
        raise ValueError('Unexpected/missing catalog manifest fields')
    if type(manifest['format']) is not int or manifest['format'] != 1 or manifest['purpose'] != 'development-only':
        raise ValueError('Unsupported catalog manifest policy')
    expected = dict(source_disc_sha256=SOURCES['kor'][1],
                    source_exe_sha256=baseline['source_file_sha256']['kor'],
                    baseline_sha256=digest(baseline),
                    character_map_sha256=baseline['character_map_sha256'])
    if any(manifest[k] != v for k,v in expected.items()):
        raise ValueError('Catalog source/baseline binding differs; re-export')
    if not isinstance(manifest['edits'],list):
        raise ValueError('Catalog edits must be a list')
    seen = set()
    for e in manifest['edits']:
        if (not isinstance(e,dict) or set(e) != {'id','expected_hex','text'} or
                any(not isinstance(v,str) for v in e.values())):
            raise ValueError('Unexpected catalog edit fields/types')
        if e['id'] in seen:
            raise ValueError('Duplicate catalog writer: '+e['id'])
        seen.add(e['id'])


def prepare(exe, baseline, manifest, mapping):
    validate_manifest(manifest,baseline)
    if sha(exe) != baseline['source_file_sha256']['kor']:
        raise ValueError('Catalog EXE source differs')
    rows = {r['id']:r for r in baseline['entries']}
    writes, records, entries = [], [], []
    descriptors = bytearray(2048)
    resident_cursor = len(descriptors)
    from technique_insert import KINDS, validate as validate_technique, help_layout
    selected = {e['id']:e for e in manifest['edits']}
    technique_rows = [r for r in rows.values() if r['category'] in KINDS]
    technique_raw = {r['id']:encode_text(r, selected[r['id']]['text'], mapping)
                     if r['id'] in selected else bytes.fromhex(r['raw']['kor'])
                     for r in technique_rows}
    def write(key,at,value):
        writes.append(dict(id=key,file=EXE,file_offset=at,
                           before=exe[at:at+len(value)].hex(),after=value.hex()))
    for edit in sorted(manifest['edits'], key=lambda e:e['id']):
        key = edit['id']
        if key not in rows:
            raise ValueError('Unknown catalog ID: '+key)
        row = rows[key]
        if edit['expected_hex'] != row['raw']['kor']:
            raise ValueError('Stale catalog bytes: '+key)
        old = bytes.fromhex(row['raw']['kor'])
        loc = row['locations']['kor']
        at = loc['logical_offset']
        if exe[at:at+len(old)] != old:
            raise ValueError('Catalog payload differs: '+key)
        try:
            new = encode_text(row,edit['text'],mapping)
            width = pixel_width(new)
            if width > MAX_PIXELS:
                raise ValueError(f'Row exceeds {MAX_PIXELS}px: {width}px; no clipping allowed')
            if loc['reference_kind'] == 'record' and len(new)>INLINE_BYTES:
                raise ValueError(f'Inline name needs {len(new)} bytes including NUL; '
                                 f'field is {INLINE_BYTES} bytes. Record relocation is unresolved')
        except ValueError as exc:
            raise ValueError(key+': '+str(exc)) from exc
        if row['category']=='technique_name':
            continue  # Whole table is repacked atomically below.
        if new == old:
            continue
        entry = dict(id=key,category=row['category'],old_bytes=len(old),new_bytes=len(new),
                     pixel_width=width,expanded_hex=new.hex(),source_logical_offset=at,
                     source_reference_offset=loc['reference_logical_offset'])
        if row['category']=='technique_help':
            validate_technique(row,new,old,pixel_width)
            index=len(records)
            if (index+1)*4>resident_cursor:
                raise ValueError('Catalog descriptor region overflow')
            struct.pack_into('<HH',descriptors,index*4,0x020f,index)
            records.append(new.ljust(2048,b'\0'))
            pointer=DESCRIPTOR_RAM+index*4
            write(key+'-pointer',loc['reference_logical_offset'],struct.pack('<I',pointer))
            entry.update(policy='independent-CD-record',record=index,target_ram=pointer)
        elif loc['reference_kind'] == 'record':
            # Preserve all bytes after the new NUL, including numeric fields.
            write(key,at,new)
            entry.update(policy='inline-field',target_ram=RAM_BASE+at)
        elif row['category']=='location_name':
            # Locations also reach BIOS strcpy/strlen and save-label copies.
            # Keep their pointers valid C strings, not renderer descriptors.
            resident_cursor=(resident_cursor-len(new))&~1
            if resident_cursor < len(records)*4:
                raise ValueError('Resident location/catalog directory capacity exceeded')
            descriptors[resident_cursor:resident_cursor+len(new)]=new
            pointer=DESCRIPTOR_RAM+resident_cursor
            write(key+'-pointer',loc['reference_logical_offset'],struct.pack('<I',pointer))
            entry.update(policy='resident-directory-string',target_ram=pointer,
                         directory_offset=0x1800+resident_cursor)
        else:
            index = len(records)
            if (index+1)*4 > resident_cursor:
                raise ValueError('Catalog descriptor region overflow')
            struct.pack_into('<HH',descriptors,index*4,0x020f,index)
            records.append(new.ljust(2048,b'\0'))
            pointer = DESCRIPTOR_RAM+index*4
            write(key+'-pointer',loc['reference_logical_offset'],struct.pack('<I',pointer))
            entry.update(policy='independent-CD-record',record=index,target_ram=pointer)
        entries.append(entry)
    from technique_insert import repack_names
    name_writes,name_entries,name_bytes=repack_names(exe,technique_rows,technique_raw,pixel_width)
    writes.extend(name_writes)
    entries.extend(name_entries)
    wording_changed=sum(e.get('wording_changed',True) for e in entries)
    help_writes,help_sprites=help_layout(exe,technique_rows,technique_raw,pixel_width)
    writes.extend(help_writes)
    return writes,records,bytes(descriptors),dict(format=1,entries=entries,
        selected=len(manifest['edits']),changed=wording_changed,unchanged=len(manifest['edits'])-wording_changed,
        half_space_hex=HALF_SPACE.hex(),half_space_pixels=6,inline_field_bytes=INLINE_BYTES,
        descriptor_ram=DESCRIPTOR_RAM,descriptor_bytes=len(records)*4,
        resident_location_bytes=sum((e['new_bytes']+1)&~1 for e in entries
                                    if e['category']=='location_name' and e['policy']=='resident-directory-string'),
        resident_directory_string_bytes=len(descriptors)-resident_cursor,
        resident_technique_bytes=name_bytes,technique_pool_capacity=0xA135C-0xA0BD4,
        original_pointer_strings_preserved=not name_entries,
        technique_help_sprites=help_sprites,
        technique_help_icon_cells={'technique_help-003':8,'technique_help-004':11},
        shared_pointers_split_per_entry=True,
        runtime_verified=False,release_eligible=False,
        limitations=['Inline names exceeding 20 bytes including NUL require further consumer work',
                     'Technique names share a 1928-byte always-resident EXE pool',
                     'Packed help rows retain original glyph counts and fragment anchors',
                     'Resident locations and description descriptors must share 2048 directory bytes',
                     '252px is renderer capacity, not verified window width',
                     'Locations and CD descriptors require DG initialization; technique names do not',
                     'CD streaming and all UI/overlay screens need gameplay verification'])


def compile_renderer(exe, helper_ram, output):
    if sha(exe[GENERAL_START:GENERAL_END]) != GENERAL_SHA:
        raise ValueError('Generic renderer source revision differs')
    output.mkdir(parents=True)
    source=f'.equ CATALOG_HELPER, {helper_ram}\n'+(ROOT/'tools/catalog_renderer.s').read_text()
    code=assemble(source,output,'generic')
    if len(code)>GENERAL_END-GENERAL_START:
        raise ValueError('Generic renderer exceeds original code extent')
    value=code.ljust(GENERAL_END-GENERAL_START,b'\0')
    verify_machine_code(value,RAM_BASE+GENERAL_START,output/'generic-addressed.asm')
    return dict(id='catalog-generic-renderer',file=EXE,file_offset=GENERAL_START,
                before=exe[GENERAL_START:GENERAL_END].hex(),after=value.hex())


def verify_machine_code(code, base, path):
    """Final-address decode and R3000 load/control delay checks after assembly."""
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
    from capstone.mips import MIPS_OP_REG, MIPS_OP_MEM
    decoder=Cs(CS_ARCH_MIPS,CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN);decoder.detail=True
    instructions=list(decoder.disasm(code,base))
    if len(instructions)*4!=len(code):raise ValueError('Incomplete catalog MIPS decode')
    control=lambda i: i.mnemonic.startswith('b') or i.mnemonic in ('j','jal','jr','jalr')
    for ins,nxt in zip(instructions,instructions[1:]):
        if ins.mnemonic in ('lw','lh','lhu','lb','lbu'):
            dest=ins.operands[0].reg
            sources=nxt.operands if control(nxt) or nxt.mnemonic in ('sw','sh','sb') else nxt.operands[1:]
            if any((p.type==MIPS_OP_REG and p.reg==dest) or
                   (p.type==MIPS_OP_MEM and p.mem.base==dest) for p in sources):
                raise ValueError(f'Catalog load delay hazard: {ins.address:x}')
        if control(ins) and control(nxt):raise ValueError('Control transfer in catalog delay slot')
        if ins.mnemonic.startswith('b'):
            target=ins.operands[-1].imm
            if target%4 or not base<=target<base+len(code):
                raise ValueError('Catalog branch leaves assembled code')
    path.write_text('\n'.join(f'{i.address:08x} {i.mnemonic} {i.op_str}' for i in instructions)+'\n')


def verify_reinsertion(exe, dg, bank_offset, report, baseline, original):
    """Re-extract every catalog entry, including unchanged aliases and records."""
    edited={e['id']:e for e in report['entries']}
    for row in baseline['entries']:
        loc=row['locations']['kor']; at=loc['logical_offset']
        entry=edited.get(row['id'])
        wanted=bytes.fromhex(entry['expanded_hex'] if entry else row['raw']['kor'])
        if loc['reference_kind']=='record':
            actual=exe[at:at+len(wanted)]
            stride=32 if row['category']=='item_name' else 52
            if exe[at+INLINE_BYTES:at+stride]!=original[at+INLINE_BYTES:at+stride]:
                raise ValueError('Numeric record fields changed: '+row['id'])
        else:
            ref=loc['reference_logical_offset']
            pointer=struct.unpack_from('<I',exe,ref)[0]
            if entry:
                if pointer!=entry['target_ram']:
                    raise ValueError('Catalog pointer target differs: '+row['id'])
                descriptor=0x1800+pointer-DESCRIPTOR_RAM
                if entry['policy']=='resident-technique-pool':
                    from technique_insert import POOL_START, POOL_END
                    target=pointer-RAM_BASE
                    if not POOL_START<=target<target+len(wanted)<=POOL_END:
                        raise ValueError('Technique pointer outside resident pool')
                    if exe[target:target+len(wanted)]!=wanted:
                        raise ValueError('Technique re-extraction differs: '+row['id'])
                    continue
                elif entry['policy']=='resident-directory-string':
                    start=descriptor
                else:
                    if dg[descriptor:descriptor+4]!=struct.pack('<HH',0x020f,entry.get('packed_offset',entry['record'])):
                        raise ValueError('Catalog descriptor differs: '+row['id'])
                    start=bank_offset+entry.get('packed_offset',entry['record']*2048)
                actual=dg[start:start+len(wanted)]
            else:
                if pointer!=RAM_BASE+at:
                    raise ValueError('Unedited catalog pointer changed: '+row['id'])
                actual=exe[at:at+len(wanted)]
            if exe[at:at+len(bytes.fromhex(row['raw']['kor']))]!=bytes.fromhex(row['raw']['kor']):
                raise ValueError('Shared original string overwritten: '+row['id'])
        if actual!=wanted:
            raise ValueError('Catalog re-extraction differs: '+row['id'])


def export(directory, output, ids):
    from dg_analyze import read_source
    workspace=Workspace(directory)
    path=ROOT/'work/text/character-map.json'
    mapping=json.loads(path.read_text())
    inputs={lang:read_source(lang)[EXE] for lang in SOURCES}
    baseline=extract(inputs,mapping,sha(path.read_bytes()))
    if baseline != workspace.baseline:
        raise ValueError('Catalog baseline differs from immutable sources')
    reviews=workspace.load()['entries']
    selected=ids if ids else sorted(reviews)
    if len(set(selected))!=len(selected) or any(key not in workspace.rows for key in selected):
        raise ValueError('Unknown or duplicate catalog ID')
    edits=[]
    for key in selected:
        row=workspace.rows[key]
        review=reviews.get(key)
        if review and review['status']=='held':
            raise ValueError('Held catalog entry: '+key)
        edits.append(dict(id=key,expected_hex=row['raw']['kor'],
                          text=review['text'] if review else row['existing']))
    manifest=dict(format=1,purpose='development-only',source_disc_sha256=SOURCES['kor'][1],
        source_exe_sha256=sha(inputs['kor']),baseline_sha256=digest(baseline),
        character_map_sha256=sha(path.read_bytes()),edits=edits)
    if output.exists() or not output.resolve().is_relative_to((ROOT/'work').resolve()):
        raise ValueError('Choose a new manifest under work/')
    output.parent.mkdir(parents=True,exist_ok=True)
    write_json(output,manifest)
    return dict(selected=len(edits),output=str(output))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,default=ROOT/'work/translation/catalog')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--id',action='append',default=[])
    a=p.parse_args()
    print(json.dumps(export(a.directory,a.output,a.id),ensure_ascii=False))
