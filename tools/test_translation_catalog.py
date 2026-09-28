"""Non-DG boundaries, source identity and review routing regression checks."""
import json
from pathlib import Path
import tempfile
import unittest

from glyph_review import atomic_json
from translation_catalog import read_string, decode_reversible, install_baseline
from translation_review import Workspace, ReviewWorkspace, digest


class CatalogTests(unittest.TestCase):
    def test_additive_catalog_preserves_authored_decisions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            base = dict(format=1, source_disc_sha256={}, source_file_sha256={},
                        character_map_sha256='fixed', consumer_evidence=[], entries=[{'id': 'old'}])
            install_baseline(path, base)
            review = json.loads((path/'reviews.json').read_text())
            review['entries']['old'] = {'text': '기존 결정', 'revision': 7, 'history': [{'text': '이전'}]}
            atomic_json(path/'reviews.json', review)
            expanded = dict(base, entries=base['entries'] + [{'id': 'new'}])
            install_baseline(path, expanded)
            updated = json.loads((path/'reviews.json').read_text())
            self.assertEqual(updated['entries'], review['entries'])
            self.assertEqual(updated['baseline_sha256'], digest(expanded))
            self.assertEqual(json.loads((path/'history'/digest(base)/'reviews.json').read_text()), review)
            for changed in [dict(expanded, entries=[{'id': 'old', 'source': 'changed'}]),
                            dict(expanded, character_map_sha256='changed')]:
                with self.assertRaises(ValueError):
                    install_baseline(path, changed)
            self.assertEqual(json.loads((path/'reviews.json').read_text()), updated)

    def test_nul_is_one_byte_and_cannot_cross_field(self):
        data = bytes(0x800) + bytes.fromhex('8140814100123456')
        raw, tokens = read_string(data, 0x800, 0x805)
        self.assertEqual(raw, bytes.fromhex('8140814100'))
        self.assertEqual(len(tokens), 2)
        for limit in [0x803, 0x804]:
            with self.assertRaises(ValueError):
                read_string(data, 0x800, limit)
        with self.assertRaises(ValueError):
            read_string(bytes(0x800) + b'\x81\0', 0x800, 0x802)

    def test_aliases_and_unknown_glyphs_are_lossless(self):
        tokens = [{'kind': 'glyph', 'raw': code} for code in ['8140', '88c0', '95e2', '9860']]
        self.assertEqual(decode_reversible(tokens, {'8140': '　', '88C0': '늪', '95E2': '늪'}),
                         '　⟦G:88C0⟧⟦G:95E2⟧⟦G:9860⟧')

    def test_catalog_glyphs_are_editable_but_controls_are_not_allowed(self):
        row = dict(id='item_name-001', text_format='nul_glyph_string', source='原文', existing='초⟦G:9860⟧꽃')
        Workspace.validate(row, '초⟦G:9860⟧꽃 열매', 'draft')
        Workspace.validate(row, '초꽃 열매', 'draft')
        Workspace.validate(dict(row, existing='개굴⟦G:95E2⟧지'), '개굴늪지', 'draft')
        for text in ['초⟦G:9860⟧꽃⟦0D00⟧', '초⟦G:9860⟧꽃\n열매',
                     '초⟦G:98600000⟧꽃', '초⟦G:zzzz⟧꽃']:
            with self.assertRaises(ValueError):
                Workspace.validate(row, text, 'draft')

    def test_routing_preserves_dialogue_and_review_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for folder, key, text, kind in [(root, 'dg-text-000100', '대사⟦0D00⟧', 'dg'),
                                            (root/'catalog', 'location_name-043', '시작의　마을', 'nul_glyph_string')]:
                folder.mkdir(exist_ok=True)
                row = dict(id=key, source=text, existing=text, text_format=kind)
                row['baseline_sha256'] = digest(row)
                base = dict(format=1, entries=[row])
                atomic_json(folder/'baseline.json', base)
                atomic_json(folder/'reviews.json', dict(format=1, baseline_sha256=digest(base), entries={}))
            original = (root/'reviews.json').read_bytes()
            workspace = ReviewWorkspace(root)
            key = 'location_name-043'
            payload = dict(id=key, baseline_sha256=workspace.rows[key]['baseline_sha256'],
                           revision=0, text='시작의 마을', status='draft')
            first = workspace.save(payload, author='assistant')
            with self.assertRaises(ValueError):
                workspace.save(payload)
            workspace.save(dict(payload, revision=1, text='시작 마을'), author='assistant')
            saved = ReviewWorkspace(root).load()['entries'][key]
            self.assertEqual(saved['history'][0]['text'], first['text'])
            self.assertFalse(saved['product_eligible'])
            self.assertEqual((root/'reviews.json').read_bytes(), original)
            self.assertEqual(len(workspace.export()['families']), 2)
            self.assertEqual(set(Workspace(root).rows), {'dg-text-000100'})


if __name__ == '__main__':
    unittest.main()
