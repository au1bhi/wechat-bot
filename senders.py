"""Remember which nickname belongs to which on-screen name fingerprint."""
import json
import os
from pathlib import Path


class SenderBook:
    def __init__(self,path):
        self.path=Path(path)
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            self.names={k:v for k,v in data.items() if isinstance(k,str) and isinstance(v,str)}
        except (OSError,ValueError,AttributeError):
            self.names={}

    def get(self,sig):
        return self.names.get(sig)

    def set(self,sig,name):
        self.names[sig]=name
        tmp=self.path.with_suffix('.tmp')
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(self.names,f,ensure_ascii=False)
        tmp.replace(self.path)


def clean_name(text):
    """A nickname is user-controlled text; keep it short and free of our own markers."""
    name=''.join(c for c in text.strip().splitlines()[0] if c not in '【】[]{}<>\\') if text.strip() else ''
    return name.strip()[:24]
