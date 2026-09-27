#!/usr/bin/env python3
"""Match recovered 12x11 glyphs against the Gulim 12px bitmap strike.

The font stays under work/reference or is passed with --font. Only derived
character candidates and pixel distances are written under work/review.
"""

import argparse
from collections import defaultdict
import hashlib
import heapq
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from glyph_review import ROOT, SOURCE, atomic_json, source_data

DEFAULT_FONT = ROOT / "work/reference/gulim/sources/ttc/gulim.ttc"
DEFAULT_OUTPUT = ROOT / "work/review/glyph-matches.json"


def render_rows(font, char):
    image = Image.new("1", (12, 11))
    ImageDraw.Draw(image).text((0, 0), char, font=font, fill=1, anchor="lt")
    return tuple(sum((0 if image.getpixel((x, y)) else 1) << (15 - x)
                     for x in range(12)) | 0x000F for y in range(11))


def difference(a, b):
    return sum(((x ^ y) & 0xFFF0).bit_count() for x, y in zip(a, b))


def generate(source=SOURCE, font_path=DEFAULT_FONT, output=DEFAULT_OUTPUT):
    source_hash, glyphs = source_data(source)
    font_bytes = font_path.read_bytes()
    font = ImageFont.truetype(str(font_path), 12, index=0)
    # The original 2.21 TTC has a 12px embedded bitmap strike. Font builds
    # without this strike must fail calibration rather than suggest false IDs.
    by_pixels = defaultdict(list)
    renderings = []
    for point in range(0xAC00, 0xD7A4):
        char = chr(point)
        rows = render_rows(font, char)
        by_pixels[rows].append(char)
        renderings.append((char, rows))

    rows = {}
    exact_ocr = 0
    exact_changed = 0
    for glyph in glyphs:
        if not glyph["changed"]:
            continue
        target = tuple(glyph["kor_rows"])
        exact = by_pixels.get(target, [])
        if exact:
            exact_changed += 1
            if glyph["ocr_suggestion"] and glyph["ocr_suggestion"]["text"] in exact:
                exact_ocr += 1
            rows[str(glyph["index"])] = {"kind": "exact" if len(exact) == 1 else "ambiguous",
                                          "characters": exact, "pixel_difference": 0}
        else:
            near = heapq.nsmallest(12, renderings,
                                   key=lambda item: (difference(target, item[1]), item[0]))
            rows[str(glyph["index"])] = {"kind": "unmatched", "characters": [
                {"character": char, "pixel_difference": difference(target, candidate),
                 "rows": list(candidate)} for char, candidate in near]}

    if exact_changed < 500:
        raise ValueError(f"Gulim calibration failed: only {exact_changed} changed glyphs matched exactly")
    report = {"format": 1, "source_sha256": source_hash,
              "font_sha256": hashlib.sha256(font_bytes).hexdigest(),
              "font_source": "https://github.com/googlefonts/gulim/tree/main/sources/ttc",
              "font_face": 0, "font_size_px": 12, "drawing": "Pillow 1-bit, anchor=lt, origin=(0,0), 12x11",
              "changed_count": sum(g["changed"] for g in glyphs),
              "exact_count": exact_changed, "ocr_same_exact_count": exact_ocr,
              "unmatched_count": sum(r["kind"] == "unmatched" for r in rows.values()),
              "matches": rows}
    atomic_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = generate(args.source, args.font, args.output)
    print(json.dumps({key: value for key, value in report.items() if key != "matches"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
