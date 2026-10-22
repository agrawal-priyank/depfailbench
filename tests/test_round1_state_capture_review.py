"""Coverage, fixed source identity and credential isolation for remeasurement."""
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import reevaluate_round1_state_capture as review


def test_partition_covers_only_original720_once_with_all_deadlines_and_repeats_together():
    p=review.check();seen=set()
    for provider in p['sources']:
        for shard in range(4):
            group=review.selected(p,provider,shard)
            assert group and all(s['round']==1 and s['cohort']=='main' for s in group)
            identities={s['artifact_id'] for s in group}
            assert not seen.intersection(identities)
            seen.update(identities)
    assert len(seen)==720


@pytest.mark.parametrize('shard',[-1,4,True,None])
def test_invalid_partition_is_rejected(shard):
    with pytest.raises(AssertionError):
        review.selected(review.check(),'OpenAI',shard)


def test_github_token_cannot_reach_saved_program_execution(tmp_path,monkeypatch):
    monkeypatch.setenv('GH_TOKEN','controlled-test-placeholder')
    monkeypatch.setattr(review,'collect',lambda *a,**k:pytest.fail('no execution with credentials'))
    with pytest.raises(AssertionError):
        review.evaluate('OpenAI',0,tmp_path)


def test_workflow_has_no_model_secrets_and_fetch_token_is_in_separate_step():
    text=(ROOT/'.github/workflows/round1-state-capture-review.yml').read_text()
    assert 'secrets' not in text and 'API_KEY' not in text
    assert text.count('GH_TOKEN:')==1 and 'persist-credentials: false' in text
    execution=text.split('- name: Re-evaluate only original sources with no credentials',1)[1].split('- uses:',1)[0]
    assert 'TOKEN' not in execution and ' prepare ' not in execution
