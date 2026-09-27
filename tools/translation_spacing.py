#!/usr/bin/env python3
"""Apply the user's 2026-09-28 spacing instruction to the current DG drafts.

Explicit, reviewable migration; never run implicitly during export/build.
Keep a complete checkpoint, per-entry before/after, and original token stream.
"""
import argparse
from collections import Counter
import copy
import fcntl
import json
from pathlib import Path
import re
import unicodedata

from glyph_review import atomic_json
from survey import ROOT, sha, write_json
from translation_review import Workspace, WORK, TOKEN, now

LINE = '⟦0D00⟧'
PREFIX = re.compile(r'^(?:[ 　]|⟦01[0-9A-F]{2}⟧)*')
PUNCT = re.compile(r'([,!、，！])[ 　]+')
PRICE = re.compile(r'([0-9０-９]+)(⟦G:816F⟧⟦G:8170⟧)([ 　]*)$')


def width(text):
    """Static pixel width for fixed glyphs/colors only; reject dynamic fields."""
    result, at = 0, 0
    for token in TOKEN.finditer(text):
        result += sum(6 if c == ' ' else 12 for c in text[at:token.start()])
        if token.group().startswith('⟦G:'):
            result += 12
        elif not token.group().startswith('⟦01'):
            raise ValueError('Dynamic width must not be guessed')
        at = token.end()
    return result + sum(6 if c == ' ' else 12 for c in text[at:])


