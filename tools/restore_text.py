#!/usr/bin/env python3
"""Bind reviewed legacy glyphs to lossless Unicode dialogue candidates.

This is analysis output, not a VM parser or product reinserter. <XXXX> keeps
unresolved two-byte units; <XXXX:character> keeps duplicate glyph identities.
Literal backslash and angle brackets are escaped with backslash.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import unicodedata

from glyph_review import SOURCE, OUTPUT, MATCHES, atomic_json, load_matches, load_review, source_data
from match_gulim import DEFAULT_FONT, render_rows
from recover_assets import font, load_inputs, scan_dialogue, script_extents
from survey import ROOT, SOURCES, sha

# Visually checked shared punctuation, digits and capitals; other legacy slots
# include icons repurposing SJIS letters. Never infer their meaning from SJIS.
SHARED_TEXT_INDICES = frozenset(range(60)) | {984}
RAW_GLYPH_INDICES = {60, 61, 452, 460, 546, 571, 653, 691, 852,
                     976, 977, 978, 979, 983, 985, 986, 987}


def one_character(value):
    if (not isinstance(value, str) or len(value) != 1
            or unicodedata.category(value).startswith("C")
            or unicodedata.normalize("NFC", value) != value):
        raise ValueError(f"Invalid Unicode glyph identity: {value!r}")
    return value


class LegacyCodec:
    """Reversible analysis codec; raw tokens grant no product-build eligibility."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.reverse = defaultdict(list)
        for code, char in self.mapping.items():
            if not re.fullmatch(r"[0-9A-F]{4}", code):
                raise ValueError(f"Invalid code {code}")
            if char is not None:
                self.reverse[one_character(char)].append(code)

    def decode(self, raw):
        if len(raw) % 2:
            raise ValueError("Truncated two-byte candidate unit")
        output = []
        for pos in range(0, len(raw), 2):
            code = raw[pos:pos + 2].hex().upper()
            char = self.mapping.get(code)
            if char is None:
                output.append(f"<{code}>")
            elif len(self.reverse[char]) > 1:
                output.append(f"<{code}:{char}>")
            else:
                output.append(("\\" if char in "\\<>" else "") + char)
        return "".join(output)

    def encode(self, text):
        output = bytearray()
        pos = 0
        while pos < len(text):
            char = text[pos]
            if char == "<":
                match = re.match(r"<([0-9A-F]{4})(?::([^<>]))?>", text[pos:])
                if not match:
                    raise ValueError(f"Malformed raw/alias token at character {pos}")
                code, label = match.groups()
                if label is not None and self.mapping.get(code) != label:
                    raise ValueError(f"Alias label does not match {code}: {label}")
                output.extend(bytes.fromhex(code))
                pos += len(match[0])
                continue
            if char == "\\":
                pos += 1
                if pos >= len(text) or text[pos] not in "\\<>":
                    raise ValueError("Invalid literal escape")
                char = text[pos]
            elif char == ">":
                raise ValueError("Unescaped closing bracket")
            codes = self.reverse.get(char, [])
            if len(codes) != 1:
                raise ValueError(f"Missing or ambiguous character {char!r}: {codes}")
            output.extend(bytes.fromhex(codes[0]))
            pos += 1
        return bytes(output)


def compile_entries(glyphs, matches, review, render):
    entries, conflicts = [], []
    for key, decision in review["decisions"].items():
        if not key.isdigit() or str(int(key)) != key or not 0 <= int(key) < len(glyphs):
            raise ValueError(f"Invalid review index {key}")
        if decision.get("code") != glyphs[int(key)]["code"]:
            raise ValueError(f"Stale review code at {key}")
        if decision.get("status") not in {"accepted", "corrected", "confirmed"}:
            raise ValueError(f"Unknown review status at {key}")
        one_character(decision.get("character"))
    expected_matches = {str(g["index"]) for g in glyphs if g["changed"]}
    if set(matches["matches"]) != expected_matches:
        raise ValueError("Font comparison population differs from changed glyphs")
    for glyph in glyphs:
        index, code = glyph["index"], glyph["code"]
        match = matches["matches"].get(str(index))
        decision = review["decisions"].get(str(index))
        char, evidence = None, "raw_glyph_identity"
        if match and match["kind"] == "exact":
            if len(match["characters"]) != 1 or match["pixel_difference"] != 0:
                raise ValueError(f"Non-unique exact match at {index}")
            char = one_character(match["characters"][0])
            if not "가" <= char <= "힣" or tuple(render(char)) != tuple(glyph["kor_rows"]):
                raise ValueError(f"Font pixels no longer match at {index}")
            evidence = "pixel_exact_gulim"
            if decision and decision["character"] != char:
                conflicts.append({"index": index, "code": code,
                                  "previous": decision, "selected_character": char,
                                  "reason": "existing_review_UI_prefers_pixel_exact"})
        elif decision:
            char, evidence = decision["character"], "human_" + decision["status"]
        elif index in SHARED_TEXT_INDICES and not glyph["changed"]:
            char = one_character(bytes.fromhex(code).decode("shift_jis"))
            evidence = "shared_pixels_visually_checked_sjis"
        elif index not in RAW_GLYPH_INDICES:
            raise ValueError(f"Unreviewed text glyph {index} {code}")
        entries.append({"id": glyph["id"], "index": index, "code": code,
                        "character": char, "evidence": evidence,
                        "review": decision})
    if len({entry["code"] for entry in entries}) != len(entries):
        raise ValueError("Duplicate legacy code")
    entries.append({"id": "renderer-space", "index": None, "code": "8140",
                    "character": "\u3000", "evidence": "renderer_space_branch", "review": None})
    return entries, conflicts


