#!/usr/bin/env python3
"""Audit all current drafts or apply an explicit, source-checked edit plan.

No rewriting runs during build/export. Apply records full backups, revisions,
widths and the exact authorized protected streams. Plan prose remains in work/.
"""
import argparse
from collections import Counter
import copy
import fcntl
import json
from pathlib import Path

from dg_layout import LINE, MAX_LINE_PIXELS, line_widths, validate_layout
from dg_line_reflows import RULES, stream_hash
from glyph_review import atomic_json
from survey import ROOT, sha, write_json
from translation_review import Workspace, WORK, TOKEN, now


def audit(reviews):
    rows = []
    for key, item in reviews['entries'].items():
        widths = line_widths(item['text'])
        rows.append(dict(id=key, revision=item['revision'], pixels=widths,
                         overflow_lines=[i+1 for i, w in enumerate(widths) if w > MAX_LINE_PIXELS]))
    return dict(total=len(rows), lines=sum(len(r['pixels']) for r in rows),
                overflow_entries=sum(bool(r['overflow_lines']) for r in rows),
                overflow_lines=sum(len(r['overflow_lines']) for r in rows),
                max_pixels=max((max(r['pixels'], default=0) for r in rows), default=0),
                entries=rows)


def apply_plan(directory, plan_path, output):
    if output.exists() or not output.resolve().is_relative_to((ROOT/'work').resolve()):
        raise ValueError('Choose a new evidence directory under work/')
    workspace = Workspace(directory)
    plan = json.loads(plan_path.read_text())
    with (directory/'.write.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        original = workspace.load()
        after = copy.deepcopy(original)
        rules = json.loads(RULES.read_text()) if RULES.exists() else dict(
            format=1, instruction=f'2026-09-28 user: all translated rows <= {MAX_LINE_PIXELS}px', entries={})
        prior_rules = copy.deepcopy(rules)
        seen = set()
        changes = []
        for edit in plan:
            key = edit['id']
            if key in seen:
                raise ValueError('Duplicate edit: '+key)
            seen.add(key)
            row, previous = workspace.rows[key], original['entries'][key]
            if edit['before'] != previous['text'] or edit['source'] != row['source']:
                raise ValueError('Stale plan text/source: '+key)
            text = edit['after']
            widths = validate_layout(text)
            nonline = lambda s: [t for t in TOKEN.findall(s) if t != LINE]
            if nonline(text) != nonline(previous['text']):
                raise ValueError('Changed non-newline protected token: '+key)
            # An embedded choice header has references before its text header.
            is_choice = row['instruction'] != row['logical_offset']
            if is_choice and text.count(LINE) != previous['text'].count(LINE):
                raise ValueError('Changed number of choices: '+key)
            if not text.endswith(LINE) or text.count(LINE) > max(4, previous['text'].count(LINE)):
                raise ValueError('Unreviewed vertical growth: '+key)
            if text == previous['text']:
                continue
            protected = [('glyph' if t.startswith('⟦G:') else 'control',
                          t[1:-1].removeprefix('G:').lower())
                         for t in TOKEN.findall(text) if t != '⟦0F00⟧']
            protected.append(('terminator', '0000'))
            rules['entries'][key] = [sha(bytes.fromhex(row['raw']['kor'])), stream_hash(protected)]
            item = after['entries'][key]
            item['history'] = previous.get('history', []) + [
                {k:v for k,v in previous.items() if k != 'history'}]
            item.update(text=text, revision=previous['revision']+1,
                        status='held' if previous['status']=='held' else 'draft',
                        author='assistant', updated_at=now(), wording_sha256=sha(text.encode()),
                        product_eligible=False, layout_verified=False, runtime_verified=False)
            item['rationale'] = previous.get('rationale','') + f'\n{MAX_LINE_PIXELS}px 행 폭 수정: '+edit['reason']
            item['source_controls_restored_in_draft'] = (item.get('source_control_difference',False)
                and [t for t in TOKEN.findall(text) if not t.startswith('⟦G:')]
                    == [t for t in TOKEN.findall(row['source']) if not t.startswith('⟦G:')])
            item['source_tokens_restored_in_draft'] = (TOKEN.findall(row['source']) != TOKEN.findall(row['existing'])
                                                       and TOKEN.findall(text)==TOKEN.findall(row['source']))
            changes.append(dict(edit, pixels_before=line_widths(previous['text']), pixels_after=widths,
                                revision_before=previous['revision'], revision_after=item['revision']))
        report = audit(after)
        if report['overflow_entries']:
            raise ValueError('Plan leaves overflowing drafts')
        output.mkdir(parents=True)
        write_json(output/'reviews-before.json', original)
        write_json(output/'rules-before.json', prior_rules)
        write_json(output/'changes.json', changes)
        write_json(output/'audit-before.json', audit(original))
        write_json(output/'audit-after.json', report)
        write_json(output/'reviews-after.json', after)
        # Validate every draft before publishing the new reviews; rollback
        # registry changes on failure.
        atomic_json(RULES, rules)
        try:
            for key, item in after['entries'].items():
                workspace.validate(workspace.rows[key], item['text'], item['status'])
        except Exception:
            atomic_json(RULES, prior_rules)
            raise
        atomic_json(directory/'reviews.json', after)
        summary = dict(total=report['total'], changed=len(changes),
                       overflow_entries=report['overflow_entries'], overflow_lines=report['overflow_lines'],
                       max_pixels=report['max_pixels'], reasons=dict(Counter(x['reason'] for x in changes)),
                       reviews_sha256=sha((directory/'reviews.json').read_bytes()),
                       plan_sha256=sha(plan_path.read_bytes()), iso_rebuilt=False, gameplay_verified=False)
        write_json(output/'summary.json', summary)
        return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,default=WORK)
    p.add_argument('--plan',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a = p.parse_args()
    if a.plan:
        print(json.dumps(apply_plan(a.directory,a.plan,a.output),ensure_ascii=False,indent=2))
    else:
        result = audit(Workspace(a.directory).load())
        write_json(a.output,result)
        print(json.dumps({k:v for k,v in result.items() if k!='entries'},indent=2))
