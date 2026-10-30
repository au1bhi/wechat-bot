"""Background reply worker. The model sees chat text, never transport credentials."""
import argparse
import datetime
from zoneinfo import ZoneInfo
import hashlib
import urllib.parse
import base64
import io
from PIL import Image, ImageStat
import fcntl
import json
import logging
import os
import random
import re
import struct
import sqlite3
import unicodedata
from collections import namedtuple
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parent
Reply=namedtuple('Reply','text latex png mood',defaults=(None,None))
from topic_policy import CONTEXT_MARKER
from guardrails import (REFUSAL, input_reason, output_reason, latex_reason, LATEX_LIKE,
                        INPUT_POLICY, ANSWER_POLICY, CALM_POLICY, FACT_COMMENT_POLICY, FACT_REVIEW_POLICY, AUDIT_POLICY, SUMMARY_POLICY, BANTER_POLICY, VISION_POLICY, VISION_FULL_POLICY, NAME_POLICY, FIXED_REPLY,
                        fixed_trigger, needs_fresh, clean_reply, SEARCH_NOTE, DENIES_EXISTENCE, VERIFIED_OWNER_POLICY, AFFECTION_NOTE)
from latex_render import render
from context_store import ContextStore, labelled
from refusal_voice import display_refusal, is_refusal
from huchenfeng import note as huchenfeng_note, unsupported_claim as huchenfeng_unsupported_claim
from social_language import note as social_language_note
from persona_hobbies import note as hobby_note
from senders import SenderBook, clean_name
from audit import Auditor
from affection import AffectionBook
from model_sandbox import DECISION_SCHEMA, DESCRIBE_SCHEMA, REPLY_SCHEMA, SUMMARY_SCHEMA
from backend import invoke
import backend
import agy_model


def new_rows(before,after):
    """Follow a stable tail even when recalls/reflow change earlier visible rows.

    A unique, informative last-seen row can anchor a continuation inside the new
    window. Never infer new messages from an unrelated or ambiguous window.
    """
    def key(row):
        return (''.join(unicodedata.normalize('NFKC',row[0]).split()),row[1])
    old=[key(r) for r in before];new=[key(r) for r in after]
    for size in range(min(len(old),len(new)),0,-1):
        if old[-size:] == new[:size]:return after[size:]
    if not old:return []
    # The window may have lost its top rows (tall pictures push them out): look for the last rows we saw as one
    # contiguous block anywhere in the new window. Only a block that occurs exactly once counts, and a single
    # row only if it is informative, so repeated stickers/images cannot create or hide messages.
    for size in range(min(len(old),len(new)),0,-1):
        block=old[-size:]
        if size==1 and (len(block[0][0])<12 or IMAGE_ROW.match(block[0][0]) or SYSTEM_ROW.search(block[0][0])):continue
        spots=[i for i in range(len(new)-size+1) if new[i:i+size]==block]
        if len(spots)==1 and (size>=2 or old.count(block[0])==1):return after[spots[0]+size:]
    anchor=old[-1]
    if (len(anchor[0])<12 or IMAGE_ROW.match(anchor[0]) or SYSTEM_ROW.search(anchor[0])
            or old.count(anchor)!=1 or new.count(anchor)!=1):return []
    return after[new.index(anchor)+1:]


SKIP_ROWS={'Video','Voice'}
IMAGE_ROW=re.compile(r'^(?:Image|Animated Stickers|\[Photo\]|\[Sticker\]|\[图片\]|\[动画表情\])')


def incoming_image(row):
    """Positive direction wins; support the old bridge only with a sender strip."""
    if row.get('outgoing') or not IMAGE_ROW.match(row.get('text','')):return False
    direction=row.get('direction')
    return direction=='incoming' or (direction is None and bool(row.get('sig')))

ASKING=re.compile(r'[?？吗呢吧么]|怎么|为什么|如何|请|帮|能不能|可不可以|可以|你觉得|你说|你看|告诉|回答|解释|是什么|是啥|啥意思|有啥|咋回事|咋办|咋样|多少|算一下|推荐|^(?:(?:你|再|来|给我|帮我)\s*)?(?:评价|锐评|点评|分析|对比|比较|讲讲|说说|谈谈|聊聊)')



def followup_key(sender=None,sig=None):
    """Conversation identity only; never confers privileges or verified identity."""
    return ('sig',sig) if sig else (('name',sender) if sender and sender!='群友' else None)


def compact(text):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',text)).casefold()


LOOKALIKES=str.maketrans({'i':'l','1':'l','|':'l','0':'o'})


def name_key(text):
    """Nickname comparison key. A vision model cannot tell capital I from small l from 1 (or O from 0)."""
    return compact(text).translate(LOOKALIKES)


def addressed(text,aliases):
    """A name used without @ counts only when the message clearly asks the bot something."""
    c=compact(text)
    normalized=unicodedata.normalize('NFKC',text).casefold()
    known={compact(alias) for alias in aliases}
    # A real @ to another group member takes precedence over an alias in the body.
    mentions=re.findall(r'[@＠]\s*([a-z0-9_.-]+|[^\s，,。!！?？:：;；]+)',normalized)
    if any(compact(target) not in known for target in mentions):return False
    for alias in aliases:
        a=compact(alias)
        if re.fullmatch(r'[a-z0-9_]+',a):
            # Short Latin aliases such as alias_b/alias_a must be separate words, not
            # pieces of a URL, identifier, or a name such as zkSync.
            match=re.search(r'(?<![a-z0-9_])'+re.escape(a)+r'(?![a-z0-9_])',normalized)
            if not match:continue
            at_start=not normalized[:match.start()].strip(' \t\n，,。.!！、:：@＠')
            if at_start or ASKING.search(text):return True
        elif a and a in c:
            at_start=c.lstrip('，,。.!！、:：').startswith(a)
            if at_start or ASKING.search(text):return True
    return False


MENTION_ONLY='（仅艾特机器人）'


QUOTE=re.compile(r"^(?P<reply>.*?)\n+Quote (?P<name>.+?)'s message: (?P<quoted>.*)$",re.S)
IMAGE_QUOTE=re.compile(r'（引用(?P<name>.+?)的消息：(?:Image|Animated Stickers[^）]*)）')
SYSTEM_ROW=re.compile(r'撤回了一条消息|加入了群聊|邀请.{0,40}加入|移出了群聊|拍了拍|修改群名|^\d{1,2}:\d{2}$')
PARTIAL_PICTURE=re.compile(r'部分截图|局部|不完整|被截断|截断|只显示|仅显示|只露出|显示不全|未显示完整|裁剪')


def crop_is_partial(png):
    """A chat preview that is tiny in one direction is a clipped slice of the picture, not the picture."""
    try:
        if isinstance(png,str):png=base64.b64decode(png[:64]+'='*(-len(png[:64])%4))
        w,h=struct.unpack('>II',png[16:24])
    except Exception:return False
    return min(w,h)<160 or max(w,h)/max(1,min(w,h))>5


NOT_LOADED=re.compile(r'未成功加载|未加载|加载失败|没加载|占位')


def split_quote(text):
    """(reply, quoted_name, quoted_text) for a WeChat quote-reply, else (text, None, None)."""
    m=QUOTE.match(text)
    return (m.group('reply').strip(),m.group('name').strip(),m.group('quoted').strip()) if m else (text,None,None)


def quotes_bot(text,bot_texts):
    """A reply that quotes one of the bot's own messages is addressed to it."""
    c=compact(text)
    for b in bot_texts:
        cb=compact(b)
        if len(cb)>=6 and cb[:14] in c and c!=cb:return True
    return False


def classify_rows(rows,names=(),aliases=(),bot_texts=(),senders=None,with_sender=False):
    """Every incoming text is kept as group context; (body, directed) says whether to answer."""
    result=[]
    for index,(text,outgoing) in enumerate(rows):
        sender=senders[index] if senders and index<len(senders) else None
        if (outgoing or text in SKIP_ROWS or IMAGE_ROW.match(text)
                or (text.startswith('[') and text.endswith(']')) or SYSTEM_ROW.search(text)):
            continue
        whole=unicodedata.normalize('NFKC',text)
        t,quoted_name,quoted_text=split_quote(whole)
        directed=False;body=t.strip()
        # Someone replying to one of the bot's own messages is talking to the bot.
        if quoted_name and any(compact(quoted_name)==compact(n) for n in list(names)+list(aliases)):directed=True
        for name in names:
            pattern=re.compile(r'[@＠]\s?'+re.escape(unicodedata.normalize('NFKC',name))+r'(?=\s|$|[,.!?:;，。！？：；])')
            if pattern.search(t):
                body=pattern.sub('',t).strip();directed=True;break
        if not directed:directed=addressed(t,aliases) or quotes_bot(whole,bot_texts)
        if directed and not body.strip(' \t\n，,。.!！?？:：;；、'):body='请回答这条引用' if quoted_name else MENTION_ONLY
        if quoted_name and body:body='%s（引用%s的消息：%s）'%(body,quoted_name,quoted_text[:200])
        if body:result.append((body,directed,sender) if with_sender else (body,directed))
    return result


def incoming_text(rows,names=()):
    """Only incoming messages that @-mention the bot."""
    return [body for body,directed in classify_rows(rows,names) if directed]


