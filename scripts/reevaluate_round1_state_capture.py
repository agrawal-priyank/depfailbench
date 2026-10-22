"""Credential-free remeasurement of the same 720 saved round-one programs."""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path

from benchmark.expanded.collect import collect, audit_collection, implementation_manifest, verify_record
from benchmark.expanded.planning import allocation, digest
from continue_main_round1 import fetch_named
from record_evaluation_host import write_record

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'scripts/round1_state_capture_plan.json'


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        handle.write(json.dumps(value, indent=2)+'\n')


def selected(plan, provider, shard):
    assert provider in plan['sources'] and type(shard) is int and 0 <= shard < 4
    return [r for r in plan['slots'] if r['provider'] == provider][shard::4]


def check():
    p = load(PLAN)
    assert p['scope'] == 'same720_saved_sources_only' and p['model_api_calls'] == 0
    assert p['source_run_id'] == 39713767564 and p['source_commit'] == 'a6c1c94bdf6dc8db52c7da29720e887fe284319d'
    assert p['shards_per_provider'] == 4 and p['new_generated_outputs'] == 0
    assert digest(ROOT/'src/benchmark/expanded/worker.py') == p['corrected_worker_sha256']
    for name, expected in p['unchanged_core_files'].items():
        assert digest(ROOT/name) == expected, name
    schedule = allocation(ROOT/'expanded_study')[0]
    wanted = [r for r in schedule if r['round'] == 1]
    assert len(wanted) == 720 and len(p['slots']) == 720
    assert [r['artifact_id'] for r in wanted] == [r['artifact_id'] for r in p['slots']]
    for slot, row in zip(wanted, p['slots']):
        assert all(row[k] == slot[k] for k in slot)
    partition = [r['artifact_id'] for provider in p['sources'] for shard in range(4)
                 for r in selected(p, provider, shard)]
    assert len(partition) == len(set(partition)) == 720
    assert set(partition) == {r['artifact_id'] for r in wanted}
    return p


def prepare(provider, shard, output):
    p = check()
    assert os.environ['GITHUB_RUN_ATTEMPT'] == '1'
    assert not output.exists()
    source = p['sources'][provider]
    # Original archives stay outside this job's new evidence upload tree.
    saved = Path('saved')/provider/str(shard)
    meta = fetch_named(p['source_run_id'], p['source_commit'], source['artifact_name'], saved)
    assert meta['id'] == source['artifact_id'] and meta['digest'] == 'sha256:'+source['archive_sha256']
    campaign = saved/'contents'/provider.lower()/'campaign'
    root = campaign/'frozen_repo/expanded_study'
    assert digest(root/'study.json') == p['frozen_study_sha256']
    slots = selected(p, provider, shard)
    expected_all = {r['artifact_id'] for r in p['slots'] if r['provider'] == provider}
    assert {d.name for d in (campaign/'artifacts').iterdir()} == expected_all
    for slot in slots:
        artifact = campaign/'artifacts'/slot['artifact_id']
        assert digest(artifact/'app.py') == slot['source_sha256']
        metadata = load(artifact/'metadata.json')
        assert all(metadata[k] == slot[k] for k in allocation(root)[0][slot['sequence']-1])
    output.mkdir(parents=True)
    save(output/'prepared_inputs.json', {'provider':provider,'shard':shard,
         'source_artifact':meta,'campaign':str(campaign),'plan_sha256':digest(PLAN),
         'reevaluation_run_id':int(os.environ['GITHUB_RUN_ID']),'reevaluation_commit':os.environ['GITHUB_SHA']})


def evaluate(provider, shard, output):
    p = check()
    # Fetching is a separate step. Generated code receives no GitHub token.
    assert 'GH_TOKEN' not in os.environ and 'GITHUB_TOKEN' not in os.environ
    assert os.environ['GITHUB_RUN_ATTEMPT'] == '1' and not (output/'collection').exists()
    prepared = load(output/'prepared_inputs.json')
    assert (prepared['provider'],prepared['shard']) == (provider,shard)
    assert prepared['plan_sha256'] == digest(PLAN)
    assert prepared['reevaluation_run_id'] == int(os.environ['GITHUB_RUN_ID'])
    assert prepared['reevaluation_commit'] == os.environ['GITHUB_SHA']
    campaign = Path(prepared['campaign']);root = campaign/'frozen_repo/expanded_study'
    assert digest(root/'study.json') == p['frozen_study_sha256']
    slots = selected(p,provider,shard);meta = prepared['source_artifact']
    for slot in slots:
        assert digest(campaign/'artifacts'/slot['artifact_id']/'app.py') == slot['source_sha256']
    write_record(output/'host_metadata.json')
    summary = collect(campaign/'artifacts', output/'collection', cohort='main',
                      artifact_ids=[r['artifact_id'] for r in slots], root=root,
                      progress=lambda r: print(json.dumps(r), flush=True))
    assert summary['complete_matrix'] and summary['programs'] == len(slots)
    assert summary['evaluation_records'] == 9*len(slots) and not summary['confirmatory_ready']
    save(output/'source_linkage.json', {'provider': provider, 'shard': shard,
         'source_artifact': meta, 'source_run_id': p['source_run_id'], 'source_commit': p['source_commit'],
         'plan_sha256': digest(PLAN), 'implementation': implementation_manifest(),
         'reevaluation_run_id': int(os.environ['GITHUB_RUN_ID']), 'reevaluation_commit': os.environ['GITHUB_SHA'],
         'model_api_calls': 0, 'source_repairs': 0, 'new_generated_outputs': 0})


