"""Cohort compatibility fails closed; host recording excludes credentials."""
import importlib.util
import json
from pathlib import Path
import re
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/(name+'.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


bridge = module('prepare_amended_main_cohort')
host = module('record_evaluation_host')


def rebuild_prompt(root, task):
    common = (root/'prompts/shared_rules.md').read_text().strip()
    text = (root/'tasks'/f'{task}.md').read_text().strip()
    scaffold = (root/'scaffold.py').read_text().strip()
    resilience = (root/'prompts/resilience.md').read_text().strip()
    c0 = f'{common}\n\n{text}\n\nStarting app.py:\n```python\n{scaffold}\n```\n'
    (root/'prompts'/f'{task}_C0.md').write_text(c0)
    (root/'prompts'/f'{task}_C1.md').write_text(c0+'\n'+resilience+'\n')


@pytest.fixture
def roots(tmp_path):
    original, candidate = tmp_path/'old/expanded_study', tmp_path/'new/expanded_study'
    for root in [original,candidate]:
        shutil.copytree(ROOT/'expanded_study', root, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copyfile(ROOT/'requirements.lock',root.parent/'requirements.lock')
    # A prior-version fixture with internally consistent prompt construction.
    for task in bridge.CHANGED:
        path=original/'tasks'/f'{task}.md'
        path.write_text(path.read_text()+'\nPrior-version fixture wording.\n')
        rebuild_prompt(original,task)
    study=bridge.load(original/'study.json');study['status']='historical fixture'
    (original/'study.json').write_text(json.dumps(study))
    return original,candidate


def test_whole_fresh_cohort_includes_all_mistral_tasks_and_cells(roots):
    slots,_,_=bridge.fresh_slots(*roots)
    assert len(slots)==len({s['artifact_id'] for s in slots})==4320
    mistral=[s for s in slots if s['provider']=='Mistral']
    assert len(mistral)==1440
    assert {s['task'] for s in mistral}=={f'E{i}' for i in range(1,9)}
    assert all(s['cohort']=='main' for s in slots)
    assert set(bridge.Counter((s['task'],s['configuration_id'],s['condition']) for s in slots).values())=={30}


def test_unchanged_task_cannot_be_silently_reused_after_prompt_edit(roots):
    original,candidate=roots
    path=candidate/'tasks/E1.md';path.write_text(path.read_text()+'\nUnapproved change.\n')
    rebuild_prompt(candidate,'E1')
    with pytest.raises(ValueError,match='five-task'):
        bridge.verify_designs(original,candidate)


@pytest.mark.parametrize('field,value',[('seed',123),('measurement_tolerance_s',0.2),('source_processing_policy','different')])
def test_other_scientific_changes_require_review(roots,field,value):
    original,candidate=roots;study=bridge.load(candidate/'study.json');study[field]=value
    (candidate/'study.json').write_text(json.dumps(study))
    with pytest.raises(ValueError,match='Scientific design'):
        bridge.verify_designs(original,candidate)


def test_model_settings_cannot_change_under_bridge(roots):
    original,candidate=roots;study=bridge.load(candidate/'study.json')
    study['configurations'][0]['generation_settings']['reasoning_effort']='high'
    (candidate/'study.json').write_text(json.dumps(study))
    with pytest.raises(ValueError,match='model settings'):
        bridge.verify_designs(original,candidate)



def test_host_record_whitelists_environment_and_preserves_existing_record(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','DO-NOT-PERSIST-TEST-CANARY')
    monkeypatch.setenv('UNRELATED_PRIVATE_NOTE','DO-NOT-PERSIST-TEST-CANARY')
    monkeypatch.setenv('GITHUB_RUN_ID','123456')
    path=tmp_path/'host.json';record=host.write_record(path)
    assert record['workflow_and_image']['GITHUB_RUN_ID']=='123456'
    assert 'DO-NOT-PERSIST-TEST-CANARY' not in path.read_text()
    assert record['model_api_calls']==record['generated_program_executions']==0
    before=path.read_bytes()
    with pytest.raises(FileExistsError):host.write_record(path)
    assert path.read_bytes()==before


def test_missing_hardware_fields_remain_unknown(monkeypatch):
    monkeypatch.setattr(host,'optional_text',lambda p:None)
    record=host.host_record()
    assert record['cpu_models_reported_by_guest'] is None
    assert record['memory_reported_by_guest'] is None
    assert record['cgroup_v2_cpu_max'] is None


def test_readiness_selector_cannot_enable_other_workflow_jobs():
    text=(ROOT/'.github/workflows/full-study.yml').read_text()
    jobs=re.split(r'^  ([a-z][a-z0-9-]+):\n',text.split('jobs:\n',1)[1],flags=re.M)
    assert len(jobs[1::2])==19
    for i in range(1,len(jobs),2):
        name,body=jobs[i],jobs[i+1]
        condition=body.split('    runs-on:',1)[0]
        if name=='amended-main-readiness':
            assert 'inputs.amended_main_readiness' in condition and '!inputs.confirm_paid_generation' in condition
            assert 'secrets' not in body and 'GH_TOKEN' not in body
            assert 'test_amended_main_preparation.py tests/test_amended_prompt_validation.py' in body
            assert 'record_evaluation_host.py' in body
        else:
            assert '!inputs.amended_main_readiness' in condition,name
