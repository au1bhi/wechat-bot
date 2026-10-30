"""Small, authenticated AT-SPI bridge confined to a dedicated X11 container."""
import base64
import io
import hashlib
import subprocess
import hmac
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi, GLib
from Xlib import X, XK, display
from Xlib.ext import xtest
from PIL import Image, ImageChops

STATE = Path('/home/wechat/bot-state')
STATE.mkdir(parents=True, exist_ok=True)
TOKEN = Path('/run/secrets/bridge_token').read_text().strip()
CHAT = os.environ.get('BOT_CHAT', 'Example Group A')
CHATS_FILE = STATE / 'chats.json'


def allowed_chats():
    """Chats the bridge may touch. The host writes this list; the default is the single env chat."""
    try:
        names = json.loads(CHATS_FILE.read_text())
        if isinstance(names, list) and all(isinstance(n, str) and 0 < len(n) <= 100 for n in names) and names:
            return names
    except (OSError, ValueError):
        pass
    return [os.environ.get('BOT_CHAT', 'Example Group A')]


def use_chat(name):
    """Select the chat for this request. The server is single-threaded, so a global is safe."""
    global CHAT
    if name not in allowed_chats():
        raise RuntimeError('CHAT_NOT_ALLOWED')
    CHAT = name
DB = sqlite3.connect(STATE / 'sends.sqlite3')
DB.execute('CREATE TABLE IF NOT EXISTS sends (id TEXT PRIMARY KEY, digest TEXT, status TEXT, created REAL)')
DB.commit()


def visible(n):
    return n.get_state_set().contains(Atspi.StateType.VISIBLE)


def walk(n, depth=0):
    if depth > 40 or not visible(n):
        return
    yield n
    for i in range(min(max(n.get_child_count(), 0), 150)):
        yield from walk(n.get_child_at_index(i), depth + 1)


def app():
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)
    r = Atspi.get_desktop(0)
    r.clear_cache()
    for i in range(r.get_child_count()):
        a = r.get_child_at_index(i)
        if a.get_name().lower() in ('wechat', 'weixin'):
            a.clear_cache()
            return a
    raise RuntimeError('WAITING_FOR_WECHAT')


def bounds(n):
    r = Atspi.Component.get_extents(n, Atspi.CoordType.SCREEN)
    return r.x, r.y, r.width, r.height


