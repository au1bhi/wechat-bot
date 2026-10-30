import sys,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import guardrails as g
import worker

CFG={'calm_chats':['示例学习群'],'spicy_speakers':['MemberA','memberb.'],'private_markers':[],'mention_names':['Legacy Bot']}
W=types.SimpleNamespace(cfg=CFG)
CALM=types.SimpleNamespace(name='示例学习群');OTHER=types.SimpleNamespace(name='示例群乙')


class Who(unittest.TestCase):
    def test_only_listed_speakers_stay_sharp_in_calm_chat(self):
        f=lambda chat,s:worker.Worker.calm_for(W,chat,s)
        self.assertTrue(f(CALM,'小明'));self.assertTrue(f(CALM,None))
        self.assertFalse(f(CALM,'MemberA'));self.assertFalse(f(CALM,'memberb.'));self.assertFalse(f(CALM,'MEMBERB'))
        self.assertFalse(f(OTHER,'小明'))


class Policy(unittest.TestCase):
    def run_generate(self,calm):
        seen=[]
        def fake(cfg,pol,payload,schema,**kw):
            if pol.startswith('你是一个默认拒绝的聊天请求'):return {'allowed':True}
            seen.append(pol);return {'reply':'好的','latex':'','mood':'neutral'}
        with patch.object(worker,'invoke',side_effect=fake):
            worker.generate(dict(CFG,_calm=calm),[{'role':'user','content':'【小明】解释一下二分查找'}])
        return seen[0]
    def test_calm_prompt_has_no_abusive_style_but_keeps_boundaries(self):
        p=self.run_generate(True)
        self.assertIn('不骂人',p);self.assertNotIn('嘴臭老哥”',p.split('不扮演')[0]);self.assertIn(g.REFUSAL,p)
    def test_default_prompt_is_unchanged(self):
        self.assertIn('嘴臭',self.run_generate(False))
    def test_calm_clock_reply_is_plain(self):
        import datetime
        self.assertEqual(worker.quick_reply('现在几点',datetime.datetime(2026,10,28,9,5),calm=True),'北京时间9点05。')


if __name__=='__main__':unittest.main()