def audit(folder, output):
    p = check()
    seen = {}; totals = Counter(); flags = []; changes = []; cell = defaultdict(Counter)
    dirs = sorted(f.parent for f in folder.rglob('source_linkage.json'))
    assert len(dirs) == 16
    parts = set()
    for base in dirs:
        link = load(base/'source_linkage.json')
        provider, shard = link['provider'], link['shard']
        assert (provider, shard) not in parts
        parts.add((provider, shard))
        assert link['source_artifact']['id'] == p['sources'][provider]['artifact_id']
        assert link['source_artifact']['digest'] == 'sha256:'+p['sources'][provider]['archive_sha256']
        assert link['plan_sha256'] == digest(PLAN) and link['implementation'] == implementation_manifest()
        assert link['reevaluation_run_id'] == int(os.environ['GITHUB_RUN_ID'])
        assert link['reevaluation_commit'] == os.environ['GITHUB_SHA']
        host = load(base/'host_metadata.json')
        assert host['workflow_and_image']['GITHUB_SHA'] == os.environ['GITHUB_SHA']
        manifest = load(base/'collection/collection_manifest.json')
        assert manifest['environment']['platform'].startswith('Linux-') and manifest['environment']['machine'] == 'x86_64'
        assert manifest['environment']['python'].startswith('3.12.14')
        assert manifest['implementation'] == implementation_manifest()
        assert not manifest['synthetic_data'] and manifest['selected_repeat'] == 1
        slots = selected(p, provider, shard)
        assert set(manifest['inputs']) == {s['artifact_id'] for s in slots}
        summary = audit_collection(base/'collection')
        assert summary['complete_matrix'] and summary['evaluation_records'] == 9*len(slots)
        totals['outputs'] += len(slots); totals['records'] += summary['evaluation_records']
        flags += summary['reproducibility_disagreements']
        for slot in slots:
            ident = slot['artifact_id']; assert ident not in seen
            assert manifest['inputs'][ident]['source_sha256'] == slot['source_sha256']
            record = load(base/'collection/records'/ident/'deadline_1_repeat_1.json')
            verify_record(record, manifest, ident, 1, 1)
            result = record['result']; seen[ident] = record
            cell[(slot['configuration_id'], slot['condition'])].update(
                outputs=1, all_pass=int(result['primary_pass']), functional=int(result['clean_qualified']))
            if (result['primary_pass'], result['clean_qualified']) != (slot['previous_primary_pass'], slot['previous_clean_qualified']):
                changes.append({'artifact_id': ident, 'before_all_pass': slot['previous_primary_pass'],
                                'after_all_pass': result['primary_pass'], 'before_functional': slot['previous_clean_qualified'],
                                'after_functional': result['clean_qualified']})
    assert parts == {(v, s) for v in p['sources'] for s in range(4)}
    assert totals == {'outputs': 720, 'records': 6480}
    save(output, {'passed': True, 'scope': p['scope'], 'outputs': 720, 'records': 6480,
        'model_api_calls': 0, 'new_generated_outputs': 0, 'source_repairs': 0,
        'source_run_id': p['source_run_id'], 'source_commit': p['source_commit'],
        'reevaluation_run_id': int(os.environ['GITHUB_RUN_ID']), 'reevaluation_commit': os.environ['GITHUB_SHA'],
        'changed_selected_outcomes': changes, 'repeat_flags_preserved': flags,
        'counts': [{'configuration_id': k[0], 'condition': k[1], **v} for k,v in cell.items()],
        'confirmatory_ready': False, 'note': 'Partial main cohort. All old evidence retained. No additional generation authorized by this workflow.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['check','prepare','evaluate','audit'])
    parser.add_argument('--provider'); parser.add_argument('--shard',type=int)
    parser.add_argument('--folder',type=Path); parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.mode == 'check':
        check(); print(json.dumps({'checked':True,'outputs':720,'records':6480,'new_generated_outputs':0}))
    elif args.mode == 'prepare':
        prepare(args.provider,args.shard,args.output)
    elif args.mode == 'evaluate':
        evaluate(args.provider,args.shard,args.output)
    else:
        audit(args.folder,args.output)
