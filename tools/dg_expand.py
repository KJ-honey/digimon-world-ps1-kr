#!/usr/bin/env python3
"""Development DG text bank: preserve script offsets, load changed text on demand.

An opt-in companion to dg_build.py; consumes the same edit manifest. Does not
change translation sources. See docs/dialogue-expansion.md for proof limits.
"""
import argparse
import json
import struct
from pathlib import Path

from build import OFFSET, BEFORE, AFTER
from cd_sector import regenerate
from dg_analyze import verified_texts
from dg_build import sector_plan
from dg_script import decode, text_tokens
from dg_spacing import dialogue_codec, is_half_space
from dg_control_restorations import restoration_allowed
from dg_line_reflows import reflow_allowed
from dg_layout import (DYNAMIC_BYTES, DYNAMIC_TABLE_MAX_CHARS,
                       DYNAMIC_TABLE_OPCODES, MAX_LINE_PIXELS, validate_encoded_layout)
from dg_pixel_row import compile_pixel_row
from font_expand import assemble, compile_font
from glyph_review import SOURCE
from match_gulim import DEFAULT_FONT
from restore_text import restore
from survey import ROOT, SOURCES, Disc, dual32, sha, write_json

SHIFT = 0x1800
DIRECTORY_RAM = 0x8015f784
CODE_RAM = DIRECTORY_RAM + 0x800
SCRATCH_RAM = DIRECTORY_RAM + 0x1000
HOOK = 0x64200
HOOK_BEFORE = bytes.fromhex('d0ffbd271c00bfaf')
MARKER = b'\x15\xd7'
BLOCK = 2048


def validate_manifest(manifest):
    fields={'format','purpose','source_disc_sha256','source_dg_sha256',
            'character_map_sha256','edits'}
    if not isinstance(manifest,dict) or set(manifest)!=fields:
        raise ValueError('Unexpected/missing manifest fields')
    if type(manifest['format']) is not int or manifest['format']!=1:
        raise ValueError('Unsupported manifest format')
    if not isinstance(manifest['edits'],list) or any(
            not isinstance(manifest[k],str) for k in fields-{'format','edits'}):
        raise ValueError('Invalid manifest field types')
    for edit in manifest['edits']:
        if (not isinstance(edit,dict) or set(edit)!={'id','expected_hex','text'}
                or any(not isinstance(v,str) for v in edit.values())):
            raise ValueError('Unexpected edit fields/types')


def validate_text(old, new, codec, *, entry_id=None):
    """Preserve ordered controls/symbols except the verified 0F00 whitespace."""
    old_end, before = text_tokens(old, 0, len(old))
    new_end, after = text_tokens(new, 0, len(new))
    if old_end != len(old) or new_end != len(new):
        raise ValueError('Early terminator/trailing text')
    protected = lambda ts: [(t['kind'], t['raw']) for t in ts
                           if not is_half_space(t, codec) and
                           (t['kind'] != 'glyph' or codec.mapping.get(t['raw'].upper()) is None)]
    restored = protected(before) != protected(after)
    reflowed = reflow_allowed(entry_id, old, protected(after))
    if restored and not restoration_allowed(entry_id, old, protected(after)) and not reflowed:
        raise ValueError('Protected control/argument/unknown glyph sequence changed')
    # Output rows have a 64-byte stride, independent of source allocation.
    # Dynamic insertion budgets require a separately established environment.
    row = 0
    budgets = []
    for token in after:
        raw = bytes.fromhex(token['raw'])
        if token['kind'] == 'terminator':
            continue
        if (token['kind'] == 'control' and raw[0] not in (0, 1, 2, 3, 12, 13, 14, 15)
                and raw[0] not in DYNAMIC_BYTES):
            raise ValueError('Dynamic insertion row budget is not established for expanded text')
        row += DYNAMIC_BYTES.get(raw[0], len(raw)) if token['kind']=='control' else len(raw)
        if row > 64:
            raise ValueError('Expanded output row exceeds 64-byte consumer stride')
        if raw[0] == 13:
            budgets.append(row)
            row = 0
    if len(new)+9 > BLOCK:
        raise ValueError('Expanded text exceeds one-sector bank record')
    if reflowed:
        validate_encoded_layout(after)
    if restored and not reflowed:
        # These reviewed restorations use full-width glyphs, 01 colors, 05
        # player names, 0F spaces and 0D row breaks only. The real glyph
        # uploader refuses origins >= 244; test the six-character name case.
        x = 0
        for token in after:
            raw = bytes.fromhex(token['raw'])
            if token['kind'] == 'glyph':
                if raw != b'\x81\x40' and x >= 244:
                    raise ValueError('Restored text exceeds DG glyph start limit (X < 244); review line layout')
                x += 12
            elif raw[0] == 5:
                if x + DYNAMIC_BYTES[5] // 2 * 12 - 12 >= 244:
                    raise ValueError('Restored text exceeds DG glyph start limit (X < 244); review line layout')
                x += DYNAMIC_BYTES[5] // 2 * 12
            elif raw[0] == 15:
                x += 6
            elif raw[0] == 13:
                x = 0
            elif raw[0] not in (0, 1):
                raise ValueError('Unreviewed layout command in control restoration')
    return budgets


