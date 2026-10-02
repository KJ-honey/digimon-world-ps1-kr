#!/usr/bin/env python3
"""Build the current dialogue, catalog, font, and name-entry development ISO.

All manifests and the expanded font map are regenerated from the current
reviews and immutable source assets. The previous output survives a failure.
Includes memory-card spacing, technique-name C strings and help sprite crops.
"""
import argparse
import json
from pathlib import Path
import tempfile

from catalog_insert import export as export_catalog
from dg_analyze import read_source
from dg_expand import build as build_image
from font_expand import compile_font
from glyph_review import SOURCE
from match_gulim import DEFAULT_FONT
from restore_text import restore
from survey import ROOT
from translation_playtest import export as export_dialogue
from translation_review import WORK

DEFAULT_OUTPUT = ROOT / 'work/build/full-development'


def build(output):
    output = output.expanduser().absolute()
    build_root = (ROOT / 'work/build').resolve()
    if output.parent.resolve() != build_root:
        raise ValueError('Choose a direct child of work/build/')
    if output.is_symlink():
        raise ValueError('Output may not be a symlink')
    build_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='.full-build-', dir=build_root) as temporary:
        stage = Path(temporary)
        restored = stage / 'restored'
        restore(restored, ROOT / 'work/survey', SOURCE.parent, DEFAULT_FONT)
        legacy_map = json.loads((restored / 'character-map.json').read_text())
        compile_font(read_source('kor')['SLPS_017.97'], legacy_map,
                     stage / 'font-preview', name_entry=True)

        dialogue = stage / 'dialogue'
        catalog = stage / 'catalog-edits.json'
        errors = []
        try:
            export_dialogue(WORK, dialogue,
                            stage / 'font-preview/character-map.json')
        except ValueError as exc:
            selection = dialogue / 'selection.json'
            if selection.exists():
                report = json.loads(selection.read_text())
                errors.extend(f"대사 {item['id']}: {item['reason']}"
                              for item in report['deferred'])
            else:
                errors.append(f'대사 내보내기: {exc}')
        try:
            export_catalog(ROOT / 'work/translation/catalog', catalog, [])
        except ValueError as exc:
            errors.append(f'카탈로그 내보내기: {exc}')
        if errors:
            raise ValueError('현재 검수 문구로 통합 빌드를 할 수 없습니다.\n' + '\n'.join(errors))

        image = stage / 'image'
        result = build_image(dialogue / 'edits.json', image,
                             expand_font=True, name_entry=True,
                             catalog_edits=catalog, resident_dialogue=True, original_dg_extent=True)

        previous = stage / 'previous'
        if output.exists():
            if not output.is_dir():
                raise ValueError('Output exists and is not a directory')
            output.rename(previous)
        try:
            image.rename(output)
        except BaseException:
            if previous.exists():
                previous.rename(output)
            raise
        built = json.loads((output / 'build.json').read_text())
        return {'output': str(output / 'dg-expanded.cue'),
                'sha256': result['output_sha256'],
                'dialogue_changed': len(built['entries']),
                'catalog_selected': result['catalog']['selected'],
                'catalog_changed': result['catalog']['changed'],
                'technique_names_changed': sum(e['category']=='technique_name' and e.get('wording_changed',True)
                    for e in result['catalog']['entries']),
                'technique_help_changed': sum(e['category']=='technique_help'
                    for e in result['catalog']['entries']),
                'memory_card_strings_changed': sum(w['id'].startswith('memory-card-spacing-')
                    for w in built['writes'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT,
                        help='Output directory directly under work/build/ (default: full-development)')
    args = parser.parse_args()
    try:
        result = build(args.output)
    except ValueError as exc:
        parser.exit(1, f'{exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
