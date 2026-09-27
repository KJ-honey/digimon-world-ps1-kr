"""Lossless text recovery guards, including ambiguous Unicode glyph IDs."""
import unittest

from restore_text import LegacyCodec, compile_entries


class CodecTest(unittest.TestCase):
    def setUp(self):
        self.codec = LegacyCodec({"88C0": "늪", "95E2": "늪", "8DEC": "뼈",
                                  "8140": "\u3000", "8281": None,
                                  "9000": "<", "9001": ">", "9002": "\\"})

    def test_alias_controls_icons_and_space_roundtrip(self):
        raw = bytes.fromhex("88C095E20D008DEC8140828101010000")
        decoded = self.codec.decode(raw)
        self.assertEqual(decoded, "<88C0:늪><95E2:늪><0D00>뼈\u3000<8281><0101><0000>")
        self.assertEqual(self.codec.encode(decoded), raw)
        # Literal token syntax cannot be confused with a control token.
        raw = bytes.fromhex("900090029001")
        self.assertEqual(self.codec.encode(self.codec.decode(raw)), raw)

    def test_missing_ambiguous_or_tampered_characters_fail(self):
        for value in ("힣", "늪", "<95E2:뼈>", "<0D0>", "<0d00>", "\\q", ">"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.codec.encode(value)
        with self.assertRaises(ValueError):
            self.codec.decode(b"\x81")


class MappingTest(unittest.TestCase):
    def setUp(self):
        self.glyphs = [{"index": 0, "id": "glyph-0", "code": "8DEC", "changed": True,
                        "kor_rows": [123] * 11}]
        self.matches = {"matches": {"0": {"kind": "exact", "characters": ["뼈"],
                                            "pixel_difference": 0}}}
        self.review = {"decisions": {"0": {"status": "accepted", "code": "8DEC", "character": "빼"}}}

    def test_existing_exact_precedence_preserves_conflict(self):
        entries, conflicts = compile_entries(self.glyphs, self.matches, self.review, lambda _: [123] * 11)
        self.assertEqual(entries[0]["character"], "뼈")
        self.assertEqual(entries[0]["review"]["character"], "빼")
        self.assertEqual(conflicts[0]["previous"]["character"], "빼")

    def test_stale_pixels_codes_and_missing_review_fail(self):
        with self.assertRaises(ValueError):
            compile_entries(self.glyphs, self.matches, self.review, lambda _: [124] * 11)
        self.review["decisions"]["0"]["code"] = "FFFF"
        with self.assertRaises(ValueError):
            compile_entries(self.glyphs, self.matches, self.review, lambda _: [123] * 11)
        self.matches["matches"]["0"] = {"kind": "unmatched", "characters": []}
        with self.assertRaises(ValueError):
            compile_entries(self.glyphs, self.matches, {"decisions": {}}, lambda _: [])

    def test_manual_correction_is_used_without_nearest_guess(self):
        self.matches["matches"]["0"] = {"kind": "unmatched", "characters": []}
        self.review["decisions"]["0"].update(status="confirmed", character="뼈")
        entries, _ = compile_entries(self.glyphs, self.matches, self.review, lambda _: [])
        self.assertEqual(entries[0]["character"], "뼈")
        self.assertEqual(entries[0]["evidence"], "human_confirmed")


if __name__ == "__main__":
    unittest.main()
