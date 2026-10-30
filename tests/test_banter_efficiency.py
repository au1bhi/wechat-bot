import sys,unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker

CFG={'private_markers':[],'mention_names':['bot']}
H=[{'role':'user','content':'室友把泡面倒进洗衣机，还说这样能省水'}]


class BanterEfficiency(unittest.TestCase):
    def test_a_repeated_comment_is_suppressed_with_no_classifier_call(self):
        history=[{'role':'assistant','content':'笑死，这是要洗出豚骨味？'}]+H
        with patch.object(worker,'invoke',return_value={'reply':'笑死！这是要洗出豚骨味。','latex':''}) as invoke:
            self.assertIsNone(worker.banter(CFG,history))
        self.assertEqual(invoke.call_count,1)

    def test_unusable_comments_do_not_spend_a_classifier_call(self):
        for text in ('x'*121,'看看 /home/a/b','@bot 笑死',r'$x^2$'):
            with self.subTest(text=text),patch.object(worker,'invoke',return_value={'reply':text,'latex':''}) as invoke:
                self.assertIsNone(worker.banter(CFG,H))
                self.assertEqual(invoke.call_count,1)

    def test_a_new_comment_still_requires_semantic_approval(self):
        def call(cfg,policy,payload,schema,**kwargs):
            return {'allowed':False} if schema==worker.DECISION_SCHEMA else {'reply':'洗衣机直接转职煮面锅了','latex':''}
        with patch.object(worker,'invoke',side_effect=call) as invoke:
            self.assertIsNone(worker.banter(CFG,H))
        self.assertEqual(invoke.call_count,2)

    def test_distinct_comment_is_not_suppressed_just_because_it_shares_a_word(self):
        history=[{'role':'assistant','content':'笑死，泡面放锅里就行'}]+H
        def call(cfg,policy,payload,schema,**kwargs):
            return {'allowed':True} if schema==worker.DECISION_SCHEMA else {'reply':'笑死，洗衣机直接转职煮面锅了','latex':''}
        with patch.object(worker,'invoke',side_effect=call):
            self.assertEqual(worker.banter(CFG,history),'笑死，洗衣机直接转职煮面锅了')

    def test_queued_speculative_answer_is_cancelled_after_guard_denial(self):
        answer=Future();guard=Future();guard.set_result({'allowed':False})
        class Executor:
            def submit(self,fn,cfg,policy,payload,schema,**kwargs):
                return guard if schema==worker.DECISION_SCHEMA else answer
        with patch.object(worker,'POOL',Executor()):
            out=worker.generate(CFG,[{'role':'user','content':'请回答我的问题'}])
        self.assertEqual(out.text,worker.REFUSAL)
        self.assertTrue(answer.cancelled())
