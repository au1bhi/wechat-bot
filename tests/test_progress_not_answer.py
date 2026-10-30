import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker
from audit import PROGRESS_NOTE, is_answer, Auditor


class ProgressNotes(unittest.TestCase):
    def test_every_progress_text_is_recognised(self):
        texts=[t for d in (worker.PROGRESS_START,worker.PROGRESS_ANSWERING) for v in d.values() for t in v]
        texts+=[t%12 for t in worker.PROGRESS_WAITING.values()]
        for t in texts:self.assertTrue(PROGRESS_NOTE.search(t),t)

    def test_progress_note_is_not_an_answer(self):
        self.assertFalse(is_answer({'outgoing':True,'text':'这题得推导一遍，我在算。'}))
        self.assertTrue(is_answer({'outgoing':True,'text':'I_n=(e_1,...,e_n)'}))
        self.assertFalse(is_answer({'outgoing':False,'text':'随便'}))


if __name__ == '__main__':
    unittest.main()
