import unittest
from font_expand import pack, unpack, extra_code, ks_syllables, checked_rows
from PIL import ImageFont

class FontPackingTests(unittest.TestCase):
    def test_preserves_pixels_and_unused_low_nibble(self):
        rows=[tuple(((n*157+i*29)&4095)<<4 | (15 if i%2 else 0) for i in range(11)) for n in range(40)]
        rows += [rows[0],tuple([65535]*11),tuple([0]*11)]
        idx,tables,desc=pack(rows)
        self.assertEqual([unpack(idx,tables,desc,i) for i in range(len(rows))],rows)
    def test_rejects_lossy_or_wrong_cell(self):
        for rows in [[],[(0,)*10],[(1,)*11],[(65536,)*11]]:
            with self.assertRaises(ValueError):pack(rows)
    def test_extension_codes_avoid_terminator_and_trail_hole(self):
        codes=[extra_code(i) for i in range(1504)]
        self.assertEqual(len(set(codes)),1504)
        self.assertEqual((codes[0],codes[62],codes[63],codes[-1]),('F040','F07E','F080','F7FC'))
        for s in codes:
            self.assertNotIn(int(s[2:],16),(0,0x7f,0xff))
        with self.assertRaises(ValueError):extra_code(1504)
    def test_ks_repertoire(self):
        chars=ks_syllables()
        self.assertEqual(len(chars),2350)
        self.assertTrue({'가','힝','뼈','팬','늪'}<=chars)

    def test_raster_rejects_empty_and_clipped_ink(self):
        small = ImageFont.load_default(size=10)
        rows = checked_rows(small, 'A')
        self.assertEqual(len(rows), 11)
        self.assertTrue(any(row != 65535 for row in rows))
        with self.assertRaisesRegex(ValueError, 'Empty glyph'):
            checked_rows(small, ' ')
        with self.assertRaisesRegex(ValueError, 'Clipped glyph'):
            checked_rows(ImageFont.load_default(size=40), 'A')

if __name__=='__main__':unittest.main()