def prepare_bank(data, parsed, edits, codec):
    texts = verified_texts(parsed)
    changed = bytearray(data)
    records, entries, seen = [], [], set()
    overlap = {p for pair in parsed['overlaps'] for p in pair}
    for edit in sorted(edits, key=lambda e: e['id']):
        key = edit['id']
        if key in seen:
            raise ValueError('Duplicate writer: '+key)
        seen.add(key)
        if key not in texts or texts[key]['instruction'] in overlap:
            raise ValueError('No unambiguous consumer-verified boundary: '+key)
        t = texts[key]
        old = data[t['payload']:t['end']]
        if edit['expected_hex'] != old[:-2].hex():
            raise ValueError('Stale source text: '+key)
        new = codec.encode(edit['text']) + old[-2:]
        validate_encoded_layout(text_tokens(new, 0, len(new))[1])
        if new == old:
            continue
        if len(old) < 4 or len(old) > 65535 or len(records) >= 65536:
            raise ValueError('Descriptor/record representation overflow: '+key)
        try:
            budgets = validate_text(old, new, codec, entry_id=key)
        except ValueError as exc:
            raise ValueError(f'{key}: {exc}') from exc
        index = len(records)
        # Original continuation length, expanded length, record signature.
        record = struct.pack('<HH4s', len(old), len(new), b'DGB1') + new
        records.append(record.ljust(BLOCK, b'\0'))
        changed[t['payload']:t['payload']+4] = MARKER + struct.pack('<H', index)
        entries.append({'id': key, 'script': t['script'], 'source_payload': t['payload'],
                        'source_end': t['end'], 'record': index, 'old_bytes': len(old),
                        'new_bytes': len(new), 'row_output_bytes': budgets,
                        'expanded_hex': new.hex()})
    # Source text is never parsed as descriptor bytes. Restoring the declared
    # four-byte descriptors must reconstruct every source byte exactly.
    restored = bytearray(changed)
    for entry in entries:
        at = entry['source_payload']
        restored[at:at+4] = data[at:at+4]
    if bytes(restored) != data:
        raise ValueError('Unplanned DG mutation')
    return bytes(changed), records, entries


def compile_bank(exe, bank_offset, output, catalog_bank_offset=None):
    if exe[HOOK:HOOK+8] != HOOK_BEFORE:
        raise ValueError('Text consumer hook revision mismatch')
    output.mkdir(parents=True)
    template = (ROOT/'tools/dg_bank.s').read_text()
    definitions = {'BANK': bank_offset, 'SCRATCH': SCRATCH_RAM, 'TRAMPOLINE': CODE_RAM}
    def source():
        return ''.join(f'.equ {k}_HI, {v>>16}\n.equ {k}_LO, {v&65535}\n'
                       for k,v in definitions.items()) + template
    initial = assemble(source(), output, 'bank-sizing')
    definitions['TRAMPOLINE'] = CODE_RAM + len(initial)-24
    code = assemble(source(), output, 'bank')
    if len(code) != len(initial) or len(code) > BLOCK:
        raise ValueError('Bank helper code budget mismatch')
    if catalog_bank_offset is not None:
        from catalog_insert import HELPER_OFFSET
        if len(code)>HELPER_OFFSET:
            raise ValueError('DG/catalog helper overlap')
        suffix=(f'.equ CATALOG_BANK_HI, {catalog_bank_offset>>16}\n'
                f'.equ CATALOG_BANK_LO, {catalog_bank_offset&65535}\n'
                f'.org {HELPER_OFFSET}\n'+(ROOT/'tools/catalog_bank.s').read_text())
        combined=assemble(source()+suffix,output,'bank-catalog')
        if combined[:len(code)]!=code or len(combined)>BLOCK:
            raise ValueError('Catalog helper composition differs/overflows')
        code=combined
        from catalog_insert import verify_machine_code
        verify_machine_code(code,CODE_RAM,output/'catalog-addressed.asm')
    # An absolute J stays in the same 256 MiB region; this fixed instruction
    # is independently decoded by Capstone and checked against its target.
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
    hook = struct.pack('<II', 0x08000000 | ((CODE_RAM >> 2) & 0x3ffffff), 0)
    cs = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    decoded = list(cs.disasm(hook, 0x80090000+HOOK))
    if [(i.mnemonic, i.op_str) for i in decoded] != [('j', hex(CODE_RAM)), ('nop', '')]:
        raise ValueError('Hook decode mismatch')
    (output/'bank-addressed.asm').write_text('\n'.join(
        f'{i.address:08x} {i.mnemonic} {i.op_str}' for i in cs.disasm(code,CODE_RAM))+'\n')
    return code, {'id':'dg-bank-consumer', 'file':'SLPS_017.97', 'file_offset':HOOK,
                  'before':HOOK_BEFORE.hex(), 'after':hook.hex()}


