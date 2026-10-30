import importlib.util
import unittest
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).parents[1]))
spec=importlib.util.spec_from_file_location('worker',Path(__file__).parents[1]/'worker.py')
worker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class CursorTests(unittest.TestCase):
    def test_append_only_new_messages(self):
        a=[('old',False)]
        self.assertEqual(worker.new_rows(a,a+[('new',False)]),[('new',False)])

    def test_scrolled_window_overlap(self):
        a=[('one',False),('two',False)]
        b=[('two',False),('three',False)]
        self.assertEqual(worker.new_rows(a,b),[('three',False)])

    def test_identical_consecutive_messages(self):
        a=[('hi',False)]
        self.assertEqual(worker.new_rows(a,a+a),a)

    def test_unrelated_window_does_not_replay_history(self):
        self.assertEqual(worker.new_rows([('old',False)],[('other',False)]),[])

    def test_own_reply_is_part_of_cursor(self):
        a=[('question',False)]
        b=a+[('reply',True),('next question',False)]
        self.assertEqual(worker.new_rows(a,b),b[1:])

    def test_recall_and_reflow_do_not_swallow_new_tail(self):
        anchor=('老子慢你妈呢，天天盯着进度条当考勤打卡。',True)
        old=[('Image',False),('旧消息',False),anchor]
        question=('给你个任务，今天把剩下的额度用完@Legacy Bot\u2005',False)
        after=[('更早的消息',False),('某人撤回了一条消息',False),anchor,question]
        self.assertEqual(worker.new_rows(old,after),[question])
        self.assertEqual(worker.new_rows(after,after),[])
        self.assertEqual(worker.new_rows(old,after[:-1]),[])

    def test_typographic_normalization_preserves_raw_new_message(self):
        old=[('已经说过的长问题，接下来该怎么办？',False)]
        question=('@Legacy Bot 继续？',False)
        after=[('已经说过的长问题,接下来该怎么办?',False),question]
        self.assertEqual(worker.new_rows(old,after),[question])

    def test_short_repeated_or_direction_changed_anchor_is_not_evidence(self):
        anchor=('这是一条足够长的旧消息用来区分窗口',True)
        for before,after in [([('好',False)],[('earlier',False),('好',False),('new',False)]),
                             ([anchor,anchor],[('earlier',False),anchor,('new',False)]),
                             ([anchor],[anchor,anchor,('new',False)]),
                             ([anchor],[('earlier',False),(anchor[0],False),('new',False)])]:
            # Duplicate exact prefixes still follow the existing overlap rule;
            # this test exercises only non-prefix, ambiguous fallback windows.
            if after[0]==anchor:after=[('earlier',False)]+after
            self.assertEqual(worker.new_rows(before,after),[])

    def test_own_messages_do_not_loop(self):
        self.assertEqual(worker.incoming_text([('@bot hello',True),('@bot again',True)],['bot']),[])

    def test_only_mentions_are_answered(self):
        rows=[('hello',False),('@Legacy\u2005Bot 你好',False),('@Legacy Bot 1+1?',False),('@别人 你好',False),('/ai hi',False),('@Legacy Bot',False)]
        self.assertEqual(worker.incoming_text(rows,['Legacy Bot']),['你好','1+1?',worker.MENTION_ONLY])

    def test_everything_is_context_but_only_addressed_messages_trigger(self):
        A=['Legacy Bot','角色乙']
        rows=[('大家吃饭吗',False),('LegacyBot 你觉得呢',False),('昨天角色乙来了',False),('@Legacy Bot 好',False),('Image',False)]
        got=worker.classify_rows(rows,['Legacy Bot'],A)
        self.assertEqual(got,[('大家吃饭吗',False),('LegacyBot 你觉得呢',True),('昨天角色乙来了',False),('好',True)])

    def test_no_mention_names_means_silence(self):
        self.assertEqual(worker.incoming_text([('hello',False)]),[])

    def test_model_has_no_execution_or_connected_app_tools(self):
        from model_sandbox import client_args
        command=client_args('Test policy')
        for feature in ['shell_tool','apps','multi_agent','computer_use','browser_use','hooks']:
            position=command.index(feature)
            self.assertEqual(command[position-1],'--disable')
        self.assertIn('--ignore-user-config',command)
        self.assertIn('read-only',command)


if __name__=='__main__':unittest.main()
