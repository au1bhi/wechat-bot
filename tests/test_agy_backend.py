import base64,json,os,subprocess,sys,tempfile,textwrap,time,unittest
from pathlib import Path
from unittest.mock import patch
from subprocess import Popen as RealPopen      # kept apart: the fixtures below replace subprocess.Popen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import agy_model
import backend
import fast_model
import model_sandbox as ms

PNG=base64.b64encode(b'\x89PNG\r\n\x1a\n'+b'x'*400).decode()

# A stand-in for `agy` that speaks the same stream-json protocol. Its behaviour is chosen by a file next to it.
STUB=textwrap.dedent('''
    import json,os,sys
    sys.stdout.write(json.dumps({"event":"init","init":{"model":"stub"}})+"\\n");sys.stdout.flush()
    turns=0
    here=os.path.dirname(os.path.abspath(__file__))
    for line in sys.stdin:
        turns+=1
        ev=json.loads(line)
        text=ev["message"]["content"][0]["text"]
        mode_file=os.path.join(here,"mode")
        mode=open(mode_file).read().strip() if os.path.exists(mode_file) else "ok"
        if mode=="error":
            res={"status":"ERROR","response":"","error":"boom"}
        elif mode=="prose":
            res={"status":"SUCCESS","response":"好的，结果如下：\\n```json\\n{\\"allowed\\": true}\\n```"}
        elif mode=="plain":
            res={"status":"SUCCESS","response":json.dumps({"allowed":True})}
        elif mode=="garbage":
            res={"status":"SUCCESS","response":"我不会输出 JSON"}
        elif mode=="flaky":
            flag=os.path.join(here,"flaky_seen")
            if not os.path.exists(flag):
                open(flag,"w").write("1")
                res={"status":"SUCCESS","response":"这不是 JSON"}
            else:
                res={"status":"SUCCESS","response":json.dumps({"allowed":True})}
        elif mode=="files":
            res={"status":"SUCCESS","response":json.dumps({"allowed":True,"cwd":os.getcwd(),"files":sorted(os.listdir("."))})}
        else:
            res={"status":"SUCCESS","response":json.dumps({"allowed":True,"pid":os.getpid(),"turns":turns,"saw":text[:2000]},ensure_ascii=False)}
        sys.stdout.write(json.dumps({"event":"result","result":res})+"\\n");sys.stdout.flush()
''')


