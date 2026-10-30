"""A question must not vanish because getting ready to answer failed once (e.g. out of threads)."""
import sys,tempfile,time,unittest,urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker


class PrepareRetry(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'state').mkdir()
        self.rows=[{'text':'old','outgoing':False}]
        self.sent=[]
        test=self
        class Bridge:
            def __init__(self,cfg):pass
            def request(self,path,data=None):
                if path.startswith('/snapshot'):return {'rows':list(test.rows)}
                if path=='/send':test.sent.append(data['text']);return {'status':'sent'}
                raise AssertionError(path)
        for p in (patch.object(worker,'ROOT',self.root),patch.object(worker,'Bridge',Bridge)):
            p.start();self.addCleanup(p.stop)
        self.executor=ThreadPoolExecutor(2);self.addCleanup(self.executor.shutdown)
        self.real_submit=self.executor.submit
        patch.object(worker,'ANSWERS',self.executor).start();self.addCleanup(patch.stopall)
        self.w=worker.Worker({'chat':'A','chats':['A'],'mention_names':['bot'],'aliases':[],'debounce_seconds':0,
                              'vision':False,'prepare_retry_delay':0,'catchup_seconds':0})
        self.addCleanup(self.w.db.close)
        self.c=self.w.chats[0];self.w.step(self.c)

    def ask(self,text):
        self.rows.append({'text':text,'outgoing':False,'sig':'s1'});self.w.step(self.c)

    def settle(self,steps=6):
        for _ in range(steps):
            time.sleep(.02)
            if self.c.answer_job:
                self.c.answer_job[0].result(timeout=3)
            self.w.step(self.c)

    def test_one_failure_is_retried_and_the_question_is_answered(self):
        fails={'n':1}
        def flaky(fn,*a,**k):
            if fails['n']:fails['n']-=1;raise RuntimeError("can't start new thread")
            return self.real_submit(fn,*a,**k)
        with patch.object(worker,'generate',return_value=worker.Reply('收到','')),\
             patch.object(self.executor,'submit',side_effect=flaky):
            self.ask('@bot 你好');self.settle()
        self.assertEqual(self.sent,['收到'])

    def test_it_gives_up_after_the_retries_and_does_not_loop_forever(self):
        calls={'n':0}
        def broken(fn,*a,**k):
            calls['n']+=1;raise RuntimeError("can't start new thread")
        with patch.object(self.executor,'submit',side_effect=broken):
            self.ask('@bot 你好');self.settle(steps=20)
        self.assertEqual(calls['n'],3)                 # first try + 2 retries
        self.assertEqual(self.c.buffered,[]);self.assertEqual(self.sent,[])

    def test_retried_messages_keep_their_order_and_stay_out_of_history_meanwhile(self):
        def broken(fn,*a,**k):raise RuntimeError('x')
        with patch.object(self.executor,'submit',side_effect=broken):
            self.ask('@bot 第一');self.w.step(self.c)
        self.assertEqual([e['content'] for e in self.c.buffered],['第一'])
        self.assertTrue(self.c.buffered[0]['pending'])
        self.assertNotIn('第一',[m['content'] for m in self.c.ctx.history()])


if __name__=='__main__':unittest.main()
