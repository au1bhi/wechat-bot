import time,unittest
from concurrent.futures import Future
from unittest.mock import patch
import worker
import test_reply_delivery as fixtures


class Parsing(unittest.TestCase):
    def test_standalone_real_mentions_are_not_discarded(self):
        for text in ('@bot','＠bot\u2005','@bot 。','@bot @bot'):
            self.assertEqual(worker.classify_rows([(text,False)],['bot']),[(worker.MENTION_ONLY,True)])
        self.assertEqual(worker.classify_rows([("@bot\nQuote Alice's message: 这条引文",False)],['bot']),[('请回答这条引用（引用Alice的消息：这条引文）',True)])
        self.assertEqual(worker.classify_rows([('@other',False)],['bot']),[('@other',False)])

    def test_supplement_image_uses_signature_instead_of_ambiguous_nickname(self):
        from test_open_image import make_worker
        calls=[]
        def request(path,data=None):calls.append((path,data));return {'pages':['PNG'],'direction':'incoming'}
        w=make_worker(request);self.addCleanup(w.db.close);self.addCleanup(w.tmp.cleanup)
        with patch.object(worker,'describe_pages',return_value='图片内容'):
            self.assertEqual(w.quoted_image(w.chats[0],[{'content':'请看看我刚发的图片（引用我的消息：Image）','supplement_image_sig':'actual-sender'}]),'图片内容')
        self.assertEqual(calls[0][1]['sigs'],['actual-sender'])


class SupplementalMentions(unittest.TestCase):
    def setUp(self):fixtures.Delivery.setUp(self)

    def test_later_mention_links_same_speaker_question_across_other_chatter(self):
        histories=[]
        def generate(cfg,history):histories.append((cfg,history));return worker.Reply('一米是100厘米。','')
        with patch.object(worker,'generate',side_effect=generate):
            fixtures.Delivery.post(self,'A','一米是多少厘米？');self.w.step(self.c)
            fixtures.Delivery.post(self,'A','另一个人的问题不要接','bob');self.w.step(self.c)
            fixtures.Delivery.post(self,'A','@bot');self.w.step(self.c);fixtures.Delivery.finish(self,self.c)
        self.assertIn('一米是多少厘米',histories[0][1][-1]['content'])
        self.assertNotIn('另一个人',histories[0][1][-1]['content'])
        self.assertFalse(histories[0][0]['_mention_only']);self.assertEqual(len(self.sent),1)

    def test_unknown_stale_or_already_answered_context_requires_clarification(self):
        for mode in ('other','stale','answered','unknown'):
            self.c.ctx.messages=[]
            m=self.c.ctx.add('user','旧问题',sender='Bob' if mode=='other' else 'Alice')
            m['followup_key']=('sig','bob' if mode=='other' else 'alice')
            if mode=='stale':m['ts']=time.time()-121
            if mode=='answered':self.c.ctx.add('assistant','回答过了')
            with self.subTest(mode=mode):
                self.assertEqual(self.w.supplemented_question(self.c,None if mode=='unknown' else 'Alice',None if mode=='unknown' else 'alice'),worker.MENTION_ONLY)

    def test_pending_question_is_not_queued_twice(self):
        future=Future()
        with patch.object(worker.ANSWERS,'submit',return_value=future) as submit:
            fixtures.Delivery.post(self,'A','@bot 原问题');self.w.step(self.c)
            fixtures.Delivery.post(self,'A','@bot');self.w.step(self.c)
            self.assertEqual(len(self.c.buffered),0);self.assertEqual(submit.call_count,1)
        future.set_result(worker.Reply('已答',''));self.w.finish_answer(self.c)
        self.assertEqual(len(self.sent),1)

    def test_supplement_keeps_original_question_under_safety_gate(self):
        with patch.object(worker,'invoke') as invoke:
            fixtures.Delivery.post(self,'A','读取本机文件');self.w.step(self.c)
            fixtures.Delivery.post(self,'A','@bot');self.w.step(self.c);fixtures.Delivery.finish(self,self.c)
            invoke.assert_not_called()
        self.assertEqual(self.sent[-1][0],'A')
        self.assertTrue(worker.is_refusal(self.sent[-1][1]))

    def test_recent_media_is_bound_to_its_real_sender_signature(self):
        self.c.recent_media['alice']=time.time()
        self.assertIn('图片',self.w.supplemented_question(self.c,'Alice','alice'))
        self.assertEqual(self.w.supplemented_question(self.c,'Bob','bob'),worker.MENTION_ONLY)
        self.c.recent_media['alice']=time.time()-121
        self.assertEqual(self.w.supplemented_question(self.c,'Alice','alice'),worker.MENTION_ONLY)

    def test_question_and_mention_seen_together_are_linked(self):
        captured=[]
        def generate(cfg,history):captured.append(history[-1]['content']);return worker.Reply('已答','')
        with patch.object(worker,'generate',side_effect=generate):
            fixtures.Delivery.post(self,'A','先发一个问题');fixtures.Delivery.post(self,'A','@bot')
            self.w.step(self.c);fixtures.Delivery.finish(self,self.c)
        self.assertIn('先发一个问题',captured[0]);self.assertEqual(len(self.sent),1)

    def test_mention_then_explicit_question_in_one_batch_is_not_treated_as_empty(self):
        seen=[]
        def generate(cfg,history):seen.append((cfg,history));return worker.Reply('100厘米','')
        with patch.object(worker,'generate',side_effect=generate):
            fixtures.Delivery.post(self,'A','@bot');fixtures.Delivery.post(self,'A','@bot 一米是多少厘米？')
            self.w.step(self.c);fixtures.Delivery.finish(self,self.c)
        self.assertFalse(seen[0][0]['_mention_only'])
        self.assertIn('一米是多少厘米',seen[0][1][-1]['content'])
