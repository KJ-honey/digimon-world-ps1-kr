"""Unverified candidate family: gap classification and review routing."""
import json
from pathlib import Path
import tempfile
import unittest

from glyph_review import atomic_json
from translation_candidates import code_gaps
from translation_review import Workspace, ReviewWorkspace, digest


class CandidateTests(unittest.TestCase):
    def test_gaps_stop_at_last_reached_end(self):
        script = dict(header_end=0x10)
        nodes = [dict(offset=0x10, end=0x14), dict(offset=0x18, end=0x30), dict(offset=0x20, end=0x24),
                 dict(offset=0x34, end=0x35)]
        self.assertEqual(code_gaps(script, nodes), ([(0x14, 0x18), (0x30, 0x34)], 0x35))

    def test_candidates_are_a_separate_family(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for folder, key in [(root, 'dg-text-000100'), (root/'candidates', 'dg-candidate-000200')]:
                folder.mkdir(exist_ok=True)
                row = dict(id=key, source='原文⟦0D00⟧', existing='대사⟦0D00⟧')
                if folder != root:
                    row.update(category='dialogue_candidate', boundary='unverified_candidate')
                row['baseline_sha256'] = digest(row)
                base = dict(format=1, entries=[row])
                atomic_json(folder/'baseline.json', base)
                atomic_json(folder/'reviews.json', dict(format=1, baseline_sha256=digest(base), entries={}))
            original = (root/'reviews.json').read_bytes()
            workspace = ReviewWorkspace(root)
            key = 'dg-candidate-000200'
            workspace.save(dict(id=key, baseline_sha256=workspace.rows[key]['baseline_sha256'],
                                revision=0, text='새 대사⟦0D00⟧', status='draft'), author='assistant')
            with self.assertRaises(ValueError):
                workspace.save(dict(id=key, baseline_sha256=workspace.rows[key]['baseline_sha256'],
                                    revision=1, text='제어 삭제', status='draft'), author='assistant')
            self.assertEqual((root/'reviews.json').read_bytes(), original)
            self.assertIn(key, json.loads((root/'candidates'/'reviews.json').read_text())['entries'])
            # Builders read the dialogue Workspace directly and never see candidates.
            self.assertEqual(set(Workspace(root).rows), {'dg-text-000100'})


if __name__ == '__main__':
    unittest.main()
