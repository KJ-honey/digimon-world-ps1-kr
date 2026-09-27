#!/usr/bin/env python3
"""Recover font pixels and paired dialogue candidates; never modify game data.

Dialogue discovery is deliberately labeled heuristic until VM boundaries have
been independently traced. Raw bytes remain authoritative. OCR is optional and
produces unreviewed suggestions only.
"""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import struct
import subprocess

from PIL import Image, ImageDraw
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
from survey import ROOT, write_json, sha

TABLE = 0x98578
PIXELS = 0x98D38
COUNT = 991
STORED_GLYPHS = COUNT + 1  # Sentinel selects a real fallback glyph after mapped glyphs.
STRIDE = 22
WIDTH, HEIGHT = 12, 11


def load_inputs(root):
    report = json.loads((root / "report.json").read_text())
    records = {r["path"]: r for r in report["files"]}
    result = {}
    for lang in ("jpn", "kor"):
        for name in ("SLPS_017.97", "SCN/DG.SCN", "SHOP_REL.BIN"):
            data = (root / "files" / lang / name).read_bytes()
            if sha(data) != records[name][lang + "_sha256"]:
                raise ValueError(f"Recovered input changed: {lang}/{name}")
            result[lang, name] = data
    return result


def font(data):
    codes = struct.unpack_from(f"<{COUNT}H", data, TABLE)
    if struct.unpack_from("<H", data, TABLE+COUNT*2)[0] != 0:
        raise ValueError("Unexpected font sentinel")
    rows = [list(struct.unpack_from("<11H", data, PIXELS+i*STRIDE)) for i in range(STORED_GLYPHS)]
    # Independent serialization of every decoded row, including unused low bits.
    encoded = b"".join(int(row).to_bytes(2, "little") for glyph in rows for row in glyph)
    if encoded != data[PIXELS:PIXELS+STORED_GLYPHS*STRIDE]:
        raise ValueError("Font row round trip failed")
    return codes, rows


def tile(rows):
    im = Image.new("L", (WIDTH, HEIGHT), 255)
    for y, row in enumerate(rows):
        for x in range(WIDTH):
            im.putpixel((x, y), 255 if row & (0x8000 >> x) else 0)
    return im


