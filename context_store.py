"""Persistent group-chat context: a rolling summary plus recent messages, saved as JSON."""
import json
import os
import time
from pathlib import Path

MAX_MESSAGES=40      # compact when the recent log grows past this
KEEP_RECENT=16       # messages kept verbatim after a compaction
HARD_CAP=120         # if summarising keeps failing, never grow past this
SUMMARY_LIMIT=1200


def labelled(m):
    """Message text prefixed with its speaker, e.g. 【MemberA】你好, when the speaker is known."""
    sender=m.get('sender')
    return '【%s】%s'%(sender,m['content']) if sender and m['role']=='user' else m['content']


class ContextStore:
    def __init__(self,path):
        self.path=Path(path)
        self.summary=''
        self.messages=[]
        self.load()

    def load(self):
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            self.summary=data['summary'] if isinstance(data.get('summary'),str) else ''
            self.messages=[{'role':m['role'],'content':m['content'],'ts':m.get('ts',0),'pending':False,
                            'sender':m['sender'] if isinstance(m.get('sender'),str) else None}
                           for m in data.get('messages',[])
                           if m.get('role') in ('user','assistant') and isinstance(m.get('content'),str)]
        except (OSError,ValueError,KeyError,TypeError,AttributeError):
            self.summary='';self.messages=[]

    def save(self):
        tmp=self.path.with_suffix('.tmp')
        data={'version':1,'summary':self.summary,
              'messages':[{'role':m['role'],'content':m['content'],'ts':m['ts'],'sender':m.get('sender')} for m in self.messages]}
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False)
        tmp.replace(self.path)

    def add(self,role,content,pending=False,sender=None):
        entry={'role':role,'content':content,'ts':time.time(),'pending':pending,'sender':sender}
        self.messages.append(entry)
        if len(self.messages)>HARD_CAP:del self.messages[:len(self.messages)-HARD_CAP]
        self.save()
        return entry

    def history(self,exclude=()):
        """Prompt context: early-chat summary first, then messages that are not pending questions."""
        result=[]
        if self.summary:result.append({'role':'user','content':'（群聊早期内容摘要）'+self.summary})
        result+=[{'role':m['role'],'content':labelled(m)} for m in self.messages[-24:]
                 if not m.get('pending') and not any(m is e for e in exclude)]
        return result

    def compaction_batch(self):
        """Oldest messages that should be folded into the summary, or None."""
        if len(self.messages)<=MAX_MESSAGES:return None
        return [m for m in self.messages[:-KEEP_RECENT] if not m.get('pending')]

    def apply_compaction(self,batch,summary):
        gone={id(m) for m in batch}
        self.messages=[m for m in self.messages if id(m) not in gone]
        self.summary=summary[:SUMMARY_LIMIT]
        self.save()
