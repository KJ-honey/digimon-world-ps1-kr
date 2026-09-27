#!/usr/bin/env python3
"""Local, source-bound review of OCR glyph suggestions.

Run: python3 tools/glyph_review.py --open
The source glyphs.json is read-only; decisions live under work/review/.
"""

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import tempfile
import unicodedata
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "work/recovered/glyphs.json"
OUTPUT = ROOT / "work/review/glyph-review.json"
MATCHES = ROOT / "work/review/glyph-matches.json"
PAGE = Path(__file__).with_name("glyph_compare.html")


def source_data(path):
    raw = path.read_bytes()
    glyphs = json.loads(raw)
    if not isinstance(glyphs, list) or len(glyphs) != 991:
        raise ValueError("Expected the 991-glyph recovered table")
    for i, glyph in enumerate(glyphs):
        if glyph.get("index") != i or glyph.get("id") != f"legacy-glyph-{i:04d}":
            raise ValueError(f"Unexpected glyph index {i}")
    return hashlib.sha256(raw).hexdigest(), glyphs


def load_review(path, source_hash):
    if not path.exists():
        return {"format": 1, "source_sha256": source_hash, "decisions": {}}
    review = json.loads(path.read_text(encoding="utf-8"))
    if review.get("format") != 1 or review.get("source_sha256") != source_hash:
        raise ValueError("Review file belongs to a different glyphs.json; move it aside or restore the source")
    if not isinstance(review.get("decisions"), dict):
        raise ValueError("Invalid review file")
    return review


def load_matches(path, source_hash):
    matches = json.loads(path.read_text(encoding="utf-8"))
    if matches.get("format") != 1 or matches.get("source_sha256") != source_hash:
        raise ValueError("Font comparison belongs to a different glyphs.json; rerun match_gulim.py")
    return matches


def validate_decision(payload, glyphs):
    if type(payload.get("index")) is not int or not 0 <= payload["index"] < len(glyphs):
        raise ValueError("Invalid glyph index")
    index = payload["index"]
    if payload.get("status") != "confirmed":
        raise ValueError("Invalid review status")
    char = payload.get("character", "")
    if not isinstance(char, str):
        raise ValueError("Character must be text")
    char = unicodedata.normalize("NFC", char.strip())
    if len(char) != 1 or unicodedata.category(char)[0] == "C":
        raise ValueError("Mapping must be exactly one visible Unicode character")
    note = payload.get("note", "")
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError("Note must be at most 2000 characters")
    return index, {"status": "confirmed", "character": char, "note": note.strip(),
                   "code": glyphs[index]["code"], "ocr_at_review": glyphs[index].get("ocr_suggestion")}


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".glyph-review-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def handler_for(source, output, page, matches_path=MATCHES):
    class Handler(BaseHTTPRequestHandler):
        def send_data(self, status, data, content_type="application/json; charset=utf-8"):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self.send_data(200, page.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/data":
                try:
                    digest, glyphs = source_data(source)
                    review = load_review(output, digest)
                    matches = load_matches(matches_path, digest)
                    self.send_data(200, {"source_sha256": digest, "glyphs": glyphs,
                                         "decisions": review["decisions"], "comparison": matches})
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    self.send_data(409, {"error": str(exc)})
            else:
                self.send_data(404, {"error": "Not found"})

        def do_POST(self):
            if self.path != "/api/review":
                self.send_data(404, {"error": "Not found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    raise ValueError("Invalid request size")
                payload = json.loads(self.rfile.read(size))
                digest, glyphs = source_data(source)
                if payload.get("source_sha256") != digest:
                    raise ValueError("Glyph source changed; reload the page")
                review = load_review(output, digest)
                matches = load_matches(matches_path, digest)
                index, decision = validate_decision(payload, glyphs)
                matched = matches["matches"].get(str(index))
                if matched and matched["kind"] == "exact":
                    raise ValueError("Pixel-identical glyphs are already resolved by the font comparison")
                review["decisions"][str(index)] = decision
                atomic_json(output, review)
                self.send_data(200, {"index": index, "decision": decision})
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_data(409, {"error": str(exc)})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--matches", type=Path, default=MATCHES)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the review page in a browser")
    args = parser.parse_args()
    digest, _ = source_data(args.source)
    load_review(args.output, digest)
    load_matches(args.matches, digest)
    server = HTTPServer(("127.0.0.1", args.port), handler_for(args.source, args.output, PAGE, args.matches))
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Glyph review: {url}\nDecisions: {args.output}", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
