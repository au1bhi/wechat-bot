"""Regression tests: follow-ups, concurrent polling and independent question turns."""
import sys, tempfile, threading, unittest, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker


class Delivery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'state').mkdir()
        self.rows={n:[{'text':'old','outgoing':False}] for n in ('A','B')}
        self.sent=[]
        test=self
        class Bridge:
            def __init__(self,cfg):pass
            def request(self,path,data=None):
                if path.startswith('/snapshot'):
                    n=urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)['chat'][0]
                    return {'rows':list(test.rows[n])}
                if path=='/send':test.sent.append((data['chat'],data['text']));return {'status':'sent'}
                raise AssertionError(path)
        for p in (patch.object(worker,'ROOT',self.root),patch.object(worker,'Bridge',Bridge)):
            p.start();self.addCleanup(p.stop)
        self.pool=ThreadPoolExecutor(3);self.addCleanup(self.pool.shutdown)
        p=patch.object(worker,'ANSWERS',self.pool);p.start();self.addCleanup(p.stop)
        self.w=worker.Worker({'chat':'A','chats':['A','B'],'mention_names':['bot'],'aliases':['bot'],
                              'debounce_seconds':0,'vision':False})
        self.addCleanup(self.w.db.close)
        for c in self.w.chats:self.w.step(c)
        self.c=self.w.chats[0]
        self.w.senders.set('alice','Alice');self.w.senders.set('bob','Bob')

    def post(self,chat,text,sig='alice'):
        self.rows[chat].append({'text':text,'outgoing':False,'sig':sig})

    def finish(self,c):
        c.answer_job[0].result(timeout=2);self.w.step(c)

    def test_same_speaker_followup_not_other_people_or_other_groups(self):
        with patch.object(worker,'generate',return_value=worker.Reply('ok','')):
            self.post('A','@bot 你好');self.w.step(self.c);self.finish(self.c)
            self.post('A','你能再解释一下吗');self.w.step(self.c)
            self.assertIsNotNone(self.c.answer_job);self.finish(self.c)
            self.post('A','你觉得呢','bob');self.w.step(self.c)
            self.assertIsNone(self.c.answer_job)
            self.post('B','你觉得呢');self.w.step(self.w.chats[1])
            self.assertIsNone(self.w.chats[1].answer_job)
        self.assertEqual(len(self.sent),2)

    def test_expired_unknown_and_explicit_other_mentions_do_not_follow_up(self):
        c=self.c
        with patch.object(worker.time,'monotonic',return_value=10):
            self.assertTrue(self.w.followup(c,'hi',True,'Alice','alice'))
            self.assertFalse(self.w.followup(c,'@someone 你觉得呢',False,'Alice','alice'))
            self.assertFalse(self.w.followup(c,'你觉得呢',False,None,None))
        with patch.object(worker.time,'monotonic',return_value=131):
            self.assertFalse(self.w.followup(c,'你觉得呢',False,'Alice','alice'))

    def test_polling_and_other_group_continue_while_answer_is_blocked(self):
        entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
        def generate(cfg,history):
            if 'slow' in history[-1]['content']:
                entered.set();release.wait(3)
            return worker.Reply('ok','')
        with patch.object(worker,'generate',side_effect=generate):
            self.post('A','@bot slow');self.w.step(self.c);self.assertTrue(entered.wait(1))
            self.post('A','你还在吗');self.w.step(self.c)
            self.assertEqual(len(self.c.buffered),1)
            b=self.w.chats[1];self.post('B','@bot fast','bob');self.w.step(b);self.finish(b)
            self.assertEqual(self.sent,[('B','ok')])
            release.set();self.finish(self.c);self.finish(self.c)
        self.assertEqual(self.sent,[('B','ok'),('A','ok'),('A','ok')])

    def test_different_speakers_are_not_merged_and_echo_text_is_not_dropped(self):
        calls=[]
        def generate(cfg,history):calls.append(history[-1]['content']);return worker.Reply('same','')
        with patch.object(worker,'generate',side_effect=generate):
            self.post('A','@bot first');self.post('A','@bot second','bob');self.w.step(self.c)
            self.finish(self.c);self.finish(self.c)
            self.post('A','same');self.w.step(self.c)
        self.assertEqual(calls,['【Alice】first','【Bob】second'])
        self.assertTrue(any(m['role']=='user' and m['content']=='same' for m in self.c.ctx.messages))

    def test_continuous_messages_cannot_postpone_answer_forever(self):
        self.w.cfg['debounce_seconds']=0.4
        with patch.object(worker,'generate',return_value=worker.Reply('ok','')):
            with patch.object(worker.time,'monotonic',return_value=10):
                self.post('A','@bot first');self.w.step(self.c)
                self.assertIsNone(self.c.answer_job)
            with patch.object(worker.time,'monotonic',return_value=12.1):
                self.post('A','你再展开说说');self.w.step(self.c)
                self.assertIsNotNone(self.c.answer_job)
                self.finish(self.c)
        self.assertEqual(self.sent,[('A','ok')])

    def test_reflow_with_recalled_history_delivers_new_mention_once(self):
        anchor={'text':'这是此前已经发送过的一条足够长的机器人回复','outgoing':True}
        self.rows['A']+=[{'text':'旧消息','outgoing':False,'sig':'alice'},anchor]
        self.w.read_chat(self.c)
        self.rows['A']=[{'text':'更早的消息','outgoing':False,'sig':'bob'},
                        {'text':'某人撤回了一条消息','outgoing':False},anchor,
                        {'text':'@bot 这是新问题','outgoing':False,'sig':'alice'}]
        with patch.object(worker,'generate',return_value=worker.Reply('已收到新问题','')):
            self.w.step(self.c);self.finish(self.c);self.w.step(self.c)
        self.assertEqual(self.sent,[('A','已收到新问题')])

    def test_pause_discards_completed_answer(self):
        with patch.object(worker,'generate',return_value=worker.Reply('ok','')):
            self.post('A','@bot hi');self.w.step(self.c)
            self.c.answer_job[0].result(timeout=2)
            (self.root/'state'/'PAUSED').touch();self.w.finish_answer(self.c)
        self.assertEqual(self.sent,[])

    def test_nickname_recognition_does_not_block_polling(self):
        entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
        def read(*args):entered.set();release.wait(3);return 'New person'
        self.rows['A'].append({'text':'hello','outgoing':False,'sig':'new','strip':'png'})
        with patch.object(worker,'read_name',side_effect=read):
            self.w.step(self.c);self.assertTrue(entered.wait(1))
            self.assertFalse(self.w.name_jobs['new'].done())
            self.w.step(self.w.chats[1])
            release.set();self.w.name_jobs['new'].result(timeout=2);self.w.harvest_names()
        self.assertEqual(self.w.senders.get('new'),'New person')
