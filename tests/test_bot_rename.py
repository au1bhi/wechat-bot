import datetime,json,unittest
from pathlib import Path
from unittest.mock import patch
import worker,guardrails as g
from test_open_image import make_worker

NAME='DemoBot'
CFG=json.loads((Path(worker.__file__).parent/'config.example.json').read_text())


class Rename(unittest.TestCase):
    def test_new_and_legacy_native_mentions_are_recognized(self):
        self.assertEqual(CFG['mention_names'][0],NAME)
        for name in (NAME,'Legacy Bot','OldBot'):
            with self.subTest(name=name):
                self.assertEqual(worker.classify_rows([('@'+name+'\u2005请解释光合作用',False)],CFG['mention_names'],CFG['aliases']),[('请解释光合作用',True)])
                self.assertEqual(worker.classify_rows([('@'+name,False)],CFG['mention_names'],CFG['aliases']),[(worker.MENTION_ONLY,True)])

    def test_new_name_quote_and_clock_fast_path(self):
        got=worker.classify_rows([("解释这句\nQuote DemoBot's message: 一米是100厘米",False)],CFG['mention_names'],CFG['aliases'])
        self.assertTrue(got[0][1])
        self.assertEqual(worker.quick_reply('@'+NAME+'\u2005现在几点',datetime.datetime(2026,10,28,9,5),calm=True),'北京时间9点05。')

    def test_name_is_not_a_new_model_claim_and_styles_are_retained(self):
        for pol in (g.INPUT_POLICY,g.ANSWER_POLICY,g.CALM_POLICY,g.BANTER_POLICY,g.FACT_COMMENT_POLICY,g.SUMMARY_POLICY):
            self.assertIn('你当前叫 '+NAME,pol)
            self.assertIn('不代表实际模型或实际版本',pol)
        self.assertIn('嘴臭',g.ANSWER_POLICY)
        self.assertIn('不骂人',g.CALM_POLICY)
        self.assertIn('【memberb.】对应群友角色乙，【MemberA】对应群友角色甲',g.ANSWER_POLICY)

    def test_own_image_quote_keeps_own_direction_lookup(self):
        calls=[]
        def request(path,data=None):calls.append((path,data));return {'pages':['PNG'],'direction':'outgoing'}
        w=make_worker(request);self.addCleanup(w.db.close);self.addCleanup(w.tmp.cleanup)
        w.chats[0].mention_names=CFG['mention_names'];w.chats[0].aliases=CFG['aliases']
        with patch.object(worker,'describe_pages',return_value='机器人的公式图'):
            self.assertIn('机器人此前发送',w.quoted_image(w.chats[0],[{'content':'这题呢（引用DemoBot的消息：Image）'}]))
        self.assertEqual(calls[0][1]['sigs'],[''])

    def test_old_history_does_not_remove_current_identity_from_answer_prompt(self):
        seen=[]
        def invoke(cfg,policy,payload,schema,**kw):
            seen.append(policy)
            return {'allowed':True} if schema==worker.DECISION_SCHEMA else {'reply':'我叫 '+NAME,'latex':''}
        with patch.object(worker,'invoke',side_effect=invoke):
            result=worker.generate({},[{'role':'assistant','content':'我LegacyBot'},{'role':'user','content':'你现在叫什么？'}])
        self.assertIn(NAME,result.text)
        self.assertTrue(any('历史聊天中的旧自称不改变当前名字' in pol for pol in seen))
