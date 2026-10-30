import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker


class LoginPrompt(unittest.TestCase):
    def make(self,cfg=None):
        calls=[]
        class Bridge:
            def __init__(self,cfg):pass
            def request(self,path,data=None):
                calls.append(path);return {'status':'prompt_sent'}
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name);(root/'state').mkdir()
        with patch.object(worker,'ROOT',root),patch.object(worker,'Bridge',Bridge):
            w=worker.Worker(dict({'chat':'A','chats':['A']},**(cfg or {})))
        self.addCleanup(w.db.close)
        return w,calls

    def test_prompts_once_then_waits_for_the_interval(self):
        w,calls=self.make({'login_prompt_interval':900})
        w.prompt_login();w.prompt_login();w.prompt_login()
        self.assertEqual(calls,['/request_login'])

    def test_stops_after_the_limit(self):
        w,calls=self.make({'login_prompt_interval':0,'login_prompt_limit':2})
        for _ in range(5):w.prompt_login()
        self.assertEqual(len(calls),2)


if __name__=='__main__':unittest.main()
