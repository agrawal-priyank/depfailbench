import hashlib

import pytest
from benchmark.full_tasks import create_reference,SCENARIOS,SAFE,Dependency,classify,CONTENT,KEY
from benchmark.full_eval import probe_new

@pytest.mark.parametrize('task',['T2','T5'])
@pytest.mark.parametrize('resilient',[False,True])
async def test_reference_matrix(task,resilient):
    factory=lambda transport,settings:create_reference(task,resilient,transport,settings)
    for scenario in SCENARIOS[task]:
        row=await probe_new(task,scenario,factory)
        if scenario=='clean':assert row['outcome_class']=='resilient_success'
        if resilient:assert row['outcome_class']=='resilient_success' or (scenario in SAFE and row['outcome_class']=='safe_failure'),row
        if not resilient and scenario=='transient_503':assert row['outcome_class']!='resilient_success'

async def test_upload_overwrites_same_object_and_detects_wrong_data():
    import httpx
    d=Dependency('T5','clean')
    async with httpx.AsyncClient(transport=d,base_url='http://dep') as c:
        await c.put('/objects/'+KEY,content=CONTENT)
        await c.put('/objects/'+KEY,content=b'wrong')
    assert len(d.objects)==1
    assert classify('T5','clean',200,{},None,False,d)=='unsafe_failure'

async def test_pagination_retries_are_per_page():
    row=await probe_new('T2','transient_503',lambda t,s:create_reference('T2',True,t,s))
    assert len(row['attempts'])==5
    assert row['outcome_class']=='resilient_success'


async def test_catalog_float_ids_do_not_satisfy_integer_schema():
    import httpx

    dependency = Dependency('T2', 'clean')
    async with httpx.AsyncClient(
        transport=dependency,
        base_url='http://dep',
        timeout=0.25,
    ) as client:
        for cursor in ('0', '1', '2'):
            await client.get('/pages', params={'cursor': cursor})
    body = {'items': [{'id': float(i), 'name': f'Item {i}'} for i in range(1, 7)]}
    assert classify('T2', 'clean', 200, body, None, False, dependency) == 'unsafe_failure'


async def test_upload_cannot_fabricate_receipt_after_lost_response():
    import httpx

    dependency = Dependency('T5', 'committed_response_lost')
    async with httpx.AsyncClient(
        transport=dependency,
        base_url='http://dep',
        timeout=0.25,
    ) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.put('/objects/' + KEY, content=CONTENT)
    fabricated = {'key': KEY, 'sha256': hashlib.sha256(CONTENT).hexdigest()}
    assert classify(
        'T5',
        'committed_response_lost',
        200,
        fabricated,
        None,
        False,
        dependency,
    ) == 'unsafe_failure'

@pytest.mark.parametrize('task',['T1','T2','T4','T5'])
async def test_full_evaluator_accepts_resilient_reference(task,tmp_path):
    import json
    from benchmark.full_eval import evaluate
    if task in {'T1','T4'}:
        code=f"from benchmark.fixtures.{task.lower()} import create_app as ref\ndef create_app(transport,settings=None):\n return ref('reference_resilient',transport,settings)\n"
    else:
        code=f"from benchmark.full_tasks import create_reference\ndef create_app(transport,settings=None):\n return create_reference('{task}',True,transport,settings)\n"
    (tmp_path/'app.py').write_text(code)
    (tmp_path/'metadata.json').write_text(json.dumps({'artifact_id':'test','task':task,'condition':'C1','model_provider':'test'}))
    (tmp_path/'raw_response.json').write_text('{}')
    result=await evaluate(tmp_path)
    assert result['primary_pass'],result
