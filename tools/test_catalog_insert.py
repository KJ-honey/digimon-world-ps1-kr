import copy
import struct
import unittest

from catalog_insert import (prepare, encode_text, pixel_width, verify_reinsertion,
                            DESCRIPTOR_RAM)
from survey import SOURCES, sha
from translation_review import digest


class CatalogInsertionTests(unittest.TestCase):
    def fixture(self):
        exe=bytearray(0x1000)
        exe[0x800:0x803]=bytes.fromhex('814100')
        rows=[]
        for key,ref,kind in [('location_name-000',0x900,'u32_ram_pointer'),
                             ('location_name-001',0x904,'u32_ram_pointer'),
                             ('item_name-000',0xa00,'record')]:
            at=0x800 if kind=='u32_ram_pointer' else ref
            if kind=='record':
                exe[at:at+32]=bytes.fromhex('814100')+b'\xa5'*29
            else:
                struct.pack_into('<I',exe,ref,0x80090800)
            rows.append(dict(id=key,category=key.rsplit('-',1)[0],text_format='nul_glyph_string',
                source='原',existing='가',raw={'kor':'814100'},
                locations={'kor':dict(logical_offset=at,reference_logical_offset=ref,reference_kind=kind)}))
        exe=bytes(exe)
        baseline=dict(entries=rows,source_file_sha256={'kor':sha(exe)},character_map_sha256='map')
        manifest=dict(format=1,purpose='development-only',source_disc_sha256=SOURCES['kor'][1],
                      source_exe_sha256=sha(exe),baseline_sha256=digest(baseline),
                      character_map_sha256='map',edits=[])
        mapping={'entries':[dict(code='8141',character='가'),dict(code='8140',character='　')]}
        return exe,baseline,manifest,mapping

    def test_space_is_two_nonzero_bytes_and_six_pixels(self):
        _,b,_,m=self.fixture()
        raw=encode_text(b['entries'][0],'가 가　가',m)
        self.assertEqual(raw,bytes.fromhex('81410f0181418140814100'))
        self.assertEqual(pixel_width(raw),54)
        for text in ['가☃','가\n가','가⟦0F00⟧','가⟦G:0F00⟧']:
            with self.assertRaises(ValueError):encode_text(b['entries'][0],text,m)

    def test_shared_alias_relocated_without_changing_unselected_entry(self):
        exe,b,manifest,m=self.fixture()
        manifest['edits']=[dict(id='location_name-000',expected_hex='814100',text='가 가 가')]
        writes,records,descriptors,report=prepare(exe,b,manifest,m)
        self.assertEqual(len(writes),1)
        self.assertEqual(struct.unpack('<I',bytes.fromhex(writes[0]['after']))[0],DESCRIPTOR_RAM)
        result=bytearray(exe)
        for w in writes:result[w['file_offset']:w['file_offset']+4]=bytes.fromhex(w['after'])
        dg=bytes(0x1800)+descriptors+b''.join(records)
        verify_reinsertion(bytes(result),dg,0x2000,report,b,exe)
        result[0x800]=0
        with self.assertRaises(ValueError):verify_reinsertion(bytes(result),dg,0x2000,report,b,exe)

    def test_independent_variants_and_deterministic_placement(self):
        exe,b,manifest,m=self.fixture()
        manifest['edits']=[dict(id=f'location_name-00{i}',expected_hex='814100',text='가 '*(i+1)+'가') for i in range(2)]
        first=prepare(exe,b,manifest,m)
        manifest['edits'].reverse()
        self.assertEqual(first,prepare(exe,b,manifest,m))
        self.assertNotEqual(first[1][0],first[1][1])

    def test_inline_growth_preserves_record_fields_and_rejects_overflow(self):
        exe,b,manifest,m=self.fixture()
        manifest['edits']=[dict(id='item_name-000',expected_hex='814100',text='가'*9)]
        writes,records,_,report=prepare(exe,b,manifest,m)
        self.assertFalse(records)
        self.assertEqual(len(bytes.fromhex(writes[0]['after'])),19)
        result=bytearray(exe);result[0xa00:0xa13]=bytes.fromhex(writes[0]['after'])
        verify_reinsertion(bytes(result),b'',0,report,b,exe)
        self.assertEqual(result[0xa13:0xa20],exe[0xa13:0xa20])
        manifest['edits'][0]['text']='가'*10
        with self.assertRaisesRegex(ValueError,'20 bytes'):prepare(exe,b,manifest,m)

    def test_unchanged_round_trip_and_fail_closed_inputs(self):
        exe,b,manifest,m=self.fixture()
        manifest['edits']=[dict(id='item_name-000',expected_hex='814100',text='가')]
        self.assertEqual(prepare(exe,b,manifest,m)[0:2],([],[]))
        for field,value in [('expected_hex','814200'),('id','unknown'),('text','가'*22)]:
            changed=copy.deepcopy(manifest);changed['edits'][0][field]=value
            with self.assertRaises(ValueError):prepare(exe,b,changed,m)
        changed=copy.deepcopy(manifest);changed['edits']*=2
        with self.assertRaisesRegex(ValueError,'Duplicate'):prepare(exe,b,changed,m)
        changed=dict(manifest,source_exe_sha256='stale')
        with self.assertRaises(ValueError):prepare(exe,b,changed,m)


if __name__=='__main__':unittest.main()
