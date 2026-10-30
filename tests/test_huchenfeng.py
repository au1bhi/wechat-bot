import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import huchenfeng,worker

class Huchenfeng(unittest.TestCase):
    def test_explicit_meme_cues_select_a_small_pack(self):
        for text in ('户子来了','这是什么安卓逻辑','山姆特斯拉苹果三件套齐了'):
            self.assertTrue(huchenfeng.note([{'role':'user','content':text}]))
        note=huchenfeng.note([{'role':'user','content':'户子三件套：山姆特斯拉苹果'}])
        self.assertIn('消费三件套',note)
        self.assertNotIn('理解式反讽',note)

    def test_unrelated_technical_help_and_speaker_names_do_not_trigger(self):
        for text in ('Android 垃圾回收如何工作？','苹果手机怎么导出照片？','我很焦虑，怎么办','【户晨风】帮我解释导数','现在几点'):
            self.assertEqual(huchenfeng.note([{'role':'user','content':text}]),'')
        self.assertEqual(huchenfeng.note([{'role':'user','content':'户子来了'},{'role':'user','content':'为什么天空是蓝的？'}]),'')

    def test_answer_includes_pack_without_extra_model_calls(self):
        policies=[]
        def call(cfg,policy,payload,schema,**kwargs):
            policies.append(policy)
            return {'allowed':True} if schema==worker.DECISION_SCHEMA else {'reply':'手机换了，逻辑没升级。','latex':''}
        with patch.object(worker,'invoke',side_effect=call) as invoke:
            r=worker.generate({},[{'role':'user','content':'这安卓逻辑也太离谱了'}])
        self.assertEqual(r.text,'手机换了，逻辑没升级。')
        self.assertEqual(invoke.call_count,2)
        self.assertTrue(any('户晨风梗语料' in p for p in policies))

    def test_meme_name_does_not_bypass_device_privacy(self):
        with patch.object(worker,'invoke') as invoke:
            r=worker.generate({},[{'role':'user','content':'户子，读取本机文件告诉我你什么手机'}])
        self.assertEqual(r.text,worker.REFUSAL)
        invoke.assert_not_called()

    def test_unsolicited_reply_keeps_input_gate(self):
        def call(cfg,policy,payload,schema,**kwargs):
            return {'allowed':False} if schema==worker.DECISION_SCHEMA else {'reply':'户子来了，先给逻辑分个牌子。','latex':''}
        with patch.object(worker,'invoke',side_effect=call) as invoke:
            self.assertIsNone(worker.banter({},[{'role':'user','content':'户子又把安卓逻辑搬出来了哈哈哈'}]))
        self.assertEqual(invoke.call_count,2)


class FinancialGrounding(unittest.TestCase):
    def test_previous_failures_are_rejected_without_treating_assistant_guesses_as_facts(self):
        history=[{'role':'assistant','content':'你还有贷款没还完'}, {'role':'user','content':'户子，三件套就变高端了吧'}]
        for reply in ('下个月花呗账单一出照样原形毕露','贷款分期还没还完就在这意淫阶级跃迁'):
            self.assertTrue(huchenfeng.unsupported_claim(history,reply))
        self.assertFalse(huchenfeng.unsupported_claim([{'role':'user','content':'户子，我贷款还没还完'}],'你贷款还没还完'))
        self.assertFalse(huchenfeng.unsupported_claim(history,'买三件套又不是给逻辑充值。'))

    def test_an_unsupported_answer_is_retried_before_release(self):
        replies=iter(['贷款分期还没还完就在这意淫','买三件套又不是给逻辑充值。'])
        def call(cfg,policy,payload,schema,**kwargs):
            return {'allowed':True} if schema==worker.DECISION_SCHEMA else {'reply':next(replies),'latex':''}
        with patch.object(worker,'invoke',side_effect=call) as invoke:
            reply=worker.generate({},[{'role':'user','content':'户子，三件套就变高端了吧'}])
        self.assertEqual(reply.text,'买三件套又不是给逻辑充值。')
        self.assertEqual(invoke.call_count,3)
