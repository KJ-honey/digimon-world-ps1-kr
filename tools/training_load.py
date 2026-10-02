"""Resolve training overlays from the original RAM file table before enqueue.

Only the DG opcode 64/27 call is redirected. Its original handler is copied
verbatim except for its two overlay-loader calls. Other uses of that handler
and the global async loader retain their original code and initialization.
"""
import struct
from font_expand import assemble
from survey import ROOT, sha

COMMAND_OFFSET = 0x200
LOADER_OFFSET = 0x2C0
END_OFFSET = 0x400
COMMAND_FILE_OFFSET = 0x543C4
COMMAND_SIZE = 0xBC
COMMAND_SHA = '3d49b8caf19d858344472b8d1c3097c8473e1e2cbbe71b425309d5eb13f8da50'
HOOK = 0x5E45C


def jal(address):
    return struct.pack('<I',0x0C000000 | ((address>>2)&0x3FFFFFF))


def install(exe, code, code_ram, files, output):
    command=bytearray(exe[COMMAND_FILE_OFFSET:COMMAND_FILE_OFFSET+COMMAND_SIZE])
    if sha(command)!=COMMAND_SHA or exe[HOOK:HOOK+4]!=jal(0x800E43C4):
        raise ValueError('Training command revision mismatch')
    if len(code)<END_OFFSET or any(code[COMMAND_OFFSET:END_OFFSET]):
        raise ValueError('Training helper overlaps resident code/data')
    # Cached LBAs and lengths must still describe the final immutable extents.
    resources=[]
    for offset,name in ((0x98428,'TRN_REL.BIN'),(0x98434,'TRN2_REL.BIN')):
        lba,size,pointer=struct.unpack_from('<III',exe,offset)
        actual=exe[pointer-0x80090000:].split(b'\0',1)[0].decode('ascii')
        if actual!=name or (lba,size)!=(files[name]['lba'],files[name]['size']):
            raise ValueError('Training file table differs from ISO extent')
        resources.append(dict(file=name,iso_lba=lba,size=size))
    for at in (0x48,0x9C):
        if command[at:at+4]!=jal(0x801044AC):
            raise ValueError('Training overlay call mismatch')
        command[at:at+4]=jal(code_ram+LOADER_OFFSET)
    helper=assemble((ROOT/'tools/training_load.s').read_text(),output,'training-load')
    if len(command)>LOADER_OFFSET-COMMAND_OFFSET or len(helper)>END_OFFSET-LOADER_OFFSET:
        raise ValueError('Training helper exceeds code slot')
    result=bytearray(code)
    result[COMMAND_OFFSET:COMMAND_OFFSET+len(command)]=command
    result[LOADER_OFFSET:LOADER_OFFSET+len(helper)]=helper
    from catalog_insert import verify_machine_code
    verify_machine_code(bytes(result[COMMAND_OFFSET:LOADER_OFFSET+len(helper)]),
                        code_ram+COMMAND_OFFSET,output/'training-addressed.asm')
    write=dict(id='training-async-cached-file-location',file='SLPS_017.97',
               file_offset=HOOK,before=exe[HOOK:HOOK+4].hex(),
               after=jal(code_ram+COMMAND_OFFSET).hex())
    report=dict(format='training-cached-location-v1',hook_ram=0x80090000+HOOK,
                command_ram=code_ram+COMMAND_OFFSET,loader_ram=code_ram+LOADER_OFFSET,
                resources=resources,original_async_queue_preserved=True,
                unknown_file_fallback=True,gameplay_runtime_verified=False)
    return bytes(result),write,report
