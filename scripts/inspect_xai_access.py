"""Read-only xAI metadata diagnosis. No generation endpoint or request body."""
import asyncio,json,os,re
from pathlib import Path
import httpx

PATHS=('/v1/models/grok-4.7','/v1/models','/v1/language-models/grok-4.7')

def safe_message(value,key):
 text=str(value).replace(key,'[REDACTED]')
 text=re.sub(r'(?i)(?:Bearer\s+[^\s\"\']+|(?:xai-|sk-)[A-Za-z0-9_-]+)','[REDACTED]',text)
 return ''.join(c for c in text if c.isprintable())[:800]

async def inspect(*,transport=None,key=None):
 key=key or os.environ['XAI_API_KEY']
 rows=[]
 async with httpx.AsyncClient(transport=transport or httpx.AsyncHTTPTransport(retries=0,trust_env=False),trust_env=False,follow_redirects=False,timeout=30) as client:
  for path in PATHS:
   response=await client.get('https://api.x.ai'+path,headers={'Authorization':'Bearer '+key})
   try:body=response.json()
   except ValueError:body={}
   row={'path':path,'http_status':response.status_code}
   if response.status_code==200:
    data=body.get('data',[]) if isinstance(body,dict) else []
    row['selected_model_present']=any(isinstance(x,dict) and (x.get('id')=='grok-4.7' or 'grok-4.7' in x.get('aliases',[])) for x in data) if path=='/v1/models' else isinstance(body,dict) and (body.get('id')=='grok-4.7' or 'grok-4.7' in body.get('aliases',[]))
   else:
    error=body.get('error',body) if isinstance(body,dict) else {}
    if isinstance(error,dict):error={k:error[k] for k in ('code','type','message','detail') if k in error}
    row['error_redacted']=safe_message(json.dumps(error),key)
   rows.append(row)
 report={'provider':'xAI','model':'grok-4.7','generation_calls':0,'requests_are_metadata_gets_only':True,'rows':rows}
 assert key not in json.dumps(report)
 return report

if __name__=='__main__':
 try:
  report=asyncio.run(inspect());folder=Path('results/expanded/xai_access_diagnostic');folder.mkdir(parents=True,exist_ok=False)
  (folder/'diagnostic.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
 except Exception as error:
  print(json.dumps({'diagnostic_failed':True,'error_type':type(error).__name__,'generation_calls':0}));raise SystemExit(1) from None
