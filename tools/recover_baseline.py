#!/usr/bin/env python3
"""Create a LOCAL legacy recovery delta and verify exact full-disc reconstruction.

This preserves every previous modification, including movies and raw-sector
protection fields. It is not an upgrade build or an approved release patch.
Requires xdelta3 in PATH. Existing outputs are never overwritten.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess

from survey import ROOT, SOURCES, write_json


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-dir", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=ROOT / "work/recovery")
    args = ap.parse_args()
    paths = {k: args.source_dir / v[0] for k, v in SOURCES.items()}
    for k, p in paths.items():
        if digest(p) != SOURCES[k][1]:
            raise ValueError(f"Unsupported or modified source: {p}")
    args.out.mkdir(parents=True, exist_ok=True)
    delta = args.out / "legacy-korean-local-recovery.xdelta"
    rebuilt = args.out / "legacy-rebuilt.iso"
    report = args.out / "verification.json"
    if any(p.exists() for p in (delta, rebuilt, report)):
        raise FileExistsError("Recovery outputs exist; choose a fresh --out directory")
    version = subprocess.run(["xdelta3", "-V"], capture_output=True, text=True, check=True)
    subprocess.run(["xdelta3", "-e", "-A", "-s", str(paths["jpn"]), str(paths["kor"]), str(delta)], check=True)
    subprocess.run(["xdelta3", "-d", "-s", str(paths["jpn"]), str(delta), str(rebuilt)], check=True)
    actual = digest(rebuilt)
    if actual != SOURCES["kor"][1]:
        raise ValueError(f"Reconstruction mismatch: {actual}")
    # Final input recheck also catches an external writer changing the baseline.
    for k, p in paths.items():
        if digest(p) != SOURCES[k][1]:
            raise ValueError(f"Source changed during recovery: {p}")
    data = {"claim": "exact legacy disc reconstruction only; no upgraded features",
            "inputs": {k: {"filename": v[0], "sha256": v[1]} for k, v in SOURCES.items()},
            "tool_version": (version.stdout+version.stderr).splitlines()[0],
            "delta_size": delta.stat().st_size, "delta_sha256": digest(delta),
            "rebuilt_size": rebuilt.stat().st_size, "rebuilt_sha256": actual,
            "full_disc_byte_identity": True, "runtime_verified": False,
            "distribution_status": "local recovery only; not reviewed for distribution"}
    write_json(report, data)
    print(f"Verified full-disc SHA-256: {actual}\nRecovery delta: {delta} ({delta.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