class Fake(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.stub=Path(self.tmp.name)/'agy_stub.py';self.stub.write_text(STUB)
        self.mode=Path(self.tmp.name)/'mode'
        self.cfg={'backend':'agy','agy_model':'m-answer','agy_gate_model':'m-gate','model':'chatgpt-a','gate_model':'chatgpt-g',
                  'agy_pool':{'m-gate':3,'m-answer':2},'agy_pool_min':1,'agy_pool_idle_seconds':300,
                  'agy_work_root':str(Path(self.tmp.name)/'work'),'network_guard_bin':'/bin/true'}
        self.workdirs=[]
        self.procs=[]
        def command(cfg,model,fd,workdir):
            self.workdirs.append(workdir)
            return [sys.executable,str(self.stub)]
        def run(cfg,model,fd,workdir):
            return command(cfg,model,fd,workdir)
        patch.object(agy_model,'sandbox_command',command).start()
        # run the stub inside its private work directory, as the real sandbox does with --chdir /work
        real_popen=agy_model.subprocess.Popen
        def popen(argv,**kw):
            kw['cwd']=self.workdirs[-1]
            proc=real_popen(argv,**kw);self.procs.append(proc);return proc
        patch.object(agy_model.subprocess,'Popen',popen).start()
        self.pool=agy_model.Pool(self.cfg)
        patch.object(agy_model,'_pool',self.pool).start()
        self.addCleanup(patch.stopall);self.addCleanup(self.pool.shutdown)

    def fresh_pool(self):
        self.pool.shutdown()
        self.pool=agy_model.Pool(self.cfg);agy_model._pool=self.pool
        self.addCleanup(self.pool.shutdown)


class Protocol(Fake):
    def test_one_turn_returns_validated_json(self):
        self.mode.write_text('plain');self.fresh_pool()
        r=agy_model.invoke(dict(self.cfg,model='chatgpt-g'),'规则X',{'history':[]},ms.DECISION_SCHEMA)
        self.assertEqual(r,{'allowed':True})

    def test_prompt_carries_policy_schema_payload_and_no_tools_notice(self):
        schema=dict(ms.DECISION_SCHEMA,properties={'allowed':{'type':'boolean'},'pid':{'type':'string'}})
        with patch.object(agy_model,'validate',lambda s,r:None):
            r=agy_model.invoke(dict(self.cfg,model='chatgpt-g'),'规则X',{'history':[{'role':'user','content':'你好'}]},schema)
        for part in ('规则X','不要使用任何工具','"allowed":<true 或 false>','你好','不可信'):self.assertIn(part,r['saw'])

    def test_every_process_serves_exactly_one_turn(self):
        cfg=dict(self.cfg,model='chatgpt-g')
        with patch.object(agy_model,'validate',lambda s,r:None):
            pids=[agy_model.invoke(cfg,'p',{},ms.DECISION_SCHEMA) for _ in range(3)]
        self.assertEqual(len({p['pid'] for p in pids}),3)
        self.assertEqual({p['turns'] for p in pids},{1})

    def test_a_ready_process_is_taken_before_one_that_is_still_starting(self):
        class W:
            def __init__(self,ready):
                self.ready=type('E',(),{'is_set':lambda s:ready,'wait':lambda s,t=None:True})();self.dead=False
                self.born=time.monotonic()
            def discard(self):pass
            def kill(self):pass
        ready,starting=W(True),W(False)
        self.pool.idle['m-gate']=[ready,starting]            # the newest entry is the one still starting
        with patch.object(self.pool,'refill',lambda:None):
            self.assertIs(self.pool.acquire('m-gate'),ready)
            self.assertEqual(self.pool.idle['m-gate'],[starting])

    def test_gate_and_answer_use_different_models(self):
        self.assertEqual(agy_model.model_for(dict(self.cfg,model='chatgpt-g')),'m-gate')
        self.assertEqual(agy_model.model_for(dict(self.cfg,model='chatgpt-a')),'m-answer')

    def test_code_fenced_json_is_accepted_and_prose_is_not(self):
        self.assertEqual(agy_model.parse_json('好的：\n```json\n{"a":1}\n```'),{'a':1})
        for bad in ('没有json','{broken'):
            with self.assertRaises(RuntimeError):agy_model.parse_json(bad)

    def test_wrong_shape_is_rejected_by_the_schema_validator(self):
        self.mode.write_text('garbage');self.fresh_pool()
        with self.assertRaises(RuntimeError):agy_model.invoke(dict(self.cfg,model='chatgpt-g'),'p',{},ms.DECISION_SCHEMA)

    def test_a_failed_turn_raises_instead_of_returning_garbage(self):
        self.mode.write_text('error');self.fresh_pool()
        with self.assertRaises(RuntimeError):agy_model.invoke(dict(self.cfg,model='chatgpt-g'),'p',{},ms.DECISION_SCHEMA)

    def test_prose_around_json_is_tolerated_end_to_end(self):
        self.mode.write_text('prose');self.fresh_pool()
        self.assertEqual(agy_model.invoke(dict(self.cfg,model='chatgpt-g'),'p',{},ms.DECISION_SCHEMA),{'allowed':True})

    def test_a_malformed_reply_gets_one_retry_on_a_fresh_process(self):
        self.mode.write_text('flaky');self.fresh_pool()
        self.assertEqual(agy_model.invoke(dict(self.cfg,model='chatgpt-g'),'p',{},ms.DECISION_SCHEMA),{'allowed':True})

    def test_persistent_garbage_is_retried_only_once(self):
        self.mode.write_text('garbage');self.fresh_pool()
        with patch.object(agy_model,'one_attempt',wraps=agy_model.one_attempt) as attempts:
            with self.assertRaises(RuntimeError):agy_model.invoke(dict(self.cfg,model='chatgpt-g'),'p',{},ms.DECISION_SCHEMA)
        self.assertEqual(attempts.call_count,2)

    def test_timeouts_and_errors_are_not_retried(self):
        self.mode.write_text('error');self.fresh_pool()
        with patch.object(agy_model,'one_attempt',wraps=agy_model.one_attempt) as attempts:
            with self.assertRaises(RuntimeError):agy_model.invoke(dict(self.cfg,model='chatgpt-g'),'p',{},ms.DECISION_SCHEMA)
        self.assertEqual(attempts.call_count,1)


class AdaptivePool(Fake):
    def wait_ready(self,n,model='m-gate',timeout=10):
        deadline=time.time()+timeout
        while time.time()<deadline:
            if len([w for w in self.pool.idle.get(model,[]) if w.ready.is_set()])>=n:return True
            time.sleep(.05)
        return False

    def test_it_keeps_the_idle_floor_while_allowing_bounded_bursts(self):
        self.pool.refill()
        self.assertEqual(len(self.pool.idle['m-gate']),1)
        self.assertTrue(self.wait_ready(1))
        w=self.pool.acquire('m-gate')
        self.assertTrue(self.wait_ready(1))
        self.assertEqual(self.pool.target['m-gate'],1)
        self.assertLessEqual(self.pool._running('m-gate'),3)
        w.discard()

    def test_empty_pool_expands_reserve_within_cap_then_shrinks(self):
        self.pool.refill()
        self.assertTrue(self.wait_ready(1))
        first=self.pool.acquire('m-gate')
        with self.pool.lock:
            for warm in self.pool.idle['m-gate']:warm.discard()
            self.pool.idle['m-gate']=[]
            second=self.pool.acquire('m-gate')
        self.assertEqual(self.pool.target['m-gate'],3)
        first.discard();second.discard()
        self.assertTrue(self.wait_ready(3))
        self.assertLessEqual(self.pool._running('m-gate'),3)
        self.pool.last_use=time.monotonic()-61
        with self.pool.lock:self.pool._shrink()
        self.assertEqual(self.pool.target['m-gate'],1)
        self.assertEqual(len(self.pool.idle['m-gate']),1)

    def test_it_gives_the_memory_back_after_the_idle_period(self):
        # A previous/manual higher idle target is still trimmed when quiet.
        self.pool.target['m-gate']=3;self.pool.refill()
        self.assertTrue(self.wait_ready(3))
        self.pool.idle_seconds=0;self.pool.last_use=time.monotonic()-5
        with self.pool.lock:self.pool._shrink()
        self.assertEqual(len(self.pool.idle['m-gate']),1)
        self.assertEqual(self.pool.target['m-gate'],1)

    def test_it_does_not_shrink_while_busy(self):
        self.pool.target['m-gate']=3;self.pool.refill()
        self.assertTrue(self.wait_ready(3))
        self.pool.idle_seconds=300;self.pool.last_use=time.monotonic()
        with self.pool.lock:self.pool._shrink()
        self.assertEqual(len(self.pool.idle['m-gate']),3)

    def test_the_idle_size_never_exceeds_the_configured_size(self):
        cfg=dict(self.cfg,agy_pool={'only':1},agy_pool_min=5)
        p=agy_model.Pool(cfg);self.addCleanup(p.shutdown)
        self.assertEqual(p.target,{'only':1})


class PrivateWorkDirs(Fake):
    def test_each_process_gets_its_own_private_directory_that_is_removed_afterwards(self):
        self.mode.write_text('files');self.fresh_pool()
        with patch.object(agy_model,'validate',lambda s,r:None):
            r=agy_model.invoke(dict(self.cfg,model='chatgpt-g'),'p',{},ms.DECISION_SCHEMA)
        self.assertEqual(r['files'],[])                                    # nothing in the workspace for a text turn
        used=Path(self.workdirs[0])
        self.assertEqual(oct(os.stat(used.parent).st_mode&0o777),'0o700')
        deadline=time.time()+10
        while time.time()<deadline and used.exists():time.sleep(.1)
        self.assertFalse(used.exists())

    def test_images_are_written_into_that_directory_only(self):
        self.mode.write_text('files');self.fresh_pool()
        with patch.object(agy_model,'validate',lambda s,r:None):
            r=agy_model.invoke(dict(self.cfg,model='chatgpt-g'),'p',{},ms.DECISION_SCHEMA,images=[PNG,PNG])
        self.assertEqual(r['files'],['image1.png','image2.png'])

    def test_image_prompt_allows_only_viewing_those_files(self):
        text=agy_model.build_prompt('规则',{},ms.DESCRIBE_SCHEMA,image_names=['image1.png'])
        self.assertIn('只允许用 view_file 或 read_file 图片读取工具',text)
        self.assertIn('/work/image1.png',text)
        self.assertIn('不要读别的文件',text)
        for banned in ('不要读别的文件','不执行命令','不联网','不生成图片'):self.assertIn(banned,text)
        self.assertNotIn('search_web',text)

    def test_a_non_png_or_oversized_image_is_refused(self):
        self.fresh_pool()
        warm=self.pool.acquire('m-gate');self.addCleanup(warm.kill)
        for bad in (base64.b64encode(b'not an image').decode(),base64.b64encode(b'\x89PNG'+b'x'*(agy_model.MAX_IMAGE_BYTES+1)).decode()):
            with self.assertRaises(RuntimeError):warm.put_images([bad])

    def test_leftover_directories_from_a_crash_are_removed_at_start(self):
        root=Path(self.cfg['agy_work_root']);root.mkdir(parents=True,exist_ok=True)
        gone=RealPopen([sys.executable,'-c','pass']);gone.wait()
        (root/('w%d-old'%gone.pid)).mkdir();(root/('w%d-old'%gone.pid)/'image1.png').write_bytes(b'old chat image')
        (root/'w-legacy').mkdir()
        p=agy_model.Pool(self.cfg);self.addCleanup(p.shutdown)
        self.assertFalse((root/('w%d-old'%gone.pid)).exists());self.assertFalse((root/'w-legacy').exists())

    def test_a_running_instances_directories_are_never_touched(self):
        root=Path(self.cfg['agy_work_root']);root.mkdir(parents=True,exist_ok=True)
        mine=root/('w%d-live'%os.getpid());mine.mkdir();(mine/'image1.png').write_bytes(b'in use')
        other=RealPopen([sys.executable,'-c','import time;time.sleep(30)']);self.addCleanup(lambda:(other.kill(),other.wait()))
        theirs=root/('w%d-live'%other.pid);theirs.mkdir()
        p=agy_model.Pool(self.cfg);self.addCleanup(p.shutdown)       # a second pool starting up must not wipe these
        self.assertTrue(mine.exists());self.assertTrue(theirs.exists())


class LeakProof(Fake):
    """The pool must never leave a running sandbox without an owner, even when the machine is out of processes."""
    def workdir_count(self):
        return len(list(Path(self.cfg['agy_work_root']).iterdir()))

    def test_a_thread_that_cannot_start_does_not_leave_a_sandbox_running(self):
        with patch.object(agy_model.threading.Thread,'start',side_effect=RuntimeError("can't start new thread")):
            with self.assertRaises(RuntimeError):agy_model.Warm(self.cfg,'m-gate')
        self.assertEqual(len(self.procs),1)
        self.assertIsNotNone(self.procs[0].poll())                         # the process that did start is gone
        self.assertEqual(self.workdir_count(),0)

    def test_a_process_that_cannot_be_forked_leaves_nothing_behind(self):
        import errno
        before=self.workdir_count()
        with patch.object(agy_model.subprocess,'Popen',side_effect=OSError(errno.EAGAIN,'Resource temporarily unavailable')):
            with self.assertRaises(OSError):agy_model.Warm(self.cfg,'m-gate')
        self.assertEqual(self.workdir_count(),before)

    def test_discard_still_works_when_no_thread_can_be_started(self):
        warm=agy_model.Warm(self.cfg,'m-gate');self.assertTrue(warm.ready.wait(10))
        with patch.object(agy_model.threading.Thread,'start',side_effect=RuntimeError("can't start new thread")):
            warm.discard()
        self.assertIsNotNone(self.procs[-1].poll());self.assertFalse(Path(warm.workdir).exists())

    def test_the_reaper_kills_a_process_held_too_long_but_not_a_recent_one(self):
        old=self.pool._spawn('m-gate');recent=self.pool._spawn('m-gate')
        self.assertTrue(old.ready.wait(10) and recent.ready.wait(10))
        now=time.monotonic()
        old.taken_at=now-agy_model.REAP_AFTER-5;recent.taken_at=now-5
        with self.pool.lock:self.pool._reap()
        self.assertIsNotNone(self.procs[-2].poll());self.assertTrue(old.dead)
        self.assertIsNone(self.procs[-1].poll());self.assertFalse(recent.dead)
        self.assertNotIn(old,self.pool.live);self.assertIn(recent,self.pool.live)
        recent.kill()

    def test_a_pool_stuck_at_its_limit_complains_once_a_minute_and_leaks_nothing(self):
        import errno
        before=self.workdir_count()
        with patch.object(agy_model.subprocess,'Popen',side_effect=OSError(errno.EAGAIN,'x')),\
             patch.object(agy_model.logging,'warning') as warn:
            for _ in range(5):self.pool.refill()
        self.assertEqual(warn.call_count,1)
        self.assertEqual(self.workdir_count(),before)

    def test_shutdown_leaves_no_process_and_no_registry_entry(self):
        for _ in range(2):self.pool._spawn('m-gate')
        self.pool.shutdown()
        self.assertTrue(all(p.poll() is not None for p in self.procs));self.assertEqual(self.pool.live,set())


class ThreadFootprint(unittest.TestCase):
    def test_go_is_limited_to_two_cpus_so_each_sandbox_opens_fewer_threads(self):
        cmd=agy_model.sandbox_command({'network_guard_bin':'/x','agy_bin':'/x/agy'},'m',9,'/w')
        i=cmd.index('GOMAXPROCS');self.assertEqual(cmd[i-1],'--setenv');self.assertEqual(cmd[i+1],'2')
        cmd=agy_model.sandbox_command({'network_guard_bin':'/x','agy_bin':'/x/agy','agy_gomaxprocs':4},'m',9,'/w')
        self.assertEqual(cmd[cmd.index('GOMAXPROCS')+1],'4')


class SearchPrompt(unittest.TestCase):
    def test_search_calls_allow_only_the_search_tool(self):
        plain=agy_model.build_prompt('规则',{},ms.DECISION_SCHEMA)
        search=agy_model.build_prompt('规则',{},ms.DECISION_SCHEMA,search=True)
        self.assertIn('不要使用任何工具',plain);self.assertNotIn('search_web',plain)
        self.assertIn('只允许使用联网搜索工具 search_web',search)
        for banned in ('不读写文件','不执行命令','不抓取具体网址','不生成图片'):self.assertIn(banned,search)
        self.assertIn('不要提到 Antigravity',search)

    def test_search_gets_a_longer_turn_timeout(self):
        self.assertGreater(agy_model.SEARCH_TURN_TIMEOUT,agy_model.TURN_TIMEOUT)


class Routing(unittest.TestCase):
    CFG={'backend':'agy','model':'a','gate_model':'g','agy_model':'x','agy_gate_model':'y'}

    def test_text_calls_use_antigravity(self):
        backend.stats.update(agy=0,fallback=0,other=0)
        with patch.object(agy_model,'invoke',return_value={'allowed':True}) as a,patch.object(fast_model,'invoke') as f:
            self.assertEqual(backend.invoke(self.CFG,'p',{},ms.DECISION_SCHEMA),{'allowed':True})
        a.assert_called_once();f.assert_not_called();self.assertEqual(backend.stats['agy'],1)

    def test_images_and_search_both_go_to_antigravity_now(self):
        with patch.object(agy_model,'invoke',return_value={'description':'x'}) as a,patch.object(fast_model,'invoke') as f:
            backend.invoke(self.CFG,'p',{},ms.DESCRIBE_SCHEMA,images=['AAA'])
            backend.invoke(self.CFG,'p',{},ms.REPLY_SCHEMA,search=True)
        f.assert_not_called();self.assertEqual(a.call_count,2)
        self.assertEqual(a.call_args_list[0].kwargs['images'],['AAA'])
        self.assertTrue(a.call_args_list[1].kwargs['search'])

    def test_an_image_call_falls_back_with_its_images(self):
        with patch.object(agy_model,'invoke',side_effect=RuntimeError('AGY_TIMEOUT')),\
             patch.object(fast_model,'invoke',return_value={'description':'x'}) as f:
            backend.invoke(dict(self.CFG,agy_fallback=True),'p',{},ms.DESCRIBE_SCHEMA,images=['AAA'])
        self.assertEqual(f.call_args.kwargs['images'],['AAA'])

    def test_other_backend_setting_never_touches_antigravity(self):
        with patch.object(agy_model,'invoke') as a,patch.object(fast_model,'invoke',return_value={'allowed':True}):
            backend.invoke(dict(self.CFG,backend='chatgpt'),'p',{},ms.DECISION_SCHEMA)
        a.assert_not_called()

    def test_failure_falls_back_and_is_counted(self):
        backend.stats.update(agy=0,fallback=0,other=0)
        with patch.object(agy_model,'invoke',side_effect=RuntimeError('AGY_TIMEOUT')),\
             patch.object(fast_model,'invoke',return_value={'allowed':False}) as f:
            self.assertEqual(backend.invoke(dict(self.CFG,agy_fallback=True),'p',{},ms.DECISION_SCHEMA),{'allowed':False})
        f.assert_called_once();self.assertEqual(backend.stats['fallback'],1)

    def test_fallback_is_off_by_default(self):
        # The unofficial backend is used only when the operator opts in explicitly.
        with patch.object(agy_model,'invoke',side_effect=RuntimeError('AGY_TIMEOUT')),patch.object(fast_model,'invoke') as f:
            with self.assertRaises(RuntimeError) as caught:backend.invoke(self.CFG,'p',{},ms.DECISION_SCHEMA)
        self.assertEqual(str(caught.exception),'AGY_FAILED')
        f.assert_not_called()

    def test_fallback_can_be_disabled(self):
        with patch.object(agy_model,'invoke',side_effect=RuntimeError('AGY_TIMEOUT')),patch.object(fast_model,'invoke') as f:
            with self.assertRaises(RuntimeError):backend.invoke(dict(self.CFG,agy_fallback=False),'p',{},ms.DECISION_SCHEMA)
        f.assert_not_called()


class SandboxShape(unittest.TestCase):
    def setUp(self):
        self.cmd=agy_model.sandbox_command({'network_guard_bin':'/x/net-guard','agy_bin':'/x/agy'},'gemini-3.8-flash-low',9,'/run/work-1')

    def test_no_host_directory_is_visible(self):
        joined=' '.join(self.cmd)
        self.assertNotIn(str(Path.home())+' ',joined)
        self.assertNotIn(' --bind / ',joined)
        binds=[(self.cmd[i+1],self.cmd[i+2]) for i,x in enumerate(self.cmd) if x=='--bind']
        bus='/run/user/%d/bus'%os.getuid()
        self.assertEqual(binds,[('/run/work-1','/work'),(bus,bus)])         # own scratch dir + the login keyring bus only
        for flag in ('--unshare-user','--unshare-pid','--unshare-ipc','--clearenv','--die-with-parent'):self.assertIn(flag,self.cmd)
        self.assertIn('--tmpfs',self.cmd)                                    # empty home and /tmp

    def test_outbound_is_limited_by_the_network_guard_and_cwd_is_the_scratch_dir(self):
        self.assertEqual(self.cmd[self.cmd.index('--chdir')+1],'/work')
        i=len(self.cmd)-1-self.cmd[::-1].index('/opt/net-guard');self.assertEqual(self.cmd[i+1],'/opt/agy')   # guard wraps the CLI
        self.assertIn('stream-json',self.cmd)


if __name__=='__main__':unittest.main()
