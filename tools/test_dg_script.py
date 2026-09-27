"""Safety tests for DG consumer boundaries and reinsertion, using synthetic data."""
import unittest

from dg_build import replace_text, sector_plan
from cd_sector import regenerate
from dg_script import instruction, text_tokens, reassemble
from restore_text import LegacyCodec


class DGBoundaryTests(unittest.TestCase):
    def test_four_byte_control_contains_zero(self):
        raw = bytes.fromhex('0300000081400d000000fe00')
        end, tokens = text_tokens(raw, 0, len(raw))
        self.assertEqual(end, 10)
        self.assertEqual(tokens[0]['raw'], '03000000')

    def test_zero_without_linebreak_is_not_terminator(self):
        raw = bytes.fromhex('8140000081410d000000')
        self.assertEqual(text_tokens(raw, 0, len(raw))[0], len(raw))

    def test_missing_terminator_fails(self):
        with self.assertRaisesRegex(ValueError, 'truncated'):
            text_tokens(bytes.fromhex('81400d00'), 0, 4)

    def test_selection_includes_text_and_relative_targets(self):
        raw = bytes.fromhex('1002100020001a0081400d000000')
        node = instruction(raw, 0, 0x800, len(raw))
        self.assertEqual([r['target'] for r in node['references']], [0x810, 0x820])
        self.assertEqual(node['texts'][0]['header'], 6)
        self.assertFalse(node['fallthrough'])

    def test_predicate_argument_widths_and_target(self):
        raw = bytes.fromhex('19002500000378563412180020001900')
        node = instruction(raw, 0, 0x800, len(raw))
        self.assertEqual(node['end'], len(raw))
        self.assertEqual(node['references'][0]['target'], 0x820)

    def test_unknown_does_not_scan_forward(self):
        with self.assertRaisesRegex(ValueError, 'unsupported opcode'):
            instruction(bytes.fromhex('6b001a0081400d000000'), 0, 0, 10)

    def test_return_consumes_one_byte(self):
        node = instruction(bytes.fromhex('fe00'), 0, 0, 2)
        self.assertEqual(node['end'], 1)
        self.assertFalse(node['fallthrough'])

    def test_reassembly_rejects_overlap(self):
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            reassemble([{'offset': 0, 'raw': 'abcd'}, {'offset': 1, 'raw': 'ef'}])


class DGWriteTests(unittest.TestCase):
    def setUp(self):
        self.raw = bytes.fromhex('1a008140030000000d000000')
        node = dict(instruction(self.raw, 0, 0, len(self.raw)), script=0)
        self.parsed = {'nodes': [node], 'overlaps': [], 'errors': []}
        self.codec = LegacyCodec({'8140':'가', '8141':'나'})
        self.edit = {'id':'dg-text-000000', 'expected_hex':self.raw[2:-2].hex(),
                     'text':'나<0300><0000><0D00>'}

    def assert_rejected(self, edit, message):
        with self.assertRaisesRegex(ValueError, message):
            replace_text(self.raw, self.parsed, [dict(self.edit, **edit)], self.codec)

    def test_control_argument_change_fails(self):
        self.assert_rejected({'text':'나<0300><0100><0D00>'}, 'Protected control')

    def test_length_change_fails(self):
        self.assert_rejected({'text':'나가<0300><0000><0D00>'}, 'Exact-length')

    def test_missing_glyph_fails(self):
        self.assert_rejected({'text':'힣<0300><0000><0D00>'}, 'Missing or ambiguous')

    def test_unverified_candidate_fails(self):
        self.assert_rejected({'id':'dg-text-004240'}, 'No consumer-verified')

    def test_source_precondition_fails(self):
        self.assert_rejected({'expected_hex':'0000'}, 'Stale source')

    def test_raw_glyph_injection_fails(self):
        self.assert_rejected({'text':'<FFFF><0300><0000><0D00>'}, 'Unknown/unsupplied')

    def test_duplicate_writer_fails(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate writer'):
            replace_text(self.raw, self.parsed, [self.edit, self.edit], self.codec)


class SectorWriteTests(unittest.TestCase):
    def setUp(self):
        raw = bytearray(2352)
        raw[:12] = b'\0'+b'\xff'*10+b'\0'
        raw[15] = 2
        self.sector = regenerate(raw)
        self.table = {'DG': {'lba': 10, 'size': 4096}}

    def test_cross_sector_and_parity(self):
        original = self.sector
        disc = type('Disc', (), {'sector': lambda _, lba: original})()
        plan = sector_plan(disc, self.table, [{'file':'DG', 'file_offset':2047,
                                             'before':'0000', 'after':'abcd'}])
        self.assertEqual(set(plan), {10, 11})
        self.assertEqual(plan[10][2071], 0xab)
        self.assertEqual(plan[11][24], 0xcd)
        for raw in plan.values():
            self.assertEqual(raw[:24], original[:24])
            self.assertEqual(regenerate(raw), raw)

    def test_overlap_fails_before_output(self):
        original = self.sector
        disc = type('Disc', (), {'sector': lambda _, lba: original})()
        write = {'file':'DG', 'file_offset':0, 'before':'0000', 'after':'abcd'}
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            sector_plan(disc, self.table, [write, write])


if __name__ == '__main__':
    unittest.main()