def directory_record(disc, path):
    """Return the exact ISO directory record location, not a byte-pattern hit."""
    pvd = disc.read(16, BLOCK)
    lba, size = dual32(pvd[156:],2), dual32(pvd[156:],10)
    parts = path.split('/')
    for depth, name in enumerate(parts):
        data = disc.read(lba,size)
        at = 0
        matches = []
        while at < len(data):
            n = data[at]
            if not n:
                at = (at//BLOCK+1)*BLOCK
                continue
            if n < 34 or at+n > len(data) or at%BLOCK+n > BLOCK:
                raise ValueError('Invalid ISO directory record')
            record = data[at:at+n]
            if record[33:33+record[32]].decode('ascii').removesuffix(';1') == name:
                matches.append((at,record))
            at += n
        if len(matches) != 1:
            raise ValueError('Missing/duplicate directory entry: '+name)
        at, record = matches[0]
        if depth == len(parts)-1:
            return lba+at//BLOCK, at%BLOCK, record
        if not record[25]&2:
            raise ValueError('Non-directory path component')
        lba,size = dual32(record,2),dual32(record,10)


def new_sector(lba, payload, subheader):
    if len(payload)!=BLOCK or len(subheader)!=4 or subheader[2]&0x20:
        raise ValueError('Expected Form 1 payload/subheader')
    address = lba+150
    minute, rem = divmod(address,4500)
    second, frame = divmod(rem,75)
    if minute > 99:
        raise ValueError('CD MSF address overflow')
    bcd = lambda n: (n//10)*16+n%10
    header = b'\0'+b'\xff'*10+b'\0'+bytes(map(bcd,(minute,second,frame)))+b'\2'
    return regenerate(header+subheader*2+payload+bytes(280))


def image_plan(disc, table, writes, dg):
    plan = sector_plan(disc,table,writes)
    source_count = len(disc.raw)//2352
    start = source_count
    count = len(dg)//BLOCK
    if len(dg)%BLOCK:
        raise ValueError('Bank DG must have complete sectors')
    record_lba, at, record = directory_record(disc,'SCN/DG.SCN')
    updates = [(record_lba,at+2, struct.pack('<I',start)+struct.pack('>I',start)),
               (record_lba,at+10, struct.pack('<I',len(dg))+struct.pack('>I',len(dg))),
               (16,80,struct.pack('<I',start+count)+struct.pack('>I',start+count))]
    if dual32(disc.read(16,BLOCK),80) != source_count:
        raise ValueError('PVD volume size differs from input track')
    sectors = {}
    for lba,offset,value in updates:
        if lba in plan:
            raise ValueError('Filesystem/data writer overlap')
        original = disc.sector(lba)
        if regenerate(original)!=original:
            raise ValueError('Source filesystem sector protection mismatch')
        candidate = sectors.setdefault(lba,bytearray(original))
        candidate[24+offset:24+offset+len(value)] = value
    plan.update({lba:regenerate(raw) for lba,raw in sectors.items()})
    # File's original XA channel/submode is reused; EOF/EOR are not invented.
    subheader = disc.sector(table['SCN/DG.SCN']['lba'])[16:20]
    for i in range(count):
        plan[start+i] = new_sector(start+i,dg[i*BLOCK:(i+1)*BLOCK],subheader)
    return plan, dict(table['SCN/DG.SCN'],lba=start,size=len(dg)), updates


def build(edits_path, output, expand_font=False, name_entry=False, catalog_edits=None):
    if name_entry and not expand_font: raise ValueError("--name-entry requires --expand-font")
    if catalog_edits and not expand_font: raise ValueError('--catalog-edits requires --expand-font')
    if output.exists() or not output.resolve().is_relative_to((ROOT/'work').resolve()):
        raise ValueError('Choose a new output directory under work/')
    manifest = json.loads(edits_path.read_text())
    validate_manifest(manifest)
    disc = Disc(ROOT/SOURCES['kor'][0])
    try:
        if sha(disc.raw)!=SOURCES['kor'][1] or manifest['source_disc_sha256']!=SOURCES['kor'][1]:
            raise ValueError('Unsupported source disc')
        table = disc.files()
        read = lambda name: disc.read(table[name]['lba'],table[name]['size'])
        data,exe,mirror = (read(n) for n in ('SCN/DG.SCN','SLPS_017.97','SCN/MAPHEAD.SCN'))
        if sha(data)!=manifest['source_dg_sha256'] or data[0x800:0x800+len(mirror)]!=mirror:
            raise ValueError('DG source binding/mirror differs')
        if MARKER in data:
            raise ValueError('Descriptor marker collides with source DG')
        output.mkdir(parents=True)
        restore(output/'verified-text',ROOT/'work/survey',SOURCE.parent,DEFAULT_FONT)
        map_path = output/'verified-text/character-map.json'
        if sha(map_path.read_bytes())!=manifest['character_map_sha256']:
            raise ValueError('Character map changed; re-export')
        mapping = json.loads(map_path.read_text())
        catalog_baseline = catalog_manifest = None
        if catalog_edits:
            from dg_analyze import read_source
            from translation_catalog import extract
            catalog_baseline=extract({'kor':exe,'jpn':read_source('jpn')['SLPS_017.97']},
                                     mapping,sha(map_path.read_bytes()))
            catalog_manifest=json.loads(catalog_edits.read_text())
        writes, font_report, pixel_report = [], None, None
        if expand_font:
            mapping,font_writes,font_report = compile_font(exe,mapping,output/'font', name_entry=name_entry)
            pixel_writes,pixel_report = compile_pixel_row(exe,font_writes,font_report,output/'pixel-row')
            name_report = None
            if name_entry:
                from name_entry import compile_names
                name_writes,name_report=compile_names(read('SHOP_REL.BIN'),mapping,font_writes,font_report,pixel_report,output/'name')
                writes.extend(name_writes)
            writes.extend(font_writes)
            writes.extend(pixel_writes)
        codec = dialogue_codec(mapping)
        parsed = decode(data)
        changed,records,entries = prepare_bank(data,parsed,manifest['edits'],codec)
        catalog_records, descriptors, catalog_report = [], bytes(BLOCK), None
        if catalog_edits:
            from catalog_insert import prepare, compile_renderer, HELPER_OFFSET
            catalog_writes,catalog_records,descriptors,catalog_report=prepare(
                exe,catalog_baseline,catalog_manifest,mapping)
            writes.extend(catalog_writes)
            if catalog_report['changed']:
                writes.append(compile_renderer(exe,CODE_RAM+HELPER_OFFSET,output/'catalog'))
        if not expand_font:
            for entry in entries:
                payload = bytes.fromhex(entry['expanded_hex'])
                if any(is_half_space(t,codec) for t in text_tokens(payload,0,len(payload))[1]):
                    raise ValueError('Exact DG half spaces require --expand-font (pixel row renderer)')
        if not entries and not (catalog_report and catalog_report['changed']):
            raise ValueError('No changed text; use dg_build.py for byte-identical no-op builds')
        bank_offset = len(data)+SHIFT
        catalog_offset=bank_offset+len(records)*BLOCK
        has_catalog=bool(catalog_report and catalog_report['changed'])
        code,hook = compile_bank(exe,bank_offset,output/'bank',catalog_offset if has_catalog else None)
        header = bytearray(data[:0x800])
        bounds = [s['base'] for s in parsed['scripts']] + [len(data)]
        struct.pack_into('<226I',header,0,*(b+SHIFT for b in bounds))
        expanded_dg = (bytes(header)+code.ljust(BLOCK,b'\0')+bytes(BLOCK)+descriptors+
                       changed[0x800:]+b''.join(records+catalog_records))
        if expanded_dg[bank_offset:]!=b''.join(records+catalog_records):
            raise ValueError('Bank layout mismatch')
        for e in entries:
            if e['script']==0:
                at = e['source_payload']-0x800
                if at+4>len(mirror):
                    raise ValueError('Descriptor outside MAPHEAD')
                writes.append({'id':e['id']+'-descriptor','file':'SCN/MAPHEAD.SCN','file_offset':at,
                               'before':mirror[at:at+4].hex(), 'after':changed[at+0x800:at+0x804].hex()})
        writes.append(hook)
        # The catalog renderer contains byte loads and owns this whole function.
        if not has_catalog:
            writes.append({'id':'alignment-repair','file':'SLPS_017.97','file_offset':OFFSET,
                           'before':BEFORE.hex(),'after':AFTER.hex()})
        plan,new_extent,metadata = image_plan(disc,table,writes,expanded_dg)
        target_count = new_extent['lba']+len(expanded_dg)//BLOCK
        image = output/'dg-expanded.iso'
        with image.open('xb') as f:
            for lba in range(target_count):
                f.write(plan[lba] if lba in plan else disc.sector(lba))
        final = Disc(image)
        try:
            expected_table = dict(table,**{'SCN/DG.SCN':new_extent})
            if final.files()!=expected_table or len(final.raw)!=target_count*2352:
                raise ValueError('Final filesystem/length differs from plan')
            for lba in range(target_count):
                expected = plan[lba] if lba in plan else disc.sector(lba)
                if final.sector(lba)!=expected:
                    raise ValueError(f'Unexplained final sector: {lba}')
            if final.read(new_extent['lba'],new_extent['size'])!=expanded_dg:
                raise ValueError('Final DG differs')
            mf = table['SCN/MAPHEAD.SCN']
            if final.read(mf['lba'],mf['size'])!=changed[0x800:0x800+len(mirror)]:
                raise ValueError('Final MAPHEAD differs')
            for filename in sorted({w['file'] for w in writes}):
                expected=bytearray(read(filename))
                for w in writes:
                    if w['file']==filename:
                        pos=w['file_offset'];value=bytes.fromhex(w['after'])
                        expected[pos:pos+len(value)]=value
                ff=table[filename]
                if final.read(ff['lba'],ff['size'])!=expected:
                    raise ValueError('Final re-extraction differs: '+filename)
            if catalog_report:
                from catalog_insert import verify_reinsertion
                ff=table['SLPS_017.97']
                verify_reinsertion(final.read(ff['lba'],ff['size']),expanded_dg,catalog_offset,
                                   catalog_report,catalog_baseline,exe)
            result_hash = sha(final.raw)
        finally:
            final.close()
        report = {'format':1,'status':'development-only','release_eligible':False,
                  'source_sha256':SOURCES['kor'][1],'output_sha256':result_hash,
                  'source_dg_sha256':sha(data),'dg_sha256':sha(expanded_dg),
                  'bank_offset':bank_offset,'code_ram':CODE_RAM,'scratch_ram':SCRATCH_RAM,
                  'script_file_offset_shift':SHIFT,'script_ram_offsets_unchanged':True,
                  'entries':entries,'writes':writes,'new_dg_extent':new_extent,
                  'catalog':dict(catalog_report,bank_file_offset=catalog_offset) if catalog_report else None,
                  'name_entry':name_report if name_entry else None,
                  'font_expansion':font_report,'metadata_writes':[
                      {'lba':l,'payload_offset':a,'after':v.hex()} for l,a,v in metadata],
                  'appended_sector_count':target_count-len(disc.raw)//2352,
                  'changed_original_lbas':sorted(l for l in plan if l<len(disc.raw)//2352),
                  'full_image_diff_verified':True,'reextraction_verified':True,
                  'gameplay_runtime_verified':False,
                  'spacing':{'ascii_space':'0F00 / 6 px',
                             'ideographic_space':'8140 / 12 px',
                             'bytes_per_space':2,'renderer_code_changed':bool(pixel_report),
                             'pixel_row':pixel_report},
                  'dynamic_table_max_characters':DYNAMIC_TABLE_MAX_CHARS,
                  'max_line_pixels':MAX_LINE_PIXELS,
                  'limitations':['protected streams require source-bound restoration/reflow rules', f'{MAX_LINE_PIXELS}px rows under declared dynamic budgets', 'dynamic table ceiling is user-specified, not independently measured',
                                 'extra synchronous CD read for each changed text',
                                 'full native/overlay caller and streaming regression pending']}
        write_json(output/'build.json',report)
        write_json(output/'edits.json',manifest)
        if catalog_manifest:
            write_json(output/'catalog-edits.json',catalog_manifest)
        (output/'dg-expanded.cue').write_text('FILE "dg-expanded.iso" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
        return {k:v for k,v in report.items() if k not in ('entries','writes','font_expansion')}
    finally:
        disc.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--edits',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--expand-font',action='store_true')
    p.add_argument('--name-entry',action='store_true')
    p.add_argument('--catalog-edits',type=Path,help='Non-DG source-bound edit manifest')
    a=p.parse_args()
    print(json.dumps(build(a.edits,a.output,a.expand_font,a.name_entry,a.catalog_edits),ensure_ascii=False,indent=2))
