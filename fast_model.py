"""Direct text-only model call over the saved ChatGPT login.

The request carries no tools, files or host data, so the model has nothing to
act on or leak; the policy text and chat history are its only inputs. Credentials
stay in this trusted process and are never part of any prompt.
"""
import http.client
import json
import threading
import time

from model_sandbox import DECISION_SCHEMA, DESCRIBE_SCHEMA, REPLY_SCHEMA, SUMMARY_SCHEMA, auth_material

HOST='chatgpt.com'
PATH='/backend-api/codex/responses'
_local=threading.local()
_auth={'token':None,'account':None,'exp':0.0}
_auth_lock=threading.Lock()


def _credentials(cfg):
    with _auth_lock:
        if _auth['token'] is None or time.time()>_auth['exp']:
            tokens=json.loads(auth_material(cfg))['tokens']
            _auth.update(token=tokens['access_token'],account=tokens['account_id'],exp=time.time()+600)
        return _auth['token'],_auth['account']


def _connection():
    conn=getattr(_local,'conn',None)
    if conn is None:
        conn=_local.conn=http.client.HTTPSConnection(HOST,timeout=40)
    return conn


def _post(cfg,policy,payload,schema,search=False,images=()):
    token,account=_credentials(cfg)
    body={'model':cfg['model'],'instructions':policy,'stream':True,'store':False,
          'reasoning':{'effort':cfg.get('effort','low')},
          'tool_choice':'auto' if search else 'none','tools':[{'type':'web_search'}] if search else [],
          'input':[{'role':'user','content':[{'type':'input_text','text':json.dumps(payload,ensure_ascii=False)}]
                    +[{'type':'input_image','image_url':'data:image/png;base64,'+b64} for b64 in images]}],
          'text':{'format':{'type':'json_schema','name':'result','schema':schema,'strict':True}}}
    headers={'Authorization':'Bearer '+token,'chatgpt-account-id':account,'Content-Type':'application/json',
             'OpenAI-Beta':'responses=experimental','originator':'codex_cli_rs','Accept':'text/event-stream'}
    conn=_connection()
    conn.request('POST',PATH,json.dumps(body,ensure_ascii=False).encode(),headers)
    response=conn.getresponse()
    if response.status!=200:
        response.read()
        raise RuntimeError('MODEL_HTTP_%d'%response.status)
    text='';done=False
    for line in response:
        if not line.startswith(b'data:'):continue
        event=json.loads(line[5:])
        kind=event.get('type','')
        if kind=='response.output_text.delta':text+=event.get('delta','')
        elif kind=='response.completed':done=True
        elif kind in ('response.failed','response.incomplete','error'):raise RuntimeError('MODEL_TURN_FAILED')
        elif kind.startswith('response.output_item.') and event.get('item',{}).get('type') not in (('message','reasoning','web_search_call') if search else ('message','reasoning')):
            raise RuntimeError('MODEL_TOOL_OR_UNKNOWN_ITEM_REJECTED')
    if not done:raise RuntimeError('MODEL_RESULT_INCOMPLETE')
    return text


def invoke(cfg,policy,payload,schema,search=False,images=()):
    for attempt in (0,1):
        try:
            result=json.loads(_post(cfg,policy,payload,schema,search,images))
            break
        except (OSError,http.client.HTTPException,ValueError):
            _local.conn=None  # reconnect once on a stale keep-alive connection
            if attempt:raise RuntimeError('MODEL_UNAVAILABLE') from None
    validate(schema,result)
    return result


def validate(schema,result):
    """Reject anything that is not exactly the shape the caller asked for."""
    if not isinstance(result,dict):raise RuntimeError('INVALID_RESULT')
    if schema==DECISION_SCHEMA:
        if set(result)!={'allowed'} or type(result['allowed']) is not bool:raise RuntimeError('INVALID_GUARD_DECISION')
    elif schema==REPLY_SCHEMA:
        if (set(result)-{'mood'}!={'reply','latex'} or not isinstance(result['reply'],str) or not isinstance(result['latex'],str)
                or result.get('mood','neutral') not in ('positive','neutral','negative')):
            raise RuntimeError('INVALID_REPLY_SCHEMA')
    elif schema==DESCRIBE_SCHEMA:
        if set(result)!={'description'} or not isinstance(result['description'],str):raise RuntimeError('INVALID_DESCRIBE_SCHEMA')
    elif schema==SUMMARY_SCHEMA:
        if set(result)!={'summary'} or not isinstance(result['summary'],str):raise RuntimeError('INVALID_SUMMARY_SCHEMA')
    else:raise RuntimeError('UNRECOGNIZED_SCHEMA')
