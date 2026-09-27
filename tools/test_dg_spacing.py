import unittest
from dg_spacing import dialogue_codec
from dg_expand import validate_text
from restore_text import LegacyCodec
from translation_playtest import encode_draft
from translation_spacing import transform, width


class SpacingTests(unittest.TestCase):
    def setUp(self):
        self.mapping = {'entries':[{'code':c,'character':v} for c,v in
                         {'8140':'　','8141':'、','8149':'！','889F':'가'}.items()]}
        self.codec = dialogue_codec(self.mapping)

    def test_two_byte_half_full_roundtrip(self):
        raw, _ = encode_draft('가 　가', self.codec)
        self.assertEqual(raw.hex(), '889f0f008140889f')
        self.assertEqual(self.codec.encode(self.codec.decode(raw)), raw)

    def test_only_exact_native_space_is_editable(self):
        old = bytes.fromhex('889f81400d000000')
        new = bytes.fromhex('889f0f000d000000')
        self.assertEqual(validate_text(old,new,self.codec),[6])
        with self.assertRaisesRegex(ValueError,'Protected'):
            validate_text(old, bytes.fromhex('889f0f010d000000'),self.codec)
        with self.assertRaisesRegex(ValueError,'Protected'):
            validate_text(old,new,LegacyCodec({'8140':'　','889F':'가'}))
        with self.assertRaisesRegex(ValueError,'Protected'):
            validate_text(bytes.fromhex('0107889f0d000000'),new,self.codec)

    def test_space_still_consumes_row_buffer(self):
        with self.assertRaisesRegex(ValueError,'64-byte'):
            validate_text(bytes.fromhex('889f0d000000'), bytes.fromhex('0f00')*32+bytes.fromhex('0d000000'),self.codec)

    def test_dialogue_indent_and_punctuation(self):
        row={'id':'fixture','script':1,'source':'「あ！⟦0D00⟧　い」⟦0D00⟧'}
        value,_=transform(row,'「가, 나! 다⟦0D00⟧ 라 마」⟦0D00⟧')
        self.assertEqual(value,'「가,나!다⟦0D00⟧　라 마」⟦0D00⟧')

    def test_color_title_and_blank_row(self):
        row={'id':'fixture','script':1,'source':'　⟦0D00⟧⟦0107⟧　　　題⟦0101⟧⟦0D00⟧'}
        value,_=transform(row,' ⟦0D00⟧⟦0107⟧제목⟦0101⟧⟦0D00⟧')
        self.assertEqual(value,'　⟦0D00⟧⟦0107⟧　　　제목⟦0101⟧⟦0D00⟧')

    def test_price_columns_and_grid(self):
        suffix='⟦G:816F⟧⟦G:8170⟧'
        row={'id':'fixture','script':1,'source':'肉　　３００'+suffix+'⟦0D00⟧'}
        value,_=transform(row,'고기: 300'+suffix+'⟦0D00⟧')
        self.assertEqual(value,'고기　300'+suffix+'⟦0D00⟧')
        row.update(script=224,source='　Ｄ　　Ｓ⟦0D00⟧')
        self.assertEqual(transform(row,row['source'])[0],row['source'])


if __name__=='__main__': unittest.main()
