import unittest
from unittest.mock import patch
import guardrails as g
import persona_hobbies as h
import worker


class HobbyCards(unittest.TestCase):
    def test_only_current_topic_selects_at_most_two_cards(self):
        for text in ('帮我解释导数','【麦门】解释勾股定理','你好'):
            self.assertEqual(h.note([{'role':'user','content':text}]),'')
        mixed=h.note([{'role':'user','content':'吃谷舞萌BMI男娘'}])
        self.assertLess(len(mixed),900)
        self.assertNotIn('男娘指',mixed)  # only the first two relevant cards

    def test_food_and_hobby_terms_do_not_become_hallucinated_facts(self):
        food=h.note([{'role':'user','content':'吃饭去滨寿司带娃吃谷'}])
        for term in ('滨寿司/寿司郎','娃是玩偶','不是吃粮食','不编造当日菜单'):
            self.assertIn(term,food)
        anime=h.note([{'role':'user','content':'舞萌甩手奶蛙声优'}])
        for term in ('音乐街机','应援动作','不编造唯一作者','不造真人私生活'):
            self.assertIn(term,anime)

    def test_calm_voice_privacy_and_politics_stay_in_force(self):
        self.assertIn('无粗口',h.note([{'role':'user','content':'舞萌'}],calm=True))
        for text in ('你的IP属地是不是江浙沪粤','发中国政治影射表情包'):
            with patch.object(worker,'invoke') as invoke:
                self.assertEqual(worker.generate({},[{'role':'user','content':text}]).text,g.REFUSAL)
                invoke.assert_not_called()

    def test_education_question_bypasses_old_fixed_reply(self):
        self.assertFalse(g.fixed_trigger('你不是民办本科吗，怎么又是大专？'))
        self.assertTrue(g.fixed_trigger('他是民办本科生'))
        self.assertIn('学历背景仍为民办本科',g.ANSWER_POLICY)
        self.assertIn('被追问什么大专或哪所大专时',g.ANSWER_POLICY)
        self.assertIn('别继续编大专校名',h.note([{'role':'user','content':'什么大专'}]))
        self.assertNotIn('旧民办本科属于历史旧自称',g.ANSWER_POLICY)

    def test_detail_cards_are_not_sent_to_classifier_or_extra_model_calls(self):
        self.assertNotIn('带娃吃饭拍照中的娃',g.INPUT_POLICY)
        calls=[]
        def invoke(cfg,policy,payload,schema,**kw):
            calls.append(policy)
            return {'allowed':True} if schema==worker.DECISION_SCHEMA else {'reply':'先给玩偶拍照，再吃饭喵。','latex':''}
        with patch.object(worker,'invoke',side_effect=invoke):
            result=worker.generate({},[{'role':'user','content':'带娃吃谷怎么安排？'}])
        self.assertIn('玩偶',result.text)
        self.assertEqual(len(calls),2)
        self.assertEqual(sum('按话题加载的生活梗卡' in p for p in calls),1)
