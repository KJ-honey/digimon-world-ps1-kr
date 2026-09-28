#!/usr/bin/env python3
"""Check all authored row widths against the original MIPS consumer/renderer.

Replace dynamic fields with full-cell maximum-length fixtures before executing
MIPS. This proves the adopted ceilings, not exhaustive in-game name lengths.
BIOS/GPU calls are stubbed; no emulator gameplay or image is claimed.
"""
import argparse
import json
from pathlib import Path
from dg_analyze import read_source
from dg_cpu_verify import Consumer
from dg_layout import DYNAMIC_BYTES, validate_layout
from dg_script import text_tokens
from dg_spacing import dialogue_codec
from dg_spacing_verify import RowRenderer
from survey import ROOT, sha, write_json
from translation_playtest import encode_draft
from translation_review import Workspace, WORK


def verify(output):
    workspace=Workspace(WORK)
    reviews=workspace.load()
    codec=dialogue_codec(json.loads((ROOT/'work/build/mona12-final/font/character-map.json').read_text()))
    exe=read_source('kor')['SLPS_017.97']
    consumer,renderer=Consumer(exe),RowRenderer(exe)
    results=[]
    for key,item in reviews['entries'].items():
        expected=validate_layout(item['text'])
        raw,_=encode_draft(item['text'],codec)
        raw+=b'\0\0'
        fixture=bytearray()
        for token in text_tokens(raw,0,len(raw))[1]:
            value=bytes.fromhex(token['raw'])
            if token['kind']=='control' and value[0] in DYNAMIC_BYTES:
                value=bytes.fromhex('8141')*(DYNAMIC_BYTES[value[0]]//2)
            fixture.extend(value)
        consumer.run(bytes(fixture))
        measured=[]
        for i,expected_width in enumerate(expected):
            row=bytes(consumer.cpu.mem_read(0x60000+64*i,64))
            events=renderer.run(row)
            edge=max([0]+[e['x']+12 if e['kind']=='glyph' else e['rect'][0]+e['rect'][2]
                          for e in events if e['kind'] in ('glyph','clear')])
            if edge!=expected_width or edge>168:
                raise ValueError(f'{key} row {i+1}: CPU {edge}, expected {expected_width}')
            measured.append(edge)
        results.append(dict(id=key,revision=item['revision'],pixels=measured))
    report=dict(total=len(results),rows=sum(len(x['pixels']) for x in results),
                max_pixels=max(max(x['pixels'],default=0) for x in results),
                reviews_sha256=sha((WORK/'reviews.json').read_bytes()),exe_sha256=sha(exe),
                dynamic_fields='maximum-length full-cell fixtures before CPU execution',
                gpu_stubbed=True,gameplay_verified=False,results=results)
    write_json(output,report)
    return {k:v for k,v in report.items() if k!='results'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    print(json.dumps(verify(p.parse_args().output),indent=2))
