"""Bounded amended checks cannot touch old or main coordinates."""
import importlib.util,json,re
from pathlib import Path
import pytest
from benchmark.expanded.spending import DispatchPaused
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('amended_check_driver',ROOT/'scripts/amended_prompt_validation.py');driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
@pytest.mark.asyncio
@pytest.mark.parametrize('provider',['Anthropic','OpenAI','Google','Mistral'])
async def test_mock_exact_batch_and_no_credentials_or_duplicates(tmp_path,provider):
 report=await driver.mock(provider,tmp_path/provider)
 assert report['complete'] and report['excluded_from_main'] and report['synthetic_data'] and report['duplicate_blocked'] and report['credential_canary_absent']
 assert report['programs']==driver.COUNTS[provider]==report['mock_requests']
 for p in (tmp_path/provider/'artifacts').iterdir():
  m=json.loads((p/'metadata.json').read_text());assert m['cohort']=='validation' and m['task'] in driver.TASKS and m['provider']==provider
@pytest.mark.parametrize('provider',['Anthropic','OpenAI','Google','Mistral'])
def test_prepare_requires_original_live_workflow(tmp_path,provider):
 with pytest.raises(DispatchPaused):driver.prepare(provider,tmp_path/provider)
 assert not(tmp_path/provider).exists()
def test_exact_scope():
 p=driver.plan();assert sum(len(s) for s in p['slots'].values())==90 and p['providers']==driver.CAPS
 for provider,rows in p['slots'].items():
  assert all(s['cohort']=='validation' and s['task'] in driver.TASKS and s['provider']==provider for s in rows)
  for config in {s['configuration_id'] for s in rows}:
   selected=[s for s in rows if s['configuration_id']==config];assert len(selected)==10 and sum(s['condition']=='C0' for s in selected)==5
def test_main_slot_rejected_by_validation_permission(tmp_path):
 from benchmark.expanded.execution_authorization import ExecutionPermit
 from benchmark.expanded.providers import TokenRates
 from benchmark.expanded.planning import allocation
 state=tmp_path/'mistral';driver.prepare('Mistral',state,mock=True);permit=ExecutionPermit(state/'execution_permission.json',root=state/'candidate_repo/expanded_study');rates={k:TokenRates(**v) for k,v in driver.plan()['token_rates'].items()}
 with pytest.raises(DispatchPaused):permit.validate_slot(allocation(state/'candidate_repo/expanded_study')[0][0],rates)
def test_workflow_isolation_and_credential_scope():
 text=(ROOT/'.github/workflows/full-study.yml').read_text();jobs=re.split(r'^  ([a-z][a-z0-9-]+):\n',text.split('jobs:\n',1)[1],flags=re.M);seen=[]
 for i in range(1,len(jobs),2):
  name,body=jobs[i],jobs[i+1];seen.append(name)
  if not name.startswith('amended-prompt-'):assert '!inputs.amended_prompt_checks' in body.split('    runs-on:',1)[0]
 assert {'amended-prompt-gate','amended-prompt-generation','amended-prompt-saved-evaluation'}<=set(seen)
 evaluation=text.split('  amended-prompt-saved-evaluation:',1)[1].split('\n  amended-main-readiness:',1)[0];assert 'secrets' not in evaluation and 'AMENDMENT_PROVIDER_API_KEY' not in evaluation
 generation=text.split('  amended-prompt-generation:',1)[1].split('  amended-prompt-saved-evaluation:',1)[0]
 assert generation.count('AMENDMENT_PROVIDER_API_KEY: ${{ secrets[matrix.secret_name] }}')==20 and 'needs: amended-prompt-gate' in generation and 'no main calls' in text
