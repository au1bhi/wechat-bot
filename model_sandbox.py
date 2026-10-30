"""Shared JSON schemas, Codex login handling and a minimal Bubblewrap option builder.

No host directory, transport secret, Docker socket, D-Bus, or GUI socket is
mounted. The only private input is the Codex client's read-only login material;
it is passed in an anonymous memory file and is never included in prompts.
"""
import base64
import fcntl
import json
import os
import signal
import subprocess
import time
from pathlib import Path

DISABLED=['shell_tool','apps','multi_agent','computer_use','browser_use',
          'image_generation','hooks','skill_search','daemon_auto_start',
          'code_mode_host','unified_exec','shell_snapshot','plugins','skill_mcp_dependency_install',
          'in_app_local_automation','in_app_browser']
DECISION_SCHEMA={'type':'object','properties':{'allowed':{'type':'boolean'}},
                 'required':['allowed'],'additionalProperties':False}
REPLY_SCHEMA={'type':'object','properties':{'reply':{'type':'string'},'latex':{'type':'string'},
                                         'mood':{'type':'string','enum':['positive','neutral','negative']}},
              'required':['reply','latex','mood'],'additionalProperties':False}
SUMMARY_SCHEMA={'type':'object','properties':{'summary':{'type':'string'}},
                'required':['summary'],'additionalProperties':False}
DESCRIBE_SCHEMA={'type':'object','properties':{'description':{'type':'string'}},
                 'required':['description'],'additionalProperties':False}
DISABLED_CODE_MODE_NOTICE=(
    'Code Mode is unavailable because code-mode host is disabled. '
    'Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.')


def memfile(name,data):
    fd=os.memfd_create(name,os.MFD_CLOEXEC)
    os.write(fd,data)
    os.lseek(fd,0,os.SEEK_SET)
    return fd


def client_args(policy,schema_path='/schema.json',model=None):
    args=['exec','--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check',
          '--sandbox','read-only','--color','never','--json']
    for feature in DISABLED:args+=['--disable',feature]
    args+=['--enable','skip_host_skill_discovery','-c','web_search="disabled"',
           '-c','suppress_unstable_features_warning=true',
           '-c','model_reasoning_effort="low"','-c','developer_instructions='+json.dumps(policy,ensure_ascii=False)]
    if schema_path:args+=['--output-schema',schema_path]
    if model:args+=['--model',model]
    return args


def run_process(command,prompt,timeout,pass_fds=(),env=None):
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             text=True,env=env,pass_fds=pass_fds,start_new_session=True)
    try:
        stdout,stderr=process.communicate(prompt,timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.communicate()
        raise RuntimeError('MODEL_TIMEOUT') from None
    if process.returncode:raise RuntimeError('MODEL_PROCESS_FAILED')
    if len(stdout)>2_000_000:raise RuntimeError('MODEL_OUTPUT_TOO_LARGE')
    return stdout


def final_message(stdout):
    messages=[];completed=False;started=False
    for line in stdout.splitlines():
        try:event=json.loads(line)
        except ValueError:raise RuntimeError('INVALID_MODEL_EVENT') from None
        kind=event.get('type','')
        if kind=='turn.started':started=True
        if kind in ('error','turn.failed'):raise RuntimeError('MODEL_TURN_FAILED')
        if kind=='turn.completed':completed=True
        if kind.startswith('item.'):
            item=event.get('item',{})
            # Version-pinned CLI diagnostic explicitly confirms Code Mode is
            # disabled. It precedes the turn and contains no model/tool output.
            # Other errors (including this text during a turn) remain denied.
            if (not started and kind=='item.completed' and item.get('type')=='error'
                    and item.get('message')==DISABLED_CODE_MODE_NOTICE):
                continue
            if item.get('type') not in ('agent_message','reasoning'):
                raise RuntimeError('MODEL_TOOL_OR_UNKNOWN_ITEM_REJECTED')
            if kind=='item.completed' and item.get('type')=='agent_message':
                messages.append(item.get('text',''))
    if not completed or len(messages)!=1:raise RuntimeError('MODEL_RESULT_NOT_UNIQUE')
    return messages[0]


def auth_material(cfg):
    path=Path(cfg['codex_home'])/'auth.json'
    raw=path.read_bytes()
    auth=json.loads(raw)
    if auth.get('auth_mode')!='chatgpt' or not isinstance(auth.get('tokens'),dict):
        raise RuntimeError('CHATGPT_LOGIN_REQUIRED')
    # No API-key fallback. Only the saved ChatGPT login may be used.
    auth['OPENAI_API_KEY']=None
    token=auth['tokens'].get('access_token','')
    try:
        segment=token.split('.')[1]
        expires=float(json.loads(base64.urlsafe_b64decode(segment+'='*(-len(segment)%4))).get('exp',0))
    except (ValueError,KeyError,IndexError,TypeError):expires=0
    if expires and expires<time.time()+300:
        # The trusted broker refreshes through the first-party CLI only. No chat
        # text enters this host-side call. The actual chat runs in Bubblewrap.
        lock_path=Path(cfg['broker_lock'])
        with lock_path.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','LANG','SSL_CERT_FILE','SSL_CERT_DIR')}
            env['CODEX_HOME']=cfg['codex_home']
            command=[cfg['codex_bin']]+client_args('Reply exactly OK. Do not use any tools.',None,cfg.get('model'))
            command+=['-C',cfg['broker_workdir'],'-']
            final_message(run_process(command,'Reply exactly OK. No tools.',120,env=env))
            auth=json.loads(path.read_text());auth['OPENAI_API_KEY']=None
    return json.dumps(auth).encode()


def sandbox_options(cfg,authfd,schemafd):
    binary=str(Path(cfg['codex_bin']).resolve())
    options=['--die-with-parent','--new-session','--unshare-user','--unshare-pid','--unshare-uts',
             '--unshare-ipc','--hostname','chat-sandbox','--cap-drop','ALL',
             '--ro-bind',binary,'/bin/codex','--proc','/proc','--dev','/dev','--tmpfs','/tmp',
             '--dir','/work','--dir','/home/bot','--dir','/codex',
             '--ro-bind-data',str(authfd),'/codex/auth.json',
             '--ro-bind-data',str(schemafd),'/schema.json',
             '--ro-bind','/etc/ssl/certs','/etc/ssl/certs',
             '--ro-bind','/usr/share/ca-certificates','/usr/share/ca-certificates',
             '--ro-bind','/etc/resolv.conf','/etc/resolv.conf',
             '--chdir','/work','--clearenv']
    options[options.index('--chdir'):options.index('--chdir')]=[
        '--ro-bind',cfg['network_guard_bin'],'/bin/net-guard']
    for path in ('/proc/cpuinfo','/proc/meminfo','/proc/uptime','/proc/version','/proc/loadavg',
                 '/proc/stat','/proc/diskstats','/proc/partitions','/proc/modules'):
        options+=['--ro-bind','/dev/null',path]
    for name,value in [('HOME','/home/bot'),('USER','bot'),('LOGNAME','bot'),('PATH','/bin'),
                       ('CODEX_HOME','/codex'),('LANG','C.UTF-8'),('TZ','UTC')]:
        options+=['--setenv',name,value]
    return options
