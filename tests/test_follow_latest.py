import ast,sys,unittest
from pathlib import Path
from PIL import Image,ImageDraw
SOURCE=Path(__file__).resolve().parents[1]/'transport.py'
FN=[n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='follow_latest']


class Node:
    def __init__(self,rect):self.rect=rect
    def get_role_name(self):return 'list'
    def get_name(self):return 'Messages'


def run(frames):
    """frames: screenshots returned in order; returns how many wheel scrolls were issued."""
    box=Node((660,300,570,380));calls=[];it=iter(frames);last=[frames[-1]]
    def shot():
        try:last[0]=next(it)
        except StopIteration:pass
        return last[0]
    scope={'walk':lambda a:[box],'app':lambda:None,'bounds':lambda n:n.rect,'screenshot':shot,
           'wheel':lambda *a:calls.append(a),'time':type('T',(),{'sleep':staticmethod(lambda s:None)})}
    exec(compile(ast.Module(body=FN,type_ignores=[]),str(SOURCE),'exec'),scope)
    scope['follow_latest']()
    return len(calls)


def frame(pill):
    im=Image.new('RGB',(1600,1000),(250,250,250))
    if pill:
        d=ImageDraw.Draw(im);d.rectangle((1035,645,1205,665),fill=(0,195,117))   # green "Go to the latest message" pill
    return im


class Follow(unittest.TestCase):
    def test_nothing_is_scrolled_when_the_chat_is_already_at_the_bottom(self):
        self.assertEqual(run([frame(False)]*5),0)

    def test_scrolls_until_the_pill_is_gone_for_three_looks(self):
        n=run([frame(True),frame(True),frame(False),frame(True),frame(False),frame(False),frame(False)])
        self.assertEqual(n,3)

if __name__=='__main__':unittest.main()
