import queue,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import agy_model
import worker

CFG={'model':'m','gate_model':'g','agy_model':'low','agy_gate_model':'low','agy_hard_model':'high'}


class Routing(unittest.TestCase):
    def test_hard_questions_are_recognised(self):
        for q in ('满秩能推出什么性质','【赵拾陆】求极限 lim x->0 sin x / x','证明 √2 是无理数','这段代码报错了怎么办','计算这个积分','算法题 dp 怎么想'):
            self.assertTrue(worker.is_hard(q),q)

    def test_chat_and_advice_stay_on_the_fast_model(self):
        for q in ('你好','今天吃啥','苏醒','概率论怎么学','计算机怎么选','解释一下二分查找'):
            self.assertFalse(worker.is_hard(q),q)

    def test_model_choice(self):
        self.assertEqual(agy_model.model_for(dict(CFG,_hard=True)),'high')
        self.assertEqual(agy_model.model_for(CFG),'low')
        self.assertEqual(agy_model.model_for(dict(CFG,_hard=True,model='g')),'low')       # classifier/audit calls never use it
        self.assertEqual(agy_model.model_for({k:v for k,v in dict(CFG,_hard=True).items() if k!='agy_hard_model'}),'low')


class Pool(unittest.TestCase):
    def test_high_model_has_no_idle_processes(self):
        p=agy_model.Pool.__new__(agy_model.Pool)
        p.cfg={'agy_pool_floors':{'high':0}};p.floor=2
        self.assertEqual(p.floor_for('high'),0);self.assertEqual(p.floor_for('low'),2)


class Stage(unittest.TestCase):
    def test_callback_fires_once_when_the_model_starts_writing(self):
        w=agy_model.Warm.__new__(agy_model.Warm)
        w.events=queue.Queue();w.proc=types.SimpleNamespace(stdin=types.SimpleNamespace(write=lambda x:None,flush=lambda:None))
        for e in ({'event':'step_update','step_update':{'step_type':'user_input'}},
                  {'event':'step_update','step_update':{'step_type':'agent_response','text_delta':'{"re'}},
                  {'event':'step_update','step_update':{'step_type':'agent_response','text_delta':'ply'}},
                  {'event':'result','result':{'status':'SUCCESS','response':'x'}}):w.events.put(e)
        seen=[];self.assertEqual(w.turn('q',5,seen.append),'x');self.assertEqual(seen,['answering'])


class Notes(unittest.TestCase):
    def fake(self,calm=True,stage='thinking',elapsed=0):
        sent=[]
        w=types.SimpleNamespace(send_progress=lambda chat,text:sent.append(text))
        chat=types.SimpleNamespace(name='A',answer_job=object(),progress={'t0':worker.time.monotonic()-elapsed,'stage':stage,'calm':calm,'waits':0,'next_wait':30,'answering_told':False})
        return w,chat,sent

    def test_quiet_at_first_then_waiting_notes_use_elapsed_time(self):
        w,chat,sent=self.fake(elapsed=10);worker.Worker.progress_tick(w,chat);self.assertEqual(sent,[])
        w,chat,sent=self.fake(elapsed=31);worker.Worker.progress_tick(w,chat);self.assertEqual(len(sent),1);self.assertIn('31',sent[0])
        worker.Worker.progress_tick(w,chat);self.assertEqual(len(sent),1)                 # next one only 30 s later

    def test_answering_note_only_when_the_writing_phase_drags_on(self):
        w,chat,sent=self.fake(stage='answering',elapsed=40)
        worker.Worker.progress_tick(w,chat);self.assertEqual(sent,[])                       # just started writing
        chat.progress['answering_at']-=9
        worker.Worker.progress_tick(w,chat);worker.Worker.progress_tick(w,chat);self.assertEqual(len(sent),1)

    def test_finished_answer_clears_the_state(self):
        w,chat,sent=self.fake(elapsed=99);chat.answer_job=None;worker.Worker.progress_tick(w,chat)
        self.assertIsNone(chat.progress);self.assertEqual(sent,[])

if __name__=='__main__':unittest.main()
