"""Full-study task fixtures. All contracts fixed before full-study generation."""
from __future__ import annotations
import hashlib, json
from collections import Counter
import httpx
from fastapi import FastAPI, HTTPException
from benchmark.fixtures.common import AppSettings

ITEMS = [{'id': i, 'name': f'Item {i}'} for i in range(1,7)]
CONTENT = b'benchmark-content-v1'
KEY = 'sample.txt'
DIGEST = hashlib.sha256(CONTENT).hexdigest()
SCENARIOS = {
'T2': ('clean','transient_503','persistent_503','timeout','rate_limit','malformed_200','cursor_cycle'),
'T5': ('clean','transient_503','persistent_503','timeout_before_commit','rate_limit','malformed_200','committed_response_lost'),
}
SAFE = {'persistent_503','rate_limit','malformed_200','cursor_cycle'}

class Dependency(httpx.AsyncBaseTransport):
    def __init__(self, task, scenario):
        self.task,self.scenario=task,scenario
        self.attempts=[]; self.counts=Counter();self.objects={};self.virtual_time_s=0.;self.writes=[]
    async def handle_async_request(self, request):
        if self.task=='T2':
            cursor=request.url.params.get('cursor')
            if request.method!='GET' or request.url.path!='/pages' or cursor not in {'0','1','2'}:
                raise ValueError('invalid catalog dependency request')
            operation=cursor; fault=cursor=='1'
        else:
            if request.method!='PUT' or not request.url.path.startswith('/objects/'):
                raise ValueError('invalid upload dependency request')
            operation=request.url.path;fault=True
        self.counts[operation]+=1;n=self.counts[operation]
        mode=self.scenario if fault else 'clean'
        status=200; timeout=False; commit=False
        if mode=='transient_503' and n<=2:status=503
        if mode=='persistent_503':status=503
        if mode=='rate_limit' and n==1:status=429
        if mode in {'timeout','timeout_before_commit','committed_response_lost'} and n==1:timeout=True
        self.virtual_time_s += .25 if timeout else .01
        if self.task=='T2':
            idx=int(operation);body={'items':ITEMS[idx*2:idx*2+2], 'next_cursor': str(idx+1) if idx<2 else None}
            if mode=='malformed_200':body={'items':'invalid','next_cursor':None}
            if mode=='cursor_cycle':body={'items':ITEMS[2:4],'next_cursor':'1'}
        else:
            key=request.url.path[len('/objects/'):]; payload=await request.aread()
            commit=status==200 and (not timeout or mode=='committed_response_lost')
            if commit:
                self.objects[key]=payload;self.writes.append({'key':key,'sha256':hashlib.sha256(payload).hexdigest()})
            body={'key':key,'sha256':hashlib.sha256(payload).hexdigest()}
            if mode=='malformed_200':body={'key':key,'sha256':'invalid'}
        self.attempts.append({'operation':operation,'status':status,'timeout':timeout})
        if timeout:raise httpx.ReadTimeout('scripted timeout',request=request)
        return httpx.Response(status,json=body if status==200 else {},headers={'Retry-After':'0'},request=request)


def create_reference(task, resilient, transport, settings=None):
    cfg=settings or AppSettings();app=FastAPI()
    async def fetch(client,method,path,**kw):
        for n in range(cfg.max_attempts if resilient else 1):
            try:r=await client.request(method,path,**kw)
            except httpx.HTTPError:
                if resilient and n+1<cfg.max_attempts:continue
                raise HTTPException(503,'unavailable')
            if r.status_code in {429,502,503,504} and resilient and n+1<cfg.max_attempts:continue
            if r.status_code!=200:raise HTTPException(503,'unavailable')
            return r.json()
        raise HTTPException(503,'unavailable')
    if task=='T2':
        @app.get('/catalog')
        async def catalog():
            items=[];cursor='0';seen=set()
            async with httpx.AsyncClient(transport=transport,base_url=cfg.downstream_url,timeout=cfg.timeout_s) as client:
                while cursor is not None:
                    if cursor in seen or len(seen)>=3:raise HTTPException(502,'invalid cursor')
                    seen.add(cursor);p=await fetch(client,'GET','/pages',params={'cursor':cursor})
                    if resilient:
                        if not isinstance(p,dict) or not isinstance(p.get('items'),list) or not (p.get('next_cursor') is None or isinstance(p.get('next_cursor'),str)):
                            raise HTTPException(502,'invalid page')
                        if any(not isinstance(x,dict) or type(x.get('id')) is not int or not isinstance(x.get('name'),str) for x in p['items']):raise HTTPException(502,'invalid item')
                    items.extend(p['items']);cursor=p['next_cursor']
            return {'items':items}
    else:
        @app.post('/uploads/{object_key}')
        async def upload(object_key:str,payload:dict):
            content=payload['content'].encode();digest=hashlib.sha256(content).hexdigest()
            async with httpx.AsyncClient(transport=transport,base_url=cfg.downstream_url,timeout=cfg.timeout_s) as client:
                body=await fetch(client,'PUT',f'/objects/{object_key}',content=content)
            if resilient and body!={'key':object_key,'sha256':digest}:raise HTTPException(502,'invalid receipt')
            return body
    return app


def classify(task, scenario, status, body, exception, deadline, dep):
    if exception or deadline or any(n>3 for n in dep.counts.values()):return 'availability_failure'
    if task=='T2':
        if status==200 and body=={'items':ITEMS} and len(dep.counts)==3:return 'resilient_success'
        if status is not None and 400<=status<600:return 'safe_failure'
    else:
        if any(k!=KEY or v!=CONTENT for k,v in dep.objects.items()):return 'unsafe_failure'
        if status==200 and body=={'key':KEY,'sha256':DIGEST} and dep.objects.get(KEY)==CONTENT:
            if scenario=='malformed_200':return 'unsafe_failure'
            return 'resilient_success'
        if status is not None and 400<=status<600:return 'safe_failure'
    return 'unsafe_failure'
