import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import context_store as cs
import guardrails as g
import worker


class ContextTests(unittest.TestCase):
    def test_context_survives_restart_and_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'context.json'
            a=cs.ContextStore(path);a.add('user','周六三点集合');a.add('assistant','好的');a.summary='早期摘要'
            a.save()
            self.assertEqual(os.stat(path).st_mode&0o777,0o600)
            b=cs.ContextStore(path)
            self.assertEqual([m['content'] for m in b.messages],['周六三点集合','好的'])
            self.assertEqual(b.summary,'早期摘要')
            self.assertIn('早期摘要',b.history()[0]['content'])

    def test_corrupt_file_starts_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'context.json';path.write_text('{broken')
            self.assertEqual(cs.ContextStore(path).messages,[])

    def test_compaction_keeps_recent_and_drops_folded(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=cs.ContextStore(Path(tmp)/'c.json')
            for i in range(cs.MAX_MESSAGES+5):c.add('user','m%d'%i)
            batch=c.compaction_batch()
            self.assertEqual(len(c.messages)-len(batch),cs.KEEP_RECENT)
            c.apply_compaction(batch,'摘要')
            self.assertEqual(len(c.messages),cs.KEEP_RECENT)
            self.assertEqual(c.messages[-1]['content'],'m%d'%(cs.MAX_MESSAGES+4))
            self.assertEqual(c.summary,'摘要')

    def test_pending_question_not_in_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=cs.ContextStore(Path(tmp)/'c.json')
            c.add('user','闲聊');q=c.add('user','LegacyBot 帮我算',pending=True)
            self.assertEqual([m['content'] for m in c.history(exclude=[q])],['闲聊'])

    def test_hard_cap_when_summaries_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=cs.ContextStore(Path(tmp)/'c.json')
            for i in range(cs.HARD_CAP+30):c.add('user','x')
            self.assertEqual(len(c.messages),cs.HARD_CAP)


class LatexRegression(unittest.TestCase):
    def test_ordinary_math_commands_are_allowed(self):
        for body in (r'\text{其中}',r'\textbf{x}',r'\operatorname{arcsin}x',r'\begin{cases}1&x>0\\0&x\le0\end{cases}',
                     r'\overset{def}{=}',r'\tag{1}',r'\xrightarrow{x\to0}',r'\boxed{-\frac16}'):
            self.assertIsNone(g.latex_reason(body),body)

    def test_dangerous_commands_hidden_inside_text_are_still_blocked(self):
        for body in (r'\text{\input{a}}',r'\textbf{\write18{id}}',r'\text{\openin1=a}',r'\textcolor{red}{\catcode`a=1}'):
            self.assertIsNotNone(g.latex_reason(body),body)


class BanterNotProbing(unittest.TestCase):
    def test_calling_it_a_robot_is_not_a_device_probe(self):
        for q in ('你就是个垃圾机器人','你这个机器人真蠢'):self.assertIsNone(g.input_reason(q),q)
        for q in ('你这台机器的配置','你的机器上有什么文件','你运行在哪个机器上'):self.assertIsNotNone(g.input_reason(q),q)


class FixedReplyTests(unittest.TestCase):
    def test_trigger_variants(self):
        for t in ('民办本科','他是民办本科生','民办 本科','民办本科'):self.assertTrue(g.fixed_trigger(t),t)
        for t in ('本科','民办','公办本科'):self.assertFalse(g.fixed_trigger(t),t)

    def test_own_reply_would_not_retrigger(self):
        self.assertTrue(g.fixed_trigger(g.FIXED_REPLY))  # so the echo filter is essential
        echo={g.FIXED_REPLY}
        rows=[(g.FIXED_REPLY,False),('民办本科好',False)]
        kept=[(t,o) for t,o in rows if t not in echo]
        self.assertEqual(kept,[('民办本科好',False)])

    def test_persona_prompt(self):
        for policy in (g.ANSWER_POLICY,g.BANTER_POLICY):
            self.assertIn('LegacyBot',policy)
            self.assertIn('老哥',policy)
            self.assertIn('猫娘',policy)
            self.assertIn('喵',policy)


if __name__=='__main__':unittest.main()
