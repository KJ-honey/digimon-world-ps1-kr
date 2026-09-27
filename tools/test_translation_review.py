"""Persistence and source/token guards for the wording-only workspace."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from glyph_review import atomic_json
from translation_review import Workspace, digest, render_tokens


class TranslationReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.row = {'id': 'dg-text-000100', 'source': '名⟦03000100⟧です⟦0D00⟧',
                    'existing': '이름⟦03000100⟧입니다⟦0D00⟧', 'script': 0}
        self.row['baseline_sha256'] = digest(self.row)
        self.baseline = {'format': 1, 'entries': [self.row]}
        atomic_json(self.path/'baseline.json', self.baseline)
        atomic_json(self.path/'reviews.json', {'format': 1, 'baseline_sha256': digest(self.baseline), 'entries': {}})
        self.workspace = Workspace(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, **kw):
        p = dict(id=self.row['id'], baseline_sha256=self.row['baseline_sha256'],
                 revision=0, text='제 이름은 ⟦03000100⟧입니다. 만나서 반갑습니다.⟦0D00⟧', status='draft')
        p.update(kw)
        return p

    def test_expansion_persists_without_byte_limit(self):
        self.workspace.save(self.payload(text='길이를 줄일 필요가 없습니다. '*50+'⟦03000100⟧⟦0D00⟧'), author='assistant')
        saved = Workspace(self.path).load()['entries'][self.row['id']]
        self.assertGreater(len(saved['text']), len(self.row['existing']))
        self.assertFalse(saved['product_eligible'])

    def test_lost_changed_or_reordered_controls_fail(self):
        for text in ['이름⟦0D00⟧', '⟦03000200⟧⟦0D00⟧', '⟦0D00⟧⟦03000100⟧', '⟦03000100⟧⟦0D00⟧⟦zz⟧']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.workspace.save(self.payload(text=text))

    def test_revision_conflict_cannot_overwrite(self):
        p=self.payload()
        self.workspace.save(p)
        with self.assertRaises(ValueError):
            self.workspace.save(dict(p, text='다른 창의 수정⟦03000100⟧⟦0D00⟧'))
        self.assertEqual(self.workspace.load()['entries'][self.row['id']]['text'], p['text'])

    def test_history_and_return_to_original(self):
        first=self.workspace.save(self.payload())
        self.workspace.save(self.payload(revision=1, text=self.row['existing'], status='unchanged'))
        item=self.workspace.load()['entries'][self.row['id']]
        self.assertEqual(item['history'][0]['wording_sha256'], first['wording_sha256'])
        self.assertEqual(item['revision'], 2)
        self.assertEqual(item['text'], self.row['existing'])

    def test_source_fields_and_stale_baselines_rejected(self):
        with self.assertRaises(ValueError):
            self.workspace.save(self.payload(source='改変'))
        with self.assertRaises(ValueError):
            self.workspace.save(self.payload(baseline_sha256='wrong'))
        changed=copy.deepcopy(self.baseline)
        changed['entries'][0]['source']='changed'
        atomic_json(self.path/'baseline.json', changed)
        with self.assertRaises(ValueError):
            Workspace(self.path)

    def test_assistant_cannot_approve(self):
        with self.assertRaises(ValueError):
            self.workspace.save(self.payload(status='accepted'), author='assistant')
        item=self.workspace.save(self.payload(status='accepted'))
        self.assertFalse(item['product_eligible'])
        self.assertFalse(item['layout_verified'])
        self.assertFalse(item['runtime_verified'])

    def test_original_missing_name_controls_can_be_restored(self):
        row=dict(self.row, source='⟦0106⟧⟦0500⟧⟦0101⟧さん⟦0D00⟧', existing='너⟦0D00⟧')
        Workspace.validate(row, '⟦0106⟧⟦0500⟧⟦0101⟧ 씨⟦0D00⟧', 'draft')
        with self.assertRaises(ValueError):
            Workspace.validate(row, '⟦0106⟧⟦0600⟧⟦0101⟧ 씨⟦0D00⟧', 'draft')

    def test_four_byte_operands_do_not_decode_as_glyphs(self):
        tokens=[{'kind':'glyph','raw':'8140'}, {'kind':'control','raw':'03000000'},
                {'kind':'glyph','raw':'abcd'}, {'kind':'control','raw':'0d00'},
                {'kind':'terminator','raw':'0000'}]
        self.assertEqual(render_tokens(tokens, {'8140':'　'}), '　⟦03000000⟧⟦G:ABCD⟧⟦0D00⟧')


if __name__ == '__main__':
    unittest.main()