def pad(pixels):
    if pixels < 0 or pixels % 6:
        raise ValueError('Unrepresentable spacing')
    full, half = divmod(pixels, 12)
    return '　' * full + ' ' * (half // 6)


def restore_indent(source, target):
    sp, tp = PREFIX.match(source).group(), PREFIX.match(target).group()
    # Preserve the exact placement relative to color controls when possible.
    if TOKEN.findall(sp) == TOKEN.findall(tp):
        return sp + target[len(tp):]
    return '　' * (sp.count('　') + sp.count(' ')) + tp.replace(' ', '').replace('　', '') + target[len(tp):]


def transform(row, text):
    source = row['source']
    quoted = '「' in source or '」' in source
    notes = []
    text, removed = PUNCT.subn(r'\1', text)
    if removed:
        notes.append(f'comma_exclamation_gap:{removed}')
    if row['script'] == 224:
        return text, notes + ['achievement_grid_full_spaces_preserved']
    # Ordinary existing ideographic spaces in dialogue prose become half spaces;
    # source indentation is restored below as explicit full spaces.
    if quoted:
        text = text.replace('　', ' ')
    src, dst = source.split(LINE), text.split(LINE)
    if len(src) != len(dst):
        raise ValueError('Source/draft line boundaries differ: '+row['id'])
    price_right = 0
    for s, t in zip(src, dst):
        sm, tm = PRICE.search(s), PRICE.search(t)
        if sm and tm and re.search(r'　|』', s[:sm.start()]):
            label = restore_indent(s, t)[:]
            lm = PRICE.search(label)
            label = label[:lm.start()].rstrip(' 　:：')
            price_right = max(price_right, width(s[:sm.end(1)]),
                              width(label) + 6 + width(tm[1]))
    out = []
    for s, t in zip(src, dst):
        before = t
        t = restore_indent(s, t)
        if t != before:
            notes.append('source_full_indent')
        if not quoted:
            # Menus reviewed as price columns: retain the original numeric right
            # edge, accounting for Korean wording length and 6 px word spaces.
            sm, tm = PRICE.search(s), PRICE.search(t)
            if sm and tm and re.search(r'　|』', s[:sm.start()]):
                if unicodedata.normalize('NFKC', sm[1]) != tm[1]:
                    raise ValueError('Price differs from source: '+row['id'])
                label = t[:tm.start()].rstrip(' 　:：')
                target_x = price_right - width(tm[1])
                if price_right > width(s[:sm.end(1)]):
                    notes.append('price_column_extended_for_wording')
                t = label + pad(target_x-width(label)) + tm[1] + tm[2] + sm[3]
                notes.append('source_price_column')
            # Reviewed repeated result displays: preserve the full-cell visual
            # separator; Korean particles remain attached to the subject.
            if '全売り上げ　' in s:
                t = t.replace('총매출 ', '총매출　')
                notes.append('result_field_full_gap')
            if '売り上げ　' in s and '全売り上げ' not in s:
                t = t.replace('매출 ', '매출　')
                notes.append('result_field_full_gap')
            if '回戦　８名出場' in s:
                t = t.replace('회전,8명', '회전　8명')
                notes.append('tournament_field_separator')
            if re.search('(?:上がった|上がる)', s) and '　' in s.strip('　'):
                t = re.sub(r'([이가]) ([0-9]+)', r'\1　\2', t)
                notes.append('stat_result_full_gap')
            if s.endswith('　'):
                t = t.rstrip(' 　') + '　' * (len(s)-len(s.rstrip('　')))
        out.append(t)
    text = LINE.join(out)
    # Individually reviewed exceptions, anchored to original IDs and words.
    replacements = {
        'dg-text-0043b8': [('소지 ', '소지'), ('  ⟦0A00⟧', '　　⟦0A00⟧')],
        'dg-text-0043ce': [('  ⟦0B00⟧', '　　⟦0B00⟧')],
        'dg-text-0059a6': [('  ', '　　')],
        'dg-text-005dc0': [('예  아니요', '예　　아니요')],
        'dg-text-006078': [('하지만 이미', '하지만　이미')],
        # Signboard, not spoken dialogue: 警告・無謀なるものには砲撃の準備あり.
        'dg-text-01013c': [(' · 무모한 자에게는 포격할 준비가 되어 있다.',
                            '·무모한 자에겐 포격 준비가 되어 있다.')],
        'dg-text-037138': [('이 앞은 혹한', '이 앞은　혹한')],
        'dg-text-067952': [('우승 횟수: ', '우승 횟수　　　 '), ('⟦1400⟧승 ', '⟦1400⟧승　')],
        'dg-text-08c97c': [('100년 전,', '100년 전　')],
    }
    for before, after in replacements.get(row['id'], []):
        if before in text:
            text = text.replace(before, after)
            notes.append('individual_source_layout_review')
    return text, notes


def migrate(directory, output, apply=False):
    if output.exists() or not output.resolve().is_relative_to((ROOT/'work').resolve()):
        raise ValueError('Choose a new output under work/')
    workspace = Workspace(directory)
    with (directory/'.write.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        original = workspace.load()
        changed = copy.deepcopy(original)
        output.mkdir(parents=True)
        write_json(output/'reviews-before.json', original)
        entries, counts = [], Counter()
        for key, previous in original['entries'].items():
            row = workspace.rows[key]
            text, reasons = transform(row, previous['text'])
            status = 'held' if previous['status']=='held' else 'draft'
            workspace.validate(row, text, status)
            if TOKEN.findall(text) != TOKEN.findall(previous['text']):
                raise ValueError('Spacing migration changed a protected token: '+key)
            unquoted = '「' not in row['source'] and '」' not in row['source']
            counts['unquoted_reviewed'] += unquoted
            counts['changed'] += text != previous['text']
            counts['unquoted_changed'] += unquoted and text != previous['text']
            for reason in reasons:
                counts[reason.split(':')[0]] += int(reason.split(':')[1]) if ':' in reason else 1
            entries.append(dict(id=key, source=row['source'], before=previous['text'], after=text,
                                unquoted=unquoted, reasons=reasons,
                                layout_review='source spacing/indent/columns; wording retained',
                                runtime_verified=False))
            if text == previous['text']:
                continue
            item = changed['entries'][key]
            item['history'] = previous.get('history', []) + [{k:v for k,v in previous.items() if k!='history'}]
            item.update(text=text, status=status, revision=previous['revision']+1,
                        author='assistant', updated_at=now(), wording_sha256=sha(text.encode()),
                        layout_verified=False, runtime_verified=False, product_eligible=False)
            item['rationale'] = previous.get('rationale','') + '\n공백 검토: 일반 공백 6px, 원문 들여쓰기·연출/표 공백 12px, 쉼표·느낌표 뒤 공백 삭제.'
        report = dict(format=1, instruction='user 2026-09-28 spacing items 1–4',
                      input_sha256=sha((directory/'reviews.json').read_bytes()),
                      applied=apply, counts=dict(counts), entries=entries)
        write_json(output/'review.json', report)
        write_json(output/'reviews-after.json', changed)
        if apply:
            atomic_json(directory/'reviews.json', changed)
        print(json.dumps(dict(counts), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', type=Path, default=WORK)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    migrate(a.directory, a.output, a.apply)
