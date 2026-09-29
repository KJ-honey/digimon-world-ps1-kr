"""Resident technique names and source-bound help-text sprite slices.

All offsets below are logical EXE offsets, not disc offsets. Keeping technique
names as resident C strings preserves the native and DG strcpy/strlen consumers.
The declared source technique-string pool is repacked without DG residency.
"""
import struct

from survey import sha

KINDS = ('technique_name', 'technique_help')
# These rows contain several independently cropped fragments. Until the editor
# exposes each fragment separately, keep their byte anchors stable. Ordinary
# full/half spaces are both two-byte units and may freely change pixel width.
PACKED_HELP = {2, 3, 4}
POOL_START, POOL_END = 0xA0BD4, 0xA135C
POOL_SHA = '9fb0c282fb364e83600321bbd7aadfe178e27f2d2bc0315b89d1c31c294f8093'


def repack_names(exe, rows, wanted, pixel_width):
    """Repack all 121 table targets atomically in their always-resident pool.

    All literal EXE references into the declared pool are the table entries;
    original native, DG and card consumers index this same table. Special
    shared strings outside this pool remain intact. No padding is reclaimed.
    """
    from translation_catalog import RAM_BASE
    rows=sorted((r for r in rows if r['category']=='technique_name'),key=lambda r:r['table_index'])
    if not rows:return [],[],0
    if len(rows)!=121 or [r['table_index'] for r in rows]!=list(range(121)):
        raise ValueError('Incomplete technique name table')
    if sha(exe[POOL_START:POOL_END])!=POOL_SHA:
        raise ValueError('Technique string pool revision differs')
    expected={r['locations']['kor']['reference_logical_offset'] for r in rows
              if POOL_START<=r['locations']['kor']['logical_offset']<POOL_END}
    actual={at for at in range(len(exe)-3)
            if RAM_BASE+POOL_START<=struct.unpack_from('<I',exe,at)[0]<RAM_BASE+POOL_END}
    if actual!=expected:
        raise ValueError('Unexpected reference into technique string pool')
    pool=bytearray(POOL_END-POOL_START)
    offsets={};cursor=0;writes=[];entries=[]
    for row in rows:
        raw=wanted[row['id']]
        if pixel_width(raw)>120:
            raise ValueError(row['id']+': technique name exceeds 120px UI/DG budget')
        if raw not in offsets:
            if cursor+len(raw)>len(pool):
                raise ValueError('Resident EXE technique pool capacity exceeded')
            offsets[raw]=cursor
            pool[cursor:cursor+len(raw)]=raw
            cursor=(cursor+len(raw)+1)&~1
        offset=POOL_START+offsets[raw]
        loc=row['locations']['kor'];ref=loc['reference_logical_offset']
        pointer=RAM_BASE+offset
        writes.append(dict(id=row['id']+'-pointer',file='SLPS_017.97',file_offset=ref,
                           before=exe[ref:ref+4].hex(),after=struct.pack('<I',pointer).hex()))
        entries.append(dict(id=row['id'],category='technique_name',
            old_bytes=len(bytes.fromhex(row['raw']['kor'])),new_bytes=len(raw),
            pixel_width=pixel_width(raw),expanded_hex=raw.hex(),
            source_logical_offset=loc['logical_offset'],source_reference_offset=ref,
            policy='resident-technique-pool',target_ram=pointer,
            wording_changed=raw!=bytes.fromhex(row['raw']['kor'])))
    writes.append(dict(id='resident-technique-string-pool',file='SLPS_017.97',file_offset=POOL_START,
                       before=exe[POOL_START:POOL_END].hex(),after=pool.hex()))
    return writes,entries,cursor
# table row, help index, first glyph, exclusive end (None = actual terminator)
SLICES = ((0,2,0,13),(1,2,14,None),(2,4,11,17),
          (3,3,0,7),(4,3,7,None),(5,4,7,17),
          (6,5,0,None),(7,6,0,10),(8,7,0,11),
          (9,8,0,None),(10,8,0,None),(11,9,0,None))


def encode_layout(row, raw):
    """Reserve the 12px cells overlaid by a separately drawn button icon.

    These are layout placeholders, not word separators. Record the resulting
    bytes in the build manifest so re-extraction checks the actual product.
    """
    if row['category']!='technique_help':
        return raw
    index={3:8,4:11}.get(row['table_index'])
    if index is None:
        return raw
    at=index*2
    if raw[at:at+2] not in (b'\x81\x40',b'\x0f\x01'):
        raise ValueError(row['id']+': button overlay cell must remain a space')
    return raw[:at]+b'\x81\x40'+raw[at+2:]


def validate(row, raw, old, pixel_width):
    if row['category'] == 'technique_name':
        if pixel_width(raw) > 120:
            raise ValueError(row['id']+': technique name exceeds 120px UI/DG budget')
    else:
        index = row['table_index']
        if index in PACKED_HELP and len(raw) != len(old):
            raise ValueError(row['id']+': packed help requires the original glyph count to preserve fragment anchors')
        if index == 2 and raw[26:28] not in (b'\x81\x40',b'\x0f\x01'):
            raise ValueError(row['id']+': glyph 13 is the icon gap and must remain a space')
        if index == 4 and raw[34:36] != old[34:36]:
            raise ValueError(row['id']+': confirmation-button glyph must be preserved')
        if index in (0,1) and pixel_width(raw) > (180 if index == 0 else 168):
            raise ValueError(row['id']+': technique-set instruction exceeds its sprite width')


