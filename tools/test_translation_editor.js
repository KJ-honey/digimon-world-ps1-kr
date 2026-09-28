// Serialization tests only; no browser automation or external packages.
// node --test tools/test_translation_editor.js
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, 'translation_review.html'), 'utf8');
const definitions = html.match(/const display=[\s\S]*?const plain=/)[0].replace(/const plain=$/, '');
const roundtrip = new Function('text', definitions + 'return fromEditor(editorText(text));');

test('editor preserves a final blank line, arguments, and unknown glyphs', () => {
  for (const text of [
    '예문⟦0D00⟧', '예문⟦0D00⟧⟦0D00⟧',
    '앞줄⟦0D00⟧　⟦0D00⟧⟦0D00⟧',
    '⟦0106⟧⟦03000000⟧⟦0101⟧ ⟦G:816F⟧⟦0D00⟧',
  ]) assert.equal(roundtrip(text), text);
});

const workspace = path.join(__dirname, '../work/translation');
test('all local baseline strings and authored drafts roundtrip exactly', {
  skip: !fs.existsSync(path.join(workspace, 'baseline.json')),
}, () => {
  const baseline = JSON.parse(fs.readFileSync(path.join(workspace, 'baseline.json')));
  for (const row of baseline.entries) assert.equal(roundtrip(row.existing), row.existing, row.id);
  const reviews = JSON.parse(fs.readFileSync(path.join(workspace, 'reviews.json')));
  for (const [id, row] of Object.entries(reviews.entries)) assert.equal(roundtrip(row.text), row.text, id);
});

const catalogRoundtrip = new Function('text', definitions +
  "const row={text_format:'nul_glyph_string'}; return fromEditor(editorText(text,row),row);");
test('catalog editor never adds DG terminators or rewrites spaces', () => {
  for (const text of ['시작의　마을', '회복 플로피', '초⟦G:9860⟧꽃 열매'])
    assert.equal(catalogRoundtrip(text), text);
  const file = path.join(workspace, 'catalog/baseline.json');
  if (fs.existsSync(file)) {
    for (const row of JSON.parse(fs.readFileSync(file)).entries)
      for (const value of [row.source, row.existing]) assert.equal(catalogRoundtrip(value), value, row.id);
  }
});

const filterDefinitions = html.slice(html.indexOf('const categories='), html.indexOf('function error('));
const matchesDefinition = html.slice(html.indexOf('function matches('), html.indexOf('function filter('));
const matchRow = new Function('r', 'data', 'reviews', 'values',
  'const $=id=>({value:values[id]});' + filterDefinitions + matchesDefinition + 'return matches(r);');
test('speaker filter combines with search, category and review status', () => {
  const r={id:'line', script:1, source:'原文', existing:'번역'};
  const data={speakers:{line:{label:'할배몬 / ジジモン', candidates:[{id:'jiji'}]}}};
  const values={category:'all',filter:'all',script:'all',search:'', 'speaker-filter':'jiji'};
  assert.equal(matchRow(r,data,{},values),true);
  assert.equal(matchRow(r,data,{}, {...values,'speaker-filter':'player'}),false);
  assert.equal(matchRow(r,data,{}, {...values,search:'할배몬'}),true);
  assert.equal(matchRow(r,data,{}, {...values,category:'item_name'}),false);
  assert.equal(matchRow(r,data,{}, {...values,filter:'accepted'}),false);
  assert.equal(matchRow({...r,id:'catalog',category:'item_name'},data,{},values),false);
});
