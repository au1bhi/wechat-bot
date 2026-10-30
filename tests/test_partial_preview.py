import base64,struct,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker


def png(w,h):return b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',w,h)


class Partial(unittest.TestCase):
    def test_clipped_previews_are_detected(self):
        self.assertTrue(worker.crop_is_partial(png(577,120)))
        self.assertTrue(worker.crop_is_partial(png(900,150)))
        self.assertFalse(worker.crop_is_partial(png(400,300)))
        self.assertFalse(worker.crop_is_partial(b'junk'))

    def test_description_wording(self):
        self.assertTrue(worker.PARTIAL_PICTURE.search('图片是一道题的部分截图'))
        self.assertFalse(worker.PARTIAL_PICTURE.search('一只猫趴在沙发上'))


class Upgrade(unittest.TestCase):
    def run_tick(self,description,partial=False,opened=False):
        class F:
            def done(s):return True
            def result(s):return description
        chat=types.SimpleNamespace(image_pending=0,image_due=0,vision_jobs=[(F(),'Image','s1')],image_retries=0,
                                   partial_sigs={'s1'} if partial else set(),opened_sigs={'s1'} if opened else set(),
                                   banter_unseen=0,last_message=0,name='G',ctx=types.SimpleNamespace(add=lambda role,text,**k:added.append(text) or {}))
        added=[];calls=[]
        w=types.SimpleNamespace(cfg={},senders=types.SimpleNamespace(get=lambda s:'A'),
                                bridge=types.SimpleNamespace(request=lambda p,d:calls.append(p) or {'pages':['x']}))
        with patch.object(worker,'describe_pages',return_value='完整题面'),patch.object(worker,'followup_key',return_value='k'):
            worker.Worker.vision_tick(w,chat)
        return added,calls

    def test_partial_description_reads_the_original(self):
        added,calls=self.run_tick('图片是题目的部分截图')
        self.assertEqual(calls,['/open_image']);self.assertIn('（原图）完整题面',added[0])

    def test_clipped_crop_reads_the_original(self):
        added,calls=self.run_tick('一道题',partial=True)
        self.assertEqual(calls,['/open_image'])

    def test_complete_picture_is_not_reopened(self):
        added,calls=self.run_tick('一只猫');self.assertEqual(calls,[])

    def test_each_picture_is_opened_once(self):
        added,calls=self.run_tick('部分截图',opened=True);self.assertEqual(calls,[])


if __name__ == '__main__':
    unittest.main()
