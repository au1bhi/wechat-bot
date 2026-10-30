import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from latex_render import preserve_breaks


class Breaks(unittest.TestCase):
    def test_one_item_per_line_becomes_separate_lines(self):
        out=preserve_breaks('一、方阵\n1. 行列式：$\\det A\\neq0$。\n2. 可逆。\n\n二、非方阵\n1. 列满秩')
        self.assertEqual(out,'一、方阵\\\\\n1. 行列式：$\\det A\\neq0$。\\\\\n2. 可逆。\n\n二、非方阵\\\\\n1. 列满秩')

    def test_blank_lines_last_line_and_existing_breaks_are_untouched(self):
        self.assertEqual(preserve_breaks('a\n\nb'),'a\n\nb')
        self.assertEqual(preserve_breaks('a\\\\\nb'),'a\\\\\nb')
        self.assertEqual(preserve_breaks('only'),'only')

    def test_environments_and_display_math_are_not_touched(self):
        body='设\n\\begin{align}\na&=1\\\\\nb&=2\n\\end{align}\n所以\n\\[\nx=1\n\\]\n完'
        out=preserve_breaks(body)
        self.assertIn('a&=1\\\\\nb&=2\n\\end{align}',out)
        self.assertIn('\\[\nx=1\n\\]',out)
        self.assertNotIn('b&=2\\\\',out)
        self.assertTrue(out.startswith('设\n\\begin'))      # no stray break before a display environment

    def test_list_environment_keeps_its_own_spacing(self):
        body='要点\n\\begin{enumerate}\n\\item 一\n\\item 二\n\\end{enumerate}'
        self.assertEqual(preserve_breaks(body),body)

if __name__=='__main__':unittest.main()
