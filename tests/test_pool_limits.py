import concurrent.futures,queue,sys,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import agy_model as agy
import test_agy_backend as fixtures


class PoolLimits(fixtures.Fake):
    def test_busy_sessions_are_counted_in_the_ceiling(self):
        held=[self.pool.acquire('m-gate') for _ in range(3)]
        self.addCleanup(lambda:[w.kill() for w in held])
        self.pool.refill()
        self.assertEqual(self.pool._running('m-gate'),3)
        with concurrent.futures.ThreadPoolExecutor(1) as executor:
            request=executor.submit(self.pool.acquire,'m-gate')
            time.sleep(.05);self.assertFalse(request.done())
            held[0].kill()
            next_warm=request.result(timeout=3);self.addCleanup(next_warm.kill)
            self.assertLessEqual(self.pool._running('m-gate'),3)

    def test_cap_is_respected_under_simultaneous_demand(self):
        peak=[];seen=set();guard=threading.Lock()
        def use(_):
            w=self.pool.acquire('m-gate')
            try:
                with self.pool.lock:count=self.pool._running('m-gate')
                with guard:peak.append(count);seen.add(w.proc.pid)
                time.sleep(.03)
            finally:w.discard()
        with concurrent.futures.ThreadPoolExecutor(8) as executor:list(executor.map(use,range(18)))
        self.assertLessEqual(max(peak),3)
        self.assertEqual(len(seen),18)  # still exactly one session per caller

    def test_shutdown_stops_maintenance_and_cannot_restart_pool(self):
        self.pool.refill();self.pool.shutdown()
        self.assertFalse(self.pool.maintainer.is_alive())
        before=len(self.procs);self.pool.refill();self.pool.wakeup.set();time.sleep(.02)
        self.assertEqual(len(self.procs),before)
        self.assertTrue(all(p.poll() is not None for p in self.procs))
        with self.assertRaisesRegex(RuntimeError,'AGY_POOL_CLOSED'):self.pool.acquire('m-gate')

    def test_repeated_acquires_do_not_spawn_refill_threads(self):
        self.pool.refill()
        for _ in range(5):
            w=self.pool.acquire('m-gate');w.discard()
        maintain=[t for t in threading.enumerate() if t is self.pool.maintainer]
        self.assertEqual(len(maintain),1)
        self.assertLessEqual(self.pool.target['m-gate'],self.pool._limit('m-gate'))

    def test_stream_pipes_are_closed_when_killed(self):
        w=self.pool.acquire('m-gate');w.kill()
        if w.pump:w.pump.join(timeout=1)
        self.assertTrue(w.proc.stdin.closed);self.assertTrue(w.proc.stdout.closed)

    def test_event_flood_does_not_override_turn_deadline(self):
        w=self.pool.acquire('m-gate')
        # Ignore writes; an endless supply of non-result events used to bypass
        # the timeout because queue.get() never had a chance to time out.
        class Flood:
            def put(self,event):pass
            def get(self,timeout=None):return {'event':'delta'}
        w.events=Flood()
        with self.assertRaisesRegex(RuntimeError,'AGY_TIMEOUT'):w.turn('test',timeout=.01)
        w.kill()

    def test_metrics_report_physical_sessions_and_bounded_high_water_mark(self):
        self.pool.refill()
        held=[self.pool.acquire('m-gate') for _ in range(3)]
        self.addCleanup(lambda:[w.kill() for w in held])
        metrics=self.pool.metrics()
        self.assertEqual(metrics['live_sessions'],sum(w.proc.poll() is None for w in self.pool.live))
        self.assertGreaterEqual(metrics['peak_live_sessions'],3)
        self.assertLessEqual(self.pool._running('m-gate'),3)
        self.assertFalse(metrics['closed'])
        self.pool.shutdown();self.assertTrue(self.pool.metrics()['closed'])
        self.assertEqual(self.pool.metrics()['live_sessions'],0)

    def test_shutdown_wakes_waiters_without_starting_replacement(self):
        held=[self.pool.acquire('m-gate') for _ in range(3)]
        with concurrent.futures.ThreadPoolExecutor(1) as executor:
            waiting=executor.submit(self.pool.acquire,'m-gate')
            time.sleep(.03);self.assertFalse(waiting.done())
            self.pool.shutdown()
            with self.assertRaisesRegex(RuntimeError,'AGY_POOL_CLOSED'):waiting.result(timeout=2)
        self.assertTrue(all(p.poll() is not None for p in self.procs))
