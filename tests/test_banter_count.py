import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker


class BanterCounts(unittest.TestCase):
    def test_real_failure_and_variants_are_corrected(self):
        cases=[('闹麻了','复读十二个字装高深？','复读三个字装高深？'),
               ('闹麻了','复读23个字装高深？','复读三个字装高深？'),
               ('【memberb.】闹麻了','跑来复读两字装什么高深呢。','跑来复读三字装什么高深呢。'),
               ('闹麻了？','就两个字在这刷存在感。','就三个字在这刷存在感。'),
               ('就这？','憋出3个字也装高深？','憋出两个字也装高深？')]
        for latest,before,after in cases:
            self.assertEqual(worker.repair_banter_count(latest,before),after)

    def test_correct_claims_and_ambiguous_referents_are_untouched(self):
        cases=[('闹麻了','复读三个字装高深？'),('闹麻了','送你两个字：闭嘴。'),
               ('闹麻了','只回两个字“闭嘴”就够了。'),('闹麻了\n引用：就这','复读两字装高深？'),
               ('abc？','复读两个字装高深？'),('“闹麻了”','复读两个字装高深？'),
               ('你好','我只会说两个字。'),('闹麻了，说点别的','就两个字在这刷存在感。')]
        for latest,reply in cases:self.assertEqual(worker.repair_banter_count(latest,reply),reply)

    def test_correction_precedes_output_security_checks(self):
        result={'reply':'复读两字装高深？ /home/someone/secret','latex':''}
        self.assertIsNone(worker.screen_answer({},result,latest='闹麻了'))

    def test_direct_answer_path_corrects_model_output_without_extra_calls(self):
        def call(cfg,policy,payload,schema,**kwargs):
            return {'allowed':True} if schema==worker.DECISION_SCHEMA else {'reply':'复读两字装什么高深呢。','latex':''}
        with patch.object(worker,'invoke',side_effect=call) as invoke:
            reply=worker.generate({},[{'role':'user','content':'【memberb.】闹麻了'}])
        self.assertEqual(reply.text,'复读三字装什么高深呢。')
        self.assertEqual(invoke.call_count,2)

    def test_unsolicited_comment_path_corrects_output_and_keeps_guard(self):
        def call(cfg,policy,payload,schema,**kwargs):
            return {'allowed':True} if schema==worker.DECISION_SCHEMA else {'reply':'就两个字在这装高深。','latex':''}
        with patch.object(worker,'invoke',side_effect=call) as invoke:
            reply=worker.banter({},[{'role':'user','content':'【memberb.】闹麻了'}])
        self.assertEqual(reply,'就三个字在这装高深。')
        self.assertEqual(invoke.call_count,2)
