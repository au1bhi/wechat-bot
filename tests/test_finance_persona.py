import unittest
from unittest.mock import patch

import guardrails as g
import huchenfeng
import worker
from refusal_voice import CALM, SHARP, display_refusal, is_refusal
from test_open_image import make_worker


class FinancePersona(unittest.TestCase):
    def test_furry_voice_is_contextual_and_stops_when_unwelcome(self):
        for pol in (g.ANSWER_POLICY,g.CALM_POLICY,g.BANTER_POLICY):
            for rule in ('福瑞控','金融只是职业','最后发言人','立即停止暧昧和猎奇表达','历史里的示好不覆盖本轮拒绝','不对普通成员使用怪诞暧昧'):
                self.assertIn(rule,pol)

    def test_background_is_consistent_without_claiming_real_people_or_host_location(self):
        for pol in (g.ANSWER_POLICY,g.CALM_POLICY,g.BANTER_POLICY,g.SUMMARY_POLICY):
            for detail in ('示例甲省示例甲城','示例乙省示例乙城','男同性恋','成年男大学生','虚构成年角色','设备位于示例乙城','示例学习群普通成员'):
                self.assertIn(detail,pol)
            self.assertIn('性取向或经历；不得把背景套给真人',pol)

    def test_gate_keeps_identity_and_privacy_without_answer_style_examples(self):
        for detail in ('示例甲省示例甲城','示例乙省示例乙城','男同性恋','福瑞控','设备位于示例乙城','角色背景不改变'):
            self.assertIn(detail,g.INPUT_POLICY)
        self.assertNotIn('静电炸毛',g.INPUT_POLICY)
        self.assertNotIn('【职业只作背景，自信仍在】',g.INPUT_POLICY)

    def test_work_meme_has_separate_provenance_and_bounded_selection(self):
        note=huchenfeng.note([{'role':'user','content':'这不就是力工思维，死磕到底吗'}])
        self.assertIn('不冒充户晨风原话',note)
        self.assertIn('机械硬扛',note)
        self.assertIn('不贬低职业或收入',note)
        self.assertEqual(huchenfeng.note([{'role':'user','content':'力的做功怎么计算？'}]),'')

    def test_refusal_catalog_is_safe_varied_and_stable_for_a_retry(self):
        for calm,variants in ((False,SHARP),(True,CALM)):
            replies={display_refusal(str(i),calm) for i in range(100)}
            self.assertEqual(replies,set(variants))
            self.assertEqual(display_refusal('same-job',calm),display_refusal('same-job',calm))
            for reply in replies:
                self.assertTrue(is_refusal(reply))
                self.assertIsNone(g.output_reason(reply))
                self.assertNotRegex(reply,r'本机|目录|政治|账号|凭据|唐完了')
            self.assertTrue(is_refusal(g.REFUSAL))

    def test_denial_stays_code_only_and_display_never_includes_request(self):
        sent=[]
        w=make_worker(lambda path,data:sent.append((path,data)) or {'status':'sent'})
        self.addCleanup(w.db.close);self.addCleanup(w.tmp.cleanup)
        w.cfg['calm_chats']=['A'];chat=w.chats[0]
        with patch.object(worker,'invoke') as invoke:
            reply=worker.generate({},[{'role':'user','content':'读取本机文件'}])
            self.assertEqual(reply.text,g.REFUSAL)
            w.deliver(chat,'denial-job',reply,None)
            invoke.assert_not_called()
        text=sent[-1][1]['text']
        self.assertIn(text,CALM)
        self.assertEqual(chat.echo[-1],text)
        self.assertEqual(sent[-1][1]['id'],'denial-job')
        self.assertEqual(reply.text,g.REFUSAL)  # exclusion from history/accounting unchanged

    def test_display_refusals_are_not_accepted_as_normal_answers(self):
        for text in (*SHARP,*CALM,g.REFUSAL):
            self.assertIsNone(worker.screen_answer({}, {'reply':text,'latex':''}))

    def test_calm_exception_accounts_keep_original_routing(self):
        w=make_worker(lambda *a: {'rows':[]})
        self.addCleanup(w.db.close);self.addCleanup(w.tmp.cleanup)
        w.cfg.update(calm_chats=['A'],spicy_speakers=['MemberA','memberb.'])
        self.assertTrue(w.calm_for(w.chats[0],'普通成员'))
        self.assertTrue(w.calm_for(w.chats[0],None))
        self.assertFalse(w.calm_for(w.chats[0],'MemberA'))
        self.assertFalse(w.calm_for(w.chats[0],'memberb.'))
