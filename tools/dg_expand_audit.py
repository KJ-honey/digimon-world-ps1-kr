#!/usr/bin/env python3
"""Audit bank prerequisites and emit explicit synthetic expansion fixtures.

This is analysis, not translation: the generated manifest adds a leading space
to each eligible verified text solely to exercise length growth.
"""
import argparse
import json
import struct
from pathlib import Path
from collections import Counter
from dg_analyze import read_source, verified_texts
from dg_script import decode
from dg_expand import validate_text, MARKER
from restore_text import LegacyCodec
from survey import ROOT, SOURCES, Disc, sha, write_json


def audit(output, map_path):
    if output.exists() or not output.resolve().is_relative_to((ROOT/'work').resolve()):
        raise ValueError('Choose a new output directory under work/')
    data=read_source('kor')['SCN/DG.SCN']
    mapping=json.loads(map_path.read_text())
    if mapping['source']['dg_sha256']['kor']!=sha(data):
        raise ValueError('Character map source mismatch')
    codec=LegacyCodec({e['code']:e['character'] for e in mapping['entries']})
    edits,excluded=[],[]
    for key,t in verified_texts(decode(data)).items():
        old=data[t['payload']:t['end']]
        new=b'\x81\x40'+old
        try:
            validate_text(old,new,codec)
        except ValueError as exc:
            excluded.append({'id':key,'reason':str(exc),'controls':[
                token['raw'] for token in t['tokens'] if token['kind']=='control']})
            continue
        edits.append({'id':key,'expected_hex':old[:-2].hex(),'text':codec.decode(new[:-2])})
    refs=[]
    disc=Disc(ROOT/SOURCES['kor'][0])
    try:
        if sha(disc.raw)!=SOURCES['kor'][1]:
            raise ValueError('Source disc mismatch')
        for name,f in disc.files().items():
            if name!='SLPS_017.97' and not (name.endswith('.BIN') and '_REL' in name):
                continue
            raw=disc.read(f['lba'],f['size'])
            matches=[]
            for at in range(0,len(raw)-3,4):
                word=struct.unpack_from('<I',raw,at)[0]
                if (word>>21)&31==28 and word&65535 in (0x930c,0x9304):
                    matches.append({'file_offset':at,'word':hex(word)})
            refs.append({'file':name,'sha256':sha(raw),'gp_directory_or_cd_cache_candidates':matches})
    finally:
        disc.close()
    output.mkdir(parents=True)
    manifest={'format':1,'purpose':'Synthetic leading-space expansion CPU fixtures; not translation',
              'source_disc_sha256':SOURCES['kor'][1],'source_dg_sha256':sha(data),
              'character_map_sha256':sha(map_path.read_bytes()),'edits':edits}
    report={'source_disc_sha256':SOURCES['kor'][1],'source_dg_sha256':sha(data),
            'source_marker_occurrences':data.count(MARKER),'accepted':len(edits),'excluded':len(excluded),
            'exclusion_reasons':dict(Counter(e['reason'] for e in excluded)),
            'reference_audit_scope':'aligned words with GP base and directory/cache immediates; not all computed aliases',
            'complete_reference_catalog':False,'gameplay_runtime_verified':False}
    write_json(output/'stress-edits.json',manifest)
    write_json(output/'exclusions.json',excluded)
    write_json(output/'reference-audit.json',refs)
    write_json(output/'summary.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--character-map',type=Path,default=ROOT/'work/text/character-map.json')
    a=p.parse_args()
    print(json.dumps(audit(a.output,a.character_map),indent=2))
