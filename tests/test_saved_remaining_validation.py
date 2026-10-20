"""Saved-provider evidence, missing-code preservation and credential isolation."""
import importlib.util,json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('saved_remaining',ROOT/'scripts/evaluate_saved_remaining_validation.py')
wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)

@pytest.mark.parametrize('provider',list(wrapper.SPECS))
def test_wrong_archive_fails_before_extraction(tmp_path,provider):
    f=tmp_path/'wrong.zip';f.write_bytes(b'wrong')
    with pytest.raises(ValueError,match='archive differs'):wrapper.prepare(f,tmp_path/'out',provider)
    assert not (tmp_path/'out').exists()

@pytest.mark.parametrize('provider',list(wrapper.SPECS))
def test_original_hash_guard_preserves_missing_code_and_only_allows_precise_bytecode(tmp_path,provider):
    slug=wrapper.SPECS[provider]['slug'];identity='validation_E1_example_C0'
    d=tmp_path/'original'/(slug+'_api_validation')/'artifacts'/identity;d.mkdir(parents=True)
    m=d/'metadata.json';m.write_text('{"source_sha256":null,"generation_status":"incomplete"}')
    rel=str(m.relative_to(tmp_path/'original'));verified={'inputs':{identity:{}},'original_files':{rel:wrapper.digest(m)}}
    assert wrapper.original_hashes(tmp_path,verified,provider)==verified['original_files'] and not (d/'app.py').exists()
    cache=d/'__pycache__/app.cpython-312.pyc';cache.parent.mkdir();cache.write_bytes(b'derived')
    assert wrapper.original_hashes(tmp_path,verified,provider)==verified['original_files']
    (d/'app.py').write_text('unexpected repair')
    with pytest.raises(ValueError,match='unexpected file'):wrapper.original_hashes(tmp_path,verified,provider)

def test_fixed_provider_scope_and_no_new_measurement_policy():
    assert set(wrapper.SPECS)=={'Mistral','Google'} and wrapper.MEASUREMENT_AMENDMENT is None
    assert wrapper.SOURCE_RUN_ID==39486369819
    assert sum(x['count'] for x in wrapper.SPECS.values())==64

def test_workflow_does_not_expose_credentials_to_generated_source_or_repeat_other_batches():
    text=(ROOT/'.github/workflows/full-study.yml').read_text()
    job=text.split('  saved-mistral-google-evaluation:',1)[1].split('  grok-request-recovery:',1)[0]
    assert 'secrets.' not in job and 'persist-credentials: false' in job
    steps=[s for s in job.split('      - ') if 'GH_TOKEN:' in s]
    assert len(steps)==1 and 'gh api' in steps[0] and 'evaluate_saved_remaining_validation.py' not in steps[0]
    assert '&& !inputs.confirm_paid_generation' in job and '&& !inputs.evaluate_saved_openai' in job
    assert 'github.run_attempt == \'1\'' in job
    assert job.index('Preserve immutable verified inputs')<job.index('Evaluate unchanged saved outcomes')
