import re,sys,types,unittest
from pathlib import Path
src=(Path(__file__).resolve().parents[1]/'transport.py').read_text()
# transport needs GI/X11 at import; take just the two helpers
a=src.index('SEND_FAILED_ROW');b=src.index('def send_image')
ns={'re':re};exec(src[a:b],ns)


class SendFailed(unittest.TestCase):
    def test_new_failure_row_is_detected(self):
        before=[{'text':'hi'}]
        self.assertFalse(ns['send_failed'](before,before+[{'text':'Image'}]))
        self.assertTrue(ns['send_failed'](before,before+[{'text':'Image'},{'text':'Unable to send Image'}]))
        self.assertTrue(ns['send_failed'](before,before+[{'text':'发送失败'}]))

    def test_old_failure_rows_do_not_count_again(self):
        old=[{'text':'Unable to send Image'}]
        self.assertFalse(ns['send_failed'](old,old+[{'text':'Image'}]))

if __name__=='__main__':unittest.main()
