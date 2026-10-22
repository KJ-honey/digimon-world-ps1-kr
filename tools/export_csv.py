#!/usr/bin/env python3
"""Read-only CSV export of the translation review workspace (for sharing).

python3 tools/export_csv.py [--directory work/translation] [--output work/export]
"""
import argparse
import csv
import json
from pathlib import Path

from survey import ROOT

COLUMNS = ['id', 'category', 'script', 'file', 'logical_offset', 'table_index',
           'source_jpn', 'existing_kor', 'review_kor', 'status', 'revision',
           'updated_at', 'note', 'context']


def rows_for(directory):
    baseline = json.loads((directory / 'baseline.json').read_text())['entries']
    reviews = json.loads((directory / 'reviews.json').read_text())['entries']
    for row in baseline:
        review = reviews.get(row['id'], {})
        offset = row.get('logical_offset')
        yield {
            'id': row['id'], 'category': row.get('category', 'dialogue'),
            'script': row.get('script'), 'file': row['file'],
            'logical_offset': f'0x{offset:X}' if offset is not None else '',
            'table_index': row.get('table_index', ''),
            'source_jpn': row['source'], 'existing_kor': row['existing'],
            'review_kor': review.get('text', ''), 'status': review.get('status', 'none'),
            'revision': review.get('revision', ''), 'updated_at': review.get('updated_at', ''),
            'note': review.get('note', ''), 'context': review.get('context') or row.get('context', ''),
        }


def write(path, rows):
    # utf-8-sig so Excel opens Korean/Japanese correctly.
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'work/translation')
    parser.add_argument('--output', type=Path, default=ROOT / 'work/export')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    dialogue = list(rows_for(args.directory))
    catalog = list(rows_for(args.directory / 'catalog'))
    write(args.output / 'dialogue.csv', dialogue)
    write(args.output / 'catalog.csv', catalog)
    write(args.output / 'all.csv', dialogue + catalog)
    print(f'dialogue {len(dialogue)}, catalog {len(catalog)} -> {args.output}')


if __name__ == '__main__':
    main()
