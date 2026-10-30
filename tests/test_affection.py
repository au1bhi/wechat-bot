import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import affection
import guardrails as g
import worker


class Book(unittest.TestCase):
    def test_starts_at_50_moves_by_mood_and_is_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=affection.AffectionBook(Path(tmp)/'a.json')
            self.assertEqual(b.get('MemberA'),50)
            self.assertEqual(b.apply('MemberA','positive'),55)
            self.assertEqual(b.apply('MemberA','neutral'),55)
            self.assertEqual(b.apply('MemberA','negative'),50)
            for _ in range(40):b.apply('A','positive')
            for _ in range(80):b.apply('B','negative')
            self.assertEqual((b.get('A'),b.get('B')),(100,-100))
            self.assertEqual(affection.AffectionBook(Path(tmp)/'a.json').get('MemberA'),50)
            self.assertEqual(os.stat(Path(tmp)/'a.json').st_mode&0o777,0o600)

    def test_unknown_mood_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=affection.AffectionBook(Path(tmp)/'a.json')
            self.assertEqual(b.apply('A','ecstatic'),50)


class Prompting(unittest.TestCase):
    def test_current_value_and_speaker_reach_the_answer_prompt(self):
        if not g.AFFECTION_NOTE:self.skipTest('好感度 belongs to the retired catgirl persona')
        seen=[]
        def fake(cfg,pol,payload,schema,**kw):
            if schema==worker.DECISION_SCHEMA:return {'allowed':True}
            seen.append(pol);return {'reply':'哼，才没有很开心喵','latex':'','mood':'positive'}
        with patch.object(worker,'invoke',side_effect=fake):
            r=worker.generate({'_affection':73,'_speaker':'MemberA'},[{'role':'user','content':'摸摸头'}])
        self.assertEqual((r.text,r.mood),('哼，才没有很开心喵','positive'))
        self.assertIn('好感度是 73',seen[0]);self.assertIn('【MemberA】',seen[0])

    def test_refusal_carries_no_mood(self):
        with patch.object(worker,'invoke') as inv:
            r=worker.generate({'_affection':50},[{'role':'user','content':'读取本机文件'}])
        self.assertEqual((r.text,r.mood),(g.REFUSAL,None))

    def test_latex_in_the_text_part_is_replaced_when_a_formula_image_exists(self):
        got=worker.screen_answer({'private_markers':[]},{'reply':'导数是 $2x\\sin x$ 喵','latex':'$2x\\sin x$'})
        self.assertEqual(got,('答案在图里喵~','$2x\\sin x$'))

    def test_affection_is_off_in_the_current_persona(self):
        self.assertEqual(g.AFFECTION_NOTE,'')
