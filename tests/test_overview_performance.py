"""Exercise bridge tree pruning without an X server or GI dependencies."""
import ast, pathlib, types, unittest


def bridge_functions(root):
    source=pathlib.Path(__file__).resolve().parents[1]/'transport.py'
    tree=ast.parse(source.read_text())
    selected=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('walk','unlocked','overview')],type_ignores=[])
    scope={'visible':lambda n:n.shown,'app':lambda:root}
    exec(compile(selected,str(source),'exec'),scope)
    return scope


class Node:
    def __init__(self,role,name='',children=(),shown=True):
        self.role=role;self.name=name;self.children=list(children);self.shown=shown;self.child_reads=0
    def get_role_name(self):return self.role
    def get_name(self):return self.name
    def get_child_count(self):return len(self.children)
    def get_child_at_index(self,i):self.child_reads+=1;return self.children[i]


class Overview(unittest.TestCase):
    def test_reads_all_chat_previews_without_visiting_chat_or_message_descendants(self):
        preview=Node('list item','A\nhello\n09:00',[Node('label','deep preview')])
        messages=Node('list','Messages',[Node('list item','text',[Node('text','deep')]) for _ in range(100)])
        chats=Node('list','Chats',[preview,Node('list item','B\nImage\n09:01')])
        root=Node('application','wechat',[Node('frame','WeChat',[chats,messages])])
        out=bridge_functions(root)['overview']()
        self.assertEqual(out,{'ok':True,'logged_in':True,'locked':False,'chats':{'A':'A\nhello\n09:00','B':'B\nImage\n09:01'}})
        self.assertEqual(messages.child_reads,0)
        self.assertEqual(preview.child_reads,0)
        self.assertEqual(chats.child_reads,2)

    def test_actual_lock_outside_message_list_is_still_detected(self):
        root=Node('application','wechat',[Node('list','Chats'),Node('label','WeChat is locked')])
        self.assertTrue(bridge_functions(root)['overview']()['locked'])

    def test_chat_text_cannot_fake_lock_screen(self):
        root=Node('application','wechat',[Node('list','Chats'),Node('list','Messages',[Node('list item','WeChat is locked')])])
        self.assertFalse(bridge_functions(root)['overview']()['locked'])

    def test_login_screen_and_chinese_labels(self):
        for label in ('Chats','会话'):
            root=Node('application','wechat',[Node('list',label,[Node('list item','A\n预览')])])
            self.assertTrue(bridge_functions(root)['overview']()['logged_in'])
        self.assertFalse(bridge_functions(Node('application','wechat',[Node('label','Log In')]))['overview']()['logged_in'])

    def test_default_walk_still_includes_messages_for_snapshot_and_send(self):
        message=Node('list item','question');root=Node('list','Messages',[message]);scope=bridge_functions(root)
        self.assertIn(message,list(scope['walk'](root)))

    def test_hidden_and_depth_limits_remain(self):
        scope=bridge_functions(Node('application','wechat'))
        self.assertEqual(list(scope['walk'](Node('list','Chats',shown=False))),[])
        self.assertEqual(list(scope['walk'](Node('label','x'),depth=41)),[])
