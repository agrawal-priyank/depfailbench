"""Fixed OpenAI saved-evidence selection; no generated source is executed."""
import importlib.util,json
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('saved_openai',ROOT/'scripts/evaluate_saved_openai_validation.py');wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)

def test_exact_archive_run_and_no_oracle_amendment():
 assert wrapper.ARCHIVE_SHA256=='859a08250f722a053e26728e240229a6ec6083e339744496b3d3233b4cbf57af'
 assert wrapper.SOURCE_RUN_ID==39474852218 and wrapper.SOURCE_ARTIFACT_ID==12290279403
 assert wrapper.MEASUREMENT_AMENDMENT is None


def test_foreign_archive_rejected_before_extraction(tmp_path):
 path=tmp_path/'foreign.zip';path.write_bytes(b'wrong archive')
 with pytest.raises(ValueError,match='archive differs'):wrapper.prepare(path,tmp_path/'out')
 assert not (tmp_path/'out').exists()


def test_bytecode_exception_still_checks_every_original(tmp_path):
 source=tmp_path/'original/openai_api_validation/artifacts/validation_E1_gpt_6_1_sol_C0/app.py';source.parent.mkdir(parents=True);source.write_text('original')
 relative=str(source.relative_to(tmp_path/'original'));verified={'inputs':{source.parent.name:{}},'original_files':{relative:wrapper.digest(source)}}
 bytecode=source.parent/'__pycache__/app.cpython-312.pyc';bytecode.parent.mkdir();bytecode.write_bytes(b'derived')
 assert wrapper.original_hashes(tmp_path,verified)==verified['original_files']
 source.write_text('changed');assert wrapper.original_hashes(tmp_path,verified)!=verified['original_files']


def test_workflow_uses_exact_archive_and_exposes_no_model_credentials_to_saved_code():
 text=(ROOT/'.github/workflows/full-study.yml').read_text();saved=text.split('  saved-openai-evaluation:',1)[1].split('  verify-remaining-setup:',1)[0]
 assert 'secrets.' not in saved and '12290279403/zip' in saved
 token_steps=[step for step in saved.split('      - ') if 'GH_TOKEN:' in step]
 assert len(token_steps)==1 and 'gh api' in token_steps[0] and 'python ' not in token_steps[0]
 assert 'persist-credentials: false' in saved
 assert saved.index('Preserve verified original inputs')<saved.index('Evaluate unchanged programs')


def test_remaining_workflow_never_runs_historical_or_main_generation():
 text=(ROOT/'.github/workflows/full-study.yml').read_text()
 assert 'benchmark.full_generate' not in text and 'full_batch_eval' not in text
 assert 'OPENAI_API_KEY' not in text and 'ANTHROPIC_API_KEY' not in text
 assert 'XAI_API_KEY: ${{ secrets.GROK_API_KEY }}' in text
 assert text.count('confirm_paid_generation && github.run_attempt')==3
 assert text.count('Generate excluded validation group')==48
