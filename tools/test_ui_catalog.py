"""Revision-bound extraction and spacing regression checks (no ISO writes)."""
import json
import unittest

from dg_analyze import read_source
from menu_layout import memory_card_writes, title_writes
from survey import ROOT, sha
from translation_catalog import extract
from catalog_insert import prepare
from translation_review import digest
from survey import SOURCES


class UICatalogTests(unittest.TestCase):
    def test_composite_legend_does_not_overlap_or_clip(self):
        from technique_insert import legend_positions
        # Reported regression: prefix [-102,96), suffix [66,126).
        self.assertEqual(legend_positions(198,60),(-114,84,-132))
        for prefix,suffix in [(168,60),(198,60),(198,72),(120,60)]:
            x,suffix_x,icon_x=legend_positions(prefix,suffix)
            self.assertEqual(suffix_x,x+prefix)
            self.assertGreaterEqual(icon_x,-146)
            self.assertLessEqual(icon_x+12,x)
            self.assertLessEqual(suffix_x+suffix,146)
        with self.assertRaisesRegex(ValueError,'Combined'):
            legend_positions(216,72)

    @classmethod
    def setUpClass(cls):
        cls.inputs = {lang: read_source(lang)['SLPS_017.97'] for lang in SOURCES}
        path = ROOT/'work/text/character-map.json'
        cls.mapping = json.loads(path.read_text())
        cls.baseline = extract(cls.inputs, cls.mapping, sha(path.read_bytes()))

    def test_table_population_aliases_and_roundtrip(self):
        rows = self.baseline['entries']
        names = [r for r in rows if r['category'] == 'technique_name']
        help_rows = [r for r in rows if r['category'] == 'technique_help']
        self.assertEqual(len(names), 121)
        self.assertEqual(len(help_rows), 10)
        self.assertEqual(len({r['id'] for r in rows}), 637)
        self.assertEqual(names[2]['source'], 'スピットファイアー')
        self.assertEqual(names[44]['raw'], names[48]['raw'])
        self.assertEqual([r['locations']['kor']['reference_logical_offset'] for r in help_rows],
                         [0xA0734, 0xA073C] + list(range(0xA0744, 0xA0764, 4)))
        for row in names+help_rows:
            for lang, exe in self.inputs.items():
                raw = bytes.fromhex(row['raw'][lang])
                at = row['locations'][lang]['logical_offset']
                self.assertEqual(exe[at:at+len(raw)], raw)
                self.assertEqual(b''.join(bytes.fromhex(t['raw']) for t in row['tokens'][lang]), raw)

    def test_memory_spacing_changes_only_complete_space_units(self):
        exe = self.inputs['kor']
        writes = memory_card_writes(exe)
        self.assertEqual(len(writes), 46)
        self.assertEqual(sum(bytes.fromhex(w['after']).count(b'\x0f\x01') for w in writes), 76)
        occupied = set()
        for w in writes+title_writes(exe):
            old, new = bytes.fromhex(w['before']), bytes.fromhex(w['after'])
            self.assertEqual(len(old), len(new))
            self.assertEqual(old[-1:], new[-1:])
            for i in range(0, len(old)-1, 2):
                if old[i:i+2] != new[i:i+2]:
                    self.assertEqual((old[i:i+2], new[i:i+2]), (b'\x81\x40', b'\x0f\x01'))
            span = set(range(w['file_offset'], w['file_offset']+len(old)))
            self.assertFalse(span & occupied)
            occupied.update(span)
        bad = bytearray(exe)
        bad[0x7BFBC] ^= 1
        with self.assertRaisesRegex(ValueError, 'revision differs'):
            memory_card_writes(bytes(bad))

    def test_technique_names_remain_c_strings_and_grow_in_resident_pool(self):
        row = next(r for r in self.baseline['entries'] if r['category'] == 'technique_name')
        manifest = dict(format=1, purpose='development-only',
            source_disc_sha256=SOURCES['kor'][1], source_exe_sha256=sha(self.inputs['kor']),
            baseline_sha256=digest(self.baseline), character_map_sha256=self.baseline['character_map_sha256'],
            edits=[dict(id=row['id'], expected_hex=row['raw']['kor'], text=row['existing'].replace('　', ' '))])
        _,records,_,report=prepare(self.inputs['kor'], self.baseline, manifest, self.mapping)
        self.assertFalse(records)
        self.assertEqual(report['entries'][0]['policy'],'resident-technique-pool')
        manifest['edits'][0]['text']=row['existing'].replace('　','  ')
        _,records,_,report=prepare(self.inputs['kor'], self.baseline, manifest, self.mapping)
        self.assertFalse(records)
        self.assertEqual(report['entries'][0]['policy'],'resident-technique-pool')
        manifest['edits'][0]['text']='가'*11
        with self.assertRaisesRegex(ValueError,'120px'):
            prepare(self.inputs['kor'], self.baseline, manifest, self.mapping)

    def test_help_word_spaces_do_not_shrink_button_overlay_cells(self):
        from catalog_insert import encode_text, pixel_width
        from technique_insert import validate
        row=next(r for r in self.baseline['entries'] if r['id']=='technique_help-004')
        raw=encode_text(row,row['existing'].replace('　',' '),self.mapping)
        self.assertEqual(raw[22:24],b'\x81\x40')
        self.assertEqual(raw[16:18],b'\x0f\x01')
        self.assertEqual(raw[34:36],bytes.fromhex(row['raw']['kor'])[34:36])
        with self.assertRaisesRegex(ValueError,'glyph count'):
            validate(row,raw[:-3]+b'\0',bytes.fromhex(row['raw']['kor']),pixel_width)

    def test_editing_one_shared_technique_preserves_other_alias(self):
        from catalog_insert import verify_reinsertion
        import struct
        row=next(r for r in self.baseline['entries'] if r['id']=='technique_name-044')
        alias=next(r for r in self.baseline['entries'] if r['id']=='technique_name-048')
        self.assertEqual(row['locations']['kor']['logical_offset'],alias['locations']['kor']['logical_offset'])
        manifest=dict(format=1,purpose='development-only',source_disc_sha256=SOURCES['kor'][1],
            source_exe_sha256=sha(self.inputs['kor']),baseline_sha256=digest(self.baseline),
            character_map_sha256=self.baseline['character_map_sha256'],
            edits=[dict(id=row['id'],expected_hex=row['raw']['kor'],text=row['existing'].replace('　',' '))])
        writes,records,directory,report=prepare(self.inputs['kor'],self.baseline,manifest,self.mapping)
        self.assertEqual(report['entries'][0]['policy'],'resident-technique-pool')
        exe=bytearray(self.inputs['kor'])
        for w in writes:
            raw=bytes.fromhex(w['after']);exe[w['file_offset']:w['file_offset']+len(raw)]=raw
        ref=alias['locations']['kor']['reference_logical_offset']
        pointer=struct.unpack_from('<I',exe,ref)[0]-0x80090000
        raw=bytes.fromhex(alias['raw']['kor'])
        self.assertEqual(exe[pointer:pointer+len(raw)],raw)
        verify_reinsertion(bytes(exe),bytes(0x1800)+directory+b''.join(records),0x2000,
                           report,self.baseline,self.inputs['kor'])

    def test_resident_technique_pool_rejects_capacity_and_unknown_references(self):
        from technique_insert import repack_names
        from catalog_insert import pixel_width
        import struct
        rows=[r for r in self.baseline['entries'] if r['category']=='technique_name']
        wanted={r['id']:b''.join(b'\x81\x41' if (i>>bit)&1 else b'\x81\x42'
                                for bit in range(8))+b'\0' for i,r in enumerate(rows)}
        with self.assertRaisesRegex(ValueError,'capacity exceeded'):
            repack_names(self.inputs['kor'],rows,wanted,pixel_width)
        bad=bytearray(self.inputs['kor'])
        struct.pack_into('<I',bad,0x900,0x80130bd4)
        with self.assertRaisesRegex(ValueError,'Unexpected reference'):
            repack_names(bytes(bad),rows,wanted,pixel_width)


if __name__ == '__main__':
    unittest.main()
