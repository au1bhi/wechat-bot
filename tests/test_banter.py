import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import guardrails as g
import worker

CFG={'private_markers':['host-canary-unique'],'mention_names':['Legacy Bot']}
H=[{'role':'user','content':'我室友把泡面倒进了洗衣机'},{'role':'user','content':'还说是为了省水'}]


def routed(gate,reply):
    def fake(cfg,pol,payload,schema,**kw):
        if pol.startswith('你是一个默认拒绝的聊天请求'):return {'allowed':gate}
        return {'reply':reply,'latex':''}
    return fake


class Banter(unittest.TestCase):
    def test_comment_is_returned_when_funny(self):
        with patch.object(worker,'invoke',side_effect=routed(True,'笑死，这是要洗出豚骨味？')):
            self.assertEqual(worker.banter(CFG,H),'笑死，这是要洗出豚骨味？')

    def test_silence_when_model_has_nothing_to_add(self):
        with patch.object(worker,'invoke',side_effect=routed(True,'')):
            self.assertIsNone(worker.banter(CFG,H))

    def test_classifier_denial_means_silence(self):
        with patch.object(worker,'invoke',side_effect=routed(False,'笑死')):
            self.assertIsNone(worker.banter(CFG,H))

    def test_leaky_or_self_mentioning_comment_is_dropped(self):
        for text in ('看这个 /home/a/b','@Legacy Bot 笑死','x'*200):
            with patch.object(worker,'invoke',side_effect=routed(True,text)):
                self.assertIsNone(worker.banter(CFG,H),text)

    def test_never_comments_on_its_own_last_line(self):
        hist=H+[{'role':'assistant','content':'笑死'}]
        with patch.object(worker,'invoke',side_effect=routed(True,'再来一句')):
            self.assertIsNone(worker.banter(CFG,hist))


class CurrentEvents(unittest.TestCase):
    def test_news_questions_use_search_and_others_do_not(self):
        self.assertTrue(g.needs_fresh('今天有什么新闻'))
        self.assertTrue(g.needs_fresh('昨晚比分多少'))
        self.assertFalse(g.needs_fresh('求导 x^2'))
        calls=[]
        def fake(cfg,pol,payload,schema,**kw):
            calls.append(kw)
            if pol.startswith('你是一个默认拒绝的聊天请求'):return {'allowed':True}
            return {'reply':'五中全会开幕了','latex':''}
        cfg=dict(CFG,model='m',search_model='s')
        with patch.object(worker,'invoke',side_effect=fake):
            worker.generate(cfg,[{'role':'user','content':'今天有什么新闻'}])
            worker.generate(cfg,[{'role':'user','content':'你好'}])
        self.assertEqual(sum(bool(k.get('search')) for k in calls),1)

    def test_links_and_markdown_are_stripped(self):
        out=g.clean_reply('**开幕**([a.news](https://a.news/x?utm=1)) 看[这篇](https://x.y/z) https://q.r')
        self.assertEqual(out,'开幕 看这篇')

    def test_prompt_keeps_the_date(self):
        self.assertIn('{TODAY}',g.ANSWER_POLICY)


class SchemaLeak(unittest.TestCase):
    def test_field_name_as_reply_is_retried_not_sent(self):
        answers=iter([{'reply':'latex','latex':''},{'reply':'Reply:','latex':''},{'reply':'行吧','latex':''}])
        def fake(cfg,pol,payload,schema,**kw):
            if pol.startswith('你是一个默认拒绝的聊天请求'):return {'allowed':True}
            return next(answers)
        with patch.object(worker,'invoke',side_effect=fake):
            out=worker.generate({'private_markers':[]},[{'role':'user','content':'帮我骂骂他'}])
        self.assertEqual(out.text,'行吧')


class SpecificPerson(unittest.TestCase):
    def test_rule_is_in_every_generating_prompt(self):
        for policy in (g.ANSWER_POLICY,g.BANTER_POLICY):
            self.assertIn('消息正文叫 alias_a/alias_a/角色甲、alias_b/alias_b/角色乙时，默认是在叫你',policy)
            self.assertIn('【memberb.】对应群友角色乙，【MemberA】对应群友角色甲',policy)
            self.assertIn('对方本人主动邀损或明显开玩笑时才接其当前的梗',policy)
            self.assertIn('不编造这些真人的经历',policy)

    def test_no_account_has_a_special_persona_or_privileges(self):
        for policy in (g.ANSWER_POLICY,g.BANTER_POLICY):
            self.assertNotIn('ExampleIl1_',policy)
        self.assertEqual(g.VERIFIED_OWNER_POLICY,'')


if __name__=='__main__':unittest.main()
