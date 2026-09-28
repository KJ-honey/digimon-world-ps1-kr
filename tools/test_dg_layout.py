import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dg_layout import LINE, line_widths, validate_layout, validate_encoded_layout
from dg_line_reflows import reflow_allowed, review_reflow_allowed, stream_hash
from dg_expand import prepare_bank
from dg_script import instruction, text_tokens
from restore_text import LegacyCodec
from survey import sha


class LayoutTests(unittest.TestCase):
    def test_exact_21_cells_and_one_half_space_overflow(self):
        self.assertEqual(validate_layout('가'*21+LINE), [252])
        with self.assertRaisesRegex(ValueError, '258px'):
            validate_layout('가'*21+' '+LINE)
        self.assertEqual(validate_layout('가'*20+'  '+LINE), [252])

    def test_punctuation_ascii_digits_and_raw_symbols_are_full_cells(self):
        self.assertEqual(line_widths('!,.A0⟦G:8283⟧　 '+LINE), [90])

    def test_colors_have_no_width_and_names_are_six_cells(self):
        self.assertEqual(line_widths('⟦0106⟧⟦0500⟧⟦0101⟧⟦0600⟧'+LINE),[144])
        self.assertEqual(validate_layout('⟦0500⟧⟦0600⟧'+'!'*9+LINE),[252])
        with self.assertRaisesRegex(ValueError,'264px'):
            validate_layout('⟦0500⟧⟦0600⟧'+'!'*10+LINE)

    def test_table_names_reserve_ten_cells_and_digits_keep_budget(self):
        for op in ('07F9','08F3','09C8','11F9','1203'):
            self.assertEqual(validate_layout('⟦'+op+'⟧가나다라'+LINE), [168])
        self.assertEqual(line_widths('⟦1000⟧⟦0A00⟧'+LINE),[132])

    def test_unknown_controls_and_malformed_tokens_are_not_zero_width(self):
        for text in ('⟦03000000⟧'+LINE,'⟦BAD⟧'+LINE,'가\n나'+LINE):
            with self.assertRaises(ValueError):validate_layout(text)

    def test_encoded_spaces_symbols_and_trailing_blank_rows(self):
        raw=bytes.fromhex('010781410f00814082830d000d000000')
        self.assertEqual(validate_encoded_layout(text_tokens(raw,0,len(raw))[1]),[42,0])

    def test_bank_cannot_bypass_width_check_with_unchanged_payload(self):
        codec=LegacyCodec({'8141':'가'})
        payload=bytes.fromhex('8141')*22+bytes.fromhex('0d000000')
        raw=b'\x1a\0'+payload+b'\xfe\0'
        node=dict(instruction(raw,0,0,len(raw)),script=0)
        edit=dict(id='dg-text-000000',expected_hex=payload[:-2].hex(),text='가'*22+'<0D00>')
        with self.assertRaisesRegex(ValueError,'252px'):
            prepare_bank(raw,dict(nodes=[node],overlaps=[]),[edit],codec)

    def test_reflow_rule_binds_id_source_and_entire_protected_stream(self):
        old=bytes.fromhex('81410d000000')
        tokens=[('control','0d00'),('control','0d00'),('terminator','0000')]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'rules.json'
            path.write_text(json.dumps(dict(entries={'test':[sha(old),stream_hash(tokens)]})))
            with patch('dg_line_reflows.RULES',path):
                self.assertTrue(reflow_allowed('test',old,tokens))
                self.assertFalse(reflow_allowed('other',old,tokens))
                self.assertFalse(reflow_allowed('test',old+b'\0',tokens))
                self.assertFalse(reflow_allowed('test',old,tokens[1:]))
                self.assertFalse(reflow_allowed('test',old,[('control','0500')]+tokens))
                row=dict(id='test',raw={'kor':old.hex()})
                self.assertTrue(review_reflow_allowed(row,'가'+LINE+'나'+LINE))
                self.assertFalse(review_reflow_allowed(row,'⟦G:8283⟧'+LINE+'나'+LINE))


if __name__=='__main__':unittest.main()