class Bridge:
    def __init__(self,cfg):
        self.url=cfg['bridge_url']
        self.token=Path(cfg['bridge_token_file']).read_text().strip()

    def request(self,path,data=None):
        req=urllib.request.Request(self.url+path,
            data=json.dumps(data,ensure_ascii=False).encode() if data is not None else None,
            headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
        except urllib.error.HTTPError as e:
            try:detail=json.load(e).get('error','BRIDGE_ERROR')
            except Exception:detail='BRIDGE_ERROR'
            raise RuntimeError(detail) from None


# Long-lived threads keep their HTTPS connections warm between requests.
POOL=ThreadPoolExecutor(4,thread_name_prefix='model')
# Coordinators wait on POOL; they must never occupy its own worker threads.
ANSWERS=ThreadPoolExecutor(3,thread_name_prefix='answer')
BANTERS=ThreadPoolExecutor(3,thread_name_prefix='banter')


def policy(cfg,text):
    # The chats are Chinese, so tell the model Beijing time, not this machine's own clock or time zone.
    now=datetime.datetime.now(ZoneInfo('Asia/Shanghai'))
    weekday='一二三四五六日'[now.weekday()]
    today=now.strftime('%Y年%m月%d日')+' 星期'+weekday
    return (text.replace('{MODEL}',cfg.get('model_public_name') or cfg.get('model') or '未公开')
                .replace('{NOW}',now.strftime('%H:%M')).replace('{TODAY}',today))


def screen_answer(cfg,result,latest=''):
    """Deterministic checks on one model answer. Returns (reply, latex), or None to try again."""
    reply=repair_banter_count(latest,clean_reply(result['reply']));latex=result['latex'].strip()
    if not reply and not latex:return None
    if is_refusal(reply):return None
    if reply.lower().strip(' :："\'') in ('latex','reply','json','null','none'):return None  # leaked schema field name
    if not latex and LATEX_LIKE.search(reply):reply,latex='',reply
    elif latex and LATEX_LIKE.search(reply):reply='答案在图里喵~'  # WeChat would show the raw LaTeX source
    markers=cfg.get('private_markers',[])
    if latex:
        if latex_reason(latex) or (reply and output_reason(reply,markers)):return None
    elif output_reason(reply,markers):return None
    if any(re.search(r'[@＠]\s*'+re.escape(n),reply+latex) for n in cfg.get('mention_names',[])):return None
    return reply,latex


def read_name(cfg,strip_png):
    """Read a nickname off the name strip above a bubble; '群友' if it cannot be trusted."""
    guard_cfg=dict(cfg,model=cfg.get('gate_model',cfg.get('model')))
    out=invoke(guard_cfg,NAME_POLICY,{'task':'读出昵称'},DESCRIBE_SCHEMA,images=[strip_png])
    name=clean_name(out['description'])
    if not name or input_reason(name) or output_reason(name,cfg.get('private_markers',[])):return '群友'
    return name


def describe_image(cfg,png,caption=''):
    """Describe a preview, retrying unsupported claims that visible pixels are blank."""
    guard_cfg=dict(cfg,model=cfg.get('gate_model',cfg.get('model')))
    for attempt in range(2):
        pol=VISION_POLICY+('\n请重新读取图片，像素检查发现有可见内容，不要猜测空白。' if attempt else '')
        out=invoke(guard_cfg,pol,{'task':'描述这条群聊图片消息','caption':caption},DESCRIBE_SCHEMA,images=[png])
        text=out['description'].strip()[:160]
        if not text or input_reason(text) or output_reason(text,cfg.get('private_markers',[])):return None
        if BLANK_DESCRIPTION.search(text) and nonblank_pixels(png):continue
        return text
    return None


BLANK_DESCRIPTION=re.compile(r'纯[白黑](?:色)?(?:的)?(?:空白)?(?:图片|画面|图)|空白图片|没有任何(?:文字|图形|内容)|未(?:成功)?(?:加载|读取)|无法(?:查看|识别)')


def nonblank_pixels(png):
    """Cheap evidence check; image pixels never become instructions or host data."""
    try:
        with Image.open(io.BytesIO(base64.b64decode(png,validate=True))) as im:
            im=im.convert('L');im.thumbnail((128,128))
            return len(im.getcolors(16384) or [])>8 and ImageStat.Stat(im).stddev[0]>12
    except Exception:return False


def describe_pages(cfg,pages):
    """Read originals; retry an unsupported blank-image claim once, then fail honestly."""
    guard_cfg=dict(cfg,model=cfg.get('gate_model',cfg.get('model')))
    for attempt in range(2):
        pol=VISION_FULL_POLICY+('\n上次声称空白与像素检查不符，请重新读取图片文件，逐项核对可见文字和物体；不能可靠读取就说明未成功加载。' if attempt else '')
        out=invoke(guard_cfg,pol,{'task':'转写并描述这张图片','screens':len(pages)},DESCRIBE_SCHEMA,images=pages)
        text=out['description'].strip()[:800]
        if not text or input_reason(text) or output_reason(text,cfg.get('private_markers',[])):return None
        if BLANK_DESCRIPTION.search(text) and any(nonblank_pixels(p) for p in pages):
            logging.info('Image description contradicted visible pixels; retry=%d',attempt+1)
            continue
        return text
    return None


ASKS_PICTURE=re.compile(r'图|截图|照片|这题|这道题|这个题|这个极限|看看这|看下这|看一下这')


FUNNY=re.compile(r'哈{2,}|笑死|绷|草|逆天|离谱|乐|蚌|典|麻了|笑哭|破涕|[😂🤣💀]|牛[逼批]|nb|[?？]{2,}|[!！]{3,}|6{3,}|孝|急了|傻|抽象|难绷|赢|输了|寄了|完了|救命')


def topic_context(history):
    """Retain a safe topic boundary when blocked prior text must be removed."""
    return [dict(m,content=CONTEXT_MARKER)
            if m.get('role')=='user' and input_reason(m.get('content',''))=='political_content'
            else m for m in history[-24:]]


def banter(cfg,history):
    """Unprompted one-liner about something funny in the chat, or None to stay quiet."""
    if history and input_reason(history[-1].get('content',''))=='political_content':return None
    markers=cfg.get('private_markers',[])
    safe=[m for m in topic_context(history) if not input_reason(m.get('content',''))
          and (m['role']=='user' or not output_reason(m['content'],markers)) and not is_refusal(m.get('content'))]
    if not safe or safe[-1]['role']!='user':return None
    recent=[m.get('content','') for m in safe[-3:] if m['role']=='user']
    if not any(FUNNY.search(t) for t in recent) and sum(len(t) for t in recent[-2:])<16:return None   # idle one-word chatter: no model call at all
    guard_cfg=dict(cfg,model=cfg.get('gate_model',cfg.get('model')))
    try:
        reply=repair_banter_count(safe[-1]['content'],clean_reply(invoke(cfg,policy(cfg,BANTER_POLICY)+huchenfeng_note(safe)+social_language_note(safe)+hobby_note(safe),{'history':safe},REPLY_SCHEMA)['reply']))
        # Reject unusable or repeated unsolicited comments before spending a
        # classifier call. None of these paths can release unchecked output.
        if huchenfeng_unsupported_claim(safe,reply):return None
        if not reply or len(reply)>120 or is_refusal(reply) or output_reason(reply,markers) or LATEX_LIKE.search(reply):return None
        if any(re.search(r'[@＠]\s*'+re.escape(n),reply) for n in cfg.get('mention_names',[])):return None
        key=re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',reply)).casefold()
        previous=[m['content'] for m in safe if m['role']=='assistant'][-8:]
        if len(key)>=4 and any(key==re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',t)).casefold() for t in previous):return None
        if not invoke(guard_cfg,policy(cfg,INPUT_POLICY),{'history':safe},DECISION_SCHEMA)['allowed']:return None
    except Exception as e:
        logging.info('Banter skipped: %s',e);return None
    return reply


FACT_CUE=re.compile(r'[?？]|多少|为什么|怎么|如何|是不是|是否|应该|好像|据说|听说|其实|确实|等于|定义|原理|补贴|分数线|国家线|学费|奖学金|[0-9]')


def factual_comment(cfg,history):
    """Optional factual contribution for calm chats; silence is a normal result."""
    if not history or history[-1].get('role')!='user' or input_reason(history[-1].get('content','')):return None
    markers=cfg.get('private_markers',[])
    safe=[m for m in topic_context(history) if not input_reason(m.get('content',''))
          and (m['role']=='user' or not output_reason(m['content'],markers)) and not is_refusal(m.get('content'))]
    if not safe or safe[-1]['role']!='user':return None
    body=re.sub(r'^【[^】]*】','',safe[-1]['content'])
    if not FACT_CUE.search(body):return None  # no model call for acknowledgments or everyday chatter
    try:
        result=invoke(cfg,policy(cfg,FACT_COMMENT_POLICY),{'history':safe},REPLY_SCHEMA)
        reply=clean_reply(result['reply']);latex=(result.get('latex') or '').strip()
        if not reply or is_refusal(reply) or len(reply)>240 or output_reason(reply,markers) or LATEX_LIKE.search(reply):return None
        if re.search(r'[:：]\s*$',reply) and not latex:return None  # announces a derivation that never arrived
        if any(re.search(r'[@＠]\s*'+re.escape(n),reply+latex) for n in cfg.get('mention_names',[])):return None
        key=compact(reply)
        if any(key==compact(m['content']) for m in safe if m['role']=='assistant'):return None
        if latex and latex_reason(latex):return None
        guard_cfg=dict(cfg,model=cfg.get('gate_model',cfg.get('model')))
        candidate=reply+('\n'+latex if latex else '')
        if not invoke(guard_cfg,policy(cfg,FACT_REVIEW_POLICY),{'history':safe,'candidate':candidate},DECISION_SCHEMA)['allowed']:return None
        if not latex:return reply
        try:png=render(latex)
        except RuntimeError as e:
            logging.info('Factual comment formula render failed: %s',e);return None
        return Reply(reply,latex,png)
    except Exception as e:
        logging.info('Factual comment skipped: %s',e);return None


HARD_QUESTION=re.compile(
    r'证明|推导|求(?:解|证|极限|导|积分|值|和|通项|最[大小]值|特征)|计算(?!机)|化简|解(?:方程|不等式)|因式分解|'
    r'积分|极限|导数|微分|级数|收敛|泰勒|洛必达|傅里叶|拉普拉斯|矩阵|行列式|特征值|特征向量|满秩|(?<![a-z])秩(?![a-z])|'
    r'线性(?:代数|方程|相关|无关)|二次型|概率(?:密度|分布)|数学期望|方差|分布函数|数列|不定积分|定积分|'
    r'[∫∑∏√≤≥∞]|\\(?:int|sum|lim|frac|sqrt)|\blim\b|\bsin\b|\bcos\b|\blog\b|\bln\b|'
    r'时间复杂度|动态规划|最短路|算法题|\bdp\b|报错|bug|为什么.{0,12}(?:不对|错了|不行)',re.I)
FOLLOWUP_ONLY=re.compile(r'^[\W\d]{0,6}$')


def is_hard(text):
    """Maths, proofs, algorithms and debugging go to the high-effort model; everything else stays on the fast one."""
    body=re.sub(r'^【[^【】\n]{1,24}】\s*','',text or '')
    body=re.sub(r'（引用[^）]*）','',body).strip()
    return len(body)>=4 and bool(HARD_QUESTION.search(body))


PROGRESS_START={
    True:['这题有点难，我认真算一下，稍等。','收到，这个要多想一会儿，先别急。','这题得推导一遍，我在算。'],
    False:['这题得好好想想，别催，本喵在算喵。','有点难度，容本喵推一遍喵。','等会，这题要多想一下喵。']}
PROGRESS_ANSWERING={True:['思路有了，正在写答案。','算完了，正在整理答案。'],False:['想出来了，正在写，马上喵。','算完了，在整理喵。']}
PROGRESS_WAITING={True:'还在推，已经 %d 秒了，快好了。',False:'还在算，已经 %d 秒了喵，别急。'}


ANSWER_ATTEMPTS=3


CLOCK_Q=re.compile(r'^(?:现在|当前|北京)?(?:是)?(?:时间)?(?:是)?(?:几点钟?|几点了|几点啦|什么时间|啥时间|多少点|时间)(?:了|啦|啊|呀|吗|呢)?$')
DATE_Q=re.compile(r'^(?:今天|今日)(?:是)?(?:几号|几月几号|星期几|周几|礼拜几|什么日子|日期)(?:了|啊|呀|吗|呢)?$')


def quick_reply(latest,now=None,calm=False):
    """Exact greetings and clock/date questions are answered by code; clock/date use Beijing time."""
    if '引用' in latest or '\n' in latest.strip():return None
    latest=re.sub(r'^【[^【】\n]{1,24}】\s*','',latest)
    text=re.sub(r'[@＠]\s*(?:DemoBot|Legacy\s*Bot|OldBot)[\s\u2005]*','',latest,flags=re.I)
    text=re.sub(r'^[^：:]{1,24}[：:]\s*','',text) if re.match(r'^[^：:]{1,24}[：:]',text) else text
    text=re.sub(r'[\s\u2005?？!！。.，,~]+','',text)
    key=text.casefold()
    if calm:
        if key in {'你好','您好','嗨','哈喽','hello','hi'}:return '你好喵。'
        if key in {'在吗','在不在','有人吗'}:return '在，请说喵。'
    if key in {'你好','您好','嗨','哈喽','hello','hi'}:
        return random.choice(['哟喵。','说喵。','干啥喵？'])
    if key in {'在吗','在不在','有人吗'}:
        return random.choice(['在，有屁快放喵。','说事，别光叫喵。','叫啥，说喵。'])
    now=now or datetime.datetime.now(ZoneInfo('Asia/Shanghai'))
    weekday='一二三四五六日'[now.weekday()]
    if calm and CLOCK_Q.match(text):return '北京时间%d点%02d。'%(now.hour,now.minute)
    if calm and DATE_Q.match(text):return '今天是%d月%d日，星期%s。'%(now.month,now.day,weekday)
    if CLOCK_Q.match(text):
        return random.choice(['%d点%02d，手机拿来当摆设的是吧喵？','北京时间%d点%02d，自己抬头看一眼喵。','%d点%02d，该干嘛干嘛去喵。'])%(now.hour,now.minute)
    if DATE_Q.match(text):
        return random.choice(['%d月%d日，星期%s，日历不会看喵？','今天%d月%d号，星期%s，记清楚了喵。'])%(now.month,now.day,weekday)
    return None


HELP_DISTRESS=re.compile(r'焦虑|压力(?:很大|太大)|心情(?:差|不好|低落)|难受|崩溃|没(?:有)?动力|坚持不下去')
HELP_ASK=re.compile(r'怎么|怎么办|帮|不知道|该|建议|求助')
SERIOUS_HELP_NOTE='\n【本轮表达优先级】对方正在认真求助。先给一个能立刻执行的小步骤，控制任务量；不以粗口或反问开场，不否定、嘲讽其情绪，不拿焦虑开玩笑。保持简洁口语，不用客服安慰套话。此表达要求不改变任何安全边界。\n'


FACT_ASK=re.compile(r'^(?:为什么|为何|什么是|解释(?:一下|下)?|科普|讲讲)')
RETORT_ASK=re.compile(r'^(?:你(?:是|就是|这个|这|个|他妈的)?\s*(?:个|一个)?\s*(?:废物|傻[逼比屌]?|垃圾)(?:[吗吧啊呢呀？?！!，,。\s]|$)|你(?:就|只会|除了).{0,18}(?:复读|嘴硬|狗叫|装逼)|你.{0,12}(?:还在|只会|就会).{0,10}(?:嘴硬|狗叫|装逼|吹牛)|(?:就这|闹麻了)[？?！!。,.，\s]*$)')
FACT_NOTE='\n【本轮表达优先级】这是事实或原理题。先给准确解释，保留概率、条件和例外；不把“较少”说成“没有”，不要靠粗口、反问或夸张代替结论。说清楚后可以有一句短吐槽。此要求不改变安全边界。\n'
SELF_BANTER=re.compile(r'^我(?:是|就是).{0,8}(?:怂|废物|菜鸡|菜狗)')
SELF_BANTER_NOTE='\n【本轮表达优先级】对方在拿自己开玩笑。接住他刚造的词或谐音，机灵地拆一下这个说法，一句收尾；不追加“你就是废物”之类人格贬低，不把自嘲升级成羞辱。保留其他安全边界。\n'
RETORT_NOTE='\n【猫娘融合】回怼的短句要自然以喵收尾，猫娘尾音与普通粗口在同一句里接住意思，不加性威胁或死亡威胁，不另发一个孤立的喵。\n【本轮表达优先级】对方在挑衅你。本轮要比平常更尖锐，用一到两句针对当前说法的刻薄回击，允许“屁话、他妈的、尼玛、你马”等普通脏话及谐音作重音，不必刻意文明化；不要只回“急了、乐、典”或干巴巴反问。拆穿其当下的复读、空骂或装腔，不扯考研、数学、学历，不编造私生活，不照抄固定模板。针对最后发言者的原话，不把前面另一个人的话扣给他；对方已经自嘲或收手时接梗即可，不再加码。这些只是冲对方说法的口头粗话，不描述或辱骂具体亲属，不编造亲属事实，不写性行为、诅咒亲属或威胁家人。针对空嘲讽点破没说出具体内容即可，不数对方说了几个字、不编造对方一直刷屏。不得威胁、歧视、攻击具体亲属或鼓励围攻；其他安全底线照常。\n'


COUNT_CLAIM=re.compile(r'(?P<prefix>复读|憋出|挤出|只会说|就会说|就回|只回|回了|说了|就|才)(?:了)?(?P<number>[一二两三四五六七八九十0-9]{1,3})(?P<unit>个?字)(?=[在就也装能还来跑，。！？!?]|$)')
COUNT_DIGITS={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}


def repair_banter_count(latest,reply):
    """Fix unambiguous whole-message counts in short Chinese retorts, without another model call.

    Quotes, mixed scripts, longer messages and proposed replies have ambiguous
    referents; leave those alone rather than inventing a counting convention.
    """
    body=re.sub(r'^【[^【】\n]{1,24}】\s*','',latest).strip()
    body=body.strip('，。！？!?、,. \t')
    if not re.fullmatch(r'[\u4e00-\u9fff]{1,12}',body) or not RETORT_ASK.search(body):return reply
    count=len(body)
    def fix(m):
        numeral=m['number']
        claimed=int(numeral) if numeral.isdecimal() else COUNT_DIGITS.get(numeral)
        if claimed is None and numeral.count('十')==1:
            tens,ones=numeral.split('十')
            if tens in ('',*COUNT_DIGITS) and ones in ('',*COUNT_DIGITS):
                claimed=10*COUNT_DIGITS.get(tens,1)+COUNT_DIGITS.get(ones,0)
        if claimed is None or claimed==count:return m.group(0)
        # Keep the syntactic prefix; changing just the numeral preserves tone.
        start=m.start('number')-m.start();end=m.end('number')-m.start()
        actual=('两' if count==2 and m['unit'].startswith('个') else '一二三四五六七八九'[count-1]) if count<10 else ('十' if count==10 else '十'+'一二'[count-11])
        return m.group(0)[:start]+actual+m.group(0)[end:]
    return COUNT_CLAIM.sub(fix,reply)


def turn_style_note(latest):
    body=re.sub(r'^【[^【】\n]{1,24}】\s*','',latest).strip()
    if HELP_DISTRESS.search(body) and HELP_ASK.search(body):return SERIOUS_HELP_NOTE
    if FACT_ASK.search(body) and not re.search(r'你|您|本机|设备',body):return FACT_NOTE
    if SELF_BANTER.search(body):return SELF_BANTER_NOTE
    if RETORT_ASK.search(body):return RETORT_NOTE
    return ''


def generate(cfg,history):
    latest=next((m.get('content','') for m in reversed(history) if m.get('role')=='user'),'')
    refusal=Reply(REFUSAL,'')
    if not input_reason(latest):
        fast=quick_reply(latest,calm=bool(cfg.get('_calm')))
        if fast:
            logging.info('Answered by code: clock/date/greeting');return Reply(fast,'',None,None)
    if input_reason(latest):
        logging.info('Security gate: deterministic_input_denied')
        return refusal
    # Never forward a previously rejected request or unvalidated reply as context.
    markers=cfg.get('private_markers',[])
    guard_cfg={k:v for k,v in dict(cfg,model=cfg.get('gate_model',cfg.get('model'))).items() if k not in ('_stage','_hard')}   # only the answer reports progress
    safe_history=[]
    for message in topic_context(history):
        role=message.get('role')
        content=message.get('content','')
        if role=='user' and not input_reason(content):
            safe_history.append({'role':'user','content':content})
        elif role=='assistant' and not output_reason(content,markers) and not is_refusal(content):
            safe_history.append({'role':'assistant','content':content})
    try:
        # Classifier and answer run concurrently; nothing is released unless both agree.
        gate=POOL.submit(invoke,guard_cfg,policy(cfg,INPUT_POLICY),{'history':safe_history},DECISION_SCHEMA)
        fresh=needs_fresh(latest)
        answer_policy=(policy(cfg,CALM_POLICY) if cfg.get('_calm') else policy(cfg,ANSWER_POLICY)+huchenfeng_note(safe_history)+social_language_note(safe_history)+turn_style_note(latest))+(VERIFIED_OWNER_POLICY if cfg.get('_verified_owner_turn') else '')+(SEARCH_NOTE if fresh else '')
        answer_policy+=hobby_note(safe_history,calm=bool(cfg.get('_calm')))
        if cfg.get('_mention_only'):
            answer_policy+='\n本轮只有艾特，未找到同一发言人近期尚未回答的明确问题。简短询问对方想问前面哪一句，不替别人提问，不编造问题或重答已回答的问题。\n'
        if cfg.get('_picture_missing'):
            answer_policy+='\n本轮未能可靠读取被问到的图片。只说明暂未读清，请对方重发清晰原图；不得声称图片空白，也不得猜测内容或拿历史其他图片顶替。\n'
        if '_affection' in cfg and AFFECTION_NOTE:
            answer_policy+=AFFECTION_NOTE.replace('{SPEAKER}','【%s】'%cfg['_speaker'] if cfg.get('_speaker') else '').replace('{AFFECTION}',str(cfg['_affection']))
        acfg=dict(cfg,model=cfg.get('search_model',cfg.get('model'))) if fresh else cfg
        hard=bool(cfg.get('agy_hard_model')) and not fresh and is_hard(latest)
        if hard:acfg=dict(acfg,_hard=True)
        extra={'search':True} if fresh else {}
        answer=POOL.submit(invoke,acfg,answer_policy,{'history':safe_history},REPLY_SCHEMA,**extra)
        allowed=gate.result()['allowed']
        if not allowed:
            answer.cancel()  # If it is still queued, do not spend an answer call on a denied request.
            logging.info('Security gate: semantic_input_denied')
            return refusal
        # The classifier already approved this request. If the answer model wavers (spurious
        # refusal, garbled LaTeX, filtered output) ask again; every attempt faces the same checks.
        screened=None
        for attempt in range(ANSWER_ATTEMPTS):
            try:
                result=answer.result() if attempt==0 else invoke(acfg,answer_policy,{'history':safe_history},REPLY_SCHEMA,**extra)
            except RuntimeError as e:
                logging.info('Answer attempt %d failed: %s',attempt+1,e);continue
            if huchenfeng_unsupported_claim(safe_history,result.get('reply','')):
                logging.info('Answer attempt %d rejected: unsupported financial claim',attempt+1)
                answer_policy+='\n【重写要求】上一个候选无依据地编造了对方的个人财务状况。本轮不提账单、贷款、分期、债务或收入，只拆穿把品牌当作身份或逻辑升级的推理；别复述本条说明。\n'
                continue
            screened=screen_answer(cfg,result,latest=latest)
            if screened:
                mood=result.get('mood');break
            logging.info('Answer attempt %d rejected by output checks',attempt+1)
        if screened and not fresh and cfg.get('verify_denials',True) and DENIES_EXISTENCE.search(screened[0]):
            # The model called something non-existent that it may simply not know: check the web before saying so.
            logging.info('Denial of existence without a search; verifying online')
            vpolicy=answer_policy+SEARCH_NOTE+'\n【重写要求】上一版把对方提到的东西说成不存在或没听过。先联网查证再答；查到就按事实说，查不到只说没查到、不确定。\n'
            vcfg=dict(cfg,model=cfg.get('search_model',cfg.get('model')))
            vcfg.pop('_hard',None)
            try:
                vres=invoke(vcfg,vpolicy,{'history':safe_history},REPLY_SCHEMA,search=True)
                vscreened=screen_answer(cfg,vres,latest=latest)
                if vscreened:screened,mood=vscreened,vres.get('mood')
            except RuntimeError as e:
                logging.info('Verification search failed: %s',e)
        if not screened:
            logging.info('Security gate: deterministic_output_denied')
            return refusal
        reply,latex=screened
        if not latex:return Reply(reply,'',None,mood)
        # Formula answers get a semantic audit, run alongside typesetting.
        audit=POOL.submit(invoke,guard_cfg,policy(cfg,AUDIT_POLICY),{'request':latest,'reply':reply,'latex':latex},DECISION_SCHEMA)
        image=POOL.submit(render,latex)
        approved=audit.result()['allowed']
        try:png=image.result()
        except RuntimeError as e:
            logging.warning('Formula render failed: %s',e);png=None
        if not approved:
            logging.info('Security gate: semantic_output_denied')
            return refusal
        return Reply(reply,latex,png,mood)
    except Exception:
        # A failed or malformed guard must never turn into permission to answer.
        logging.warning('Security gate failed closed; request refused')
        return refusal


class Chat:
    """Per-chat state: its own baseline, saved context and echo filter."""
    def __init__(self,name,cfg,state_dir):
        self.name=name
        self.mention_names=cfg.get('mention_names',[])
        self.aliases=cfg.get('aliases',[])
        digest=hashlib.sha1(name.encode()).hexdigest()[:8]
        path=state_dir/('context-%s.json'%digest)
        legacy=state_dir/'context.json'
        if not path.exists() and legacy.exists() and name==cfg.get('chat'):legacy.replace(path)
        self.ctx=ContextStore(path)
        self.echo=deque(maxlen=40)  # own replies, never treated as new incoming messages
        self.previous=None
        self.seen_path=state_dir/('seen-%s.json'%digest)
        self.seen_saved=0.0
        self.catching_up=False
        self.buffered=[]
        self.answer_job=None
        self.answer_followup_key=None
        self.followups={}
        self.progress=None       # status notes for a slow answer in flight
        self.auditor=Auditor()   # finds directed messages that were read but never answered
        self.followup_path=state_dir/('followup-%s.json'%digest)
        try:
            wall=time.time();mono=time.monotonic();limit=cfg.get('followup_seconds',120)
            for entry in json.loads(self.followup_path.read_text()):
                kind,value,expires=entry
                remaining=float(expires)-wall
                if kind in ('sig','name') and isinstance(value,str) and 0<remaining<=limit:
                    self.followups[(kind,value)]=mono+remaining
        except (OSError,ValueError,TypeError):pass
        self.last_change=0.0
        self.compaction=None
        self.compact_after=0.0
        self.banter_future=None
        self.banter_followup_key=None
        self.vision_jobs=[]      # (future, caption, sender) for images being described
        self.partial_sigs=set()  # images whose chat preview is only a slice
        self.opened_sigs=set()   # images already re-read from the original
        self.recent_media={}    # sender signature -> observation time for a later standalone mention
        self.image_pending=0     # new images waiting to be captured
        self.image_due=0.0
        self.image_retries=0
        self.banter_unseen=0     # new undirected messages not yet judged
        self.last_message=0.0
        self.last_banter_eval=0.0
        self.last_comment=0.0


class Worker:
    def __init__(self,cfg):
        self.cfg=cfg
        self.bridge=Bridge(cfg)
        self.db=sqlite3.connect(ROOT/'state'/'worker.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,status TEXT,created REAL,updated REAL,error TEXT)')
        self.db.commit()
        self.last_error=None
        self.list_text={};self.last_read={};self.last_active=0.0
        self.name_jobs={}
        names=cfg.get('chats') or [cfg['chat']]
        self.chats=[Chat(n,dict(cfg,chat=cfg.get('chat',names[0])),ROOT/'state') for n in names]
        self.senders=SenderBook(ROOT/'state'/'senders.json')
        self.affection=AffectionBook(ROOT/'state'/'affection.json')
        self.status('starting')

    def status(self,state,**extra):
        p=ROOT/'state'/'status.json'
        tmp=p.with_suffix('.tmp')
        tmp.write_text(json.dumps({'state':state,'updated':time.time(),'chats':[c.name for c in self.chats],**extra},ensure_ascii=False))
        tmp.replace(p)

    def set_job(self,id,state,error=None):
        now=time.time()
        self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,updated=excluded.updated,error=excluded.error',
                        (id,state,now,now,error))
        self.db.commit()

    def deliver(self,chat,id,reply,png):
        """Send text and/or formula image; an uncertain send pauses the bot and is never retried."""
        # Keep the sentinel for internal safety/accounting; vary only the public text.
        text=display_refusal(id,self.calm_for(chat,getattr(chat,'answer_speaker',None))) if is_refusal(reply.text) else reply.text
        parts=[]
        if text:parts.append(('/send',{'id':id,'chat':chat.name,'text':text}))
        if png:parts.append(('/send_image',{'id':id+'-img','chat':chat.name,'png':base64.b64encode(png).decode()}))
        self.set_job(id,'sending')
        if text:chat.echo.append(text)
        for path,payload in parts:
            result=self.bridge.request(path,payload)
            self.set_job(id,result['status'])
            if result['status']!='sent':
                (ROOT/'state'/'PAUSED').write_text('auto')
                raise RuntimeError('SEND_UNCERTAIN_PAUSED')

    def compact(self,chat):
        """Fold old messages into the summary in the background; state changes stay on the main thread."""
        if chat.compaction:
            future,batch=chat.compaction
            if not future.done():return
            chat.compaction=None
            try:
                summary=future.result()['summary'].strip()
                if input_reason(summary) or output_reason(summary,self.cfg.get('private_markers',[])):
                    summary=chat.ctx.summary
            except Exception as e:
                logging.warning('Context compaction failed: %s',e)
                chat.compact_after=time.monotonic()+60
                return
            chat.ctx.apply_compaction(batch,summary)
            logging.info('Context compacted: %d messages folded',len(batch))
            return
        batch=chat.ctx.compaction_batch()
        if not batch or time.monotonic()<chat.compact_after:return
        lines=[('DemoBot：' if m['role']=='assistant' else '')+labelled(m) for m in batch if not input_reason(m['content'])]
        guard_cfg=dict(self.cfg,model=self.cfg.get('gate_model',self.cfg.get('model')))
        future=POOL.submit(invoke,guard_cfg,SUMMARY_POLICY,{'previous_summary':chat.ctx.summary,'messages':lines},SUMMARY_SCHEMA)
        chat.compaction=(future,batch)

    def harvest_names(self):
        for sig,future in list(self.name_jobs.items()):
            if not future.done():continue
            del self.name_jobs[sig]
            try:self.senders.set(sig,future.result())
            except Exception as e:logging.info('Name reading failed: %s',e)

    def resolve_senders(self,chat,rows):
        """Nickname for each row (None when unknown). New name fingerprints are read once and cached."""
        unknown={r['sig'] for r in rows if r.get('sig') and not SYSTEM_ROW.search(r['text']) and not self.senders.get(r['sig'])}
        self.harvest_names()
        unknown-=set(self.name_jobs)
        unknown={sig for sig in unknown if not self.senders.get(sig)}
        if unknown:
            try:
                snap=self.bridge.request('/snapshot?chat='+urllib.parse.quote(chat.name)+'&strips=1')
                for r in snap['rows']:
                    sig=r.get('sig')
                    if sig in unknown and r.get('strip') and sig not in self.name_jobs:
                        self.name_jobs[sig]=POOL.submit(read_name,self.cfg,r['strip'])
            except Exception as e:
                logging.info('Sender lookup skipped: %s',e)
        return [self.senders.get(r['sig']) if r.get('sig') and not SYSTEM_ROW.search(r['text']) else None for r in rows]

    def note_multiline(self,rows):
        """Keep a few multi-line rows (quotes, forwards) on disk so their layout can be inspected."""
        path=ROOT/'state'/'multiline_rows.log'
        try:
            if path.exists() and path.stat().st_size>100_000:return
            lines=[t for t,o in rows if '\n' in t and not o]
            if lines:
                with path.open('a',encoding='utf-8') as f:
                    for t in lines:f.write(json.dumps(t[:300],ensure_ascii=False)+'\n')
        except OSError:pass

    def sigs_for(self,chat,name):
        """Name fingerprints to look for: [''] = the bot's own pictures, None = any sender."""
        if not name:return None
        key=name_key(name)
        if key in {name_key(n) for n in list(chat.mention_names)+list(chat.aliases)}:return ['']
        sigs=[sig for sig,n in self.senders.names.items() if name_key(n)==key]
        return sigs or None

    def wants_picture(self,chat,batch):
        """(name or None) when the question is about a picture: a quote of one, or a 'this picture' ask right after one."""
        found=next((m for e in batch for m in [IMAGE_QUOTE.search(e['content'])] if m),None)
        if found:return True,found.group('name')
        asking=any(ASKS_PICTURE.search(e['content']) for e in batch)
        recent=any('[图片]' in m['content'] for m in chat.ctx.messages[-8:]) or bool(chat.image_pending or chat.vision_jobs)
        return (True,None) if asking and recent else (False,None)

    def quoted_image(self,chat,batch):
        """Look at the picture a question is about: the original in WeChat's viewer, else the chat preview."""
        if not self.cfg.get('vision',True):return None
        wanted,name=self.wants_picture(chat,batch)
        if not wanted:return None
        sigs=self.sigs_for(chat,name)
        supplied=next((e.get('supplement_image_sig') for e in batch if e.get('supplement_image_sig')),None)
        if supplied:sigs=[supplied]
        if self.cfg.get('open_images',True):
            try:
                res=self.bridge.request('/open_image',{'chat':chat.name,'sigs':sigs,'pages':self.cfg.get('image_pages',4)})
                text=describe_pages(self.cfg,res['pages'])
                if text and not NOT_LOADED.search(text):
                    own=sigs==[''] or res.get('direction')=='outgoing'
                    if own:
                        chat.ctx.add('assistant','[图片] （机器人此前发送的原图，本轮被用户引用）'+text)
                        return '（机器人此前发送的图片）'+text
                    chat.ctx.add('user','[图片] （原图）'+text,sender=name)
                    return text
            except Exception as e:
                if 'VIEWER_NOT_CLOSED' in str(e):
                    (ROOT/'state'/'PAUSED').write_text('auto')    # never keep driving WeChat with a viewer stuck open
                    raise
                logging.info('Opening the picture failed (%s); using the chat preview',e)
        try:
            snap=self.bridge.request('/snapshot?chat='+urllib.parse.quote(chat.name)+'&images=1')
            rows=[r for r in snap['rows'] if r.get('png')]
            if sigs==['']:rows=[r for r in rows if r.get('outgoing')]
            elif sigs:rows=[r for r in rows if r.get('sig') in sigs]
            else:rows=[r for r in rows if r.get('sig')]
            if not rows:return None
            text=describe_image(self.cfg,rows[-1]['png'],rows[-1]['text'])
        except Exception as e:
            logging.info('Quoted image lookup failed: %s',e);return None
        if not text or NOT_LOADED.search(text):return None
        return ('（机器人此前发送的图片）'+text) if rows[-1].get('outgoing') else text

    def start_vision(self,chat,rows):
        """Note new images/stickers; they are captured a moment later, once WeChat has loaded them."""
        if not self.cfg.get('vision',True):return
        new=[r for r in rows if incoming_image(r)]
        if new:
            chat.image_pending+=len(new)
            chat.image_due=time.monotonic()+self.cfg.get('image_delay',2.5)

    def capture_images(self,chat):
        count,chat.image_pending=chat.image_pending,0
        if count<=0:return
        if len(chat.vision_jobs)>=4:
            chat.image_pending=count;chat.image_due=time.monotonic()+1;return
        try:
            snap=self.bridge.request('/snapshot?chat='+urllib.parse.quote(chat.name)+'&images=1')
        except Exception as e:
            logging.info('Image capture skipped: %s',e);return
        # Direction is checked both when queued and after the delayed recapture.
        crops=[r for r in snap['rows'] if r.get('png') and incoming_image(r)][-count:]
        if not crops and chat.image_retries<2:
            chat.image_retries+=1;chat.image_pending=count
            chat.image_due=time.monotonic()+self.cfg.get('image_retry_delay',4)
            logging.info('No loaded incoming image crop yet; retry=%d',chat.image_retries)
        for row in crops:
            future=POOL.submit(describe_image,self.cfg,row['png'],row['text'])
            if crop_is_partial(row['png']):chat.partial_sigs.add(row.get('sig'))
            chat.vision_jobs.append((future,row['text'],row.get('sig')))

    def vision_tick(self,chat):
        if chat.image_pending and time.monotonic()>=chat.image_due:self.capture_images(chat)
        remaining=[]
        for future,caption,sig in chat.vision_jobs:
            if not future.done():remaining.append((future,caption,sig));continue
            try:text=future.result()
            except Exception as e:
                logging.info('Image description failed: %s',e);text=None
            if text and NOT_LOADED.search(text):
                # Captured before the picture finished loading: look again shortly (twice at most).
                text=None
                if chat.image_retries<2:
                    chat.image_retries+=1;chat.image_pending+=1
                    chat.image_due=time.monotonic()+self.cfg.get('image_retry_delay',4)
            label='表情包' if caption.startswith(('Animated','[Sticker]','[动画表情]')) else '图片'
            if (text and label=='图片' and sig and sig not in chat.opened_sigs and self.cfg.get('open_images',True)
                    and self.cfg.get('open_partial_images',True) and (PARTIAL_PICTURE.search(text) or sig in chat.partial_sigs)):
                # The chat shows only a slice of the picture: open the original in WeChat's viewer, as for quoted pictures.
                chat.opened_sigs.add(sig)
                try:
                    res=self.bridge.request('/open_image',{'chat':chat.name,'sigs':[sig],'pages':self.cfg.get('image_pages',4)})
                    full=describe_pages(self.cfg,res['pages'])
                    if full and not NOT_LOADED.search(full):
                        logging.info('Preview was partial; read the original picture instead: chat=%s',chat.name)
                        text=full;label='原图'
                except Exception as e:
                    if 'VIEWER_NOT_CLOSED' in str(e):
                        (ROOT/'state'/'PAUSED').write_text('auto');raise
                    logging.info('Opening the original failed (%s); keeping the preview',e)
            if text:
                chat.image_retries=0
                entry=chat.ctx.add('user','[图片] （%s）%s'%(label,text),sender=self.senders.get(sig))
                entry['followup_key']=followup_key(self.senders.get(sig),sig)
                chat.banter_unseen+=1;chat.last_message=time.monotonic()
        chat.vision_jobs=remaining

    def banter_tick(self,chat):
        """Judge settled group chatter in the background; chip in only when something is really funny."""
        if not self.cfg.get('banter'):return
        last=next((m for m in reversed(chat.ctx.messages) if m['role']=='user'),None)
        if last is None:return
        now=time.monotonic()
        if chat.banter_future is not None:
            if not chat.banter_future.done():return
            future,chat.banter_future=chat.banter_future,None
            conversation,chat.banter_followup_key=chat.banter_followup_key,None
            try:text=future.result()
            except Exception:text=None
            png=None
            if isinstance(text,Reply):text,png=text.text,text.png   # factual comment with a typeset formula
            if text and now-chat.last_comment>=self.cfg.get('banter_cooldown',45):
                id=uuid.uuid4().hex
                self.set_job(id,'generating')
                try:
                    self.deliver(chat,id,Reply(text,''),png)
                    chat.ctx.add('assistant',text+('（已发送公式图片）' if png else ''));chat.last_comment=time.monotonic()
                    self.remember_followup(chat,conversation)
                    logging.info('Banter verified: chat=%s job=%s',chat.name,id)
                except Exception as e:
                    self.set_job(id,'failed',str(e));logging.warning('Banter stopped: %s',e)
            return
        if (chat.banter_unseen==0 or now-chat.last_message<self.cfg.get('banter_settle',1.5)
                or now-chat.last_banter_eval<self.cfg.get('banter_gap',8)
                or now-chat.last_comment<self.cfg.get('banter_cooldown',45)):return
        last=next((m for m in reversed(chat.ctx.messages) if m['role']=='user' and not m.get('pending')),None)
        chat.banter_followup_key=last.get('followup_key') if last else None
        comment=factual_comment if self.calm_for(chat,last.get('sender') if last else None) else banter
        chat.banter_future=BANTERS.submit(comment,self.cfg,chat.ctx.history())
        chat.last_banter_eval=now;chat.banter_unseen=0

    def owner_identity(self,chat,row,sender):
        names=self.cfg.get('owner_candidate_names',[])
        if row.get('outgoing') or not row.get('sig'):return False
        if sender not in names and row['sig'] not in self.cfg.get('owner_candidate_sigs',[]):return False
        try:
            result=self.bridge.request('/verify_owner',{'chat':chat.name,'text':row['text'],'sig':row['sig']})
            verified=result.get('owner_verified') is True
            logging.info('Owner identity checked: chat=%s verified=%s',chat.name,verified)
            return verified
        except Exception as e:
            if 'PROFILE_NOT_CLOSED' in str(e):
                (ROOT/'state'/'PAUSED').write_text('auto');raise
            logging.warning('Owner identity not verified: chat=%s error=%s',chat.name,e)
            return False

    def remember_followup(self,chat,conversation):
        """Renew after confirmed send; carry the short window across safe restarts."""
        if not conversation:return
        mono=time.monotonic();wall=time.time()
        chat.followups[conversation]=mono+self.cfg.get('followup_seconds',120)
        entries=[[kind,value,wall+expiry-mono] for (kind,value),expiry in chat.followups.items() if expiry>mono]
        try:
            tmp=chat.followup_path.with_suffix('.tmp')
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(entries,f,ensure_ascii=False)
            tmp.replace(chat.followup_path)
        except OSError as e:logging.warning('Could not save follow-up window: %s',e)

    def followup(self,chat,body,directed,sender,sig):
        """Only the same identified speaker can continue a recently addressed conversation."""
        now=time.monotonic()
        chat.followups={k:v for k,v in chat.followups.items() if v>now}
        key=followup_key(sender,sig)
        if not directed and key in chat.followups:
            reply,quoted_name,_=split_quote(body)
            to_other=bool(re.search(r'[@＠]',reply)) or '（引用' in body or quoted_name is not None
            directed=not to_other and bool(ASKING.search(reply) or re.search(r'你|继续|再说|展开|然后|举例',reply))
            if directed:logging.info('Follow-up accepted: chat=%s',chat.name)
        if directed and key:
            chat.followups[key]=now+self.cfg.get('followup_seconds',120)
        return directed

    def finish_answer(self,chat):
        if chat.answer_job is None:return
        future,id,started=chat.answer_job
        if not future.done():return
        chat.answer_job=None
        conversation,chat.answer_followup_key=chat.answer_followup_key,None
        try:
            reply=future.result()
            png=reply.png
            if reply.latex and not png:reply=Reply('公式排版失败了，换个问法再试试。','')
            if (ROOT/'state'/'PAUSED').exists():
                self.set_job(id,'cancelled');return
            self.deliver(chat,id,reply,png)
            self.remember_followup(chat,conversation)
            shown=reply.text or ('（已发送公式图片）' if png else '')
            if not is_refusal(reply.text):chat.ctx.add('assistant',shown)
            if self.cfg.get('affection',False) and not is_refusal(reply.text) and reply.mood:
                self.affection.apply(getattr(chat,'answer_speaker',''),reply.mood)
            logging.info('Reply verified: chat=%s job=%s elapsed=%.2fs since_mention_seen',chat.name,id,time.monotonic()-started)
            self.status('listening',last_reply=time.time())
        except Exception as e:
            self.set_job(id,'failed',str(e));self.status('error',error=str(e))
            logging.warning('Reply stopped: chat=%s error=%s',chat.name,e)
            # An uncertain send is never retried.

    def save_seen(self,chat,keys,force=False):
        """Remember the last rows read, so a restart can tell which messages arrived while it was down."""
        if not self.cfg.get('catchup_seconds',900):return
        now=time.time()
        if not force and now-chat.seen_saved<2:return
        chat.seen_saved=now
        data={'ts':now,'keys':[[t[:300],bool(o)] for t,o in keys[-60:]]}
        try:
            tmp=chat.seen_path.with_suffix('.tmp')
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False)
            tmp.replace(chat.seen_path)
        except OSError as e:
            logging.info('Could not save the read position: %s',e)

    def load_seen(self,chat):
        """Rows read before the last stop, or None when too much time has passed to answer them any more."""
        limit=self.cfg.get('catchup_seconds',900)
        if not limit:return None
        try:
            data=json.loads(chat.seen_path.read_text(encoding='utf-8'))
            if time.time()-float(data['ts'])>limit:return None
            return [(str(t),bool(o)) for t,o in data['keys']]
        except (OSError,ValueError,KeyError,TypeError):
            return None

    def auto_paused(self):
        """True when the bot paused itself (failed send check, stuck viewer): messages seen meanwhile are answered after resume."""
        try:return (ROOT/'state'/'PAUSED').read_text().strip()=='auto'
        except OSError:return False

    def rewind_seen(self,chat):
        """Forget the rows from the oldest unanswered question onward, so the catch-up on resume answers it."""
        pending=[e['content'] for e in chat.buffered]
        if chat.answer_job:pending+=[e['content'] for e in getattr(chat,'answer_batch',[])]
        if not pending or not chat.previous:return
        index=next((i for i,(text,_) in enumerate(chat.previous) if any(p and p in text for p in pending)),None)
        if index is None:return
        self.save_seen(chat,chat.previous[:index],force=True)
        logging.info('Paused with %d unanswered message(s): chat=%s; they will be answered after resume',len(pending),chat.name)

    def forget_seen(self):
        """Pausing means 'stop answering', so nothing from before the pause may be answered on resume."""
        for c in self.chats:
            c.followups.clear()
            try:c.followup_path.unlink()
            except FileNotFoundError:pass
            try:c.seen_path.unlink()
            except FileNotFoundError:pass

    def supplemented_question(self,chat,sender,sig):
        """Bind a standalone @ to this speaker's recent unaddressed turn only."""
        key=followup_key(sender,sig)
        if not key:return MENTION_ONLY
        if chat.answer_job and chat.answer_followup_key==key:return None
        now=time.time();limit=self.cfg.get('supplement_mention_seconds',120)
        media_ts=chat.recent_media.get(sig,0) if sig else 0
        for previous in reversed(chat.ctx.messages[-16:]):
            if now-previous.get('ts',0)>limit:break
            if previous['role']=='assistant':
                if media_ts>previous.get('ts',0):break
                return MENTION_ONLY  # don't replay a question already followed by an answer
            same=previous.get('followup_key')==key
            if not previous.get('followup_key') and sender and sender!='群友':same=previous.get('sender')==sender
            if not same:continue
            if previous.get('pending'):return None  # already waiting for this question's answer
            if previous['content']==MENTION_ONLY:continue
            if media_ts>previous.get('ts',0):break
            if previous['content'].startswith('[图片]'):
                return '请看看我刚发的图片（引用%s的消息：Image）'%(sender or '我')
            return '（补艾特，请回答我刚才这条消息）'+previous['content']
        if media_ts and 0<=now-media_ts<=limit:
            return '请看看我刚发的图片（引用%s的消息：Image）'%(sender or '我')
        return MENTION_ONLY

    def read_chat(self,chat):
        """Read the chat window and queue what is new. Returns None when there is nothing more to do this tick, else whether the fixed reply is due."""
        self.harvest_names()
        snap=self.bridge.request('/snapshot?chat='+urllib.parse.quote(chat.name))
        keys=[(r['text'],r['outgoing']) for r in snap['rows']]
        if not chat.auditor.started:
            chat.auditor.started=True;chat.auditor.mark(snap['rows'])      # what is on screen at start is not audited
        if chat.previous is None:
            saved=self.load_seen(chat)
            if not saved:
                chat.previous=keys
                self.save_seen(chat,keys,force=True)
                return None
            chat.previous=saved;chat.catching_up=True      # what arrived since is answered below
        fresh=new_rows(chat.previous,keys) if chat.previous else keys
        if keys and chat.previous and keys!=chat.previous and not fresh:
            logging.info('Message window reset without proven new rows: chat=%s',chat.name)
        tail=snap['rows'][len(snap['rows'])-len(fresh):] if fresh else []
        fixed_due=False
        if keys != chat.previous:
            chat.previous=keys
            self.save_seen(chat,keys)
            kept=[r for r in tail if not (r['outgoing'] and r['text'] in chat.echo)]
            fresh=[(r['text'],r['outgoing']) for r in kept]
            names=self.resolve_senders(chat,kept)
            self.note_multiline(fresh)
            self.start_vision(chat,kept)
            mine=list(chat.echo)+[m['content'] for m in chat.ctx.messages if m['role']=='assistant'][-8:]
            missed=[]
            for index,(row,sender) in enumerate(zip(kept,names)):
                if incoming_image(row) and row.get('sig'):chat.recent_media[row['sig']]=time.time()
                owner=self.owner_identity(chat,row,sender)
                # A message the bot already answered before it stopped has its own reply right after it.
                answered=chat.catching_up and any(r['outgoing'] for r in kept[index+1:])
                for body,directed,sender in classify_rows([(row['text'],row['outgoing'])],chat.mention_names,chat.aliases,mine,senders=[sender],with_sender=True):
                    supplemental=directed and body==MENTION_ONLY
                    if supplemental:
                        body=self.supplemented_question(chat,sender,row.get('sig'))
                        if body is None:continue
                        logging.info('Standalone mention linked: chat=%s context_found=%s',chat.name,body!=MENTION_ONLY)
                    directed=owner or self.followup(chat,body,directed,sender,row.get('sig'))
                    logging.info('Message classified: chat=%s directed=%s',chat.name,directed)
                    joke=fixed_trigger(body) and not self.calm_for(chat,sender)    # the stock joke is part of the sharp persona only
                    if chat.catching_up and (answered or joke):directed=False   # no stale answers or jokes
                    elif joke and not owner:directed=False;fixed_due=True
                    entry=chat.ctx.add('user',body,pending=directed,sender=sender)
                    if supplemental and body.startswith('请看看我刚发的图片') and row.get('sig'):
                        entry['supplement_image_sig']=row['sig']
                    entry['owner_verified']=owner
                    entry['followup_key']=followup_key(sender,row.get('sig'))
                    if directed:
                        entry['speaker_key']=row.get('sig') or sender or uuid.uuid4().hex
                        entry['observed_at']=time.monotonic()
                        chat.buffered.append(entry);chat.last_change=time.monotonic()
                        if chat.catching_up:missed.append(entry)
                    elif not joke and not chat.catching_up:
                        chat.banter_unseen+=1;chat.last_message=time.monotonic()
            chat.auditor.mark(kept)              # every row that reached the classifier has been decided about
            if chat.catching_up:
                limit=self.cfg.get('catchup_max',4)
                for stale in missed[:-limit] if limit else missed:     # only the newest few are still worth answering
                    stale['pending']=False
                    if stale in chat.buffered:chat.buffered.remove(stale)
                kept_n=len([m for m in missed if m in chat.buffered])
                if fresh:logging.info('Caught up after downtime: chat=%s new_rows=%d to_answer=%d',chat.name,len(fresh),kept_n)
        chat.catching_up=False
        self.audit_missed(chat,snap['rows'])
        return fixed_due

    def needs_read(self,chat,listing,now):
        """Only open and scan a chat when its entry in the chat list changed, work needs a look, or a periodic check is due."""
        if listing is None or chat.previous is None or chat.image_pending:return True
        if listing.get(chat.name)!=self.list_text.get(chat.name):return True
        return now-self.last_read.get(chat.name,0)>=self.cfg.get('idle_refresh_seconds',10)

    def step(self,chat,read=True):
        fixed_due=False
        if read:
            self.last_read[chat.name]=time.monotonic()
            fixed_due=self.read_chat(chat)
            if fixed_due is None:return
        self.vision_tick(chat)
        if fixed_due:
            id=uuid.uuid4().hex
            self.set_job(id,'generating')
            try:
                self.deliver(chat,id,Reply(FIXED_REPLY,''),None)
                chat.ctx.add('assistant',FIXED_REPLY)
                logging.info('Fixed reply verified: job=%s',id)
            except Exception as e:
                self.set_job(id,'failed',str(e));self.status('error',error=str(e))
                logging.warning('Reply stopped: %s',e)
        self.finish_answer(chat)
        self.progress_tick(chat)
        if chat.answer_job is None and chat.buffered and (
                time.monotonic()-chat.last_change>=self.cfg['debounce_seconds'] or
                time.monotonic()-chat.buffered[0].get('observed_at',chat.last_change)>=2):
            # Merge only adjacent questions from the same speaker. Other speakers
            # get their own turn, so one answer cannot silently swallow their ask.
            count=1
            while count<len(chat.buffered) and chat.buffered[count].get('speaker_key')==chat.buffered[0].get('speaker_key') and chat.buffered[count].get('owner_verified',False)==chat.buffered[0].get('owner_verified',False):
                count+=1
            batch=chat.buffered[:count];del chat.buffered[:count];started=time.monotonic()
            id=uuid.uuid4().hex
            self.set_job(id,'generating')
            self.status('generating')
            try:
                for e in batch:
                    if not e.get('sender'):e['sender']=self.senders.get(e.get('speaker_key'))
                question='\n'.join(labelled(e) for e in batch)
                prompt_context=chat.ctx.history(exclude=batch)
                picture=self.quoted_image(chat,batch)
                if picture:prompt_context.append({'role':'user','content':'[图片] （被引用的图片）'+picture})
                picture_missing=self.wants_picture(chat,batch)[0] and not picture
                prompt_context.append({'role':'user','content':question})
                for e in batch:e['pending']=False
                chat.ctx.save()
                turn_cfg=dict(self.cfg,_verified_owner_turn=all(e.get('owner_verified') is True for e in batch),_calm=self.calm_for(chat,batch[0].get('sender')),_picture_missing=picture_missing,_mention_only=all(e['content']==MENTION_ONLY for e in batch))
                speaker=batch[0].get('sender') or batch[0].get('speaker_key') or ''
                if self.cfg.get('affection',False):turn_cfg.update(_affection=self.affection.get(speaker),_speaker=batch[0].get('sender'))
                chat.answer_speaker=speaker;chat.answer_batch=batch
                chat.answer_followup_key=batch[0].get('followup_key')
                hard=bool(self.cfg.get('agy_hard_model')) and not needs_fresh(question) and is_hard(question)
                chat.progress=None
                if hard:
                    chat.progress={'t0':started,'stage':'thinking','calm':bool(turn_cfg.get('_calm')),'waits':0,'next_wait':30,'answering_told':False}
                    turn_cfg['_stage']=lambda stage,pr=chat.progress:pr.__setitem__('stage',stage)
                chat.answer_job=(ANSWERS.submit(generate,turn_cfg,prompt_context),id,started)
                if hard:self.send_progress(chat,random.choice(PROGRESS_START[chat.progress['calm']]))
            except Exception as e:
                self.set_job(id,'failed',str(e));self.status('error',error=str(e))
                logging.warning('Reply preparation stopped: chat=%s error=%s',chat.name,e)
                self.requeue(chat,batch)
        elif not chat.buffered and chat.answer_job is None:
            self.compact(chat)
            self.banter_tick(chat)

    def send_progress(self,chat,text):
        """A short status line for a slow answer. It is not part of the conversation context."""
        id=uuid.uuid4().hex
        self.set_job(id,'generating')
        try:
            self.deliver(chat,id,Reply(text,''),None)
            logging.info('Progress note sent: chat=%s',chat.name)
        except Exception as e:
            self.set_job(id,'failed',str(e))
            logging.warning('Progress note failed: %s',e)

    def progress_tick(self,chat):
        """Tell the group how a slow answer is going, using only what is really known: elapsed time and whether the
        model has started writing (agy reports no reasoning text, so nothing about individual steps is invented)."""
        pr=getattr(chat,'progress',None)
        if not pr:return
        if chat.answer_job is None:
            chat.progress=None;return
        now=time.monotonic()
        elapsed=now-pr['t0']
        if pr['stage']=='answering':
            # Typesetting usually finishes within seconds, so only say something if the writing phase drags on.
            pr.setdefault('answering_at',now)
            if not pr['answering_told'] and now-pr['answering_at']>=8:
                pr['answering_told']=True
                self.send_progress(chat,random.choice(PROGRESS_ANSWERING[pr['calm']]))
        elif pr['waits']<2 and elapsed>=pr['next_wait']:
            pr['waits']+=1;pr['next_wait']+=30
            self.send_progress(chat,PROGRESS_WAITING[pr['calm']]%int(elapsed))

    def audit_missed(self,chat,rows):
        """Queue directed messages that were read but slipped past the normal path (see audit.py)."""
        if not self.cfg.get('audit',True):return
        mine=list(chat.echo)+[m['content'] for m in chat.ctx.messages if m['role']=='assistant'][-8:]
        def directed(row):
            return any(d and b!=MENTION_ONLY for b,d,_ in classify_rows([(row['text'],False)],chat.mention_names,chat.aliases,mine,senders=[None],with_sender=True))
        for row in chat.auditor.find_missed(rows,time.monotonic(),directed):
            names=self.resolve_senders(chat,[row])
            for body,is_directed,sender in classify_rows([(row['text'],False)],chat.mention_names,chat.aliases,mine,senders=[names[0]],with_sender=True):
                if not is_directed or body==MENTION_ONLY:continue
                entry=chat.ctx.add('user',body,pending=True,sender=sender)
                entry['speaker_key']=row.get('sig') or sender or uuid.uuid4().hex
                entry['observed_at']=time.monotonic()
                entry['followup_key']=followup_key(sender,row.get('sig'))
                chat.buffered.append(entry);chat.last_change=time.monotonic()
                logging.warning('Audit: a mention was read but never answered; answering it now: chat=%s',chat.name)
            chat.auditor.recovered([row],time.monotonic())

    def calm_for(self,chat,sender):
        """In the calm groups only the listed speakers (MemberA, memberb.) keep the sharp-tongued persona."""
        if chat.name not in self.cfg.get('calm_chats',[]):return False
        return name_key(sender or '').strip('.') not in {name_key(n).strip('.') for n in self.cfg.get('spicy_speakers',[])}

    def requeue(self,chat,batch):
        """A failure before any answer was sent must not silently drop the question: try again shortly, a couple of times."""
        delay=self.cfg.get('prepare_retry_delay',5)
        retry=[e for e in batch if e.get('tries',0)<self.cfg.get('prepare_retries',2)]
        for e in retry:
            e['tries']=e.get('tries',0)+1
            e['pending']=True
            e['observed_at']=time.monotonic()+delay
        chat.buffered[:0]=retry
        chat.last_change=time.monotonic()+delay
        if len(retry)<len(batch):
            logging.warning('Gave up on %d message(s) after repeated failures: chat=%s',len(batch)-len(retry),chat.name)

    def prompt_login(self):
        """After WeChat drops the session (e.g. a client crash), ask the phone to confirm the login again.

        Rate-limited so the phone is not spammed; the owner still has to confirm every time.
        """
        now=time.monotonic()
        interval=self.cfg.get('login_prompt_interval',900)
        if now-getattr(self,'last_login_prompt',-interval)<interval:return
        if getattr(self,'login_prompts',0)>=self.cfg.get('login_prompt_limit',4):return
        self.last_login_prompt=now
        try:
            result=self.bridge.request('/request_login',{})
        except Exception as e:
            logging.warning('Login prompt failed: %s',e);return
        if result.get('status')=='prompt_sent':
            self.login_prompts=getattr(self,'login_prompts',0)+1
            logging.warning('WeChat is logged out; sent a login confirmation to the phone (%d)',self.login_prompts)

    def run(self):
        while True:
            try:
                if (ROOT/'state'/'PAUSED').exists():
                    self.status('paused')
                    keep=self.auto_paused()
                    if not keep:self.forget_seen()
                    for c in self.chats:
                        if keep:self.rewind_seen(c)
                        c.previous=None;c.buffered=[];c.followups.clear()
                        if c.answer_job:
                            future,id,_=c.answer_job;future.cancel();self.set_job(id,'cancelled');c.answer_job=None
                    time.sleep(3);continue
                listing=None
                try:
                    health=self.bridge.request('/overview')
                    if health.get('ok'):listing=health.get('chats') or {}
                    else:health=self.bridge.request('/status?chat='+urllib.parse.quote(self.chats[0].name))
                except Exception:
                    health=self.bridge.request('/status?chat='+urllib.parse.quote(self.chats[0].name))
                if not health.get('logged_in') or health.get('locked'):
                    if not health.get('logged_in'):self.prompt_login()
                    self.status('login_required' if not health.get('logged_in') else 'wechat_locked')
                    for c in self.chats:
                        c.previous=None;c.buffered=[];c.followups.clear()
                        if c.answer_job:
                            future,id,_=c.answer_job;future.cancel();self.set_job(id,'cancelled');c.answer_job=None
                    time.sleep(4);continue
                self.login_prompts=0
                errors={}
                for chat in self.chats:
                    if (ROOT/'state'/'PAUSED').exists():break
                    try:
                        now=time.monotonic()
                        read=self.needs_read(chat,listing,now)
                        if listing is not None and listing.get(chat.name)!=self.list_text.get(chat.name):self.last_active=now
                        self.step(chat,read)
                        if read and listing is not None:self.list_text[chat.name]=listing.get(chat.name)
                    except Exception as e:
                        errors[chat.name]=str(e)
                        logging.warning('Chat polling failed: chat=%s error=%s',chat.name,e)
                state=('paused' if (ROOT/'state'/'PAUSED').exists() else
                       'waiting' if errors else 'generating' if any(c.answer_job for c in self.chats) else 'listening')
                self.status(state,poll_errors=errors,queued_messages=sum(len(c.buffered) for c in self.chats),model_calls=dict(backend.stats),audit_recovered=sum(c.auditor.recovered_total for c in self.chats),model_pool=agy_model.metrics() if self.cfg.get('backend')=='agy' else {})
                self.last_error=None
                busy=any(c.answer_job or c.buffered or c.catching_up or c.image_pending or c.vision_jobs for c in self.chats)
                if busy:self.last_active=time.monotonic()
                recent=time.monotonic()-self.last_active<self.cfg.get('active_window_seconds',8)
                time.sleep(self.cfg['poll_seconds'] if busy or recent or listing is None else self.cfg.get('idle_poll_seconds',0.6))
            except Exception as e:
                self.status('waiting',error=str(e))
                if str(e)!=self.last_error:logging.warning('Waiting: %s',e)
                self.last_error=str(e)
                time.sleep(5)


def main():
    os.umask(0o077)
    cfg=json.loads((ROOT/'config.json').read_text())
    for d in ['state','runtime/codex-work']:(ROOT/d).mkdir(parents=True,exist_ok=True)
    parser=argparse.ArgumentParser()
    parser.add_argument('--check-model',action='store_true')
    parser.add_argument('--status',action='store_true')
    args=parser.parse_args()
    if args.check_model:
        print(generate(cfg,[{'role':'user','content':'请只回答2+2的结果。'}]).text);return
    if args.status:
        try:
            bridge_status=Bridge(cfg).request('/status')
        except Exception as e:
            bridge_status={'ok':False,'error':str(e),'next_step':'Check the desktop container with docker compose ps/logs.'}
        print(json.dumps(bridge_status,ensure_ascii=False))
        if (ROOT/'state'/'status.json').exists():print((ROOT/'state'/'status.json').read_text())
        return
    lock=open(ROOT/'state'/'worker.lock','w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Another worker is already running')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    if cfg.get('backend')=='agy':agy_model.start(cfg)   # start the warm pool before the first message
    Worker(cfg).run()


if __name__=='__main__':main()
