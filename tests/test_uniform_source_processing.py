"""One uniform extraction rule: no block selection, repair or status rescue."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from source_processing_policy import process
from evaluate_uniform_source_processing import derivation,prepare

@pytest.mark.parametrize('text,expected',[
    ('print(1)','print(1)\n'),
    ('```python\nprint(1)\n```','print(1)\n'),
    ('Intro\n```python\nprint(1)\n```\nExplanation','print(1)\n'),
    ('Intro\n```\nprint(1)\n```\nExplanation','print(1)\n'),
    ('```python\nprint(1)','```python\nprint(1)\n'),
    ('```javascript\nalert(1)\n```','```javascript\nalert(1)\n```\n'),
    ('',''),
])
def test_exact_structural_handling(text,expected):
    assert process(text)['source']==expected

def test_multiple_code_blocks_are_never_chosen_or_merged():
    text='Intro\n```python\nx=1\n```\n```python\nx=2\n```'
    assert process(text)['source']==text+'\n'
    assert process(text)['method']=='ambiguous_or_unfinished_fences'

@pytest.mark.parametrize('status',['incomplete','refused','truncated'])
def test_incomplete_or_refused_generation_is_not_rescued_by_compilable_code(status):
    metadata={'source_sha256':'original','generation_status':status}
    source,strict,derived=derivation(metadata,'Intro\n```python\nx=1\n```')
    assert source=='x=1\n' and derived['generation_status']==status
    assert metadata=={'source_sha256':'original','generation_status':status}
    assert derived['original_source_sha256']=='original' and derived['derived_for_excluded_validation']

def test_empty_code_block_remains_a_no_code_failure():
    source,strict,metadata=derivation({'source_sha256':'original','generation_status':'completed'},'Intro\n```python\n\n```')
    assert not source and metadata['generation_status']=='no_code' and metadata['source_sha256'] is None

def test_syntax_is_never_repaired():
    assert process('Intro\n```python\nx = (\n```')['source']=='x = (\n'

def test_wrong_archive_fails_before_any_derived_files(tmp_path):
    f=tmp_path/'wrong.zip';f.write_bytes(b'wrong')
    with pytest.raises(ValueError,match='wrong original archive'):prepare(f,tmp_path/'out','Google')
    assert not (tmp_path/'out').exists()

def test_extra_or_unfinished_fence_prevents_selecting_an_otherwise_complete_block():
    text='Intro\n```python\nx=1\n```\n```python\nx='
    assert process(text)['source']==text+'\n'
    assert process(text)['method']=='ambiguous_or_unfinished_fences'

def test_uniform_workflow_has_no_model_credentials_and_token_is_only_in_download_step():
    text=(Path(__file__).parents[1]/'.github/workflows/full-study.yml').read_text()
    job=text.split('  uniform-saved-source-evaluation:',1)[1]
    assert 'secrets.' not in job and 'persist-credentials: false' in job
    token_steps=[s for s in job.split('      - ') if 'GH_TOKEN:' in s]
    assert len(token_steps)==1 and 'gh api' in token_steps[0]
    assert 'evaluate_uniform_source_processing.py' not in token_steps[0]
    assert job.index('Preserve exact original and derived inputs')<job.index('Test only changed completed saved sources')
    assert 'github.run_attempt == \'1\'' in job
    for mode in ('confirm_paid_generation','resume_grok_request_fix','recover_grok_after_key_fix',
                 'evaluate_saved_mistral_google','evaluate_saved_openai','inspect_grok_access_only','verify_setup_only','continue_grok_budget'):
        assert '!inputs.'+mode in job

def test_every_other_job_is_excluded_from_uniform_evaluation_dispatch():
    text=(Path(__file__).parents[1]/'.github/workflows/full-study.yml').read_text()
    other=text.split('jobs:',1)[1].split('  uniform-saved-source-evaluation:',1)[0]
    guards=[line for line in other.splitlines() if line.startswith('    if:')]
    assert len(guards)==10
    assert all('!inputs.evaluate_uniform_saved_sources' in line for line in guards)
