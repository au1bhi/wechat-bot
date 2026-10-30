#!/usr/bin/python3
"""Container health: the noVNC page answers AND WeChat is logged in and readable through the bridge.

Used by compose.yaml. Logged out, locked or a dead AT-SPI bridge makes the container unhealthy, which
`docker ps` and any monitoring then show, instead of a green status while no message can be read.
"""
import json
import os
import sys
import urllib.request

BRIDGE=os.environ.get('HEALTH_BRIDGE','http://127.0.0.1:18765/status')
VNC=os.environ.get('HEALTH_VNC','http://127.0.0.1:6080/vnc.html')
TOKEN_FILE=os.environ.get('HEALTH_TOKEN_FILE','/run/secrets/bridge_token')


def check():
    urllib.request.urlopen(VNC,timeout=5).close()
    with open(TOKEN_FILE) as f:token=f.read().strip()
    request=urllib.request.Request(BRIDGE,headers={'Authorization':'Bearer '+token})
    with urllib.request.urlopen(request,timeout=8) as response:
        status=json.load(response)
    if not status.get('ok'):return 'bridge: '+str(status.get('error','not ok'))
    if not status.get('logged_in'):return 'WeChat is logged out'
    if status.get('locked'):return 'WeChat is locked'
    return None


if __name__=='__main__':
    try:problem=check()
    except Exception as e:problem='%s: %s'%(type(e).__name__,e)
    if problem:
        print(problem,file=sys.stderr);sys.exit(1)
