"""Request metadata only: never retain prompts, transcripts, images or keys."""
import math
import time
import uuid
from contextvars import ContextVar
from contextlib import contextmanager
from urllib.parse import urlsplit


_trace=ContextVar('request_trace',default={})


@contextmanager
def request_scope(**fields):
    allowed={'session_id','analysis_id','episode_id','turn_id','phase','input_finished_at'}
    token=_trace.set({**_trace.get(),**{k:v for k,v in fields.items() if k in allowed}})
    try:
        yield
    finally:
        _trace.reset(token)


def numeric_usage(value, depth=0):
    if depth>4 or not isinstance(value,dict):
        return {}
    out={}
    for key,item in list(value.items())[:80]:
        if not isinstance(key,str) or not key.isascii() or not key.replace('_','').isalnum() or len(key)>64:
            continue
        if isinstance(item,(int,float)) and not isinstance(item,bool) and math.isfinite(item):
            out[key]=item
        elif isinstance(item,dict):
            nested=numeric_usage(item,depth+1)
            if nested: out[key]=nested
    return out


def input_scale(kwargs):
    payload=kwargs.get('json') or {}
    result={'text_characters':0,'image_count':0,'audio_bytes':0}
    for message in payload.get('messages',[]):
        content=message.get('content','')
        if isinstance(content,str): result['text_characters']+=len(content)
        elif isinstance(content,list):
            for block in content:
                if block.get('type')=='text': result['text_characters']+=len(block.get('text',''))
                elif block.get('type')=='image_url': result['image_count']+=1
    if isinstance(payload.get('input'),str): result['text_characters']+=len(payload['input'])
    for part in (kwargs.get('files') or {}).values():
        if isinstance(part,tuple) and len(part)>1 and isinstance(part[1],bytes):
            result['audio_bytes']+=len(part[1])
    return result


def record(config, purpose, started, status, units, *, request_id=None, **metadata):
    return {'request_id':request_id or uuid.uuid4().hex,
            'provider':urlsplit(config.base_url).hostname,'model':config.model,
            'purpose':purpose,'started_monotonic':started,'finished_monotonic':time.monotonic(),
            'elapsed_ms':round((time.monotonic()-started)*1000),'status':status,
            'usage':numeric_usage(units),'cost':None,'price_version':None,
            'cost_status':'not_computed','retry':0,**metadata,**_trace.get()}
