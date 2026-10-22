"""Declare a fully fresh amended main cohort without rewriting original evidence.

This creates a planning manifest with zero original-source reuse. It does not authorize paid execution,
change provenance, import generated programs, or supply old results to analysis.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from benchmark.expanded.collect import asset_manifest
from benchmark.expanded.planning import allocation, check, digest

UNCHANGED = {'E1', 'E2', 'E3'}
CHANGED = {'E4', 'E5', 'E6', 'E7', 'E8'}
STUDY_ADMIN_FIELDS = {'protocol_version', 'status', 'frozen', 'paid_execution_authorized',
                      'budget_authorized', 'cost_note', 'prompt_amendment'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return json.loads(Path(path).read_text())


def verify_designs(original, candidate):
    check(original)
    check(candidate)
    old, new = load(original/'study.json'), load(candidate/'study.json')
    require({k:v for k,v in old.items() if k not in STUDY_ADMIN_FIELDS} ==
            {k:v for k,v in new.items() if k not in STUDY_ADMIN_FIELDS},
            'Scientific design or model settings changed beyond the approved prompt amendment')
    before, after = asset_manifest(original), asset_manifest(candidate)
    expected = {'study.json'} | {f'tasks/{t}.md' for t in CHANGED} | {
        f'prompts/{t}_{c}.md' for t in CHANGED for c in ['C0', 'C1']}
    require(before.keys() == after.keys(), 'Asset inventory changed')
    actual = {name for name in before if before[name] != after[name]}
    require(actual == expected, 'Expected only the five-task prompt clarification and study declaration')
    old_slots, new_slots = allocation(original)[0], allocation(candidate)[0]
    require(len(old_slots) == len(new_slots) == 4320, 'Wrong full cohort size')
    for a, b in zip(old_slots, new_slots):
        require({k:v for k,v in a.items() if k != 'prompt_sha256'} ==
                {k:v for k,v in b.items() if k != 'prompt_sha256'}, 'Allocation or identifiers changed')
        require((a['prompt_sha256'] == b['prompt_sha256']) == (a['task'] in UNCHANGED),
                'Unexpected prompt-version relation')
    return new_slots, before, after


def fresh_slots(original, candidate):
    slots, before, after = verify_designs(original, candidate)
    require(len(slots) == 4320 and len({s['artifact_id'] for s in slots}) == 4320,
            'Fresh cohort must have all4320 unique coordinates')
    require(Counter(s['provider'] for s in slots) ==
            {'Mistral':1440,'OpenAI':1920,'Anthropic':480,'Google':480},
            'Fresh cohort must regenerate all1440 Mistral outputs')
    require(all(s['cohort'] == 'main' for s in slots), 'Validation must not enter main cohort')
    return slots, before, after


def prepare(original, candidate, audit_path, archive_path, output):
    require(not output.exists(), 'Preserve existing execution plans; inspect instead')
    slots, old_assets, new_assets = fresh_slots(original, candidate)
    audit = load(audit_path)
    require(audit['passed'] is True and audit['run_id'] == 39533790606 and
            audit['commit'] == 'ad4709017a2b90135dca790d4987478aac9e24b7' and
            audit['main_mistral_outputs'] == 1440 and audit['archive_sha256'] == digest(archive_path),
            'Original audited Mistral archive identity does not match')
    old_slots = [s for s in allocation(original)[0] if s['provider'] == 'Mistral']
    require(len(audit['rows']) == len({r['artifact_id'] for r in audit['rows']}) == 1440 and
            {r['artifact_id'] for r in audit['rows']} == {s['artifact_id'] for s in old_slots},
            'Original audit has missing or duplicate coordinates')
    record = {
        'schema_version':1, 'status':'author selected fully fresh main cohort; exact batch freeze/dispatch pending',
        'author_instruction':'we can re-run whole mistral study since they were super cheap, scrap the previous one?',
        'decision':'Regenerate all1440 Mistral main outputs; preserve the previous1440 separately as superseded original-prompt main results. Reuse no original source in the amended main cohort.',
        'campaign_namespace':'main-clarified-prompts-20261021-fresh-v1',
        'original_run_id':audit['run_id'], 'original_commit':audit['commit'],
        'original_archive_sha256':audit['archive_sha256'], 'original_audit_sha256':digest(audit_path),
        'original_assets':old_assets, 'candidate_assets':new_assets,
        'final_main_outputs':4320, 'new_generation_slots':slots,
        'counts':{'reuse':0,'new':4320,'superseded_separate':1440},
        'new_by_provider':dict(Counter(s['provider'] for s in slots)),
        'superseded_original_main_slots_retained_separately':old_slots,
        'retention_policy':'Preserve original responses, source, scores, ledgers, timestamps and correction history. Do not relabel old main programs as validation or delete them because performance was poor.',
        'provenance_policy':'All new responses live under the fresh campaign namespace and new frozen protocol. Textual coordinate IDs may match old run IDs only in separate versioned evidence roots; never overwrite or merge the old directories.',
        'measurement_policy':'Evaluate all4320 fresh outputs under the same final measured implementation, pinned runtime and per-job host-recording procedure. Keep all failed, incomplete, refused, no-source and syntax-invalid returned outcomes. No source repairs or favorable-repeat selection.',
        'excluded_validation_added_to_main':0,'paid_execution_authorized':False,
        'model_api_calls':0,'generated_program_executions':0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as handle:
        handle.write(json.dumps(record,indent=2)+'\n')
    return {k:record[k] for k in ['status','counts','new_by_provider','model_api_calls','generated_program_executions']}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['original','candidate','audit','archive','output']:
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(prepare(a.original,a.candidate,a.audit,a.archive,a.output),indent=2))
