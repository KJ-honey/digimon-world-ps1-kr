"""Resident compression preserves controls and refuses silent CD fallbacks."""
import struct
import unittest
from dg_resident import prepare, unpack


class ResidentTests(unittest.TestCase):
    def fixture(self, lengths, payloads):
        data=bytearray(b'X'*64)
        entries=[]
        for i,(n,raw) in enumerate(zip(lengths,payloads)):
            pos=len(data)
            data += bytes([i+32])*n + b'\x1a\0'
            entries.append(dict(id=str(i),script=0,source_payload=pos,
                                source_end=pos+n,old_bytes=n,new_bytes=len(raw),
                                expanded_hex=raw.hex()))
        return bytes(data), {'scripts':[{'base':64}]}, entries

    def test_pool_links_and_literal_control_bytes_roundtrip(self):
        raw=bytes(range(256))*4+b'\x03\0\0\0\x0d\0\0\0'
        data,parsed,entries=self.fixture([80]*40,[raw[i:i+24] for i in range(0,960,24)])
        changed,tail,dictionary,report=prepare(data,parsed,entries)
        for e in entries:
            actual=unpack(changed,64,tail,[dictionary[i:i+2] for i in range(0,506,2)],e['resident_pointer'])
            self.assertEqual(actual,struct.pack('<H',e['old_bytes'])+bytes.fromhex(e['expanded_hex']))
            self.assertEqual(changed[e['source_end']:e['source_end']+2],b'\x1a\0')
        self.assertEqual(changed[:64],data[:64])
        self.assertEqual(report['per_dialogue_cd_reads'],0)

    def test_four_byte_source_uses_initial_directory_tail(self):
        data,parsed,entries=self.fixture([4],[b'\x81\x40'*100+b'\x0d\0\0\0'])
        _,tail,_,report=prepare(data,parsed,entries)
        self.assertTrue(entries[0]['resident_pointer'] & 0x8000)
        self.assertGreater(report['resident_end'],report['resident_start'])
        self.assertEqual(tail[:report['resident_start']],bytes(report['resident_start']))

    def test_pool_never_overlaps_output_or_falls_back_to_cd(self):
        data,parsed,entries=self.fixture([4]*20,[bytes([i,0])*900 for i in range(20)])
        with self.assertRaisesRegex(ValueError,'capacity exceeded'):
            prepare(data,parsed,entries)

    def test_self_link_rejected(self):
        with self.assertRaisesRegex(ValueError,'cycle'):
            unpack(b'\xfe\0\0',0,bytes(2048),[b'\0\0']*253,0)


if __name__=='__main__':
    unittest.main()
