import unittest
from guardrails import DENIES_EXISTENCE, needs_fresh, ANSWER_POLICY, CALM_POLICY


class VerifyDenial(unittest.TestCase):
    def test_denial_detected(self):
        for t in ('没听说过这个游戏', '这玩意不存在吧', '你是不是编的吧'):
            self.assertTrue(DENIES_EXISTENCE.search(t), t)
        self.assertFalse(DENIES_EXISTENCE.search('这个游戏挺好玩的'))

    def test_claims_trigger_search(self):
        for t in ('听说出了新游戏', '真的假的', '有这个人吗'):
            self.assertTrue(needs_fresh(t), t)
        self.assertFalse(needs_fresh('哈哈哈'))

    def test_policies_carry_notes(self):
        self.assertIn('先求证', ANSWER_POLICY)
        self.assertIn('谐音', ANSWER_POLICY)
        self.assertIn('谐音', CALM_POLICY)
        self.assertNotIn('偶尔（不是每句）用一个自然的谐音梗', CALM_POLICY)


if __name__ == '__main__':
    unittest.main()
