#!/usr/bin/env python3
"""Translation-only workspace. No encoder, ISO writer, or product manifest export.

python3 tools/translation_review.py prepare
python3 tools/translation_review.py serve --open
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import secrets
import webbrowser
import fcntl

from glyph_review import atomic_json
from survey import ROOT, SOURCES, sha

WORK = ROOT / 'work/translation'
TOKEN = re.compile(r'⟦(?:G:)?[0-9A-F]{4,8}⟧')
STATES = {'draft', 'accepted', 'held', 'unchanged'}


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True).encode())


def now():
    return datetime.now(timezone.utc).isoformat()


def render_tokens(tokens, mapping):
    """Decode only glyph tokens; a 03 operand is never decoded as text."""
    out = []
    for token in tokens:
        code = token['raw'].upper()
        if token['kind'] == 'terminator':
            continue
        if token['kind'] == 'control':
            out.append('⟦' + code + '⟧')
        else:
            char = mapping.get(code)
            out.append(char if char is not None else '⟦G:' + code + '⟧')
    return ''.join(out)


def prepare(directory=WORK):
    from dg_analyze import read_source, verified_texts
    from dg_script import decode
    from restore_text import RAW_GLYPH_INDICES
    inputs = {lang: read_source(lang) for lang in SOURCES}
    map_path = ROOT / 'work/text/character-map.json'
    cmap = json.loads(map_path.read_text())
    maps = {'kor': {e['code']: e['character'] for e in cmap['entries']}, 'jpn': {}}
    for entry in cmap['entries']:
        if entry['index'] in RAW_GLYPH_INDICES:
            maps['jpn'][entry['code']] = None
        else:
            maps['jpn'][entry['code']] = bytes.fromhex(entry['code']).decode('shift_jis')
    parsed = {lang: decode(files['SCN/DG.SCN']) for lang, files in inputs.items()}
    texts = {lang: verified_texts(p) for lang, p in parsed.items()}
    if texts['kor'].keys() != texts['jpn'].keys():
        raise ValueError('Different JP/KR consumer boundaries')
    for lang in inputs:
        if cmap['source']['dg_sha256'][lang] != sha(inputs[lang]['SCN/DG.SCN']):
            raise ValueError('Stale character map')
    entries = []
    for key, kr in texts['kor'].items():
        jp = texts['jpn'][key]
        if (jp['payload'], jp['end']) != (kr['payload'], kr['end']):
            raise ValueError('Different JP/KR text ends')
        row = {'id': key, 'script': kr['script'], 'file': 'SCN/DG.SCN',
               'logical_offset': kr['header'], 'instruction': kr['instruction'],
               'source': render_tokens(jp['tokens'], maps['jpn']),
               'existing': render_tokens(kr['tokens'], maps['kor']),
               'raw': {lang: inputs[lang]['SCN/DG.SCN'][t[key]['payload']:t[key]['end']].hex()
                       for lang, t in texts.items()},
               'tokens': {'jpn': jp['tokens'], 'kor': kr['tokens']},
               'context': '동일 script의 파일 순서. 실제 대화 순서·화자 확정 자료가 아님.',
               'boundary': 'consumer_verified', 'product_eligible': False}
        row['baseline_sha256'] = digest(row)
        entries.append(row)
    baseline = {'format': 1, 'source_disc_sha256': {k: v[1] for k, v in SOURCES.items()},
                'character_map_sha256': sha(map_path.read_bytes()), 'entries': entries,
                'scope': {'confirmed_dg_units': len(entries), 'unresolved_search_candidates': 3381,
                          'complete_game_extraction': False, 'other_modules': 'not inventoried',
                          'unresolved_vm_paths': parsed['kor']['errors']},
                'purpose': 'wording_review_only; not a reinsertion manifest'}
    path = directory / 'baseline.json'
    if path.exists() and json.loads(path.read_text()) != baseline:
        raise ValueError('Baseline changed; do not overwrite a workspace with reviews')
    atomic_json(path, baseline)
    if not (directory / 'reviews.json').exists():
        atomic_json(directory / 'reviews.json', {'format': 1, 'baseline_sha256': digest(baseline), 'entries': {}})
    print(json.dumps({'entries': len(entries), 'baseline': str(path)}, ensure_ascii=False))


class Workspace:
    def __init__(self, directory):
        self.directory = directory
        self.baseline = json.loads((directory / 'baseline.json').read_text())
        self.baseline_hash = digest(self.baseline)
        self.baseline_stat = (directory / 'baseline.json').stat()
        self.rows = {r['id']: r for r in self.baseline['entries']}
        if len(self.rows) != len(self.baseline['entries']):
            raise ValueError('Duplicate baseline IDs')
        self.load()

    def load(self):
        current = (self.directory / 'baseline.json').stat()
        if (current.st_mtime_ns, current.st_size) != (self.baseline_stat.st_mtime_ns, self.baseline_stat.st_size):
            if digest(json.loads((self.directory / 'baseline.json').read_text())) != self.baseline_hash:
                raise ValueError('원문 기준 파일이 바뀌었습니다. 서버를 다시 시작해 주세요.')
            self.baseline_stat = current
        data = json.loads((self.directory / 'reviews.json').read_text())
        if data['baseline_sha256'] != self.baseline_hash:
            raise ValueError('Review baseline mismatch')
        for key, item in data['entries'].items():
            if key not in self.rows or item['baseline_sha256'] != self.rows[key]['baseline_sha256']:
                raise ValueError('Stale or unknown review ID')
            self.validate(self.rows[key], item['text'], item['status'])
        return data

    @staticmethod
    def validate(row, text, status):
        if not isinstance(text, str) or not text.strip() or len(text) > 50000:
            raise ValueError('번역문이 비어 있거나 비정상적으로 큽니다.')
        if status not in STATES:
            raise ValueError('Unknown wording state')
        controls = lambda s: re.findall(r'⟦[0-9A-F]{4,8}⟧', s)
        glyphs = lambda s: re.findall(r'⟦G:[0-9A-F]{4}⟧', s)
        restored_source_controls = (controls(row['source']) != controls(row['existing'])
                                    and controls(text) == controls(row['source'])
                                    and glyphs(text) == glyphs(row['existing']))
        # A prior translation can omit a button glyph together with its colors.
        # Restore only the exact source token stream, retaining every existing
        # unknown glyph in order; never infer a replacement button or drop one.
        source_glyphs = iter(glyphs(row['source']))
        retains_existing_glyphs = all(any(candidate == glyph for candidate in source_glyphs)
                                      for glyph in glyphs(row['existing']))
        restored_source_tokens = (controls(row['source']) != controls(row['existing'])
                                  and TOKEN.findall(text) == TOKEN.findall(row['source'])
                                  and retains_existing_glyphs)
        if (TOKEN.findall(text) != TOKEN.findall(row['existing'])
                and not restored_source_controls and not restored_source_tokens):
            raise ValueError('보호 토큰의 순서·값·개수를 유지해 주세요. 원문 토큰 보기에서 확인할 수 있습니다.')
        remainder = TOKEN.sub('', text)
        if '⟦' in remainder or '⟧' in remainder or any(ord(c) < 32 and c not in '\n\t' for c in remainder):
            raise ValueError('잘못된 보호 토큰 또는 제어 문자가 있습니다.')
        if status == 'unchanged' and text != row['existing']:
            raise ValueError('기존 번역 유지 상태에는 원래 문장만 저장할 수 있습니다.')

    def save(self, payload, author='human'):
        # The browser server and a CLI draft import may run at the same time.
        with (self.directory / '.write.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._save_locked(payload, author)

    def _save_locked(self, payload, author):
        allowed = {'id', 'baseline_sha256', 'revision', 'text', 'status', 'note', 'rationale', 'context'}
        if set(payload) - allowed:
            raise ValueError('Cannot edit protected source fields')
        row = self.rows[payload['id']]
        if payload['baseline_sha256'] != row['baseline_sha256']:
            raise ValueError('Source baseline changed')
        data = self.load()
        previous = data['entries'].get(row['id'])
        revision = previous['revision'] if previous else 0
        if type(payload['revision']) is not int or payload['revision'] != revision:
            raise ValueError('다른 창에서 저장한 내용이 있습니다. 초안을 복사한 뒤 새로고침해 주세요.')
        self.validate(row, payload['text'], payload['status'])
        if author != 'human' and payload['status'] in {'accepted', 'unchanged'}:
            raise ValueError('Only a human can approve wording')
        for field in ('note', 'rationale', 'context'):
            if not isinstance(payload.get(field, ''), str) or len(payload.get(field, '')) > 10000:
                raise ValueError('Invalid '+field)
        history = previous.get('history', []) + [{k: v for k, v in previous.items() if k != 'history'}] if previous else []
        item = {k: payload.get(k, '') for k in ('text', 'status', 'note', 'rationale', 'context')}
        item.update(baseline_sha256=row['baseline_sha256'], revision=revision+1,
                    updated_at=now(), author=author, wording_sha256=sha(item['text'].encode()),
                    history=history, product_eligible=False,
                    layout_verified=False, runtime_verified=False)
        controls = lambda s: re.findall(r'⟦[0-9A-F]{4,8}⟧', s)
        item['source_control_difference'] = controls(row['source']) != controls(row['existing'])
        item['source_controls_restored_in_draft'] = item['source_control_difference'] and controls(item['text']) == controls(row['source'])
        item['source_tokens_restored_in_draft'] = (TOKEN.findall(row['source']) != TOKEN.findall(row['existing'])
                                                 and TOKEN.findall(item['text']) == TOKEN.findall(row['source']))
        data['entries'][row['id']] = item
        atomic_json(self.directory / 'reviews.json', data)
        return item

    def export(self):
        reviews = self.load()
        return {'format': 1, 'purpose': 'wording review backup; not product input',
                'baseline': self.baseline, 'reviews': reviews,
                'supporting_records': {name: json.loads((self.directory/name).read_text())
                                       for name in ('style-decisions.json', 'issues.json')
                                       if (self.directory/name).exists()}}


def handler_for(workspace):
    csrf = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def valid_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

        def respond(self, status, body, kind='application/json; charset=utf-8'):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.valid_host():
                self.respond(403, {'error': 'Local host only'})
                return
            try:
                if self.path == '/':
                    self.respond(200, Path(__file__).with_name('translation_review.html').read_bytes(), 'text/html; charset=utf-8')
                elif self.path == '/api/data':
                    self.respond(200, {'baseline': workspace.baseline, 'reviews': workspace.load()['entries'], 'csrf': csrf})
                elif self.path == '/api/export':
                    self.respond(200, workspace.export())
                else:
                    self.respond(404, {'error': 'Not found'})
            except (OSError, ValueError) as exc:
                self.respond(409, {'error': str(exc)})

        def do_POST(self):
            if not self.valid_host():
                self.respond(403, {'error': 'Local host only'})
                return
            if self.path != '/api/save':
                self.respond(404, {'error': 'Not found'})
                return
            if self.headers.get('X-Review-Token') != csrf:
                self.respond(403, {'error': 'Invalid session token'})
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size < 300000:
                    raise ValueError('Invalid request size')
                item = workspace.save(json.loads(self.rfile.read(size)))
                self.respond(200, item)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.respond(409, {'error': str(exc)})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'serve', 'import', 'report'])
    parser.add_argument('--directory', type=Path, default=WORK)
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    if not args.directory.resolve().is_relative_to((ROOT / 'work').resolve()):
        parser.error('Workspace must stay under work/')
    if args.command == 'prepare':
        prepare(args.directory)
        return
    workspace = Workspace(args.directory)
    if args.command == 'import':
        # Authored per-unit drafts only: this command has no prose transformation rule.
        rows = json.loads(args.input.read_text())
        seen = set()
        for item in rows:
            if item['id'] in seen:
                raise ValueError('Duplicate draft ID')
            seen.add(item['id'])
            workspace.validate(workspace.rows[item['id']], item['text'], item['status'])
            if item['id'] in workspace.load()['entries']:
                raise ValueError('Import cannot overwrite an existing decision')
        for item in rows:
            workspace.save(dict(item, baseline_sha256=workspace.rows[item['id']]['baseline_sha256'], revision=0), author='assistant')
        print(f'Imported {len(rows)} authored drafts')
    elif args.command == 'report':
        reviews = workspace.load()['entries']
        print(json.dumps({'scope': workspace.baseline['scope'], 'wording_states': dict(Counter(x['status'] for x in reviews.values())),
                          'changed': sum(x['text'] != workspace.rows[k]['existing'] for k, x in reviews.items()),
                          'not_started': len(workspace.rows)-len(reviews), 'product_eligible': 0}, ensure_ascii=False, indent=2))
    else:
        server = HTTPServer(('127.0.0.1', args.port), handler_for(workspace))
        url = f'http://127.0.0.1:{server.server_port}/'
        print(f'Translation review: {url}\nSaved: {args.directory / "reviews.json"}', flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
