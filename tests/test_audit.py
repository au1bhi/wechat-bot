import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audit import Auditor
R=lambda text,out=False,sig=None:{'text':text,'outgoing':out,'sig':sig}
ask=lambda r:'@bot' in r['text']


class Audit(unittest.TestCase):
    def test_unanswered_mention_that_never_reached_the_classifier_is_reported_after_the_grace_time(self):
        a=Auditor(grace=20);rows=[R('旧'),R('@bot 问题')]
        a.mark([rows[0]])
        self.assertEqual(a.find_missed(rows,100,ask),[])             # first sighting starts the clock
        self.assertEqual(a.find_missed(rows,105,ask),[])
        self.assertEqual(a.find_missed(rows,125,ask),[rows[1]])

    def test_handled_answered_and_undirected_rows_are_never_reported(self):
        a=Auditor(grace=0)
        rows=[R('@bot 已处理'),R('@bot 已回复'),R('回答',True),R('闲聊')]
        a.mark([rows[0]])
        self.assertEqual(a.find_missed(rows,1,ask),[])
        self.assertEqual(a.find_missed(rows,9,ask),[])

    def test_identical_repeated_question_is_counted_per_occurrence(self):
        a=Auditor(grace=0);rows=[R('@bot 在吗'),R('@bot 在吗')]
        a.mark([rows[0]])                                            # only the first was decided about
        a.find_missed(rows,1,ask)
        self.assertEqual(len(a.find_missed(rows,2,ask)),1)

    def test_recovery_is_marked_handled_and_rate_limited(self):
        a=Auditor(grace=0,hourly_limit=1);rows=[R('@bot 一'),R('@bot 二')]
        a.find_missed(rows,1,ask)
        got=a.find_missed(rows,2,ask);self.assertEqual(len(got),1)
        a.recovered(got,2)
        self.assertEqual(a.find_missed(rows,3,ask),[])               # hourly limit reached
        self.assertEqual(a.recovered_total,1)

class Recovery(unittest.TestCase):
    def test_worker_queues_a_swallowed_mention(self):
        import types,worker
        added=[]
        ctx=types.SimpleNamespace(messages=[],add=lambda role,body,pending=False,sender=None:added.append((role,body,pending,sender)) or {})
        chat=types.SimpleNamespace(name='A',echo=[],ctx=ctx,buffered=[],mention_names=['bot'],aliases=[],auditor=Auditor(grace=0,hourly_limit=5),last_change=0)
        w=types.SimpleNamespace(cfg={},resolve_senders=lambda c,rows:['小明'])
        rows=[R('闲聊'),R('@bot 这题怎么做'),R('回答',True)][:2]
        chat.auditor.mark([rows[0]])
        worker.Worker.audit_missed(w,chat,rows)                       # first sighting starts the clock
        worker.Worker.audit_missed(w,chat,rows)
        self.assertEqual(len(chat.buffered),1)
        self.assertEqual(added[0][:3],('user','这题怎么做',True))
        worker.Worker.audit_missed(w,chat,rows)
        self.assertEqual(len(chat.buffered),1)                        # recovered once, not again
        self.assertEqual(chat.auditor.recovered_total,1)

    def test_audit_can_be_switched_off(self):
        import types,worker
        chat=types.SimpleNamespace(auditor=Auditor(grace=0))
        worker.Worker.audit_missed(types.SimpleNamespace(cfg={'audit':False}),chat,[R('@bot x')])
        self.assertEqual(chat.auditor.recovered_total,0)


if __name__=='__main__':unittest.main()
