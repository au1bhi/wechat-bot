"""After a restart the bot answers what was addressed to it while it was down, and nothing stale."""
import json,sys,tempfile,time,unittest,urllib.parse
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker


class CatchUp(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'state').mkdir()
        self.rows=[{'text':'old','outgoing':False,'sig':'s0'}]
        self.calls=[]
        test=self
        class Bridge:
            def __init__(self,cfg):pass
            def request(self,path,data=None):
                test.calls.append(path)
                if path.startswith('/snapshot'):return {'rows':[dict(r) for r in test.rows]}
                raise AssertionError('unexpected bridge call '+path)
        for p in (patch.object(worker,'ROOT',self.root),patch.object(worker,'Bridge',Bridge)):
            p.start();self.addCleanup(p.stop)
        self.cfg={'chat':'A','chats':['A'],'mention_names':['bot'],'aliases':[],'debounce_seconds':999,'vision':False}   # keep queued messages visible

    def boot(self,**extra):
        w=worker.Worker(dict(self.cfg,**extra));self.addCleanup(w.db.close)
        return w,w.chats[0]

    def first_run(self):
        w,c=self.boot();w.step(c)                     # baseline: writes the read position
        return c

    def restart(self,**extra):
        w,c=self.boot(**extra);w.step(c);return w,c

    def say(self,text,outgoing=False):
        self.rows.append({'text':text,'outgoing':outgoing,'sig':None if outgoing else 's1'})

    def test_a_message_that_arrived_while_down_is_answered(self):
        self.first_run()
        self.say('@bot 你好');self.say('随便聊聊')
        w,c=self.restart()
        self.assertEqual([e['content'] for e in c.buffered],['你好'])
        self.assertEqual(c.banter_unseen,0)            # old chatter does not trigger unprompted comments

    def test_a_message_the_bot_already_answered_is_not_answered_again(self):
        self.first_run()
        self.say('@bot 你好');self.say('收到',outgoing=True)
        w,c=self.restart()
        self.assertEqual(c.buffered,[])

    def test_only_the_newest_few_are_answered(self):
        self.first_run()
        for i in range(7):self.say('@bot 问题%d'%i)
        w,c=self.restart(catchup_max=3)
        self.assertEqual([e['content'] for e in c.buffered],['问题4','问题5','问题6'])

    def test_stale_jokes_are_skipped(self):
        self.first_run()
        self.say('他是民办本科')
        w,c=self.restart()
        self.assertEqual(c.buffered,[])
        self.assertNotIn('/send',self.calls)           # no late 民办本科 reply either

    def test_too_long_a_downtime_means_no_catch_up(self):
        c0=self.first_run()
        seen=c0.seen_path;data=json.loads(seen.read_text());data['ts']=time.time()-3600;seen.write_text(json.dumps(data))
        self.say('@bot 你好')
        w,c=self.restart()
        self.assertEqual(c.buffered,[])

    def test_unrelated_screen_means_no_catch_up(self):
        self.first_run()
        self.rows=[{'text':'completely different','outgoing':False,'sig':'s2'},{'text':'@bot 嗨','outgoing':False,'sig':'s2'}]
        w,c=self.restart()
        self.assertEqual(c.buffered,[])                 # no overlap, so nothing is *proven* new

    def test_nothing_new_nothing_to_do(self):
        self.first_run()
        w,c=self.restart()
        self.assertEqual(c.buffered,[])

    def test_catch_up_can_be_turned_off(self):
        self.first_run();self.say('@bot 你好')
        w,c=self.restart(catchup_seconds=0)
        self.assertEqual(c.buffered,[])

    def test_pausing_forgets_the_read_position(self):
        c=self.first_run()
        w,c2=self.boot();self.assertTrue(c2.seen_path.exists())
        w.forget_seen();self.assertFalse(c2.seen_path.exists())
        self.say('@bot 你好')
        w3,c3=self.restart()                            # after a pause there is nothing to catch up on
        self.assertEqual(c3.buffered,[])

    def test_the_saved_file_is_private_and_small(self):
        c=self.first_run()
        import os
        self.assertEqual(os.stat(c.seen_path).st_mode&0o777,0o600)
        self.assertLessEqual(len(json.loads(c.seen_path.read_text())['keys']),60)

    def test_normal_operation_still_ignores_old_history_on_first_ever_start(self):
        w,c=self.boot()                                  # no saved position at all
        self.say('@bot 以前的消息')
        w.step(c)                                        # first step is only a baseline
        self.assertEqual(c.buffered,[])


if __name__=='__main__':unittest.main()
