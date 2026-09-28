"""Speaker attribution must follow branches and retain unresolved entry state."""
import unittest
from translation_speakers import inline_name, speakers_for


def node(pos, op, end=None, refs=(), raw=None, fallthrough=True):
    return dict(offset=pos, opcode=op, end=end or pos+2, references=list(refs),
                raw=raw or f'{op:02x}00', fallthrough=fallthrough, script=0)


def row(pos, source='「대사」⟦0D00⟧'):
    return dict(id=str(pos), instruction=pos, script=0, source=source, existing=source)


def parsed(nodes):
    return dict(nodes=nodes, scripts=[dict(sections=[dict(id=0, target=0)])])


class SpeakerTests(unittest.TestCase):
    def test_branch_merge_retains_both_speakers(self):
        refs = [dict(kind='script_relative_u16', target=p) for p in (2, 6)]
        jump = [dict(kind='script_relative_u16', target=10)]
        data = parsed([node(0, 0x19, refs=refs, fallthrough=False),
                       node(2, 0x1b, raw='1bfd'), node(4, 0x16, refs=jump, fallthrough=False),
                       node(6, 0x1b, raw='1b05'), node(8, 0x16, refs=jump, fallthrough=False),
                       node(10, 0x1a)])
        result = speakers_for([row(10)], data, {})['10']
        self.assertTrue(result['ambiguous'])
        self.assertEqual({c['id'] for c in result['candidates']}, {'player', 'actor:0:05'})

    def test_call_invalidates_but_choice_keeps_speaker(self):
        data = parsed([node(0, 0x1b, raw='1bfd'), node(2, 0x10), node(4, 0x13), node(6, 0x1a)])
        result = speakers_for([row(2), row(6)], data, {})
        self.assertEqual(result['2']['candidates'][0]['id'], 'player')
        self.assertTrue(result['2']['is_choice'])
        self.assertEqual(result['6']['candidates'][0]['id'], 'unknown')

    def test_native_entry_does_not_inherit_file_neighbor(self):
        data = parsed([node(0, 0x1b, raw='1bfd'), node(2, 0x1a)])
        data['native_text_references'] = [dict(target=2)]
        result = speakers_for([row(2)], data, {})['2']
        self.assertTrue(result['ambiguous'])
        self.assertIn('unknown', {c['id'] for c in result['candidates']})

    def test_inline_name_does_not_match_colored_item_or_body_mention(self):
        self.assertIsNone(inline_name('⟦0106⟧고기⟦0101⟧를 얻었다!⟦0D00⟧'))
        self.assertIsNone(inline_name('「⟦0107⟧할배몬⟦0101⟧」⟦0D00⟧'))
        source='⟦0107⟧ジジモン⟦0101⟧⟦0D00⟧「안녕」⟦0D00⟧'
        self.assertEqual(inline_name(source), 'ジジモン')
        result=speakers_for([row(0, source)], parsed([node(0, 0x1a)]), {})['0']
        self.assertIn('ジジモン', result['label'])


if __name__ == '__main__':
    unittest.main()

class NpcRecordTests(unittest.TestCase):
    def test_variable_patrol_lengths_and_actor_type_are_separate(self):
        import struct
        from translation_npcs import map_npcs
        desc = bytearray(16); desc[12] = 0x80
        data = bytearray(512)
        struct.pack_into('<I', data, 4, 16)
        start = 16 + 0x78
        struct.pack_into('<H', data, start, 2)
        first = [0]*42; first[0]=44; first[10]=11; first[33]=2
        struct.pack_into('<42H',data,start+2,*first)
        second=[0]*42;second[0]=117;second[10]=5
        struct.pack_into('<42H',data,start+2+96,*second)
        rows=map_npcs(data,desc)
        self.assertEqual([(r['type_id'],r['actor_id']) for r in rows],[(44,11),(117,5)])
        self.assertEqual(rows[1]['logical_offset'],start+98)
        with self.assertRaises(ValueError):map_npcs(data[:start+100],desc)

    def test_named_candidates_merge_across_maps_without_losing_alternatives(self):
        data=parsed([node(0,0x1b,raw='1b0b'),node(2,0x1a)])
        names={(0,11):[dict(id='name:タネモン',label='씨앗몬 / タネモン'),
                       dict(id='name:パルモン',label='팔몬 / パルモン')]}
        result=speakers_for([row(2)],data,{},names)['2']
        self.assertTrue(result['ambiguous'])
        self.assertEqual(len(result['candidates']),2)
        self.assertIn('씨앗몬',result['label'])
