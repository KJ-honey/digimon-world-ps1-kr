"""Mode 2 Form 1 EDC and Reed-Solomon P/Q regeneration.

Only header bytes 12..15 are excluded from XA parity. This module accepts
complete raw sectors and preserves sync, address, subheaders and payload.
"""
import struct


def parity(data, major_count, minor_count, major_mult, minor_inc):
    forward = [((v << 1) ^ (0x11D if v & 128 else 0)) for v in range(256)]
    backward = [0] * 256
    for v, f in enumerate(forward):
        backward[v ^ f] = v
    size = major_count * minor_count
    result = bytearray(major_count * 2)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            value = data[index]
            a ^= value
            b ^= value
            a = forward[a]
            index = (index + minor_inc) % size
        a = backward[forward[a] ^ b]
        result[major] = a
        result[major + major_count] = a ^ b
    return result


def regenerate(sector):
    if (len(sector) != 2352 or sector[:12] != b'\0' + b'\xff' * 10 + b'\0'
            or sector[15] != 2 or sector[18] & 0x20
            or sector[16:20] != sector[20:24]):
        raise ValueError('Expected Mode 2 Form 1 raw sector')
    result = bytearray(sector)
    crc = 0
    for value in result[16:2072]:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0xD8018001 if crc & 1 else 0)
    struct.pack_into('<I', result, 2072, crc)
    header = result[12:16]
    result[12:16] = bytes(4)
    result[2076:2248] = parity(result[12:2076], 86, 24, 2, 86)
    result[2248:2352] = parity(result[12:2248], 52, 43, 86, 88)
    result[12:16] = header
    return bytes(result)
