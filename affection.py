"""The catgirl's 好感度 towards each chat member: -100..100, starting at 50, saved as JSON."""
import json
import os
from pathlib import Path

INITIAL=50
STEP={'positive':5,'neutral':0,'negative':-5}


class AffectionBook:
    def __init__(self,path):
        self.path=Path(path)
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            self.values={k:int(v) for k,v in data.items() if isinstance(k,str) and isinstance(v,int)}
        except (OSError,ValueError,AttributeError,TypeError):
            self.values={}

    def get(self,key):
        return self.values.get(key,INITIAL)

    def apply(self,key,mood):
        """Move the value by the turn's mood and keep it within -100..100."""
        if mood not in STEP or not key:return self.get(key)
        value=max(-100,min(100,self.get(key)+STEP[mood]))
        self.values[key]=value
        tmp=self.path.with_suffix('.tmp')
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(self.values,f,ensure_ascii=False)
        tmp.replace(self.path)
        return value
