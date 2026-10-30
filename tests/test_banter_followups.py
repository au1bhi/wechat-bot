import sys,unittest
from pathlib import Path
from concurrent.futures import Future
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker
import test_reply_delivery as fixtures


class BanterFollowups(unittest.TestCase):
    def setUp(self):
        fixtures.Delivery.setUp(self)
        self.w.cfg.update(banter=True,banter_settle=0,banter_gap=0,banter_cooldown=0)

    def start(self,text='锐评一下梅西 VS 姆巴佩'):
        fixtures.Delivery.post(self,'A',text)
        self.w.read_chat(self.c)
        future=Future()
        with patch.object(worker.BANTERS,'submit',return_value=future):self.w.banter_tick(self.c)
        return future

    def test_a_verified_unsolicited_answer_opens_same_speaker_followup(self):
        with patch.object(worker.time,'monotonic',return_value=10):future=self.start()
        future.set_result('一个荣誉大满贯，一个还得继续踢，别乱碰瓷。')
        with patch.object(worker.time,'monotonic',return_value=15):self.w.banter_tick(self.c)
        self.w.cfg['banter']=False
        with patch.object(worker.time,'monotonic',return_value=16),patch.object(worker,'generate',return_value=worker.Reply('不是，看具体表现。','')):
            fixtures.Delivery.post(self,'A','你看不起姆巴佩还是怎么')
            self.w.step(self.c)
            self.assertIsNotNone(self.c.answer_job)
            fixtures.Delivery.finish(self,self.c)
        self.assertEqual(len(self.sent),2)
        self.assertEqual(self.sent[-1],('A','不是，看具体表现。'))

    def test_speaker_is_captured_at_generation_start_not_after_other_messages(self):
        with patch.object(worker.time,'monotonic',return_value=10):future=self.start()
        fixtures.Delivery.post(self,'A','别人插话','bob');self.w.read_chat(self.c)
        future.set_result('只回刚才那个足球话题。')
        with patch.object(worker.time,'monotonic',return_value=15):self.w.banter_tick(self.c)
        self.assertIn(('sig','alice'),self.c.followups)
        self.assertNotIn(('sig','bob'),self.c.followups)
        with patch.object(worker.time,'monotonic',return_value=16):
            self.assertFalse(self.w.followup(self.c,'你觉得呢',False,'Bob','bob'))
            self.assertFalse(self.w.followup(self.w.chats[1],'你觉得呢',False,'Alice','alice'))

    def test_empty_or_failed_comment_does_not_open_followup(self):
        for text,fail in ((None,False),('准备发出的评论',True)):
            self.c.followups.clear()
            with patch.object(worker.time,'monotonic',return_value=10):future=self.start()
            future.set_result(text)
            if fail:
                with patch.object(self.w,'deliver',side_effect=RuntimeError('SEND_UNCERTAIN_PAUSED')):self.w.banter_tick(self.c)
            else:self.w.banter_tick(self.c)
            self.assertEqual(self.c.followups,{})

    def test_direct_answer_extends_timeout_from_confirmed_send(self):
        self.w.cfg['banter']=False
        future=Future()
        with patch.object(worker.ANSWERS,'submit',return_value=future),patch.object(worker.time,'monotonic',return_value=10):
            fixtures.Delivery.post(self,'A','@bot 解释一下');self.w.step(self.c)
        future.set_result(worker.Reply('解释完成。',''))
        with patch.object(worker.time,'monotonic',return_value=150):self.w.finish_answer(self.c)
        self.assertEqual(self.c.followups[('sig','alice')],270)
        with patch.object(worker.time,'monotonic',return_value=151):self.assertTrue(self.w.followup(self.c,'再说具体点',False,'Alice','alice'))

    def test_plain_evaluation_request_continues_only_a_known_conversation(self):
        with patch.object(worker.time,'monotonic',return_value=10):
            self.w.followup(self.c,'hello',True,'Bob','bob')
            self.assertTrue(self.w.followup(self.c,'评价一下阿根廷这个国家',False,'Bob','bob'))
            self.assertTrue(self.w.followup(self.c,'点评一下这个操作',False,'Bob','bob'))
            self.assertTrue(self.w.followup(self.c,'开塞露是啥',False,'Bob','bob'))
            self.assertTrue(self.w.followup(self.c,'这有啥区别',False,'Bob','bob'))
            self.assertFalse(self.w.followup(self.c,'开塞露是啥',False,'Alice','alice'))
            self.assertFalse(self.w.followup(self.c,'我今天得到一个好评价',False,'Bob','bob'))
            self.assertFalse(self.w.followup(self.c,'评价一下这个操作',False,'Alice','alice'))

    def test_verified_window_survives_restart_but_expires_and_clears_on_pause(self):
        self.w.remember_followup(self.c,('sig','alice'))
        other=worker.Chat('A',self.w.cfg,self.root/'state')
        self.assertIn(('sig','alice'),other.followups)
        with patch.object(worker.time,'time',return_value=worker.time.time()+121):
            expired=worker.Chat('A',self.w.cfg,self.root/'state')
        self.assertEqual(expired.followups,{})
        self.w.forget_seen()
        self.assertFalse(self.c.followup_path.exists())
        self.assertEqual(self.c.followups,{})
