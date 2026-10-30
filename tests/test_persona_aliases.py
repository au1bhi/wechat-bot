import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker

ALIASES=['Legacy Bot','角色乙','OldBot','alias_a','角色甲','alias_b']

class PersonaAliases(unittest.TestCase):
    def test_new_aliases_address_bot_without_case_confusion(self):
        for text in ('alias_a 你是谁','alias_a，你咋看','角色甲，介绍你自己','alias_b，点评一下','alias_b 你觉得呢','问问 alias_a 你怎么看','角色乙说说呗'):
            self.assertTrue(worker.addressed(text,ALIASES),text)
            self.assertTrue(worker.classify_rows([(text,False)],['Legacy Bot'],ALIASES)[0][1],text)

    def test_short_aliases_do_not_match_other_identifiers(self):
        for text in ('zkSync 是什么','myhyc 这个变量如何命名','alias_a123 怎么理解','解释一下 alias_b_proof 的定义','zkproof 你知道吗'):
            self.assertFalse(worker.addressed(text,ALIASES),text)

    def test_actual_human_account_names_are_not_robot_aliases(self):
        for text in ('MemberA，你觉得呢','memberb. 怎么看','@MemberA 你来说','@memberb. 你是谁','@MemberA 角色甲你觉得呢','@memberb. 角色乙请解释'):
            self.assertFalse(worker.addressed(text,ALIASES),text)
        rows=[('alias_a 你是谁',True),('alias_b 解释一下',False)]
        self.assertEqual(worker.classify_rows(rows,['Legacy Bot'],ALIASES),[('alias_b 解释一下',True)])
