"""Contracts of the opt-in text bank, using source-independent fixtures."""
import struct
import unittest
from dg_expand import prepare_bank, validate_text, validate_manifest, new_sector, MARKER
from dg_script import instruction
from restore_text import LegacyCodec
from cd_sector import regenerate


class TextBankTests(unittest.TestCase):
    def setUp(self):
        self.codec=LegacyCodec({'8140':'\u3000','8141':'가','8142':'나'})
        self.old=bytes.fromhex('81410d000000')

    def test_longer_text_and_moved_line_terminator(self):
        new=bytes.fromhex('8141814081420d000000')
        self.assertEqual(validate_text(self.old,new,self.codec),[8])

    def test_shorter_text_is_not_padded(self):
        self.assertEqual(validate_text(self.old,bytes.fromhex('0d000000'),self.codec),[2])

    def test_control_change_rejected(self):
        with self.assertRaisesRegex(ValueError,'Protected'):
            validate_text(self.old,bytes.fromhex('81410d010000'),self.codec)

    def test_control_order_rejected(self):
        old=bytes.fromhex('01020300000181410d000000')
        new=bytes.fromhex('03000001010281410d000000')
        with self.assertRaisesRegex(ValueError,'Protected'):
            validate_text(old,new,self.codec)

    def test_unknown_glyph_injection_rejected(self):
        with self.assertRaisesRegex(ValueError,'Protected'):
            validate_text(self.old,bytes.fromhex('ffff0d000000'),self.codec)

    def test_row_exact_capacity_and_overflow(self):
        validate_text(self.old,bytes.fromhex('8141')*31+bytes.fromhex('0d000000'),self.codec)
        with self.assertRaisesRegex(ValueError,'64-byte'):
            validate_text(self.old,bytes.fromhex('8141')*32+bytes.fromhex('0d000000'),self.codec)

    def test_early_termination_rejected(self):
        with self.assertRaisesRegex(ValueError,'Early'):
            validate_text(self.old,self.old+self.old,self.codec)

    def test_user_specified_ten_character_table_budgets(self):
        for op in (0x08, 0x11, 0x12):
            with self.subTest(op=op):
                old=bytes((op,0xf9))+bytes.fromhex('81410d000000')
                self.assertEqual(validate_text(old,old,self.codec),[24])
                exact=bytes((op,0xf9))+bytes.fromhex('8141')*21+bytes.fromhex('0d000000')
                self.assertEqual(validate_text(old,exact,self.codec),[64])
                with self.assertRaisesRegex(ValueError,'64-byte'):
                    validate_text(old,exact[:-4]+bytes.fromhex('8141')+exact[-4:],self.codec)

    def test_inline_name_tables_consume_eighteen_bytes(self):
        for op in (0x07, 0x09):
            old=bytes((op,0xf9))+bytes.fromhex('81410d000000')
            self.assertEqual(validate_text(old,old,self.codec),[22])

    def test_repeated_inline_name_insertions_use_actual_field_capacity(self):
        raw=bytes.fromhex('07f9076709c881410d000000')
        self.assertEqual(validate_text(raw,raw,self.codec),[58])
        exact=raw[:-4]+bytes.fromhex('8141')*3+raw[-4:]
        self.assertEqual(validate_text(raw,exact,self.codec),[64])
        with self.assertRaisesRegex(ValueError,'64-byte'):
            validate_text(raw,exact[:-4]+bytes.fromhex('8141')+exact[-4:],self.codec)

    def test_six_character_name_and_digit_budgets(self):
        old=bytes.fromhex('05000a0081410d000000')
        self.assertEqual(validate_text(old,old,self.codec),[28])
        new=old[:-4]+bytes.fromhex('8141')*19+old[-4:]
        with self.assertRaisesRegex(ValueError,'64-byte'):
            validate_text(old,new,self.codec)

    def prepare(self,text='가\u3000나<0D00>'):
        raw=b'\x1a\0'+self.old+b'\xfe\0'
        node=dict(instruction(raw,0,0,len(raw)),script=0)
        edit={'id':'dg-text-000000','text':text,'expected_hex':self.old[:-2].hex()}
        return raw,{'nodes':[node],'overlaps':[]},edit

    def test_descriptor_preserves_next_instruction_and_record_recovers_text(self):
        raw,parsed,edit=self.prepare()
        changed,records,entries=prepare_bank(raw,parsed,[edit],self.codec)
        self.assertEqual(changed[2:6],MARKER+b'\0\0')
        self.assertEqual(changed[6:],raw[6:])
        oldlen,newlen,magic=struct.unpack_from('<HH4s',records[0])
        self.assertEqual((oldlen,magic),(len(self.old),b'DGB1'))
        self.assertEqual(records[0][8:8+newlen],self.codec.encode(edit['text'])+b'\0\0')
        self.assertEqual(len(records[0]),2048)

    def test_duplicate_writer_and_stale_source_rejected(self):
        raw,parsed,edit=self.prepare()
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            prepare_bank(raw,parsed,[edit,edit],self.codec)
        edit['expected_hex']=''
        with self.assertRaisesRegex(ValueError,'Stale'):
            prepare_bank(raw,parsed,[edit],self.codec)

    def test_unchanged_entry_creates_no_record(self):
        raw,parsed,edit=self.prepare('가<0D00>')
        self.assertEqual(prepare_bank(raw,parsed,[edit],self.codec),(raw,[],[]))

    def test_empty_source_can_expand(self):
        self.old=bytes.fromhex('0d000000')
        raw,parsed,edit=self.prepare()
        changed,records,entries=prepare_bank(raw,parsed,[edit],self.codec)
        self.assertEqual(changed[-2:],b'\xfe\0')
        self.assertEqual(entries[0]['old_bytes'],4)

    def test_new_sector_address_and_integrity(self):
        sector=new_sector(4500-150,bytes(2048),b'\0\0\x08\0')
        self.assertEqual(sector[12:16],b'\1\0\0\2')
        self.assertEqual(regenerate(sector),sector)
        with self.assertRaisesRegex(ValueError,'overflow'):
            new_sector(100*4500,bytes(2048),b'\0\0\x08\0')

    def test_manifest_rejects_ignored_fields_and_wrong_types(self):
        manifest=dict(format=1,purpose='test',source_disc_sha256='',source_dg_sha256='',
                      character_map_sha256='',edits=[])
        validate_manifest(manifest)
        with self.assertRaisesRegex(ValueError,'fields'):
            validate_manifest(dict(manifest,allow_overflow=True))
        with self.assertRaisesRegex(ValueError,'format'):
            validate_manifest(dict(manifest,format=True))
        manifest['edits']=[dict(id='x',text='가',expected_hex='',ignore_missing=True)]
        with self.assertRaisesRegex(ValueError,'edit fields'):
            validate_manifest(manifest)


if __name__=='__main__':
    unittest.main()
