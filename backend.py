"""Choose which model backend serves a call.

With `backend: agy` every call goes to Antigravity (`agy`): plain text, live web search (only the search tool is
allowed) and pictures (the images are placed in that process's private work directory and read with `view_file`).
If Antigravity fails (logged out, quota, outage, unusable output) the call falls back to the original backend
instead of silently refusing the user. Every result still goes through the same validators and the same output
checks in worker.py.
"""
import logging
import threading

import agy_model
import fast_model

stats={'agy':0,'fallback':0,'other':0}
_stats_lock=threading.Lock()


def _count(key):
    with _stats_lock:stats[key]+=1


def invoke(cfg,policy,payload,schema,search=False,images=()):
    if cfg.get('backend')!='agy':
        _count('other')
        return fast_model.invoke(cfg,policy,payload,schema,search=search,images=images)
    try:
        result=agy_model.invoke(cfg,policy,payload,schema,search=search,images=images)
        _count('agy')
        return result
    except Exception as e:
        _count('fallback')
        logging.warning('Antigravity call failed (%s); falling back%s',e,'' if cfg.get('agy_fallback',False) else ' is disabled')
        if not cfg.get('agy_fallback',False):raise RuntimeError('AGY_FAILED') from None
        return fast_model.invoke(cfg,policy,payload,schema,search=search,images=images)
