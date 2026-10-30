import ast,unittest
from pathlib import Path

p=Path(__file__).resolve().parents[1]/'transport.py'
tree=ast.parse(p.read_text());scope={}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='confirmed_image_send'],type_ignores=[]),str(p),'exec'),scope)
confirmed=scope['confirmed_image_send']


def row(text,direction='incoming'):return {'text':text,'direction':direction,'outgoing':direction=='outgoing'}


class ImageSendConfirmation(unittest.TestCase):
    def test_equal_visible_image_count_still_confirms_new_image_after_text(self):
        before=[row('Image'),row('这条是刚发的回复','outgoing')]
        after=[row('这条是刚发的回复','outgoing'),row('Image','outgoing')]
        self.assertTrue(confirmed(before,after))

    def test_user_messages_arriving_after_image_do_not_hide_confirmation(self):
        self.assertTrue(confirmed([row('已发文字','outgoing')],[row('已发文字','outgoing'),row('Image','outgoing'),row('群友新消息')]))

    def test_incoming_unknown_and_old_outgoing_images_are_not_confirmation(self):
        for direction in ('incoming','unknown'):
            self.assertFalse(confirmed([row('文字','outgoing')],[row('文字','outgoing'),row('Image',direction)]))
        self.assertFalse(confirmed([row('Image','outgoing')],[row('Image','outgoing')]))
        self.assertFalse(confirmed([row('Image','outgoing'),row('文字','outgoing')],[row('Image','outgoing'),row('文字','outgoing')]))

    def test_consecutive_images_require_count_growth(self):
        self.assertTrue(confirmed([row('Image','outgoing')],[row('Image','outgoing'),row('Image','outgoing')]))

    def test_duplicate_or_lost_anchor_does_not_confirm_same_count(self):
        before=[row('Image','outgoing'),row('相同文字','outgoing')]
        self.assertFalse(confirmed(before,[row('相同文字'),row('相同文字'),row('Image','outgoing')]))
        self.assertFalse(confirmed(before,[row('别人文字'),row('Image','outgoing')]))
