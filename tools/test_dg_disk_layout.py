"""Original-extent catalog packing preserves sectors and script addresses."""
import struct
import unittest
from dg_disk_layout import pack_catalog, compose


class DiskLayoutTests(unittest.TestCase):
    def catalog(self, payloads):
        descriptors=bytearray(2048)
        entries=[]
        for i,payload in enumerate(payloads):
            struct.pack_into('<HH',descriptors,i*4,0x020f,i)
            entries.append(dict(record=i,policy='independent-CD-record',expanded_hex=payload.hex()))
        return [p.ljust(2048,b'\0') for p in payloads],bytes(descriptors),dict(entries=entries)

    def test_multiple_strings_share_sector_without_crossing_boundary(self):
        payloads=[b'A'*1998+b'\0',b'B'*98+b'\0',b'C'*18+b'\0']
        records,directory,report=self.catalog(payloads)
        packed,updated=pack_catalog(records,directory,report,4096)
        self.assertEqual(len(packed),4096)
        for i,(e,payload) in enumerate(zip(report['entries'],payloads)):
            at=e['packed_offset']
            self.assertEqual(at//2048,(at+len(payload)-1)//2048)
            self.assertEqual(packed[at:at+len(payload)],payload)
            self.assertEqual(struct.unpack_from('<HH',updated,i*4),(0x020f,at))
        self.assertEqual(report['entries'][1]['packed_offset'],2048)
        self.assertEqual(updated[12:],directory[12:])

    def test_capacity_and_descriptor_ownership_fail_closed(self):
        records,directory,report=self.catalog([b'A'*2046+b'\0',b'B\0'])
        with self.assertRaisesRegex(ValueError,'exceeds'):
            pack_catalog(records,directory,report,2048)
        directory=bytes(2048)
        with self.assertRaisesRegex(ValueError,'ownership'):
            pack_catalog(records,directory,report,4096)

    def test_no_record_is_not_an_extra_sector(self):
        self.assertEqual(pack_catalog([],bytes(2048),None,4096),(b'',bytes(2048)))

    def test_script_one_and_later_keep_original_offsets(self):
        original=b'X'*0x8000
        changed=original[:0x6800]+b'Y'*0x1800
        parsed={'scripts':[dict(base=0x800,limit=0x6800),dict(base=0x6800)]}
        built,report=compose(original,changed,parsed,b'CODE',bytes(2048),bytes(2048),b'P'*4096)
        self.assertEqual(len(built),len(original))
        self.assertEqual(built[:0x800],original[:0x800])
        self.assertEqual(built[0x6800:],changed[0x6800:])
        self.assertEqual(report['appended_sectors'],0)
        self.assertEqual(built[0x2000:0x3000],b'P'*4096)
        with self.assertRaisesRegex(ValueError,'contract'):
            compose(original,changed,parsed,b'CODE',bytes(2048),bytes(2048),bytes(0x5000))


if __name__=='__main__':
    unittest.main()
