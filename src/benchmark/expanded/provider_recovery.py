"""Recover saved provider bytes locally. No credentials, API or fresh generation.

With store=false there is no assumption that an interrupted response can be
retrieved remotely. An accepted response with no recoverable content stays
unfilled and paused. It is not silently replaced by another model response.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from .dispatch_lock import slot_lock
from .planning import allocation, assets_root, prompt
from .provider_generation import publish_output, save_json
from .provider_streams import ResponseAssembler, SSEDecoder
from .providers import TokenRates, build_request, canonical, parse_response, sha256
from .spending import DispatchPaused


def replay_wire(provider, wire, headers, completed):
    assembler, decoder = ResponseAssembler(provider), SSEDecoder()
    error = completed.get('error_kind')
    status = headers.get('http_status', completed.get('http_status'))
    if status == 200:
        try:
            if headers.get('content-type', '').split(';')[0] == 'text/event-stream':
                for start in range(0, len(wire), 4096):
                    for event in decoder.feed(wire[start:start+4096]):
                        assembler.add(event)
                decoder.feed(b'', final=True)
            else:
                raw = json.loads(wire)
                if not isinstance(raw, dict):
                    raise ValueError('response must be an object')
                assembler.raw = raw
                assembler.accepted = bool(raw.get('id'))
                assembler.content_received = bool(raw.get('content') or raw.get('output') or raw.get('steps') or raw.get('choices'))
                assembler.terminal = True
        except (ValueError, KeyError, TypeError, UnicodeError, AttributeError):
            error = 'InterruptedOrInvalidSavedWire'
    raw = assembler.response()
    try:
        parsed = parse_response(provider, raw, stream_complete=assembler.terminal and error is None)
    except (KeyError, ValueError, TypeError, AttributeError):
        error = 'AdapterSchemaError'
        parsed = parse_response(provider, {}, stream_complete=False)
        parsed['provider_response_id'] = raw.get('id')
    returned = (raw.get('status') in {'completed','incomplete'} or
                raw.get('stop_reason') in {'end_turn','refusal','max_tokens','stop_sequence'} or
                bool(raw.get('choices') and raw['choices'][0].get('finish_reason')))
    consumed = status == 200 and (assembler.content_received or assembler.terminal and returned)
    return {'parsed':parsed,'raw':raw,'consumed':consumed,'accepted':assembler.accepted,
            'error_kind':error,'http_status':status,'terminal_received':assembler.terminal}


def recover_saved_response(artifact, *, ledger, root=None):
    """Caller must stop/reap the sender first; the slot lock also enforces this."""
    artifact, root = Path(artifact), assets_root(root)
    with slot_lock(artifact.parent, artifact.name):
        slot = json.loads((artifact/'slot.json').read_text())
        if slot['artifact_id'] != artifact.name:
            raise DispatchPaused('artifact directory and saved identity differ')
        declared = {s['artifact_id']:s for batch in allocation(root) for s in batch}
        if slot != declared.get(artifact.name):
            raise DispatchPaused('saved slot differs from the declared allocation')
        config = json.loads((artifact/'configuration.json').read_text())
        design = json.loads((root/'study.json').read_text())
        if config != next(c for c in design['configurations'] if c['id']==slot['configuration_id']):
            raise DispatchPaused('saved provider configuration differs')
        text = (artifact/'prompt.txt').read_text()
        if text != prompt(slot['task'],slot['condition'],root):
            raise DispatchPaused('saved prompt differs; preserve evidence for review')
        provenance = json.loads((artifact/'provenance.json').read_text())
        simulation = provenance.get('simulation_only')
        if simulation is not ledger.simulation_only:
            raise DispatchPaused('simulation and actual evidence cannot share a ledger')
        rates = TokenRates(**provenance['token_rates'])
        request = build_request(config,text)
        fingerprint = sha256(canonical({'slot':slot,'request':request,'rates':asdict(rates)}))
        if provenance.get('dispatch_fingerprint') != fingerprint:
            raise DispatchPaused('dispatch fingerprint differs from saved evidence')
        for key,path in (('study_sha256',root/'study.json'),('scaffold_sha256',root/'scaffold.py'),
                         ('task_manifest_sha256',root/'task_contracts.json'),('dependency_lock_sha256',root.parent/'requirements.lock')):
            if provenance[key] != sha256(path.read_text()):
                raise DispatchPaused('saved provenance differs from the protocol snapshot')
        directories=sorted(artifact.glob('attempt_[0-9][0-9]'))
        if not directories:
            raise DispatchPaused('no saved attempt; preserve the pending reservation for operator review')
        directory=directories[-1];number=int(directory.name.rsplit('_',1)[1]);identity=f"{artifact.name}:{number}"
        attempt=ledger.get_attempt(identity)
        if attempt['fingerprint'] != fingerprint or attempt['provider'] != slot['provider']:
            raise DispatchPaused('ledger fingerprint differs from saved request')
        if json.loads((directory/'request.json').read_text()) != request:
            raise DispatchPaused('saved request differs; no recovery overwrite permitted')
        started=json.loads((directory/'started.json').read_text())
        if started['id'] != identity or started['dispatch_fingerprint'] != fingerprint:
            raise DispatchPaused('attempt start journal differs')
        header_path=directory/'response_headers.json'
        headers=json.loads(header_path.read_text()) if header_path.exists() else {}
        wire_path=directory/'wire_response.bin'
        wire=wire_path.read_bytes() if wire_path.exists() else b''
        complete_path=directory/'wire_complete.json'
        completed=json.loads(complete_path.read_text()) if complete_path.exists() else {}
        if completed and completed['wire_sha256'] != hashlib.sha256(wire).hexdigest():
            raise DispatchPaused('wire bytes differ from their completed journal hash')
        report=replay_wire(slot['provider'],wire,headers,completed)
        parsed=report['parsed'];cost=rates.estimate(parsed['usage'])
        files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()
               if p.is_file() and not p.name.startswith('.generation-')}
        evidence=sha256(canonical(files))
        generated_at=completed.get('finished_at',started['started_at'])
        metadata=None
        if report['consumed']:
            metadata=publish_output(artifact,slot=slot,config=config,request=request,parsed=parsed,cost=cost,
                                    simulation_only=simulation,synthetic_data=provenance.get('synthetic_data',simulation),
                                    generated_at=generated_at)
        outcome=parsed['generation_status'] if report['consumed'] else 'service_unfilled'
        ledger.recover_finish(identity,cost_usd=cost,outcome=outcome,response_id=parsed['provider_response_id'],
                              consume=report['consumed'],evidence_sha256=evidence)
        if not report['consumed'] or not parsed['usage']['complete']:
            ledger.pause(slot['provider'],'saved response recovered or inspected; unresolved output/billing requires review')
        recovery={'attempt_id':identity,'recovered_at':datetime.now(timezone.utc).isoformat(),
                  'simulation_only':simulation,'wire_sha256':hashlib.sha256(wire).hexdigest(),
                  'completion_marker_available':bool(completed),
                  'metadata_time_basis':'wire_completion' if completed else 'attempt_start_fallback',
                  'evidence_sha256':evidence,'evidence_file_hashes':files,'outcome':outcome,
                  'output_retained':report['consumed'],'accepted':report['accepted'],
                  'provider_response_id':parsed['provider_response_id'],'model_api_calls':0,
                  'new_generation_performed':False,'metadata':metadata}
        index=len(list(artifact.glob('recovery_[0-9][0-9][0-9].json')))+1
        save_json(artifact/f'recovery_{index:03d}.json',recovery)
        return recovery


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact',type=Path)
    parser.add_argument('--ledger',type=Path,required=True)
    args=parser.parse_args()
    report=recover_saved_response(args.artifact,ledger=SpendingLedger.open_for_recovery(args.ledger))
    print(json.dumps({k:v for k,v in report.items() if k not in {'metadata','evidence_file_hashes'}},indent=2))


if __name__=='__main__':
    main()
