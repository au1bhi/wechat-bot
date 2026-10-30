"""Exercise native bridge direction without GI, an X server, or model calls."""
import ast,re,sys,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import worker
import test_reply_delivery as fixtures

SOURCE=Path(__file__).resolve().parents[1]/'transport.py'
TREE=ast.parse(SOURCE.read_text())
FUNCTIONS=ast.Module(body=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in ('message_direction','snapshot')],type_ignores=[])


def picture(side,green=False):
    crop=Image.new('RGB',(578,128),(250,250,250));d=ImageDraw.Draw(crop)
    # Image body can be white, dark, or green; it never occupies avatar gutters.
    d.rectangle((70,30,500,110),fill=(80,220,90) if green else 'white')
    if side in ('incoming','both'):d.rectangle((20,8,55,43),fill=(95,120,145))
    if side in ('outgoing','both'):d.rectangle((521,8,556,43),fill=(95,120,145))
    return crop


class Node:
    def __init__(self,name,bounds,children=()):self.name=name;self.rect=bounds;self.children=list(children)
    def get_name(self):return self.name
    def get_role_name(self):return 'list' if self.children else 'list item'
    def get_child_count(self):return len(self.children)
    def get_child_at_index(self,i):return self.children[i]


def bridge(crop,clipped=False):
    row=Node('Image',(20,20,578,128));listing=Node('Messages',(20,40 if clipped else 20,578,128),[row])
    shot=Image.new('RGB',(640,200),(250,250,250));shot.paste(crop,(20,20))
    scope={'open_chat':lambda:None,'app':lambda:listing,'walk':lambda a:[a],
           'visible':lambda n:True,'bounds':lambda n:n.rect,'screenshot':lambda:shot,
           'IMAGE_ROW':worker.IMAGE_ROW,'re':re,'CHAT':'A',
           'name_strip':lambda c,w:('NAME',None),'strip_png':lambda x:'STRIP','crop_png':lambda c:'PNG'}
    exec(compile(FUNCTIONS,str(SOURCE),'exec'),scope)
    return scope


class ImageDirection(unittest.TestCase):
    def test_white_self_image_is_outgoing_and_never_gets_a_sender_strip(self):
        scope=bridge(picture('outgoing'))
        def forbidden(*args):raise AssertionError('Outgoing content must not become a nickname')
        scope['name_strip']=forbidden
        row=scope['snapshot'](images=True,strips=True)['rows'][0]
        self.assertTrue(row['outgoing']);self.assertEqual(row['direction'],'outgoing')
        self.assertNotIn('sig',row);self.assertNotIn('strip',row)

    def test_green_image_from_friend_remains_incoming(self):
        row=bridge(picture('incoming',green=True))['snapshot'](images=True)['rows'][0]
        self.assertFalse(row['outgoing']);self.assertEqual(row['direction'],'incoming')
        self.assertEqual(row['sig'],'NAME')

    def test_uncertain_or_clipped_image_never_becomes_incoming(self):
        for side,clipped in (('none',False),('both',False),('outgoing',True)):
            row=bridge(picture(side),clipped)['snapshot'](images=True)['rows'][0]
            self.assertEqual(row['direction'],'unknown')
            self.assertNotIn('sig',row)
            if clipped:self.assertNotIn('png',row)
            self.assertFalse(worker.incoming_image(row))


class ImageEchoPipeline(unittest.TestCase):
    def setUp(self):fixtures.Delivery.setUp(self);self.w.cfg.update(vision=True,image_delay=0)

    def test_outgoing_and_unknown_media_never_schedule_vision_or_banter(self):
        with patch.object(worker,'describe_image') as describe:
            self.rows['A']+=[{'text':'Image','outgoing':True,'direction':'outgoing'},
                             {'text':'Image','outgoing':False,'direction':'unknown','sig':'fake-name'}]
            self.w.step(self.c);self.w.step(self.c)
            self.assertEqual(self.c.image_pending,0);self.assertEqual(self.c.vision_jobs,[])
            self.assertEqual(self.c.banter_unseen,0)
            self.assertFalse(any(m['content'].startswith('[图片]') for m in self.c.ctx.messages))
            describe.assert_not_called()

    def test_delayed_capture_rechecks_direction_instead_of_trusting_name(self):
        self.c.image_pending=1
        with patch.object(self.w.bridge,'request',return_value={'rows':[{'text':'Image','outgoing':True,'direction':'outgoing','sig':'fake-name','png':'OWN'}]}),patch.object(worker,'describe_image') as describe:
            self.w.capture_images(self.c)
            self.assertEqual(self.c.vision_jobs,[]);describe.assert_not_called()

    def test_zero_pending_does_not_scan_all_images(self):
        # Python list[-0:] is the whole list; it must never queue old images.
        self.c.image_pending=0
        with patch.object(self.w.bridge,'request',return_value={'rows':[{'text':'Image','outgoing':False,'direction':'incoming','sig':'alice','png':'OTHER'}]}):
            self.w.capture_images(self.c)
        self.assertEqual(self.c.vision_jobs,[])

    def test_positive_incoming_media_with_no_readable_nickname_is_still_processed(self):
        self.c.image_pending=1
        with patch.object(self.w.bridge,'request',return_value={'rows':[{'text':'Image','outgoing':False,'direction':'incoming','png':'OTHER'}]}),patch.object(worker,'describe_image',return_value='群友发来的绿色卡通图') as describe:
            self.w.capture_images(self.c)
            for job in self.c.vision_jobs:job[0].result(timeout=2)
            self.w.vision_tick(self.c)
            self.assertEqual(describe.call_count,1)
        self.assertTrue(any('绿色卡通图' in m['content'] for m in self.c.ctx.messages))
