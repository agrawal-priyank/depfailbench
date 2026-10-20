"""Verify a rejected, unconsumed Grok request and reconcile a COPY of its ledger.

No model credentials or generation calls. Original archive bytes are preserved.
The zero cost is an explicit author-reported UI observation, not a verified invoice.
"""
import hashlib,io,json,sqlite3,tempfile,zipfile
from pathlib import Path
from benchmark.expanded.planning import assets_root
from benchmark.expanded.providers import build_request,canonical,sha256
from benchmark.expanded.provider_generation import save_json
from benchmark.expanded.spending import SpendingLedger,DispatchPaused

PRIOR_RUN=39489509581
PRIOR_COMMIT='c8f84ccd18f8c6c41f3e1ca78ccb4efc51905919'
PRIOR_ARTIFACT=12294488585
PRIOR_ARCHIVE_SHA256='05cb5b2f7cd756fb190d08222a946f65fa90ba9cedbcebece1a40f17d35f6f41'
PRIOR_PROVIDER_SHA256='cc0116573e387c5ea00bdecf621b6d9eed56d1467df80c3ec49204c126e709fb'
PRIOR_SLOT='validation_E5_grok_4_7_C1'
ERROR='Invalid request content: A tool_choice was set on the request but no tools were specified.'

def require(value,message):
    if not value:raise DispatchPaused(message)

def verify(archive,plan):
    require(hashlib.sha256(archive).hexdigest()==PRIOR_ARCHIVE_SHA256,'rejected-request archive differs')
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        read=lambda n:json.loads(z.read('xai_api_validation/'+n))
        previous=read('reviewed_plan.json');manifest=read('run_manifest.json')
        require(manifest['github_run_id']==str(PRIOR_RUN) and manifest['github_commit']==PRIOR_COMMIT
                and manifest['synthetic_data'] is False,'previous run identity differs')
        require(previous['slots']==plan['slots'],'unfilled allocation changed')
        changed={k for k in previous['snapshot'].keys()|plan['snapshot'].keys() if previous['snapshot'].get(k)!=plan['snapshot'].get(k)}
        require(changed=={'implementation/providers.py'} and previous['snapshot']['implementation/providers.py']==PRIOR_PROVIDER_SHA256,
                'only reviewed xAI request transport compatibility may change')
        prefix='artifacts/'+PRIOR_SLOT+'/'
        require(not any(n.endswith('/metadata.json') or n.endswith('/app.py') for n in z.namelist()),'previous output exists; do not replace')
        attempt=read(prefix+'attempt_01/attempt.json');complete=read(prefix+'attempt_01/wire_complete.json')
        wire=z.read('xai_api_validation/'+prefix+'attempt_01/wire_response.bin')
        require(json.loads(wire)=={'code':'invalid-argument','error':ERROR},'previous rejection differs')
        require(complete['wire_sha256']==hashlib.sha256(wire).hexdigest(),'previous wire digest differs')
        require(attempt['http_status']==400 and attempt['accepted'] is False and attempt['content_received'] is False
                and attempt['consumed'] is False and attempt['provider_response_id'] is None,'previous request may have returned content')
        root=assets_root();config=read(prefix+'configuration.json');slot=read(prefix+'slot.json');prompt=z.read('xai_api_validation/'+prefix+'prompt.txt').decode()
        require(slot in plan['slots'] and slot['artifact_id']==PRIOR_SLOT,'prior slot differs')
        require(prompt==(root/'prompts'/f"{slot['task']}_{slot['condition']}.md").read_text(),'prior prompt changed')
        require(config==next(c for c in json.loads((root/'study.json').read_text())['configurations'] if c['id']==slot['configuration_id']),
                'prior model settings changed')
        old_request=read(prefix+'attempt_01/request.json');expected=json.loads(json.dumps(old_request))
        require(expected['body'].pop('tool_choice')=='none' and expected['body']['tools']==[],'unexpected prior tools setting')
        expected['request_sha256']=sha256(canonical(expected['body']))
        require(build_request(config,prompt)==expected,'new request differs beyond omission of unsupported tool_choice')
        ledger_bytes=z.read('xai_api_validation/spending.sqlite')
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'ledger.sqlite';f.write_bytes(ledger_bytes);db=sqlite3.connect(f.as_uri()+'?mode=ro',uri=True)
            try:
                rows=db.execute('SELECT id,slot_id,number,provider,state,reserved,charged,outcome,response_id FROM attempts').fetchall()
                require(rows==[(PRIOR_SLOT+':1',PRIOR_SLOT,1,'xAI','uncertain',500000000,None,'service_unfilled',None)],'previous ledger attempts differ')
                require(db.execute('SELECT consumed FROM slots').fetchall()==[(0,)],'previous slot consumed')
            finally:db.close()
    return {'previous_run_id':PRIOR_RUN,'previous_artifact_id':PRIOR_ARTIFACT,'previous_archive_sha256':PRIOR_ARCHIVE_SHA256,
        'previous_http_requests':1,'previous_accepted_requests':0,'previous_programs':0,'prior_affected_slot':PRIOR_SLOT,
        'new_requests_same_slots':16,'changed_request_field_only':'omit tool_choice when tools=[]',
        'author_charge_observation':'Grok usage on UI is showing 0','reviewed_prior_cost_usd':'0',
        'invoice_independently_verified':False,'original_ledger_sha256':hashlib.sha256(ledger_bytes).hexdigest()}

def reconcile_copy(archive,destination,plan):
    proof=verify(archive,plan);destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=False)
    save_json(destination/'review.json',proof)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        f=destination/'spending.sqlite';f.write_bytes(z.read('xai_api_validation/spending.sqlite'))
    ledger=SpendingLedger.open_for_recovery(f)
    reason='Explicit review of HTTP400 invalid-argument before acceptance/content, and Priyank confirms Grok UI usage is 0. Reviewed zero, not independently verified invoice.'
    ledger.reconcile_cost(PRIOR_SLOT+':1',cost_usd='0',evidence_path=destination/'review.json',reason=reason)
    ledger.clear_pause('xAI',evidence_path=destination/'review.json',reason=reason)
    snapshot=ledger.snapshot();require(snapshot['cost']==snapshot['held']==0 and not snapshot['pauses'],'previous cost review incomplete')
    save_json(destination/'reviewed_ledger_snapshot.json',snapshot)
    return proof