def help_layout(exe, rows, wanted, pixel_width):
    """Recompute texture U and crop width; screen positions remain fixed.

    The original table's last slices in rows 2/3 omit a Korean final glyph.
    Their right boundary is the NUL, not the shorter Japanese crop width.
    """
    help_rows = {r['table_index']:r for r in rows if r['category']=='technique_help'}
    if not help_rows:
        return [], []
    if set(help_rows) != set(range(10)):
        raise ValueError('Incomplete technique-help population')
    if sha(exe[0xA019C:0xA01FC]) != 'd353f37b49b5c9f2c2c0dd5ea1a1d7724edc2b4e3b17395cf82997475d4bbd55':
        raise ValueError('Technique-help sprite table revision differs')
    if sha(exe[0x33F2C:0x34150]) != 'ea7885fa9641718d0ef4896f5c494f8c397e7e41d3570fbcb088e68d90ad4490':
        raise ValueError('Technique-help crop consumer revision differs')
    raws = {n:wanted[r['id']] for n,r in help_rows.items()}
    writes, evidence = [], []
    def crop(index, first, last):
        raw=raws[index]
        count=(len(raw)-1)//2
        # Legend suffix starts at the full-width opening parenthesis, not a
        # byte offset: prose before it may grow while this semantic anchor stays.
        if index in (6,7):
            units=[raw[i:i+2] for i in range(0,len(raw)-1,2)]
            if units.count(b'\x81\x69')!=1:
                raise ValueError('Technique-help legend requires one opening parenthesis')
            boundary=units.index(b'\x81\x69')
            if first: first=boundary
            else: last=boundary
        last=count if last is None else last
        if not 0 <= first < last <= count:
            raise ValueError('Technique-help fragment outside text')
        u=pixel_width(raw[:first*2]+b'\0')
        width=pixel_width(raw[first*2:last*2]+b'\0')
        if u+width>252:
            raise ValueError('Technique-help fragment outside texture')
        return u,width
    for table_index,index,first,last in SLICES:
        at=0xA019C+table_index*8
        x,y,old_width,old_u,v=struct.unpack_from('<hhhBB',exe,at)
        u,width=crop(index,first,last)
        # The inner help panel spans [-146,146]. Adjacent independent pieces
        # retain their source anchors; reject growth into a neighbour/icon.
        max_width={0:156,1:80,2:72,3:84,4:152,5:120,6:248,
                   7:168,8:168,9:248,10:248,11:248}[table_index]
        if width>max_width or x+width>146:
            raise ValueError(f'Technique-help sprite {table_index} exceeds its screen slot')
        new=struct.pack('<hhhBB',x,y,width,u,v)
        if new!=exe[at:at+8]:
            writes.append(dict(id=f'technique-help-sprite-{table_index}',file='SLPS_017.97',
                file_offset=at,before=exe[at:at+8].hex(),after=new.hex()))
        evidence.append(dict(table_index=table_index,help_index=index,first=first,last=last,
                             u=u,width=width,x=x,y=y,texture_y=v))
    # Immediate crop arguments in the same help display callback: title,
    # repeated confirmation icon, and the two legend suffixes.
    patches=((0x33F5C,4,0,7,'width'),
             (0x33F70,4,17,18,'u'),(0x33FB0,4,17,18,'u'),(0x33FF0,4,17,18,'u'),
             (0x340D8,6,10,None,'u'),(0x34104,6,10,None,'width'),
             (0x34118,7,11,None,'u'),(0x34144,7,11,None,'width'))
    # Check actual instruction opcodes, then decode/check the resulting writes.
    for at,index,first,last,field in patches:
        u,width=crop(index,first,last)
        old=struct.unpack_from('<I',exe,at)[0]
        expected_reg=7 if field=='width' else 2
        if old>>16 != (0x2400|expected_reg):
            raise ValueError('Technique-help crop instruction differs')
        value=u if field=='u' else width
        if index in (6,7) and field=='width' and value>80:
            raise ValueError('Technique-help legend suffix exceeds screen slot')
        new=struct.pack('<I',(old&0xffff0000)|value)
        if new!=exe[at:at+4]:
            writes.append(dict(id=f'technique-help-crop-{at:06x}',file='SLPS_017.97',
                file_offset=at,before=exe[at:at+4].hex(),after=new.hex()))
        evidence.append(dict(instruction_offset=at,help_index=index,first=first,last=last,
                             field=field,value=value))
    # This third confirmation icon overlays row 4's placeholder inside the
    # selection clause. Word spaces before it move its screen X position.
    at=0x34014
    value=-90+pixel_width(raws[4][14:22]+b'\0')
    old=exe[at:at+4]
    if old!=struct.pack('<I',0x2405ffd6):
        raise ValueError('Technique-help icon screen anchor differs')
    new=struct.pack('<I',0x24050000|(value&0xffff))
    if new!=old:
        writes.append(dict(id='technique-help-confirmation-x',file='SLPS_017.97',
                           file_offset=at,before=old.hex(),after=new.hex()))
    evidence.append(dict(instruction_offset=at,field='screen_x',value=value,help_index=4))
    return writes,evidence
