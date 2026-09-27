"""Data-integrity checks for the local glyph review tool."""
import hashlib
from http.server import HTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import glyph_review


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source = base / "glyphs.json"
        self.output = base / "review.json"
        self.matches = base / "matches.json"
        glyphs = [{"id": f"legacy-glyph-{i:04d}", "index": i,
                   "code": f"{i:04X}", "ocr_suggestion":
                   {"text": "가", "confidence": 80} if i == 0 else None}
                  for i in range(991)]
        self.source.write_text(json.dumps(glyphs), encoding="utf-8")
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.matches.write_text(json.dumps({"format": 1, "source_sha256": self.digest,
            "matches": {"0": {"kind": "unmatched", "characters": []},
                        "1": {"kind": "exact", "characters": ["나"]}}}))
        self.server = HTTPServer(("127.0.0.1", 0),
            glyph_review.handler_for(self.source, self.output, glyph_review.PAGE, self.matches))
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def post(self, **fields):
        payload = {"source_sha256": self.digest, "index": 0,
                   "status": "confirmed", "character": "가", "note": "checked"} | fields
        request = Request(self.url + "/api/review", json.dumps(payload).encode(),
                          {"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_save_and_reload_with_source_binding(self):
        self.assertFalse(self.output.exists())
        status, result = self.post()
        self.assertEqual(status, 200)
        self.assertEqual(result["decision"]["character"], "가")
        with urlopen(self.url + "/api/data") as response:
            self.assertEqual(json.load(response)["decisions"]["0"]["status"], "confirmed")
        self.assertEqual(json.loads(self.output.read_text())["source_sha256"], self.digest)
        status, _ = self.post(source_sha256="0" * 64)
        self.assertEqual(status, 409)
        self.assertEqual(len(json.loads(self.output.read_text())["decisions"]), 1)

    def test_invalid_mapping_does_not_replace_review(self):
        self.post()
        original = self.output.read_bytes()
        for change in ({"character": "가나"}, {"character": ""},
                       {"status": "rejected"}, {"index": 991}, {"index": 1, "character": "나"}):
            status, _ = self.post(**change)
            self.assertEqual(status, 409)
            self.assertEqual(self.output.read_bytes(), original)
        status, _ = self.post(character="나")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(self.output.read_text())["decisions"]["0"]["character"], "나")


if __name__ == "__main__":
    unittest.main()
