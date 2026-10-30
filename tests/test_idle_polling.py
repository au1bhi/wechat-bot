import sys,types,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker

def make(previous=['x'],pending=0):
    w=types.SimpleNamespace(cfg={'idle_refresh_seconds':10},list_text={'A':'t1'},last_read={'A':100.0})
    c=types.SimpleNamespace(name='A',previous=previous,image_pending=pending)
    return w,c

class NeedsRead(unittest.TestCase):
    def test_unchanged_chat_is_not_read(self):
        w,c=make();self.assertFalse(worker.Worker.needs_read(w,c,{'A':'t1'},105))
    def test_changed_preview_is_read(self):
        w,c=make();self.assertTrue(worker.Worker.needs_read(w,c,{'A':'t2'},101))
    def test_periodic_refresh(self):
        w,c=make();self.assertTrue(worker.Worker.needs_read(w,c,{'A':'t1'},111))
    def test_first_look_and_fallback(self):
        w,c=make(previous=None);self.assertTrue(worker.Worker.needs_read(w,c,{'A':'t1'},101))
        w,c=make();self.assertTrue(worker.Worker.needs_read(w,c,None,101))
    def test_pending_images(self):
        w,c=make(pending=1);self.assertTrue(worker.Worker.needs_read(w,c,{'A':'t1'},101))

if __name__=='__main__':unittest.main()


class QuickReply(unittest.TestCase):
    def test_clock_and_date_by_code(self):
        import datetime
        now=datetime.datetime(2026,10,28,12,33)
        self.assertIn('12点33',worker.quick_reply('张三：@Legacy Bot 现在是几点',now))
        self.assertIn('星期三',worker.quick_reply('今天星期几？',now))
    def test_other_questions_go_to_the_model(self):
        for t in ('几点睡觉好','帮我算一下几点','（引用）现在几点'):self.assertIsNone(worker.quick_reply(t))
