"""One uniform extraction rule: no block selection, repair or status rescue."""
import sys
import re
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


@pytest.mark.parametrize('provider', ['OpenAI', 'Anthropic', 'Google', 'Mistral'])
@pytest.mark.parametrize('condition', ['C0', 'C1'])
def test_generation_pipeline_preserves_raw_response_and_records_uniform_extraction(tmp_path, provider, condition):
    import json
    from benchmark.expanded.planning import allocation, assets_root
    from benchmark.expanded.provider_dry_run import fixture
    from benchmark.expanded.provider_generation import publish_output
    from benchmark.expanded.providers import build_request, parse_response
    text = 'Explanation\n```python\nx = 1\n```\nEnd explanation'
    raw = fixture(provider)
    if provider == 'OpenAI':
        raw['output'] = [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]
    elif provider == 'Anthropic':
        raw['content'] = [{'type': 'text', 'text': text}]
    elif provider == 'Google':
        raw['steps'] = [{'type': 'model_output', 'content': [{'type': 'text', 'text': text}]}]
    else:
        raw['choices'][0]['message']['content'] = text
    parsed = parse_response(provider, raw)
    slot = next(s for s in allocation()[1] if s['provider'] == provider and s['condition'] == condition)
    configs = json.loads((assets_root()/'study.json').read_text())['configurations']
    config = next(c for c in configs if c['id'] == slot['configuration_id'])
    metadata = publish_output(tmp_path, slot=slot, config=config, request=build_request(config, 'test'),
        parsed=parsed, cost='0.01', simulation_only=True, generated_at='synthetic-test')
    assert (tmp_path/'response.txt').read_text() == text
    assert (tmp_path/'app.py').read_text() == 'x = 1\n'
    assert metadata['generation_status'] == 'completed'
    assert metadata['source_processing']['policy'] == 'single-unambiguous-python-fence-2026-10-20'
    assert metadata['source_processing']['surrounding_text_removed']
    assert not metadata['source_processing']['structural_format_compliant_under_original_rule']
    assert json.loads((tmp_path/'metadata.json').read_text()) == metadata


def test_core_extraction_cannot_turn_an_incomplete_response_into_a_completed_program():
    from benchmark.expanded.provider_dry_run import fixture
    from benchmark.expanded.providers import parse_response
    raw = fixture('OpenAI')
    raw['status'] = 'incomplete'
    raw['output'] = [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Intro\n```python\nx=1\n```'}]}]
    parsed = parse_response('OpenAI', raw)
    assert parsed['source'] == 'x=1\n'
    assert parsed['generation_status'] == 'incomplete'

def test_uniform_workflow_has_no_model_credentials_and_token_is_only_in_download_step():
    text=(Path(__file__).parents[1]/'.github/workflows/full-study.yml').read_text()
    job=re.split(r'\n  [a-zA-Z0-9_-]+:\n',text.split('  uniform-saved-source-evaluation:',1)[1],maxsplit=1)[0]
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
    jobs=text.split('jobs:',1)[1]
    target=re.split(r'\n  [a-zA-Z0-9_-]+:\n',jobs.split('  uniform-saved-source-evaluation:',1)[1],maxsplit=1)[0]
    other=jobs.replace(target,'',1)
    guards=[line for line in other.splitlines() if line.startswith('    if:')]
    assert len(guards)==14
    assert all('!inputs.evaluate_uniform_saved_sources' in line for line in guards)
