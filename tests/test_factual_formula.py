import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker

HISTORY=[{'role':'user','content':'外积矩阵的秩是多少？'}]


def run(result,render=b'\x89PNGxx',allowed=True):
    def fake(cfg,pol,payload,schema,**kw):
        return {'allowed':allowed} if 'candidate' in payload else result
    with patch.object(worker,'invoke',side_effect=fake),patch.object(worker,'render',return_value=render):
        return worker.factual_comment({},HISTORY)


class FactualFormula(unittest.TestCase):
    def test_formula_is_typeset_and_returned_with_text(self):
        r=run({'reply':'外积矩阵的推导如下：','latex':'\\operatorname{rank}(uv^T)=1','mood':'neutral'})
        self.assertIsInstance(r,worker.Reply)
        self.assertEqual(r.text,'外积矩阵的推导如下：');self.assertTrue(r.png)

    def test_announcement_without_formula_is_dropped(self):
        self.assertIsNone(run({'reply':'外积矩阵性质的推导如下：','latex':'','mood':'neutral'}))

    def test_render_failure_stays_silent(self):
        def boom(_):raise RuntimeError('render')
        with patch.object(worker,'render',side_effect=boom):
            def fake(cfg,pol,payload,schema,**kw):
                return {'allowed':True} if 'candidate' in payload else {'reply':'见下：','latex':'x=1','mood':'neutral'}
            with patch.object(worker,'invoke',side_effect=fake):
                self.assertIsNone(worker.factual_comment({},HISTORY))

    def test_plain_text_comment_unchanged(self):
        self.assertEqual(run({'reply':'秩为1。','latex':'','mood':'neutral'}),'秩为1。')


if __name__ == '__main__':
    unittest.main()
