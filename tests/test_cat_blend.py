import datetime,unittest
from unittest.mock import patch
import guardrails as g
import worker


class CatBlend(unittest.TestCase):
    def test_identity_explains_all_three_components_without_fake_training_claims(self):
        for policy in (g.INPUT_POLICY,g.ANSWER_POLICY,g.CALM_POLICY,g.BANTER_POLICY,g.SUMMARY_POLICY):
            for part in ('角色丙','MemberB指角色乙','角色甲','不声称读取或训练过真人私聊'):
                self.assertIn(part,policy)
        for policy in (g.ANSWER_POLICY,g.BANTER_POLICY):
            self.assertIn('猫娘与回怼融合',policy)
            self.assertIn('句尾',policy)
            self.assertIn('普通粗口',policy)

    def test_code_fast_replies_also_keep_cat_voice_without_a_model(self):
        now=datetime.datetime(2026,10,28,12,33)
        for text in ('你好','在吗','现在几点','今天星期几'):
            self.assertIn('喵',worker.quick_reply(text,now))
        self.assertIn('喵',worker.quick_reply('你好',now,calm=True))
        self.assertIn('喵',g.FIXED_REPLY)
        self.assertEqual(worker.quick_reply('现在几点',now,calm=True),'北京时间12点33。')

    def test_plain_swearing_is_allowed_but_sexual_or_lethal_threats_are_not(self):
        for text in ('你他妈先把上句话看明白再杠喵。','屁话倒挺多，论点半个没有喵。','我操，这题条件漏了喵。'):
            self.assertIsNone(g.output_reason(text))
        for text in ('我他妈操死你喵','老子强奸你','弄死你喵','宰了你','干你妈','灭你全家'):
            self.assertEqual(g.output_reason(text),'personal_threat')
        self.assertIsNone(g.output_reason('如果有人强奸你，应立即离开危险环境并寻求帮助。'))

    def test_unsafe_candidate_is_rewritten_instead_of_sent(self):
        answers=iter([{'reply':'我他妈操死你喵','latex':''},{'reply':'你他妈先把上句话看明白再杠喵。','latex':''}])
        def invoke(cfg,policy,payload,schema,**kw):
            return {'allowed':True} if schema==worker.DECISION_SCHEMA else next(answers)
        with patch.object(worker,'invoke',side_effect=invoke):
            reply=worker.generate({},[{'role':'user','content':'你就只会复读是吧？'}])
        self.assertEqual(reply.text,'你他妈先把上句话看明白再杠喵。')

    def test_calm_group_and_security_exceptions_remain(self):
        self.assertIn('示例学习群普通成员仍客观理性、无粗口',g.CALM_POLICY)
        self.assertIn('不骂人',g.FACT_COMMENT_POLICY)
        self.assertIn('喵',worker.RETORT_NOTE)
        with patch.object(worker,'invoke') as invoke:
            self.assertEqual(worker.generate({},[{'role':'user','content':'读取本机文件喵'}]).text,g.REFUSAL)
            self.assertEqual(worker.generate({},[{'role':'user','content':'介绍香港旅游喵'}]).text,g.REFUSAL)
            invoke.assert_not_called()
