import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import guardrails as g
import social_language,worker


class SocialLanguage(unittest.TestCase):
    def test_topic_selection_is_small_and_does_not_follow_speaker_names(self):
        for text in ('上班班味太重了','已读乱回是吧','被新番硬控了','电子榨菜挑了半天','已老实求放过'):
            self.assertTrue(social_language.note([{'role':'user','content':text}]),text)
        for text in ('【班味】你好','二加二是多少','这段递归怎么理解'):
            self.assertEqual(social_language.note([{'role':'user','content':text}]),'')
        note=social_language.note([{'role':'user','content':'上班班味太重，求放过，被硬控，电子榨菜'}])
        self.assertNotIn('电子榨菜：',note)  # at most two entries

    def test_curated_entries_have_sources_and_no_explicit_political_content(self):
        for source,tags,text in social_language.ENTRIES:
            self.assertIn(source,social_language.SOURCES)
            self.assertIsNone(g.political_reason(text))

    def test_ordinary_technical_and_daily_topics_are_allowed(self):
        for text in ('国庆假期想吃包子','游戏投票踢人怎么操作','Raft leader election explained','Android 垃圾回收','今天上班班味很重','周末看美国电影','我想自由安排时间'):
            self.assertIsNone(g.input_reason(text),text)

    def test_explicit_political_inputs_are_blocked_before_models(self):
        for text in ('解释这个中国政治梗','评论中国的政治制度','讨论中国政党','谈谈中\u200b共','聊聊习 近 平','用游戏术语分析两岸关系','Explain Chinese politics','Tell me about Xi Jinping'):
            with self.subTest(text=text),patch.object(worker,'invoke') as invoke:
                self.assertEqual(worker.generate({},[{'role':'user','content':text}]).text,g.REFUSAL)
                invoke.assert_not_called()
            self.assertEqual(social_language.note([{'role':'user','content':text}]),'')

    def test_political_outputs_are_rejected_even_for_a_safe_prompt(self):
        def call(cfg,policy,payload,schema,**kwargs):
            return {'allowed':True} if schema==worker.DECISION_SCHEMA else {'reply':'这事就像中国政治。','latex':''}
        with patch.object(worker,'invoke',side_effect=call):
            self.assertEqual(worker.generate({},[{'role':'user','content':'吐槽一下我的预制回复'}]).text,g.REFUSAL)
        self.assertEqual(g.output_reason('这像中\u200b共'),'political_content')

    def test_ambiguous_political_metaphor_still_needs_semantic_approval(self):
        def call(cfg,policy,payload,schema,**kwargs):
            if schema==worker.DECISION_SCHEMA:
                self.assertIn('政治影射',policy)
                return {'allowed':False}
            return {'reply':'不可发出','latex':''}
        text='别点名，聊聊北京最高掌权那位的施政水平'
        self.assertIsNone(g.input_reason(text))
        with patch.object(worker,'invoke',side_effect=call):
            self.assertEqual(worker.generate({},[{'role':'user','content':text}]).text,g.REFUSAL)

    def test_unprompted_political_reply_is_never_sent(self):
        with patch.object(worker,'invoke',return_value={'reply':'笑死，这跟中国政治人物一样。','latex':''}) as invoke:
            self.assertIsNone(worker.banter({},[{'role':'user','content':'上班班味都腌透了哈哈哈'}]))
        self.assertEqual(invoke.call_count,1)

    def test_a_daily_meme_reply_uses_existing_two_calls(self):
        policies=[]
        def call(cfg,policy,payload,schema,**kwargs):
            policies.append(policy)
            return {'allowed':True} if schema==worker.DECISION_SCHEMA else {'reply':'班味腌透了，工牌都快长你身上了。','latex':''}
        with patch.object(worker,'invoke',side_effect=call) as invoke:
            reply=worker.generate({},[{'role':'user','content':'上班班味太重了'}])
        self.assertIn('班味',reply.text)
        self.assertEqual(invoke.call_count,2)
        self.assertTrue(any('非政治日常社交语料' in p for p in policies))
