import ast,base64,io,types,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from PIL import Image,ImageChops
import worker
from test_open_image import make_worker


def content_png():
    im=Image.new('L',(160,160));im.putdata([(x+y)%256 for y in range(160) for x in range(160)])
    out=io.BytesIO();im.save(out,'PNG');return base64.b64encode(out.getvalue()).decode()


class Descriptions(unittest.TestCase):
    def test_nonblank_claim_is_retried_with_same_pixels(self):
        png=content_png()
        for function,arg in ((worker.describe_pages,[png]),(worker.describe_image,png)):
            with self.subTest(function=function.__name__),patch.object(worker,'invoke',side_effect=[{'description':'这是一张纯白图片'},{'description':'图上有手机和电视'}]) as invoke:
                self.assertEqual(function({},arg),'图上有手机和电视')
                self.assertEqual(invoke.call_count,2)
                self.assertEqual(invoke.call_args.kwargs['images'],[png])

    def test_repeated_blank_claim_is_not_kept_as_content(self):
        with patch.object(worker,'invoke',return_value={'description':'这是一张空白图片'}) as invoke:
            self.assertIsNone(worker.describe_pages({},[content_png()]))
            self.assertEqual(invoke.call_count,2)

    def test_pending_vision_already_counts_as_a_picture_question(self):
        w=make_worker(lambda *a,**k:{'rows':[]});self.addCleanup(w.db.close);self.addCleanup(w.tmp.cleanup)
        c=w.chats[0];c.image_pending=1
        self.assertEqual(w.wants_picture(c,[{'content':'看一下这个图'}]),(True,None))
        c.image_pending=0;c.vision_jobs=[(None,'Image','s')]
        self.assertEqual(w.wants_picture(c,[{'content':'这题怎么做'}]),(True,None))

    def test_no_crop_and_busy_pool_do_not_drop_pending_image(self):
        w=make_worker(lambda *a,**k:{'rows':[]});self.addCleanup(w.db.close);self.addCleanup(w.tmp.cleanup)
        c=w.chats[0];c.image_pending=1;w.capture_images(c)
        self.assertEqual(c.image_pending,1);self.assertEqual(c.image_retries,1)
        c.vision_jobs=[None]*4;w.capture_images(c)
        self.assertEqual(c.image_pending,1)

    def test_missing_picture_adds_honest_answer_instruction(self):
        seen=[]
        def invoke(cfg,policy,payload,schema,**kw):
            seen.append(policy)
            return {'allowed':True} if schema==worker.DECISION_SCHEMA else {'reply':'这次没读清，请重发原图。','latex':''}
        with patch.object(worker,'invoke',side_effect=invoke):
            self.assertNotEqual(worker.generate({'_picture_missing':True},[{'role':'user','content':'这个图怎么样'}]).text,worker.REFUSAL)
        self.assertTrue(any('不得声称图片空白' in p for p in seen))


class NativeCapture(unittest.TestCase):
    def scope(self):
        tree=ast.parse((Path(worker.__file__).parent/'transport.py').read_text())
        fs=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('wait_viewer_image','open_image')],type_ignores=[])
        row=object();listing=types.SimpleNamespace(get_child_count=lambda:1,get_child_at_index=lambda i:types.SimpleNamespace(get_name=lambda:'Image'))
        clock=[0.0]
        def sleep(n):clock[0]+=n
        scope={'time':types.SimpleNamespace(monotonic=lambda:clock[0],sleep=sleep),'ImageChops':ImageChops,
               'viewer_frame':lambda:None,'app':lambda:None,'walk':lambda a:[listing],
               'bounds':lambda n:(0,50,160,160) if n is listing else (0,10,160,100),
               'wheel':Mock()}
        listing.get_role_name=lambda:'list';listing.get_name=lambda:'Messages'
        exec(compile(fs,'transport.py','exec'),scope)
        return scope

    def test_clipped_image_is_revealed_and_viewport_restored(self):
        s=self.scope();s['open_image_visible']=Mock(side_effect=[RuntimeError('IMAGE_NOT_VISIBLE'),{'pages':['real']}])
        self.assertEqual(s['open_image']({'chat':'A'}),{'pages':['real']})
        self.assertEqual([c.args[2:] for c in s['wheel'].call_args_list],[(4,2),(5,2)])

    def test_stuck_viewer_is_never_scrolled(self):
        s=self.scope();s['open_image_visible']=Mock(side_effect=RuntimeError('VIEWER_NOT_CLOSED'))
        with self.assertRaisesRegex(RuntimeError,'VIEWER_NOT_CLOSED'):s['open_image']({})
        s['wheel'].assert_not_called()

    def test_render_wait_ignores_early_blank_frames(self):
        s=self.scope();frame=object();s['viewer_frame']=lambda:frame;s['bounds']=lambda n:(0,0,160,202)
        blank=Image.new('RGB',(160,202),'white');visible=blank.copy()
        for x in range(160):
            for y in range(42,202):visible.putpixel((x,y),((x+y)%256,)*3)
        s['screenshot']=Mock(side_effect=[blank,blank,visible,visible,visible])
        self.assertEqual(s['wait_viewer_image'](frame).size,(160,160))
        self.assertEqual(s['screenshot'].call_count,5)

    def test_flat_viewer_times_out_instead_of_returning_fake_white_image(self):
        s=self.scope();frame=object();s['viewer_frame']=lambda:frame;s['bounds']=lambda n:(0,0,160,202)
        s['screenshot']=lambda:Image.new('RGB',(160,202),'white')
        with self.assertRaisesRegex(RuntimeError,'IMAGE_NOT_LOADED'):s['wait_viewer_image'](frame,timeout=.6)
