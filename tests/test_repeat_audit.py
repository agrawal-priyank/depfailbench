"""Internal UUID renaming must never hide changed behavior or key reuse."""
from copy import deepcopy
import pytest
from benchmark.expanded.repeat_audit import behavior_view,literal_view

A='11111111-1111-4111-8111-111111111111'
B='22222222-2222-4222-8222-222222222222'
C='33333333-3333-4333-8333-333333333333'


def example(condition='C1'):
    attempts=[{'public_index':0,'method':'POST','path':'/charges','operation':'/charges',
               'payload':{'order_id':'order-1'},'idempotency_key':A} for _ in range(2)]
    return {'task':'E5','condition':condition,'clean_qualified':True,'primary_pass':True,
            'observations':[{'scenario':'transient_503','pass':True,'outcome_class':'resilient_success',
                'responses':[{'status':200,'body':{'order_id':'order-1','status':'PAID','charge_id':'charge-1'}}],
                'dependency':{'attempts':attempts,'effects':[{'charge_id':'charge-1','order_id':'order-1','status':'captured'}]},
                'application_state':{'orders':{'order-1':{'status':'PAID','charge_id':'charge-1','idempotency_key':A}},'reservations':{}}}]}


def renamed(row):
    result=deepcopy(row)
    for a in result['observations'][0]['dependency']['attempts']:a['idempotency_key']=B
    result['observations'][0]['application_state']['orders']['order-1']['idempotency_key']=B
    return result


@pytest.mark.parametrize('condition',['C0','C1'])
def test_fresh_consistently_linked_uuid_is_comparison_equivalent_only(condition):
    left=example(condition);right=renamed(left);before=deepcopy((left,right))
    assert literal_view(left)!=literal_view(right)
    assert behavior_view(left)==behavior_view(right)
    assert (left,right)==before


def test_one_key_per_retry_is_not_equivalent_even_if_state_matches_last_key():
    left=example();right=renamed(left)
    right['observations'][0]['dependency']['attempts'][0]['idempotency_key']=C
    assert behavior_view(left)!=behavior_view(right)


def test_state_key_must_be_linked_to_recorded_dependency_key():
    left=example();right=deepcopy(left)
    right['observations'][0]['application_state']['orders']['order-1']['idempotency_key']=B
    assert behavior_view(left)!=behavior_view(right)


def test_key_reuse_relationship_across_public_requests_is_preserved():
    left=example();left['observations'][0]['dependency']['attempts'][1]['public_index']=1
    right=renamed(left);right['observations'][0]['dependency']['attempts'][1]['idempotency_key']=C
    assert behavior_view(left)!=behavior_view(right)


@pytest.mark.parametrize('change',['duplicate_charge','receipt','public_body','state_status','stock','payload','attempt_count','result_pass','probe_pass','watchdog','order_identity','unrelated_uuid','public_uuid'])
def test_meaningful_changes_remain_visible_after_uuid_renaming(change):
    left=example();right=renamed(left);o=right['observations'][0]
    if change=='duplicate_charge':o['dependency']['effects'].append(deepcopy(o['dependency']['effects'][0]))
    elif change=='receipt':o['dependency']['effects'][0]['charge_id']='charge-2'
    elif change=='public_body':o['responses'][0]['body']['status']='UNRESOLVED'
    elif change=='state_status':o['application_state']['orders']['order-1']['status']='UNRESOLVED'
    elif change=='stock':o['dependency']['stock']={'widget':9}
    elif change=='payload':o['dependency']['attempts'][1]['payload']['order_id']='order-2'
    elif change=='attempt_count':o['dependency']['attempts'].append(deepcopy(o['dependency']['attempts'][0]))
    elif change=='result_pass':right['primary_pass']=False
    elif change=='probe_pass':o['pass']=False
    elif change=='watchdog':o['watchdog_intervened']=True
    elif change=='order_identity':o['application_state']['orders']['order-2']=o['application_state']['orders'].pop('order-1')
    elif change=='unrelated_uuid':o['application_state']['orders']['order-1']['unrelated_uuid']=C
    elif change=='public_uuid':o['responses'][0]['body']['uuid']=C
    assert behavior_view(left)!=behavior_view(right)


@pytest.mark.parametrize('value',['not-a-uuid','11111111111141118111111111111111',None,123])
def test_noncanonical_or_non_uuid_state_is_never_renamed(value):
    left=example();right=renamed(left)
    left['observations'][0]['application_state']['orders']['order-1']['idempotency_key']=value
    assert behavior_view(left)!=behavior_view(right)


def test_other_task_or_state_path_is_not_normalized():
    left=example();right=renamed(left);left['task']=right['task']='E6'
    assert behavior_view(left)!=behavior_view(right)
    left=example();right=renamed(left)
    for row in [left,right]:
        state=row['observations'][0]['application_state'];state['reservations']=state.pop('orders')
    assert behavior_view(left)!=behavior_view(right)


def test_timing_only_variation_remains_excluded():
    left=example();right=deepcopy(left)
    right['observations'][0]['responses'][0]['wall_latency_s']=0.1
    right['observations'][0]['startup_s']=0.3
    assert behavior_view(left)==behavior_view(right)

def test_collection_preserves_literal_flags_and_repeat_one_without_execution(tmp_path):
    import json
    from benchmark.expanded.collect import collect,digest,record_path
    from benchmark.expanded.collection_dry_run import write_control
    from benchmark.expanded.contracts import scenarios
    from benchmark.expanded.planning import allocation
    slot=next(s for s in allocation()[1] if s['task']=='E5')
    write_control(tmp_path/'inputs'/slot['artifact_id'],slot,source='def create_app(transport, settings=None):\n    raise RuntimeError("synthetic control never executed")\n')
    calls=[]
    def evaluator(task,condition,*,source,settings,metadata):
        key=f'00000000-0000-4000-8000-{len(calls)+1:012d}'
        observation=example(condition)['observations'][0]
        for attempt in observation['dependency']['attempts']:attempt['idempotency_key']=key
        observation['application_state']['orders']['order-1']['idempotency_key']=key
        probes=[]
        for scenario in scenarios(task):
            probe=deepcopy(observation);probe['scenario']=scenario;probes.append(probe)
        calls.append(key)
        return {'task':task,'condition':condition,'deadline_s':settings.deadline_s,'metadata':metadata,
                'source_sha256':digest(source),'clean_qualified':True,'primary_pass':True,'observations':probes}
    report=collect(tmp_path/'inputs',tmp_path/'collection',cohort='validation',artifact_ids=[slot['artifact_id']],evaluator=evaluator)
    assert len(calls)==9 and not report['reproducibility_disagreements']
    assert len(report['literal_trace_disagreements'])==3
    assert report['literal_trace_disagreements']==report['permitted_internal_identifier_variations']
    assert not report['confirmatory_ready'] and report['selected_repeat']==1
    saved=json.loads(record_path(tmp_path/'collection',slot['artifact_id'],1,1).read_text())
    assert saved['result']['observations'][0]['application_state']['orders']['order-1']['idempotency_key'] in calls
    assert isinstance(saved['result']['observations'][0]['application_state']['orders']['order-1']['idempotency_key'],str)
