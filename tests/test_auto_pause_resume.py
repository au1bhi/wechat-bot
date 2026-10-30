import sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker


class AutoPause(unittest.TestCase):
    def test_marker_and_rewind(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'state').mkdir()
            saved=[]
            w=types.SimpleNamespace(save_seen=lambda chat,keys,force=False:saved.append(keys))
            chat=types.SimpleNamespace(name='A',buffered=[{'content':'问题二'}],answer_job=None,
                                       previous=[('旧消息',False),('@bot 问题一',False),('问题二',False)])
            with patch.object(worker,'ROOT',root):
                self.assertFalse(worker.Worker.auto_paused(w))
                (root/'state'/'PAUSED').write_text('auto')
                self.assertTrue(worker.Worker.auto_paused(w))
                (root/'state'/'PAUSED').write_text('')
                self.assertFalse(worker.Worker.auto_paused(w))      # a manual pause still forgets everything
            worker.Worker.rewind_seen(w,chat)
            self.assertEqual(saved,[[('旧消息',False),('@bot 问题一',False)]])
    def test_nothing_pending_keeps_seen_untouched(self):
        saved=[]
        w=types.SimpleNamespace(save_seen=lambda *a,**k:saved.append(a))
        chat=types.SimpleNamespace(name='A',buffered=[],answer_job=None,previous=[('x',False)])
        worker.Worker.rewind_seen(w,chat);self.assertEqual(saved,[])

if __name__=='__main__':unittest.main()
