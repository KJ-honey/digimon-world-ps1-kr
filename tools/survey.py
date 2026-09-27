#!/usr/bin/env python3
"""Read-only, revision-locked survey of the two user-supplied raw PS1 discs.

Raw offsets, ISO LBAs and logical file offsets are kept distinct. Outputs are
local recovery evidence, not release inputs or a general-purpose ISO rebuilder.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import mmap
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "jpn": ("Digimon World(JPN).iso", "a99ce1cf5c3524b866603fe29f412c956131e7a2d48807e2508d9304ba6f20cd"),
    "kor": ("Digimon World (patched).iso", "12346b169b67fed618df8262e701781f42db1cdde7c459bb92190a24371f54d9"),
}
SECTOR = 2352
BLOCK = 2048


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dual32(b, offset):
    le = struct.unpack_from("<I", b, offset)[0]
    be = struct.unpack_from(">I", b, offset + 4)[0]
    if le != be:
        raise ValueError(f"ISO endian copies disagree at {offset}")
    return le


class Disc:
    def __init__(self, path):
        self.path = path
        self.handle = path.open("rb")
        self.raw = mmap.mmap(self.handle.fileno(), 0, access=mmap.ACCESS_READ)
        if len(self.raw) % SECTOR:
            raise ValueError("Not an integral raw-sector image")

    def close(self):
        self.raw.close()
        self.handle.close()

    def sector(self, lba):
        s = self.raw[lba * SECTOR:(lba + 1) * SECTOR]
        if len(s) != SECTOR or s[:12] != b"\x00" + b"\xff" * 10 + b"\x00":
            raise ValueError(f"Invalid sector {lba}")
        if s[15] != 2 or s[16:20] != s[20:24]:
            raise ValueError(f"Not Mode 2 with matching subheaders: {lba}")
        return s

    def read(self, lba, size):
        data = bytearray()
        for n in range((size + BLOCK - 1) // BLOCK):
            s = self.sector(lba + n)
            if s[18] & 0x20:
                raise ValueError(f"Form 2 cannot be read as a Form 1 file: {lba+n}")
            data.extend(s[24:2072])
        return bytes(data[:size])

    def files(self):
        pvd = self.read(16, BLOCK)
        if pvd[:7] != b"\x01CD001\x01" or struct.unpack_from("<H", pvd, 128)[0] != BLOCK:
            raise ValueError("Unsupported PVD")
        self.volume = pvd[40:72].decode("ascii").rstrip()
        result, seen = {}, set()

        def walk(lba, size, parent):
            if lba in seen:
                raise ValueError("Directory cycle/alias")
            seen.add(lba)
            b = self.read(lba, size)
            i = 0
            while i < len(b):
                length = b[i]
                if length == 0:
                    i = (i // BLOCK + 1) * BLOCK
                    continue
                if length < 34 or i + length > len(b) or i % BLOCK + length > BLOCK:
                    raise ValueError("Invalid directory record")
                r = b[i:i + length]
                i += length
                name = r[33:33 + r[32]]
                if name in (b"\0", b"\1"):
                    continue
                if r[1] or r[25] & 0x80 or r[26] or r[27]:
                    raise ValueError("Extended attributes, multi-extent or interleaving unsupported")
                name = name.decode("ascii").removesuffix(";1")
                if name in (".", "..") or "/" in name or "\\" in name:
                    raise ValueError("Unsafe path")
                path = parent + name
                extent, length = dual32(r, 2), dual32(r, 10)
                if r[25] & 2:
                    walk(extent, length, path + "/")
                else:
                    if path in result:
                        raise ValueError("Duplicate file")
                    result[path] = {"lba": extent, "size": length, "flags": r[25]}

        walk(dual32(pvd[156:], 2), dual32(pvd[156:], 10), "")
        return result


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "work/survey")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    discs, inputs, tables = {}, {}, {}
    try:
        for label, (name, expected) in SOURCES.items():
            d = Disc(args.source_dir / name)
            discs[label] = d
            digest = sha(d.raw)
            if digest != expected:
                raise ValueError(f"Unsupported {label} SHA-256: {digest}")
            tables[label] = d.files()
            inputs[label] = {"filename": name, "sha256": digest, "size": len(d.raw), "volume": d.volume}
        if tables["jpn"] != tables["kor"]:
            raise ValueError("Filesystem layouts differ; reassess correspondence")
        a, b = discs["jpn"], discs["kor"]
        if len(a.raw) != len(b.raw):
            raise ValueError("Image sizes differ")
        changed, payload_changed, protection_only = [], [], []
        sector_kinds = Counter()
        raw_diff_bytes = 0
        for lba in range(len(a.raw) // SECTOR):
            sa, sb = a.sector(lba), b.sector(lba)
            sector_kinds["form2" if sa[18] & 0x20 else "form1"] += 1
            if sa == sb:
                continue
            changed.append(lba)
            raw_diff_bytes += sum(x != y for x, y in zip(sa, sb))
            if sa[:24] != sb[:24]:
                raise ValueError(f"Modified header/subheader: {lba}")
            end = 2348 if sa[18] & 0x20 else 2072
            (payload_changed if sa[24:end] != sb[24:end] else protection_only).append(lba)
        changed_set, covered = set(changed), set()
        records = []
        for name, entry in sorted(tables["jpn"].items()):
            lba, size = entry["lba"], entry["size"]
            sectors = set(range(lba, lba + (size + BLOCK - 1) // BLOCK))
            affected = sorted(changed_set & sectors)
            covered.update(affected)
            record = {"path": name, **entry, "changed_sectors": len(affected)}
            records.append(record)
            if not affected and name not in ("SYSTEM.CNF", "SCN/MAPHEAD.SCN", "SHOP_REL.BIN"):
                continue
            forms = Counter("form2" if a.sector(s)[18] & 0x20 else "form1" for s in sectors)
            record["sector_kinds"] = dict(forms)
            if forms["form2"]:
                record["extraction_status"] = "raw extent hashed; mixed/Form 2 payload interpretation deferred"
                record["changed_payload_sectors"] = len(set(affected) & set(payload_changed))
                for label, d in discs.items():
                    record[label + "_raw_extent_sha256"] = sha(d.raw[lba*SECTOR:(lba+len(sectors))*SECTOR])
                continue
            record["extraction_status"] = "form1 payload extracted and verified"
            for label, d in discs.items():
                content = d.read(lba, size)
                out = args.out / "files" / label / name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(content)
                record[label + "_sha256"] = sha(content)
                # Independent final read against the raw source coordinates.
                recovered = out.read_bytes()
                for off in range(0, size, BLOCK):
                    count = min(BLOCK, size - off)
                    raw_at = (lba + off // BLOCK) * SECTOR + 24
                    if recovered[off:off+count] != d.raw[raw_at:raw_at+count]:
                        raise ValueError(f"Extraction mismatch: {label}/{name}/{off}")
            ca = (args.out / "files/jpn" / name).read_bytes()
            cb = (args.out / "files/kor" / name).read_bytes()
            record["changed_payload_bytes"] = sum(x != y for x, y in zip(ca, cb))
            record["first_difference"] = next((i for i, (x, y) in enumerate(zip(ca, cb)) if x != y), None)
            record["last_difference"] = next((i for i in range(size-1, -1, -1) if ca[i] != cb[i]), None)
        report = {
            "inputs": inputs, "raw_sector_bytes": SECTOR, "logical_block_bytes": BLOCK,
            "sector_count": len(a.raw) // SECTOR, "sector_kinds": dict(sector_kinds),
            "file_count": len(records), "identical_directory_layout": True,
            "changed_sector_count": len(changed), "changed_raw_bytes": raw_diff_bytes,
            "changed_payload_sector_count": len(payload_changed),
            "protection_only_changed_sectors": protection_only,
            "changed_sectors_outside_file_extents": sorted(changed_set - covered),
            "extraction_check": "All extracted bytes equal their raw-source payload coordinates; not a rebuild claim.",
            "files": records,
        }
        write_json(args.out / "report.json", report)
        write_json(args.out / "changed-sectors.json", changed)
        with (args.out / "files.csv").open("w", newline="") as f:
            fields = ["path", "lba", "size", "changed_sectors", "changed_payload_bytes", "first_difference", "last_difference", "jpn_sha256", "kor_sha256"]
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items() if k not in ("files", "inputs")}, indent=2))
        for r in records:
            if r["changed_sectors"]:
                print(r["path"], r["size"], r.get("changed_payload_bytes"), r.get("first_difference"), r.get("last_difference"))
    finally:
        for d in discs.values():
            d.close()


if __name__ == "__main__":
    main()
