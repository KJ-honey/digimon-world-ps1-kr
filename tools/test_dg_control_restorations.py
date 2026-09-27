"""Scoped control restoration and authorized row-layout guards."""
import hashlib
import unittest
from unittest.mock import patch
from dg_control_restorations import RESTORATIONS, review_restoration_allowed
from dg_expand import validate_text
from restore_text import LegacyCodec
from translation_review import Workspace


class RestorationTests(unittest.TestCase):
    def setUp(self):
        self.codec = LegacyCodec({'8141':'가'})
        self.old = bytes.fromhex('81410d000000')
        self.key = 'dg-text-test'
        self.tokens = (('control','0107'),('control','0101'),
                       ('control','0d00'),('control','0d00'),('terminator','0000'))
        self.rule = (hashlib.sha256(self.old).hexdigest(), self.tokens)
        self.new = bytes.fromhex('0107814101010d0081410d000000')

    def test_only_exact_id_source_and_token_stream_are_allowed(self):
        with patch.dict(RESTORATIONS, {self.key:self.rule}):
            self.assertEqual(validate_text(self.old,self.new,self.codec,entry_id=self.key),[8,4])
            for old,new,key in [(self.old,self.new,'wrong'),(self.old,self.new,None),
                                (bytes.fromhex('814181410d000000'),self.new,self.key),
                                (self.old,self.new.replace(b'\x01\x07',b'\x01\x06'),self.key)]:
                with self.assertRaisesRegex(ValueError,'Protected'):
                    validate_text(old,new,self.codec,entry_id=key)

    def test_byte_and_pixel_limits_still_apply(self):
        with patch.dict(RESTORATIONS, {self.key:self.rule}):
            for count,reason in [(22,'glyph start'),(32,'64-byte')]:
                new=self.new[:-6]+bytes.fromhex('8141')*count+bytes.fromhex('0d000000')
                with self.assertRaisesRegex(ValueError,reason):
                    validate_text(self.old,new,self.codec,entry_id=self.key)

    def test_review_only_accepts_the_scoped_reflow(self):
        row=dict(id=self.key,source='⟦0107⟧가⟦0101⟧⟦0D00⟧',existing='가⟦0D00⟧',
                 raw={'kor':self.old.hex()})
        text='⟦0107⟧가⟦0101⟧⟦0D00⟧가⟦0D00⟧'
        with patch.dict(RESTORATIONS, {self.key:self.rule}):
            Workspace.validate(row,text,'draft')
            self.assertTrue(review_restoration_allowed(row,text))
            for invalid in [text+'⟦0D00⟧',text.replace('0107','0106'),text+'⟦G:8283⟧']:
                with self.assertRaises(ValueError):Workspace.validate(row,invalid,'draft')


if __name__=='__main__':unittest.main()
