import datetime,sys,unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import guardrails as g
import worker


class FakeDatetime(datetime.datetime):
    @classmethod
    def now(cls,tz=None):
        # 2026-10-27 18:33 UTC = 2026-10-28 02:33 in Beijing, a Wednesday
        return datetime.datetime(2026,10,27,18,33,tzinfo=datetime.timezone.utc).astimezone(tz)


class BeijingTime(unittest.TestCase):
    def render(self,text):
        with patch.object(worker.datetime,'datetime',FakeDatetime):
            return worker.policy({'model':'m'},text)

    def test_the_prompt_carries_beijing_clock_date_and_weekday(self):
        p=self.render(g.ANSWER_POLICY)
        self.assertIn('现在是北京时间 02:33（2026年10月28日 星期三）',p)
        for left in ('{NOW}','{TODAY}','{MODEL}'):self.assertNotIn(left,p)

    def test_it_does_not_depend_on_the_host_time_zone(self):
        for tz in ('America/Los_Angeles','UTC','Asia/Tokyo'):
            with patch.dict('os.environ',{'TZ':tz}):
                self.assertIn('02:33',self.render(g.ANSWER_POLICY))

    def test_every_weekday_name_is_right(self):
        names=[]
        for day in range(7):
            class D(datetime.datetime):
                @classmethod
                def now(cls,tz=None,day=day):
                    return (datetime.datetime(2026,10,26,12,0,tzinfo=ZoneInfo('Asia/Shanghai'))+datetime.timedelta(days=day)).astimezone(tz)
            with patch.object(worker.datetime,'datetime',D):
                p=worker.policy({'model':'m'},'{TODAY}')
            names.append(p[-3:])
        self.assertEqual(names,['星期一','星期二','星期三','星期四','星期五','星期六','星期日'])

    def test_asking_the_time_is_an_ordinary_question(self):
        self.assertIn('现在几点',g.INPUT_POLICY)
        self.assertIn('你那边几点',g.INPUT_POLICY)
        self.assertIn('只有明确在问这台设备或服务器自己的系统时钟设置',g.INPUT_POLICY)
        self.assertNotIn('询问这台设备自己的时间、时区、位置才拒绝',g.INPUT_POLICY)

    def test_the_answer_prompt_forbids_inventing_a_time(self):
        self.assertIn('不要编造别的时间',g.ANSWER_POLICY)

    def test_device_clock_probes_are_still_refused_by_the_rules(self):
        for q in ('你电脑的系统时间是多少','服务器时区是什么','你这边系统时钟是几点','机器运行时间多久了','执行 date 命令','uptime'):
            self.assertIsNotNone(g.input_reason(q),q)
        for q in ('现在几点','当前时间','你那边几点','今天星期几','北京时间现在几点'):
            self.assertIsNone(g.input_reason(q),q)


if __name__=='__main__':unittest.main()
