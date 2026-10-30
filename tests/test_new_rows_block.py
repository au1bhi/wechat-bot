import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker
R=lambda text,out=False:(text,out)


class Block(unittest.TestCase):
    def test_new_message_after_our_own_image_is_found_when_the_top_scrolled_away(self):
        before=[R('旧消息'),R('公式呢'),R('回复文字',True),R('Image',True)]
        after=[R('一地址指令…'),R('公式呢'),R('回复文字',True),R('Image',True),R('新问题@bot')]
        self.assertEqual(worker.new_rows(before,after),[R('新问题@bot')])

    def test_ambiguous_blocks_never_invent_messages(self):
        before=[R('Image',True)]
        after=[R('a'),R('Image',True),R('b'),R('Image',True)]
        self.assertEqual(worker.new_rows(before,after),[])          # a lone image row is not an anchor

    def test_unrelated_window_gives_nothing(self):
        self.assertEqual(worker.new_rows([R('甲'),R('乙')],[R('丙'),R('丁')]),[])

    def test_existing_behaviour_unchanged(self):
        self.assertEqual(worker.new_rows([R('a'),R('b')],[R('a'),R('b'),R('c')]),[R('c')])
        self.assertEqual(worker.new_rows([R('a'),R('b')],[R('b'),R('c')]),[R('c')])

if __name__=='__main__':unittest.main()
