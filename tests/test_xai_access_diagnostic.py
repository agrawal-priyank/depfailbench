"""Read-only diagnostic scope and redaction; no real credentials."""
import importlib.util,json
from pathlib import Path
import httpx
spec=importlib.util.spec_from_file_location('xai_diagnostic',Path(__file__).parents[1]/'scripts/inspect_xai_access.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

async def test_only_metadata_gets_and_all_errors_redact_in_memory_credential():
 key='synthetic-private-key-value';calls=[]
 def handler(request):
  assert request.method=='GET' and request.url.host=='api.x.ai' and request.url.path in d.PATHS
  assert request.content==b'' and request.headers['authorization']=='Bearer '+key
  calls.append(request.url.path)
  return httpx.Response(400,json={'error':{'message':'Credential '+key+' failed'}},request=request)
 report=await d.inspect(transport=httpx.MockTransport(handler),key=key)
 assert calls==list(d.PATHS) and key not in json.dumps(report) and report['generation_calls']==0
 assert all('[REDACTED]' in row['error_redacted'] for row in report['rows'])

async def test_catalog_can_distinguish_single_model_route_failure():
 def handler(request):
  return httpx.Response(200,json={'data':[{'id':'grok-4.7'}]} if request.url.path=='/v1/models' else {'id':'grok-4.7'},request=request)
 report=await d.inspect(transport=httpx.MockTransport(handler),key='synthetic')
 assert all(row['selected_model_present'] for row in report['rows']) and report['generation_calls']==0