def atlas(codes, rows, out, lang):
    for page in range((COUNT+255)//256):
        im = Image.new("RGB", (1024, 1024), "#ddd")
        draw = ImageDraw.Draw(im)
        for i in range(page*256, min((page+1)*256, COUNT)):
            x, y = i % 16 * 64, i % 256 // 16 * 64
            draw.text((x+2, y+1), f"{i:03d} {codes[i]:04X}", fill="black")
            im.paste(tile(rows[i]).resize((48, 44), Image.Resampling.NEAREST), (x+8, y+16))
        im.save(out / f"{lang}-{page}.png")


def scan_dialogue(data):
    """Candidate 1A00 + two-byte tokens + 0000; not a VM disassembler."""
    result = {}
    cursor = 0
    while (at := data.find(b"\x1a\x00", cursor)) >= 0:
        cursor = at+2
        end = cursor
        while end+1 < len(data) and end-at < 1000 and data[end:end+2] != b"\0\0":
            if data[end] > 0x80 or 1 <= data[end] <= 13:
                end += 2
            else:
                break
        if end-at > 6 and data[end:end+2] == b"\0\0":
            result[at] = data[at+2:end]
    return result


def script_extents(data):
    # Fixed-revision directory: 225 aligned starts and one EOF boundary.
    # Bytes after this table within the 0x800 header include embedded filenames.
    offsets = struct.unpack_from("<226I", data)
    if offsets[0] != 0x800 or offsets[-1] != len(data):
        raise ValueError("Unexpected DG directory endpoints")
    if not all(a < b and a % 2048 == 0 for a, b in zip(offsets, offsets[1:])):
        raise ValueError("Unexpected DG directory layout")
    return [(offsets[i], offsets[i+1]) for i in range(225)]


def decode_jpn(data):
    result = []
    for i in range(0, len(data), 2):
        pair = data[i:i+2]
        if pair[0] > 0x80:
            try:
                result.append(pair.decode("shift_jis"))
                continue
            except UnicodeDecodeError:
                pass
        result.append("<"+pair.hex().upper()+">")
    return "".join(result)


def ocr_suggestions(rows, out):
    # Fixed cells let us associate OCR boxes with glyph IDs without trusting word order.
    sheet = Image.new("L", (32*96, 31*96), 255)
    for i, row in enumerate(rows):
        sheet.paste(tile(row).resize((72, 66), Image.Resampling.NEAREST), (i%32*96+12, i//32*96+15))
    path = out / "ocr-sheet.png"
    sheet.save(path)
    subprocess.run(["tesseract", str(path), str(out / "ocr"), "-l", "kor", "--psm", "6", "tsv"], check=True, capture_output=True)
    suggestions = {}
    with (out / "ocr.tsv").open() as f:
        for row in csv.DictReader(f, delimiter="\t"):
            text = row["text"].strip()
            if len(text) != 1 or not "가" <= text <= "힣":
                continue
            x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
            cell = ((y+h//2)//96)*32+(x+w//2)//96
            if cell < COUNT and x//96 == (x+w-1)//96 and y//96 == (y+h-1)//96:
                suggestions[cell] = {"text": text, "confidence": float(row["conf"]), "status": "unreviewed_ocr"}
    return suggestions


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--survey", type=Path, default=ROOT / "work/survey")
    ap.add_argument("--out", type=Path, default=ROOT / "work/recovered")
    ap.add_argument("--ocr", action="store_true")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    inputs = load_inputs(args.survey)
    fonts = {lang: font(inputs[lang, "SLPS_017.97"]) for lang in ("jpn", "kor")}
    if fonts["jpn"][0] != fonts["kor"][0]:
        raise ValueError("Font code table changed")
    codes = fonts["jpn"][0]
    for lang, (_, rows) in fonts.items():
        atlas(codes, rows, args.out, lang)
        (args.out / f"{lang}.1bppf").write_bytes(inputs[lang, "SLPS_017.97"][TABLE:PIXELS+STORED_GLYPHS*STRIDE])
        tile(rows[COUNT]).resize((120, 110), Image.Resampling.NEAREST).save(args.out / f"{lang}-fallback.png")
    suggestions = ocr_suggestions(fonts["kor"][1], args.out) if args.ocr else {}
    glyphs = []
    for i, code in enumerate(codes):
        raw = code.to_bytes(2, "big")
        glyphs.append({"id": f"legacy-glyph-{i:04d}", "index": i, "code": f"{code:04X}",
                       "japanese": decode_jpn(raw), "korean": None, "status": "unicode_mapping_pending",
                       "changed": fonts["jpn"][1][i] != fonts["kor"][1][i],
                       "jpn_rows": fonts["jpn"][1][i], "kor_rows": fonts["kor"][1][i],
                       "ocr_suggestion": suggestions.get(i)})
    write_json(args.out / "glyphs.json", glyphs)
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN)
    machine = inputs["kor", "SLPS_017.97"][0x1575C:0x15B48]
    if machine != inputs["jpn", "SLPS_017.97"][0x1575C:0x15B48]:
        raise ValueError("Legacy renderer differs from Japanese source")
    (args.out / "font-renderer.asm").write_text("\n".join(
        f"{i.address:08x} {i.bytes.hex():8} {i.mnemonic} {i.op_str}"
        for i in md.disasm(machine, 0x800A575C))+"\n")
    extents = script_extents(inputs["jpn", "SCN/DG.SCN"])
    if extents != script_extents(inputs["kor", "SCN/DG.SCN"]):
        raise ValueError("Script allocation changed")
    scans = {lang: scan_dialogue(inputs[lang, "SCN/DG.SCN"]) for lang in ("jpn", "kor")}
    shared = sorted(scans["jpn"].keys() & scans["kor"].keys())
    pairs = []
    missing = {"jpn": Counter(), "kor": Counter()}
    mapping = set(codes) | {0x8140}
    for n, at in enumerate(shared):
        row = {"id": f"dialogue-candidate-{n:05d}", "file": "SCN/DG.SCN", "offset": at,
               "status": "candidate_same_offset_vm_boundary_unverified", "reviewed": False}
        row["script_index"] = next(i for i,(start,end) in enumerate(extents) if start <= at < end)
        for lang in ("jpn", "kor"):
            raw = scans[lang][at]
            row[lang+"_hex"] = raw.hex().upper()
            if bytes.fromhex(row[lang+"_hex"]) != raw:
                raise ValueError("Raw token round trip failed")
            for j in range(0, len(raw), 2):
                code = int.from_bytes(raw[j:j+2], "big")
                if raw[j] > 0x80 and code not in mapping:
                    missing[lang][f"{code:04X}"] += 1
        row["japanese"] = decode_jpn(scans["jpn"][at])
        row["unchanged_bytes"] = scans["jpn"][at] == scans["kor"][at]
        pairs.append(row)
    with (args.out / "dialogue-candidates.jsonl").open("w") as f:
        for row in pairs:
            f.write(json.dumps(row, ensure_ascii=False)+"\n")
    summary = {"font_table_offset": TABLE, "glyph_data_offset": PIXELS, "mapped_glyph_count": COUNT,
               "stored_glyph_count_including_fallback": STORED_GLYPHS,
               "fallback_glyph_offset": PIXELS+COUNT*STRIDE,
               "glyph_width": WIDTH, "glyph_height": HEIGHT, "bytes_per_glyph": STRIDE,
               "changed_glyphs": sum(g["changed"] for g in glyphs), "font_rows_roundtrip": True,
               "blank_glyph_indices": [g["index"] for g in glyphs if all(r&0xFFF0 == 0xFFF0 for r in g["kor_rows"])],
               "script_allocation_count": len(extents), "renderer_unchanged": True,
               "paired_dialogue_candidates": len(pairs), "candidate_raw_roundtrip": True,
               "unpaired_jpn_offsets": sorted(scans["jpn"].keys()-scans["kor"].keys()),
               "unpaired_kor_offsets": sorted(scans["kor"].keys()-scans["jpn"].keys()),
               "candidate_glyph_codes_not_in_table": {k: dict(v) for k,v in missing.items()},
               "ocr_suggestions": len(suggestions), "ocr_accepted_mappings": 0,
               "runtime_verified": False, "complete_text_extraction": False}
    write_json(args.out / "summary.json", summary)
    payload = json.dumps({"glyphs": glyphs, "pairs": pairs}, ensure_ascii=False).replace("<", "\\u003c")
    template = (ROOT / "tools/review.html").read_text()
    (args.out / "review.html").write_text(template.replace("/*RECOVERY_DATA*/null", payload))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
