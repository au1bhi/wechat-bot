import json,sys,tempfile,unittest,urllib.parse
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker


class MultiChat(unittest.TestCase):
    def test_each_group_is_isolated(self):
        sent=[]
        rows={'A':[('old',False)],'B':[('old',False)]}
        class Bridge:
            def __init__(self,cfg):pass
            def request(self,path,data=None):
                if path.startswith('/snapshot'):
                    name=urllib.parse.unquote(path.split('chat=')[1])
                    return {'rows':[{'text':t,'outgoing':o} for t,o in rows[name]]}
                if path=='/send':
                    sent.append((data['chat'],data['text']));return {'status':'sent'}
                raise AssertionError(path)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'state').mkdir()
            cfg={'chat':'A','chats':['A','B'],'mention_names':['bot'],'aliases':['bot'],'debounce_seconds':0}
            with patch.object(worker,'ROOT',root),patch.object(worker,'Bridge',Bridge),\
                 patch.object(worker,'generate',return_value=worker.Reply('ok','')):
                w=worker.Worker(cfg)
                for c in w.chats:w.step(c)            # baselines
                rows['B']+=[('B里的闲聊',False),('@bot 你好',False)]
                rows['A']+=[('他是民办本科',False)]
                for c in w.chats:w.step(c)
                w.chats[1].answer_job[0].result(timeout=2)
                w.step(w.chats[1])
                self.assertIn(('B','ok'),sent)
                self.assertIn(('A',worker.FIXED_REPLY),sent)
                self.assertNotIn(('A','ok'),sent)
                self.assertEqual([m['content'] for m in w.chats[1].ctx.messages][:2],['B里的闲聊','你好'])
                self.assertNotIn('B里的闲聊',json.dumps([m['content'] for m in w.chats[0].ctx.messages],ensure_ascii=False))
                w.db.close()


if __name__=='__main__':unittest.main()