def restore(out, survey, recovered, font_path):
    from PIL import ImageFont

    source = recovered / "glyphs.json"
    digest, glyphs = source_data(source)
    matches = load_matches(MATCHES, digest)
    review = load_review(OUTPUT, digest)
    inputs = load_inputs(survey)
    report = json.loads((survey / "report.json").read_text())
    for lang, (_, expected_hash) in SOURCES.items():
        if report["inputs"][lang]["sha256"] != expected_hash:
            raise ValueError("Unsupported survey baseline")
        codes, rows = font(inputs[lang, "SLPS_017.97"])
        for index, glyph in enumerate(glyphs):
            if glyph["code"] != f"{codes[index]:04X}" or glyph[lang + "_rows"] != rows[index]:
                raise ValueError(f"Glyph source differs from extracted EXE: {lang}/{index}")
    for glyph in glyphs:
        if glyph["changed"] != (glyph["jpn_rows"] != glyph["kor_rows"]):
            raise ValueError("Invalid changed-glyph flag")
    if sha(font_path.read_bytes()) != matches["font_sha256"]:
        raise ValueError("Comparison font changed")
    bitmap_font = ImageFont.truetype(str(font_path), 12, index=0)
    entries, conflicts = compile_entries(glyphs, matches, review,
                                         lambda char: render_rows(bitmap_font, char))
    kor_map = {e["code"]: e["character"] for e in entries}
    jp_map = {g["code"]: (None if g["index"] in RAW_GLYPH_INDICES else
                          one_character(bytes.fromhex(g["code"]).decode("shift_jis")))
              for g in glyphs}
    jp_map["8140"] = "\u3000"
    codecs = {"kor": LegacyCodec(kor_map), "jpn": LegacyCodec(jp_map)}
    for codec in codecs.values():
        for code in codec.mapping:
            raw = bytes.fromhex(code)
            if codec.encode(codec.decode(raw)) != raw:
                raise ValueError("Character-table round trip failed")

    candidate_path = recovered / "dialogue-candidates.jsonl"
    pairs = [json.loads(line) for line in candidate_path.read_text().splitlines()]
    scans = {lang: scan_dialogue(inputs[lang, "SCN/DG.SCN"]) for lang in codecs}
    shared = sorted(scans["jpn"].keys() & scans["kor"].keys())
    if len(pairs) != len(shared):
        raise ValueError("Candidate population changed")
    extents = script_extents(inputs["jpn", "SCN/DG.SCN"])
    if extents != script_extents(inputs["kor", "SCN/DG.SCN"]):
        raise ValueError("DG allocations differ")
    raw_counts = {lang: Counter() for lang in codecs}
    uses = Counter()
    checked_bytes = Counter()
    restored = []
    for number, (pair, offset) in enumerate(zip(pairs, shared)):
        if (pair["offset"] != offset or pair["file"] != "SCN/DG.SCN"
                or pair["id"] != f"dialogue-candidate-{number:05d}"):
            raise ValueError("Candidate identity changed")
        section = next(i for i, (start, end) in enumerate(extents) if start <= offset < end)
        if section != pair["script_index"]:
            raise ValueError("Candidate allocation changed")
        row = dict(pair, product_eligible=False, offset_kind="logical_file_offset",
                   text_offset=f"0x{offset + 2:08X}")
        for lang, codec in codecs.items():
            raw = bytes.fromhex(pair[lang + "_hex"])
            if raw != scans[lang][offset]:
                raise ValueError(f"Candidate bytes changed: {pair['id']} {lang}")
            text = codec.decode(raw)
            encoded = codec.encode(text)
            source_bytes = inputs[lang, "SCN/DG.SCN"][offset + 2:offset + 2 + len(raw)]
            if encoded != raw or encoded != source_bytes:
                raise ValueError("Unicode round trip does not match source file")
            row["korean" if lang == "kor" else "japanese"] = text
            row[lang + "_roundtrip"] = True
            checked_bytes[lang] += len(raw)
            for at in range(0, len(raw), 2):
                code = raw[at:at + 2].hex().upper()
                if codec.mapping.get(code) is None:
                    raw_counts[lang][code] += 1
                if lang == "kor":
                    uses[code] += 1
        restored.append(row)

    aliases = {char: codes for char, codes in codecs["kor"].reverse.items() if len(codes) > 1}
    binding = {"glyphs_sha256": digest, "matches_sha256": sha(MATCHES.read_bytes()),
               "review_sha256": sha(OUTPUT.read_bytes()),
               "candidates_sha256": sha(candidate_path.read_bytes()),
               "font_sha256": matches["font_sha256"],
               "disc_sha256": {lang: values[1] for lang, values in SOURCES.items()},
               "dg_sha256": {lang: sha(inputs[lang, "SCN/DG.SCN"]) for lang in codecs}}
    summary = {"format": 1, "source": binding,
               "mapped_glyphs": sum(e["character"] is not None for e in entries if e["index"] is not None),
               "hangul_glyphs": sum(e["character"] is not None and "가" <= e["character"] <= "힣" for e in entries),
               "unique_hangul": len({e["character"] for e in entries if e["character"] is not None and "가" <= e["character"] <= "힣"}),
               "raw_glyph_codes": [e["code"] for e in entries if e["character"] is None],
               "duplicate_characters": aliases, "superseded_manual_conflicts": len(conflicts),
               "candidate_pairs": len(restored), "roundtrip_candidate_bytes": dict(checked_bytes),
               "all_candidate_unicode_roundtrips": True,
               "unresolved_units": {lang: dict(sorted(counts.items())) for lang, counts in raw_counts.items()},
               "raw_glyph_candidate_uses": {e["code"]: uses[e["code"]] for e in entries if e["character"] is None},
               "vm_boundaries_verified": False, "complete_text_extraction": False,
               "runtime_verified": False, "product_eligible": False}
    mapping = {"format": 1, "source": binding,
               "scope": "legacy EXE 0x800A575C glyph identities; DG units remain heuristic",
               "entries": entries, "duplicate_characters": aliases,
               "superseded_manual_decisions": conflicts}
    # All validation precedes output; preserve the exact review inputs locally.
    out.mkdir(parents=True, exist_ok=True)
    for path in (source, MATCHES, OUTPUT, candidate_path):
        snapshot = out / "inputs" / (sha(path.read_bytes()) + "-" + path.name)
        snapshot.parent.mkdir(exist_ok=True)
        if not snapshot.exists():
            snapshot.write_bytes(path.read_bytes())
    atomic_json(out / "character-map.json", mapping)
    atomic_json(out / "summary.json", summary)
    (out / "dialogue-candidates.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in restored), encoding="utf-8")
    display_glyphs = [dict(g, korean=kor_map[g["code"]]) for g in glyphs]
    payload = json.dumps({"glyphs": display_glyphs, "pairs": restored,
                          "mapping_summary": summary}, ensure_ascii=False).replace("<", "\\u003c")
    template = (ROOT / "tools/review.html").read_text()
    (out / "review.html").write_text(template.replace("/*RECOVERY_DATA*/null", payload), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "work/text")
    parser.add_argument("--survey", type=Path, default=ROOT / "work/survey")
    parser.add_argument("--recovered", type=Path, default=SOURCE.parent)
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    args = parser.parse_args()
    if not args.out.resolve().is_relative_to((ROOT / "work").resolve()):
        parser.error("Analysis outputs must stay under work/")
    if args.out.resolve() in {args.recovered.resolve(), MATCHES.parent.resolve(), args.survey.resolve()}:
        parser.error("Use a separate output directory to preserve inputs")
    print(json.dumps(restore(args.out, args.survey, args.recovered, args.font), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
