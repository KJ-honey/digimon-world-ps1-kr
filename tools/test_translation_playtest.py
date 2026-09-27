import unittest
from restore_text import LegacyCodec
from translation_playtest import encode_draft


class DraftEncodingTests(unittest.TestCase):
    def setUp(self):
        self.codec = LegacyCodec({'8140':'　','8142':'。','824F':'０','826C':'Ｍ',
                                  '8148':'?','8149':'!','88C0':'늪','95E2':'늪'})

    def test_full_cell_aliases_and_four_byte_control(self):
        raw, aliases = encode_draft('M 0.⟦03000000⟧⟦G:8283⟧⟦0D00⟧', self.codec)
        self.assertEqual(raw.hex(),'826c8140824f81420300000082830d00')
        self.assertEqual(aliases['0'],'０')

    def test_unavailable_character_fails_without_case_substitution(self):
        with self.assertRaisesRegex(ValueError,"character 'm'"):
            encode_draft('m',self.codec)

    def test_duplicate_identity_has_explicit_new_occurrence_code(self):
        self.assertEqual(encode_draft('늪?!',self.codec)[0].hex(),'88c081488149')


if __name__ == '__main__':
    unittest.main()