def click(n):
    x, y, w, h = bounds(n)
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        raise RuntimeError('CONTROL_NOT_VISIBLE')
    d = display.Display()
    try:
        xtest.fake_input(d, X.MotionNotify, x=x+w//2, y=y+h//2)
        xtest.fake_input(d, X.ButtonPress, 1)
        xtest.fake_input(d, X.ButtonRelease, 1)
        d.sync()
    finally:
        d.close()


def enter():
    d = display.Display()
    try:
        key = d.keysym_to_keycode(XK.string_to_keysym('Return'))
        xtest.fake_input(d, X.KeyPress, key)
        xtest.fake_input(d, X.KeyRelease, key)
        d.sync()
    finally:
        d.close()


def screenshot():
    d = display.Display()
    try:
        r = d.screen().root
        g = r.get_geometry()
        raw = r.get_image(0, 0, g.width, g.height, X.ZPixmap, 0xffffffff)
        return Image.frombytes('RGB', (g.width, g.height), raw.data, 'raw', 'BGRX')
    finally:
        d.close()


SEARCH_NAMES = ('Search', '搜索')


def message_entries(ns):
    return [n for n in ns if n.get_role_name() == 'text' and n.get_name() not in SEARCH_NAMES]


def selected(ns):
    labels = [n.get_name() for n in ns if n.get_role_name() == 'label']
    # Match the exact header and require exactly one message entry next to it.
    header = any(s == CHAT or re.fullmatch(re.escape(CHAT)+r'\s*[（(]\d+[)）]', s) for s in labels)
    return header and len(message_entries(ns)) == 1


def unlocked(ns):
    return not any('is locked' in n.get_name() or '已锁定' in n.get_name() for n in ns)


def open_chat():
    a = app()
    ns = list(walk(a))
    if not unlocked(ns):
        raise RuntimeError('WECHAT_LOCKED')
    if selected(ns):
        return
    candidates = [n for n in ns if n.get_role_name() == 'list item'
                  and n.get_name().split('\n')[0] == CHAT]
    if not candidates:
        searches = [n for n in ns if n.get_role_name() == 'text' and n.get_name() in ('Search', '搜索')]
        if len(searches) != 1:
            raise RuntimeError('CHAT_NOT_FOUND: '+CHAT)
        search = searches[0]
        click(search)
        Atspi.EditableText.set_text_contents(search, CHAT)
        time.sleep(1)
        ns = list(walk(a))
        candidates = [n for n in ns if n.get_role_name() == 'list item'
                      and n.get_name().split('\n')[0] == CHAT]
    if len(candidates) != 1:
        raise RuntimeError('CHAT_NOT_UNIQUE: '+CHAT)
    click(candidates[0])
    for _ in range(30):
        time.sleep(.1)
        if selected(list(walk(a))):
            return
    raise RuntimeError('CHAT_HEADER_NOT_VERIFIED')


def status():
    try:
        ns = list(walk(app()))
        names = [n.get_name() for n in ns if n.get_name()]
        login = any(n.get_role_name() == 'list' and n.get_name() in ('Chats', '会话') for n in ns)
        return {'ok': True, 'logged_in': login, 'locked': not unlocked(ns),
                'chat': CHAT, 'chat_selected': selected(ns),
                'screen': 'ready' if login else 'login_required',
                'labels': names[:15] if not login else []}
    except Exception as e:
        return {'ok': False, 'logged_in': False, 'error': str(e), 'chat': CHAT}


def overview():
    """Read each required UI property once and never descend into message bubbles."""
    try:
        chats={};login=False;locked=False
        pending=[(app(),0)]
        while pending:
            n,depth=pending.pop()
            if depth>40 or not visible(n):continue
            role=n.get_role_name();name=n.get_name()
            if 'is locked' in name or '已锁定' in name:locked=True
            if role=='list' and name in ('Chats','会话'):
                login=True
                for i in range(n.get_child_count()):
                    child=n.get_child_at_index(i)
                    if child is not None:
                        preview=child.get_name()
                        if preview:chats.setdefault(preview.split('\n')[0],preview)
                continue
            if role=='list' and name in ('Messages','消息'):continue
            count=min(max(n.get_child_count(),0),150)
            pending.extend((n.get_child_at_index(i),depth+1) for i in range(count-1,-1,-1))
        return {'ok':True,'logged_in':login,'locked':locked,'chats':chats if login else {}}
    except Exception as e:
        return {'ok':False,'logged_in':False,'error':str(e)}


IMAGE_ROW = re.compile(r'^(?:Image|Animated Stickers|\[Photo\]|\[Sticker\]|\[图片\]|\[动画表情\])')


def crop_png(img, limit=768):
    """Downscale a row crop and return it as base64 PNG, small enough to send to a vision model."""
    img = img.copy()
    img.thumbnail((limit, limit))
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'PNG', optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def name_strip(crop, width):
    """Fingerprint of the sender name drawn above an incoming bubble (None when there is none).

    The same nickname is rendered with identical pixels, so the fingerprint is a stable key;
    the host maps it to a text name once (via a vision model) and caches that.
    """
    strip = crop.crop((60, 0, min(width, 420), 24)).convert('L')
    ink = strip.point(lambda v: 255 if v < 205 else 0)
    box = ink.getbbox()
    if not box or box[2]-box[0] < 6:
        return None, None
    core = ink.crop(box)
    sig = hashlib.sha1(core.tobytes() + repr(core.size).encode()).hexdigest()[:12]
    return sig, strip


def strip_png(strip):
    big = strip.resize((strip.width*3, strip.height*3), Image.LANCZOS)
    buf = io.BytesIO()
    big.convert('RGB').save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode()



def message_direction(crop, media=False, avatar_visible=True):
    """Use avatar gutters, which media content cannot reach, before bubble color.

    Qt's message rows span the list width. At this desktop's fixed 96 DPI,
    avatars occupy 36px squares, inset 20px horizontally and 8px vertically.
    Uncertain media must never be treated as an incoming message.
    """
    w,h=crop.size
    if avatar_visible and w>=140 and h>=44:
        background=crop.getpixel((2,10))
        def avatar_score(left):
            pixels=crop.crop((left,8,left+36,44)).getdata()
            return sum(max(abs(a-b) for a,b in zip(pixel,background))>20 for pixel in pixels)
        left,right=avatar_score(20),avatar_score(w-57)
        if right>=60 and left<20:return 'outgoing'
        if left>=60 and right<20:return 'incoming'
    if media:return 'unknown'
    samples=list(crop.crop((w//2,0,w,h)).getdata())[::5]
    green=sum(g>95 and g-r>25 and g-b>12 for r,g,b in samples)
    return 'outgoing' if green>max(25,len(samples)*.025) else 'incoming'


def snapshot(images=False, strips=False):
    open_chat()
    ns = list(walk(app()))
    lists = [n for n in ns if n.get_role_name() == 'list' and n.get_name() in ('Messages', '消息')]
    if len(lists) != 1:
        raise RuntimeError('MESSAGE_LIST_NOT_UNIQUE')
    shot = screenshot()
    lx,ly,lw,lh=bounds(lists[0])
    rows = []
    for i in range(lists[0].get_child_count()):
        n = lists[0].get_child_at_index(i)
        text = n.get_name()
        if not visible(n) or not text:
            continue
        x, y, w, h = bounds(n)
        if h < 1 or (h <= 42 and re.fullmatch(r'(?:[^\n]{0,30}\s+)?\d{1,2}:\d{2}', text)):
            continue  # Time separators are not messages.
        if x < 0 or y < 0 or y+h > shot.height or x+w > shot.width:
            continue
        crop = shot.crop((x, y, x+w, y+h))
        media=bool(IMAGE_ROW.match(text))
        avatar_visible=(y>=ly and y+44<=ly+lh)
        fully_visible=(y>=ly and y+h<=ly+lh)
        direction=message_direction(crop,media=media,avatar_visible=avatar_visible)
        outgoing=direction=='outgoing'
        row={'text':text,'outgoing':outgoing,'direction':direction}
        if direction=='incoming' and avatar_visible:
            try:
                sig, strip = name_strip(crop, w)
            except Exception:
                sig, strip = None, None  # never let a name fingerprint break a snapshot
            if sig:
                row['sig'] = sig
                if strips:
                    row['strip'] = strip_png(strip)
        if images and media and fully_visible:
            row['png'] = crop_png(crop)
        rows.append(row)
    return {'chat': CHAT, 'rows': rows}


def send(data):
    use_chat(data.get('chat'))
    opid = data.get('id', '')
    text = data.get('text', '')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', opid) or not isinstance(text,str) or not 1 <= len(text) <= 1500:
        raise RuntimeError('INVALID_SEND')
    digest = hashlib.sha256(text.encode()).hexdigest()
    old = DB.execute('SELECT digest,status FROM sends WHERE id=?', (opid,)).fetchone()
    if old:
        if old[0] != digest:
            raise RuntimeError('IDEMPOTENCY_CONFLICT')
        return {'status': old[1], 'replayed': True}
    open_chat()
    ns = list(walk(app()))
    if not selected(ns):
        raise RuntimeError('CHAT_HEADER_NOT_VERIFIED')
    entry = message_entries(ns)[0]
    if Atspi.Text.get_text(entry,0,-1):
        raise RuntimeError('EXISTING_DRAFT')
    if not Atspi.EditableText.set_text_contents(entry,text) or Atspi.Text.get_text(entry,0,-1) != text:
        raise RuntimeError('INPUT_VERIFICATION_FAILED')
    # Persist BEFORE the physical send. An uncertain send is never retried.
    DB.execute('INSERT INTO sends VALUES (?,?,?,?)',(opid,digest,'uncertain',time.time()))
    DB.commit()
    ns = list(walk(app()))
    if not selected(ns):
        raise RuntimeError('CHAT_CHANGED')
    button = next((n for n in ns if n.get_role_name() == 'push button' and n.get_name() in ('Send','发送')),None)
    if button:
        click(button)
    else:
        click(entry)
        enter()
    for _ in range(30):
        time.sleep(.1)
        current = Atspi.Text.get_text(entry,0,-1)
        if not current:
            snap = snapshot()
            if any(r['text'] == text for r in snap['rows']):
                DB.execute('UPDATE sends SET status=? WHERE id=?',('sent',opid))
                DB.commit()
                return {'status':'sent'}
    return {'status':'uncertain'}


def paste():
    d = display.Display()
    try:
        ctrl = d.keysym_to_keycode(XK.string_to_keysym('Control_L'))
        v = d.keysym_to_keycode(XK.string_to_keysym('v'))
        xtest.fake_input(d, X.KeyPress, ctrl)
        xtest.fake_input(d, X.KeyPress, v)
        xtest.fake_input(d, X.KeyRelease, v)
        xtest.fake_input(d, X.KeyRelease, ctrl)
        d.sync()
    finally:
        d.close()


def image_count():
    return sum(1 for r in snapshot()['rows'] if r['text'] == 'Image')


def confirmed_image_send(before,after):
    """Use a unique preceding message when older images scroll out of view."""
    outgoing=lambda rows:[r for r in rows if r.get('text')=='Image' and r.get('direction')=='outgoing']
    if not outgoing(after):return False
    if before and before[-1].get('text')!='Image':
        anchor=before[-1].get('text','')
        matches=[i for i,r in enumerate(after) if r.get('text')==anchor]
        if anchor and sum(r.get('text')==anchor for r in before)==1 and len(matches)==1:
            return bool(outgoing(after[matches[0]+1:]))
    # Consecutive images have no unique text anchor: retain the conservative fallback.
    return len(outgoing(after))>len(outgoing(before))


def send_image(data):
    use_chat(data.get('chat'))
    opid = data.get('id', '')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', opid):
        raise RuntimeError('INVALID_SEND')
    raw = base64.b64decode(data.get('png', ''), validate=True)
    if not raw.startswith(b'\x89PNG\r\n\x1a\n') or not 200 <= len(raw) <= 3_000_000:
        raise RuntimeError('INVALID_IMAGE')
    digest = hashlib.sha256(raw).hexdigest()
    old = DB.execute('SELECT digest,status FROM sends WHERE id=?', (opid,)).fetchone()
    if old:
        if old[0] != digest:
            raise RuntimeError('IDEMPOTENCY_CONFLICT')
        return {'status': old[1], 'replayed': True}
    open_chat()
    ns = list(walk(app()))
    if not selected(ns):
        raise RuntimeError('CHAT_HEADER_NOT_VERIFIED')
    entry = message_entries(ns)[0]
    if Atspi.Text.get_text(entry,0,-1):
        raise RuntimeError('EXISTING_DRAFT')
    before = snapshot()['rows']
    path = STATE / ('img-'+opid+'.png')
    path.write_bytes(raw)
    subprocess.run(['xclip','-selection','clipboard','-t','image/png','-i',str(path)],
                   check=True,timeout=10,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    DB.execute('INSERT INTO sends VALUES (?,?,?,?)',(opid,digest,'uncertain',time.time()))
    DB.commit()
    click(entry)
    time.sleep(.3)
    paste()
    time.sleep(1.2)
    enter()
    for _ in range(40):
        time.sleep(.25)
        if confirmed_image_send(before,snapshot()['rows']):
            DB.execute('UPDATE sends SET status=? WHERE id=?',('sent',opid))
            DB.commit()
            path.unlink(missing_ok=True)
            return {'status':'sent'}
    return {'status':'uncertain'}


def click_xy(x, y):
    d = display.Display()
    try:
        xtest.fake_input(d, X.MotionNotify, x=x, y=y)
        xtest.fake_input(d, X.ButtonPress, 1)
        xtest.fake_input(d, X.ButtonRelease, 1)
        d.sync()
    finally:
        d.close()


def press_key(name):
    d = display.Display()
    try:
        key = d.keysym_to_keycode(XK.string_to_keysym(name))
        xtest.fake_input(d, X.KeyPress, key)
        xtest.fake_input(d, X.KeyRelease, key)
        d.sync()
    finally:
        d.close()


def wheel(x, y, button, clicks):
    d = display.Display()
    try:
        xtest.fake_input(d, X.MotionNotify, x=x, y=y)
        for _ in range(clicks):
            xtest.fake_input(d, X.ButtonPress, button)
            xtest.fake_input(d, X.ButtonRelease, button)
        d.sync()
    finally:
        d.close()


def viewer_frame():
    """The picture viewer is a second top-level frame next to the main 'Weixin' one."""
    return next((n for n in walk(app()) if n.get_role_name() == 'frame' and n.get_name() != 'Weixin'), None)


def close_viewer():
    for attempt in range(3):
        if viewer_frame() is None:
            return
        if attempt == 0:
            press_key('Escape')
        else:
            frame = viewer_frame()
            button = next((n for n in walk(frame) if n.get_role_name() == 'push button'
                           and n.get_name() in ('Close', '关闭')), None) if frame else None
            if button:
                click(button)
        for _ in range(10):
            time.sleep(.2)
            if viewer_frame() is None:
                return
    raise RuntimeError('VIEWER_NOT_CLOSED')


def page_png(img, limit=1600):
    img = img.copy()
    img.thumbnail((limit, limit))
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'PNG', optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def press_button(frame, names):
    button = next((n for n in walk(frame) if n.get_role_name() == 'push button' and n.get_name() in names), None)
    if button is None:
        raise RuntimeError('VIEWER_BUTTON_NOT_FOUND: ' + names[0])
    click(button)


def drag(x1, y1, x2, y2):
    d = display.Display()
    try:
        xtest.fake_input(d, X.MotionNotify, x=x1, y=y1)
        xtest.fake_input(d, X.ButtonPress, 1)
        d.sync()
        for step in range(1, 9):
            xtest.fake_input(d, X.MotionNotify, x=x1+(x2-x1)*step//8, y=y1+(y2-y1)*step//8)
            d.sync()
            time.sleep(.02)
        xtest.fake_input(d, X.ButtonRelease, 1)
        d.sync()
    finally:
        d.close()


def content_aspect(view):
    """Height/width of the picture inside the viewer (the viewer's own background is a flat grey)."""
    gray = view.convert('L')
    background = gray.getpixel((4, 4))
    box = gray.point(lambda v: 255 if abs(v-background) > 3 else 0).getbbox()
    if not box or box[2]-box[0] < 10:
        return 0
    return (box[3]-box[1]) / (box[2]-box[0])


def wait_viewer_image(frame, timeout=5):
    """Wait for painted, stable image pixels rather than a fixed animation delay."""
    deadline=time.monotonic()+timeout
    previous=None;stable=0
    while True:
        frame=viewer_frame() or frame
        fx,fy,fw,fh=bounds(frame)
        view=screenshot().crop((fx,fy+42,fx+fw,fy+fh))
        thumb=view.convert('L').resize((128,128))
        colors=thumb.getcolors(16384) or []
        nonflat=len(colors)>8 and thumb.getextrema()[1]-thumb.getextrema()[0]>35
        stable=stable+1 if previous is not None and ImageChops.difference(thumb,previous).getbbox() is None else 0
        if nonflat and stable>=2:return view
        if time.monotonic()>=deadline:
            if not nonflat:raise RuntimeError('IMAGE_NOT_LOADED')
            return view  # animated pictures need not become perfectly still
        previous=thumb
        time.sleep(.2)


def open_image(data):
    """Reveal a clipped image's avatar before selecting it, then restore the viewport."""
    moved=0;area=None
    try:
        for attempt in range(4):
            try:return open_image_visible(data)
            except RuntimeError as e:
                if str(e)!='IMAGE_NOT_VISIBLE' or attempt==3:raise
            ls=[n for n in walk(app()) if n.get_role_name()=='list' and n.get_name() in ('Messages','消息')]
            if len(ls)!=1:raise RuntimeError('MESSAGE_LIST_NOT_UNIQUE')
            lx,ly,lw,lh=bounds(ls[0])
            clipped=any(n.get_name()=='Image' and bounds(n)[1]<ly<bounds(n)[1]+bounds(n)[3]
                        for n in (ls[0].get_child_at_index(i) for i in range(ls[0].get_child_count())))
            if not clipped:raise RuntimeError('IMAGE_NOT_VISIBLE')
            area=(lx+lw//2,ly+lh//2)
            wheel(*area,4,2);moved+=2;time.sleep(.3)
    finally:
        if moved and area and viewer_frame() is None:
            wheel(*area,5,moved);time.sleep(.2)


def open_image_visible(data):
    """Open one picture in WeChat's viewer, capture it at full size (several screens for a long one), close it."""
    use_chat(data.get('chat'))
    sigs = data.get('sigs')                       # None = any sender, '' = the bot's own pictures
    if sigs is not None and not (isinstance(sigs, list) and all(isinstance(x, str) for x in sigs)):
        raise RuntimeError('INVALID_SIGS')
    pages = max(1, min(int(data.get('pages', 4)), 6))
    open_chat()
    ns = list(walk(app()))
    lists = [n for n in ns if n.get_role_name() == 'list' and n.get_name() in ('Messages', '消息')]
    if len(lists) != 1:
        raise RuntimeError('MESSAGE_LIST_NOT_UNIQUE')
    shot = screenshot()
    lx,ly,lw,lh=bounds(lists[0])
    picked = None
    for i in range(lists[0].get_child_count()):
        n = lists[0].get_child_at_index(i)
        if n.get_name() != 'Image' or not visible(n):
            continue
        x, y, w, h = bounds(n)
        if x < 0 or y < 0 or y+h > shot.height or x+w > shot.width or h < 40:
            continue
        if y<ly or y+h>ly+lh:continue
        crop = shot.crop((x, y, x+w, y+h))
        direction=message_direction(crop,media=True,avatar_visible=True)
        if direction=='unknown':continue
        sig=None
        if direction=='incoming':
            try:sig,_=name_strip(crop,w)
            except Exception:pass
        if sigs==[''] and direction!='outgoing':continue
        if sigs is not None and sigs!=[''] and sig not in sigs:continue
        picked=(x,y,w,h,crop,sig,direction)
    if not picked:
        raise RuntimeError('IMAGE_NOT_VISIBLE')
    x, y, w, h, crop, sig, direction = picked
    # Click the middle of the picture itself, not its avatar, name line or scrollbar.
    left, top, right = (60, 24, w-70) if direction=='incoming' else (0, 0, w-70)
    body = crop.crop((left, top, right, h)).convert('L')
    background = crop.convert('L').getpixel((3, 3))
    box = body.point(lambda v: 255 if abs(v-background) > 2 else 0).getbbox()
    if not box:
        raise RuntimeError('IMAGE_NOT_FOUND_IN_ROW')
    click_xy(x + left + (box[0]+box[2])//2, y + top + (box[1]+box[3])//2)
    frame = None
    for _ in range(30):
        time.sleep(.1)
        frame = viewer_frame()
        if frame:
            break
    if not frame:
        raise RuntimeError('VIEWER_NOT_OPENED')
    shots = []
    try:
        time.sleep(.5)
        frame = viewer_frame() or frame
        if bounds(frame)[2]<1500:
            press_button(frame, ('Maximize', '最大化'))      # no toggle when already maximized
        for _ in range(20):
            time.sleep(.1)
            if bounds(frame)[2] >= 1500:
                break
        view=wait_viewer_image(frame)
        fx, fy, fw, fh = bounds(viewer_frame() or frame)
        shots.append(page_png(view))
        if pages > 1 and content_aspect(view) > 2.2:
            # A tall picture is squeezed to fit; show it at its real size and pan down in steps.
            # (Best effort: scrolling a long picture has not been verified on a real one.)
            press_button(frame, ('Original image size', '原始大小'))
            time.sleep(.6)
            previous = None
            for _ in range(pages-1):
                part = screenshot().crop((fx, fy+42, fx+fw, fy+fh))
                if previous is not None and ImageChops.difference(part.convert('L'), previous.convert('L')).getbbox() is None:
                    break                                    # the picture stopped moving: that was the end
                shots.append(page_png(part))
                previous = part
                drag(fx+fw//2, fy+fh//2+260, fx+fw//2, fy+fh//2-260)
                time.sleep(.5)
    finally:
        close_viewer()
    # The main window must be back and showing the same chat before anything else touches it.
    if not selected(list(walk(app()))):
        open_chat()
    return {'pages': shots, 'sig': sig, 'direction': direction}


PROFILE_ID_LABELS=('Weixin ID:', 'WeChat ID:', '微信号：', '微信号:')


def profile_ids():
    """Read only the native profile ID field, never a chat message or OCR nickname."""
    values=[]
    for n in walk(app()):
        if n.get_role_name()!='label' or n.get_name() not in PROFILE_ID_LABELS:continue
        parent=n.get_parent()
        peers=[parent.get_child_at_index(i) for i in range(parent.get_child_count())]
        peers=[p.get_name().strip() for p in peers if p.get_role_name()=='label' and p.get_name() not in PROFILE_ID_LABELS]
        if len(peers)==1:values.append(peers[0])
    return values


def verify_owner(data):
    """Open this exact incoming bubble's avatar; display-name fingerprints confer no authority."""
    use_chat(data.get('chat'));open_chat()
    expected=json.loads((STATE/'owner.json').read_text()).get('weixin_id')
    if not isinstance(expected,str) or not expected:return {'owner_verified':False}
    if profile_ids():raise RuntimeError('PROFILE_ALREADY_OPEN')
    ns=list(walk(app()))
    lists=[n for n in ns if n.get_role_name()=='list' and n.get_name() in ('Messages','消息')]
    if len(lists)!=1:raise RuntimeError('MESSAGE_LIST_NOT_UNIQUE')
    shot=screenshot();candidates=[]
    for i in range(lists[0].get_child_count()):
        n=lists[0].get_child_at_index(i)
        if not visible(n) or n.get_name()!=data.get('text'):continue
        x,y,w,h=bounds(n)
        if x<0 or y<0 or h<1 or y+h>shot.height or x+w>shot.width:continue
        sig,_=name_strip(shot.crop((x,y,x+w,y+h)),w)
        if sig and sig==data.get('sig'):candidates.append((x,y,w,h))
    if len(candidates)!=1:return {'owner_verified':False}
    x,y,w,h=candidates[0]
    d=display.Display()
    try:
        xtest.fake_input(d,X.MotionNotify,x=x+27,y=y+min(30,h//2))
        xtest.fake_input(d,X.ButtonPress,1);xtest.fake_input(d,X.ButtonRelease,1);d.sync()
    finally:d.close()
    try:
        ids=[]
        for _ in range(15):
            time.sleep(.1);ids=profile_ids()
            if ids:break
        verified=len(ids)==1 and hmac.compare_digest(ids[0],expected)
    finally:
        press_key('Escape');time.sleep(.15)
        if profile_ids():
            press_key('Escape');time.sleep(.2)
            if profile_ids():raise RuntimeError('PROFILE_NOT_CLOSED')
    # New arrivals can move a bubble between capture and click. Never authenticate
    # the original message if its sender row moved or changed while the card was open.
    shot=screenshot()
    unchanged=[]
    for n in walk(app()):
        if n.get_role_name()!='list item' or n.get_name()!=data.get('text') or bounds(n)!=(x,y,w,h):continue
        sig,_=name_strip(shot.crop((x,y,x+w,y+h)),w)
        if sig==data.get('sig'):unchanged.append(n)
    return {'owner_verified':verified and len(unchanged)==1}


def request_login(data):
    """On WeChat's 'Log In' screen, press the button so the phone shows its confirm prompt.

    This never logs in by itself: the account owner still has to confirm on the phone.
    """
    ns = list(walk(app()))
    if any(n.get_role_name() == 'list' and n.get_name() in ('Chats', '会话') for n in ns):
        return {'status': 'already_logged_in'}
    button = next((n for n in ns if n.get_role_name() == 'push button' and n.get_name() in ('Log In', '登录')), None)
    if button is None:
        return {'status': 'no_login_button'}     # e.g. a QR code screen: needs a scan, nothing to press
    click(button)
    return {'status': 'prompt_sent'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):
        pass  # Do not put private chat bodies in access logs.

    def respond(self,data,code=200):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authenticated(self):
        return hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+TOKEN)

    def do_GET(self):
        if not self.authenticated():
            return self.respond({'error':'UNAUTHORIZED'},401)
        try:
            url = urllib.parse.urlsplit(self.path)
            chat = urllib.parse.parse_qs(url.query).get('chat', [None])[0]
            if chat is not None:use_chat(chat)
            if url.path == '/status':return self.respond(status())
            if url.path == '/overview':return self.respond(overview())
            if url.path == '/snapshot':
                query = urllib.parse.parse_qs(url.query)
                return self.respond(snapshot(query.get('images') == ['1'], query.get('strips') == ['1']))
            if url.path == '/tree':
                return self.respond([{'role':n.get_role_name(),'name':n.get_name(),'bounds':bounds(n)} for n in walk(app()) if n.get_name()])
            return self.respond({'error':'NOT_FOUND'},404)
        except Exception as e:
            return self.respond({'error':str(e)},409)

    def do_POST(self):
        if not self.authenticated():return self.respond({'error':'UNAUTHORIZED'},401)
        try:
            size=int(self.headers.get('Content-Length','0'))
            limit = 4_500_000 if self.path == '/send_image' else 16384
            if not 0 < size <= limit:raise RuntimeError('INVALID_REQUEST_SIZE')
            data=json.loads(self.rfile.read(size))
            if self.path == '/send':return self.respond(send(data))
            if self.path == '/send_image':return self.respond(send_image(data))
            if self.path == '/open_image':return self.respond(open_image(data))
            if self.path == '/request_login':return self.respond(request_login(data))
            if self.path == '/verify_owner':return self.respond(verify_owner(data))
            return self.respond({'error':'NOT_FOUND'},404)
        except Exception as e:
            return self.respond({'error':str(e)},409)


if __name__ == '__main__':
    HTTPServer(('0.0.0.0',18765),Handler).serve_forever()
