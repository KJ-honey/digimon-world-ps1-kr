"""Exact, source-bound protected streams for authorized dialogue reflows.

The registry contains hashes only, not game assets or translated prose. It
does not authorize arbitrary new lines, changed buttons, names, or arguments.
"""
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re

RULES = Path(__file__).with_name('dg_line_reflows.json')


def stream_hash(tokens):
    return sha256(json.dumps(tokens, separators=(',', ':')).encode()).hexdigest()


@lru_cache(maxsize=1)
def _load(path, stamp, size):
    return json.loads(path.read_text())['entries']


def reflow_allowed(entry_id, old, protected):
    if not RULES.exists():
        return False
    stat = RULES.stat()
    rule = _load(RULES, stat.st_mtime_ns, stat.st_size).get(entry_id)
    return rule == [sha256(old).hexdigest(), stream_hash(protected)]


def review_reflow_allowed(row, text):
    old = row.get('raw', {}).get('kor')
    if not old:
        return False
    tokens = [('glyph' if glyph else 'control', raw.lower())
              for glyph, raw in re.findall(r'⟦(G:)?([0-9A-F]{4,8})⟧', text)
              if glyph or raw != '0F00']
    tokens.append(('terminator', '0000'))
    return reflow_allowed(row['id'], bytes.fromhex(old), tokens)
