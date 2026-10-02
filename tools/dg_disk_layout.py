"""Keep DG's original ISO extent once dialogue records are resident.

Script 0 is served from MAPHEAD by 800F0988, never from DG. The initial DG read
uses only the first 8 KiB; normal scripts begin at the next directory boundary.
We reuse the on-disc DG script-0 copy for initial helpers and packed catalog
sectors. MAPHEAD retains the complete patched script-0 program and text pools.
"""
import struct
from survey import sha

BLOCK = 2048
CATALOG_OFFSET = 0x2000


def pack_catalog(records, descriptors, report, capacity):
    if capacity < 0 or capacity % BLOCK:
        raise ValueError('Invalid packed catalog capacity')
    result = bytearray()
    directory = bytearray(descriptors)
    entries = {e['record']: e for e in report['entries']
               if e['policy'] == 'independent-CD-record'} if report else {}
    if set(entries) != set(range(len(records))):
        raise ValueError('Catalog record ownership mismatch')
    for index, record in enumerate(records):
        entry = entries[index]
        payload = bytes.fromhex(entry['expanded_hex'])
        if len(payload)>BLOCK or record!=payload.ljust(BLOCK,b'\0'):
            raise ValueError('Catalog sector representation differs')
        offset = (len(result)+1)&~1
        if offset//BLOCK != (offset+len(payload)-1)//BLOCK:
            offset = (offset+BLOCK-1)&~(BLOCK-1)
        if offset+len(payload)>capacity or offset>65535:
            raise ValueError('Packed catalog exceeds original DG script-0 disc slot')
        result += bytes(offset-len(result)) + payload
        if directory[index*4:index*4+4]!=struct.pack('<HH',0x020f,index):
            raise ValueError('Catalog descriptor ownership mismatch')
        struct.pack_into('<H',directory,index*4+2,offset)
        entry['packed_offset'] = offset
    result += bytes((-len(result))%BLOCK)
    if report is not None:
        report['record_layout'] = 'sector-packed-byte-offset'
        report['packed_bytes'] = len(result)
        report['packed_capacity'] = capacity
    return bytes(result),bytes(directory)


def compose(original, changed, parsed, code, scratch, descriptors, packed):
    first = parsed['scripts'][1]['base']
    if (len(original)!=len(changed) or parsed['scripts'][0]['base']!=0x800
            or parsed['scripts'][0]['limit']!=first or first%BLOCK
            or len(code)>BLOCK or len(scratch)!=BLOCK or len(descriptors)!=BLOCK
            or len(packed)%BLOCK or CATALOG_OFFSET+len(packed)>first):
        raise ValueError('Original DG extent/layout contract differs')
    result=bytearray(changed)
    result[:0x800]=original[:0x800]  # Original boundary table; no offset shift.
    result[0x800:0x1000]=code.ljust(BLOCK,b'\0')
    result[0x1000:0x1800]=scratch
    result[0x1800:0x2000]=descriptors
    result[CATALOG_OFFSET:CATALOG_OFFSET+len(packed)]=packed
    if result[first:]!=changed[first:] or len(result)!=len(original):
        raise ValueError('Original normal-script extent changed')
    return bytes(result),dict(format='original-dg-extent-v1',
        first_normal_script_offset=first,script_file_offset_shift=0,
        catalog_file_offset=CATALOG_OFFSET,catalog_sector_count=len(packed)//BLOCK,
        reused_disc_range=[0x800,CATALOG_OFFSET+len(packed)],
        dg_script_zero_runtime_source='SCN/MAPHEAD.SCN',
        original_directory_sha256=sha(original[:0x800]),
        original_file_size=len(original),appended_sectors=0)
