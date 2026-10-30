"""Safety net against messages that were read but never answered.

The normal path classifies every new row it believes it has found. Anything that never went through that
path (a window reset the matcher could not follow, a scroll, a restart in the middle of a send) is invisible to
it: the row simply sits in the chat as "already read". This module remembers which rows the normal path decided
about and, on every later read, reports directed rows that were never decided about and have no reply after them.
"""
import re
import hashlib
import unicodedata
from collections import Counter


# Status lines the bot posts while a slow answer is being worked on; they are not answers (see worker.PROGRESS_*).
PROGRESS_NOTE=re.compile(r'这题有点难，我认真算|收到，这个要多想|这题得推导一遍|这题得好好想想|有点难度，容本喵|等会，这题要多想|'
                         r'思路有了，正在写|算完了，正在整理|想出来了，正在写|算完了，在整理|还在推，已经|还在算，已经')


def is_answer(row):
    return bool(row.get('outgoing')) and not PROGRESS_NOTE.search(row.get('text',''))


def row_key(row):
    text=''.join(unicodedata.normalize('NFKC',row.get('text','')).split())
    return hashlib.sha1(((row.get('sig') or '')+'|'+text).encode()).hexdigest()[:16]


class Auditor:
    def __init__(self,grace=20.0,lookahead=12,hourly_limit=6):
        self.handled=Counter()
        self.first_seen={}
        self.started=False
        self.grace=grace
        self.lookahead=lookahead
        self.hourly_limit=hourly_limit
        self.recovered_at=[]
        self.recovered_total=0

    def mark(self,rows):
        """These rows went through the normal decision path (answered, deliberately skipped, or just context)."""
        for row in rows:
            if not row.get('outgoing'):self.handled[row_key(row)]+=1

    def find_missed(self,rows,now,is_directed):
        seen=Counter(row_key(r) for r in rows if not r.get('outgoing'))
        unhandled={k:n-self.handled[k] for k,n in seen.items() if n>self.handled[k]}
        self.first_seen={k:t for k,t in self.first_seen.items() if k in unhandled}
        missed=[]
        for index in range(len(rows)-1,-1,-1):                       # newest occurrences are the unhandled ones
            row=rows[index]
            if row.get('outgoing'):continue
            key=row_key(row)
            if unhandled.get(key,0)<=0:continue
            unhandled[key]-=1
            if any(is_answer(r) for r in rows[index+1:index+1+self.lookahead]):continue   # answered
            if not is_directed(row):
                self.handled[key]+=1;continue                       # not for the bot: nothing to recover
            self.first_seen.setdefault(key,now)
            if now-self.first_seen[key]<self.grace:continue
            missed.append(row)
        self.recovered_at=[t for t in self.recovered_at if now-t<3600]
        room=max(0,self.hourly_limit-len(self.recovered_at))
        return list(reversed(missed))[:room]

    def recovered(self,rows,now):
        self.mark(rows)
        self.recovered_at+=[now]*len(rows)
        self.recovered_total+=len(rows)
