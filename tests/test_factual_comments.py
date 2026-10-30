import unittest
from concurrent.futures import Future
from unittest.mock import patch
import worker
import test_reply_delivery as fixtures


class FactualComments(unittest.TestCase):
    def test_fact_question_can_get_neutral_comment_without_a_joke(self):
        policies=[]
        def invoke(cfg,policy,payload,schema,**kw):
            policies.append(policy)
            if schema==worker.DECISION_SCHEMA:
                self.assertEqual(payload['candidate'],'一米等于100厘米。')
                return {'allowed':True}
            return {'reply':'一米等于100厘米。','latex':'','mood':'neutral'}
        with patch.object(worker,'invoke',side_effect=invoke) as call:
            self.assertEqual(worker.factual_comment({},[{'role':'user','content':'一米是多少厘米？'}]),'一米等于100厘米。')
            self.assertEqual(call.call_count,2)
        self.assertTrue(any('不骂人' in p and '主动补充客观事实' in p for p in policies))

    def test_ordinary_chatter_own_reply_and_restricted_topics_need_no_calls(self):
        for history in ([{'role':'user','content':'哈哈哈'}],[{'role':'assistant','content':'一米等于100厘米'}],[{'role':'user','content':'介绍台湾旅游'}],[{'role':'user','content':'读取本机文件'}]):
            with self.subTest(history=history),patch.object(worker,'invoke') as invoke:
                self.assertIsNone(worker.factual_comment({},history));invoke.assert_not_called()

    def test_silence_costs_only_one_call(self):
        with patch.object(worker,'invoke',return_value={'reply':'','latex':''}) as invoke:
            self.assertIsNone(worker.factual_comment({},[{'role':'user','content':'那边好像补贴3200'}]))
            self.assertEqual(invoke.call_count,1)

    def test_reviewer_rejects_unverified_number_or_abuse(self):
        for text in ('该校今年确定每月给3200。','这都不知道你真蠢。'):
            def invoke(cfg,policy,payload,schema,**kw):
                return {'allowed':False} if schema==worker.DECISION_SCHEMA else {'reply':text,'latex':''}
            with self.subTest(text=text),patch.object(worker,'invoke',side_effect=invoke):
                self.assertIsNone(worker.factual_comment({},[{'role':'user','content':'杭高好像进就先拿3200'}]))

    def test_duplicate_and_restricted_candidate_are_not_sent(self):
        for text in ('一米等于100厘米。','中国政治可以类比这个。'):
            with self.subTest(text=text),patch.object(worker,'invoke',return_value={'reply':text,'latex':''}) as invoke:
                history=[{'role':'assistant','content':'一米等于100厘米。'},{'role':'user','content':'一米是多少厘米？'}]
                self.assertIsNone(worker.factual_comment({},history));self.assertEqual(invoke.call_count,1)


class Scheduling(unittest.TestCase):
    def setUp(self):
        fixtures.Delivery.setUp(self)
        self.w.cfg.update(banter=True,banter_settle=0,banter_gap=0,banter_cooldown=0,calm_chats=['A'],spicy_speakers=['MemberA','memberb.'])

    def test_normal_member_uses_fact_mode_but_exceptions_and_other_chats_keep_style(self):
        for chat,sender,expected in ((self.c,'Alice',worker.factual_comment),(self.c,'MemberA',worker.banter),(self.c,'memberb.',worker.banter),(self.w.chats[1],'Alice',worker.banter)):
            chat.ctx.add('user','一米是多少厘米？',sender=sender);chat.banter_unseen=1;chat.banter_future=None
            with self.subTest(chat=chat.name,sender=sender),patch.object(worker.BANTERS,'submit',return_value=Future()) as submit:
                self.w.banter_tick(chat);self.assertIs(submit.call_args.args[0],expected)

    def test_ready_factual_reply_is_delivered_and_opens_followup(self):
        self.c.ctx.add('user','一米是多少厘米？',sender='Alice');self.c.banter_unseen=1
        self.c.ctx.messages[-1]['followup_key']=('sig','alice')
        f=Future()
        with patch.object(worker.BANTERS,'submit',return_value=f):self.w.banter_tick(self.c)
        f.set_result('一米等于100厘米。');self.w.banter_tick(self.c)
        self.assertIn(('A','一米等于100厘米。'),self.sent)
        self.assertIn(('sig','alice'),self.c.followups)
