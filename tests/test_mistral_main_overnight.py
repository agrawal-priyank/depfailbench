"""Frozen Mistral-only continuation, retained spending and failure checkpoints."""
import asyncio,importlib.util,json,sqlite3,zipfile,hashlib,sys
from pathlib import Path
import httpx,pytest
from benchmark.expanded.provider_dry_run import fixture,stream_events,sse_bytes
from benchmark.expanded.spending import DispatchPaused
ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
night=module('mistral_overnight_tests','mistral_main_overnight.py');first=module('mistral_first_for_overnight','mistral_main_first_block.py')
@pytest.fixture(scope='module')
def original_mock_archive(tmp_path_factory):
    base=tmp_path_factory.mktemp('original_main_mock');state=base/'main_mistral_first_block';first.prepare(state,mock=True)
    def wire(request):
        b=json.loads(request.content);return httpx.Response(200,headers={'content-type':'text/event-stream'},content=sse_bytes(stream_events('Mistral',fixture('Mistral',b['model']))),request=request)
    async def fill():
        for i in range(10):await first.generate(state,i,mock_transport=httpx.MockTransport(wire),mock_credential=lambda p:'MOCK-ONLY')
    asyncio.run(fill());archive=base/'source.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for p in state.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(base))
    return archive

def test_waves_cover_exactly_remaining1430_once_and_preserve_schedule():
    p=night.load_plan();waves=[night.wave_slots(p,i) for i in range(36)];flat=[s for wave in waves for s in wave]
    assert flat==p['mistral_slots'][10:] and len(flat)==1430 and len({s['artifact_id'] for s in flat})==1430
    assert len(waves[-1])==30 and all(s['provider']=='Mistral' and s['cohort']=='main' for s in flat)

@pytest.mark.parametrize('key,value',[('author_approved',False),('maximum_cost_usd','20'),('overall_main_allowance_usd','46'),('source_archive_sha256','wrong'),('snapshot',{}),('mistral_slots',[]),('wave_size',100),('driver_sha256','wrong')])
def test_changed_scope_rejected(tmp_path,monkeypatch,key,value):
    p=night.load(night.PLAN);p[key]=value;f=tmp_path/'bad.json';f.write_text(json.dumps(p));monkeypatch.setattr(night,'PLAN',f)
    with pytest.raises(DispatchPaused):night.load_plan()

def test_budget_amendment_preserves_every_old_charge_and_original_file(tmp_path,original_mock_archive):
    state=tmp_path/'state';night.prepare(state,original_mock_archive,mock=True)
    old=sqlite3.connect(state/'original_first_block/main_mistral_first_block/spending.sqlite');new=sqlite3.connect(state/'campaign/spending.sqlite')
    assert list(old.execute('select * from attempts'))==list(new.execute('select * from attempts'))
    assert list(old.execute('select * from slots'))==list(new.execute('select * from slots'))
    assert new.execute("select value from settings where name='limit'").fetchone()[0]=='2000000000'
    assert old.execute("select value from settings where name='limit'").fetchone()[0]=='1000000000'
    assert new.execute("select count(*) from audit where event='explicit_author_budget_amendment'").fetchone()[0]==1
    old.close();new.close()
    with pytest.raises(DispatchPaused):night.prepare(state,original_mock_archive,mock=True)

async def test_wave_mocks_onlyMistral_atMostTwo_and_cannot_repeat(tmp_path,original_mock_archive):
    state=tmp_path/'state';night.prepare(state,original_mock_archive,mock=True);active=0;peak=0;calls=[]
    async def handler(request):
        nonlocal active,peak
        active+=1;peak=max(peak,active);b=json.loads(request.content);calls.append(b['messages'][0]['content']);assert b['model'] in {'ministral-3b-2512','ministral-14b-2512'}
        await asyncio.sleep(.001);active-=1
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=sse_bytes(stream_events('Mistral',fixture('Mistral',b['model']))),request=request)
    wire=httpx.MockTransport(handler);r=await night.generate_wave(state,0,mock_transport=wire,mock_credential=lambda p:'MOCK-ONLY')
    assert r['new_main_responses']==40 and r['mistral_main_total_so_far']==50 and len(calls)==40 and peak<=2
    assert len(list((state/'campaign/artifacts').iterdir()))==50
    assert (state.parent/'mistral_wave_checkpoints/wave_0/spending.sqlite').exists()
    with pytest.raises(DispatchPaused):await night.generate_wave(state,0,mock_transport=wire,mock_credential=lambda p:'MOCK-ONLY')
    assert len(calls)==40

async def test_failure_preserves_attempts_and_stops_before_further_pairs(tmp_path,original_mock_archive):
    state=tmp_path/'state';night.prepare(state,original_mock_archive,mock=True);calls=[]
    def reject(request):calls.append(1);return httpx.Response(400,json={'error':'synthetic rejection'},request=request)
    with pytest.raises(DispatchPaused):await night.generate_wave(state,0,mock_transport=httpx.MockTransport(reject),mock_credential=lambda p:'MOCK-ONLY')
    assert len(calls)<=2 and not(state/'wave_0_summary.json').exists()
    pack=state.parent/'mistral_wave_checkpoints/wave_0';assert (pack/'spending.sqlite').exists() and len(list((pack/'artifacts').iterdir()))==len(calls)

@pytest.mark.parametrize('index',[-1,36,None,True])
def test_invalid_wave_rejected(index):
    with pytest.raises(DispatchPaused):night.wave_slots(night.load_plan(),index)

async def test_cannot_skip_a_wave_or_use_real_transport_on_mock(tmp_path,original_mock_archive):
    state=tmp_path/'state';night.prepare(state,original_mock_archive,mock=True)
    with pytest.raises(DispatchPaused):await night.generate_wave(state,0)
    with pytest.raises(DispatchPaused):await night.generate_wave(state,1,mock_transport=httpx.MockTransport(lambda r:pytest.fail('must not call wire')),mock_credential=lambda p:'MOCK-ONLY')

def test_eval_cells_cover_all1440_frozen_ids_without_outcome_selection():
    from evaluate_main_mistral import selected_slots
    from benchmark.expanded.planning import assets_root
    p=night.load_plan();cells=[selected_slots(assets_root(),task,config) for task in [f'E{i}' for i in range(1,9)] for config in ['ministral_3b_2512','ministral_14b_2512','ministral_14b_2512_temperature_0p2']]
    assert len(cells)==24 and all(len(cell)==60 for cell in cells)
    assert {s['artifact_id'] for cell in cells for s in cell}=={s['artifact_id'] for s in p['mistral_slots']}

def test_workflow_is_Mistral_only_and_eval_has_no_model_keys():
    text=(ROOT/'.github/workflows/full-study.yml').read_text();gen=text.split('  mistral-main-overnight:',1)[1].split('  mistral-main-saved-evaluation:',1)[0];evaluation=text.split('  mistral-main-saved-evaluation:',1)[1]
    keys=[s for s in gen.split('      - ') if 'secrets.MISTRAL_API_KEY' in s];assert len(keys)==36
    assert all(f'--index {i}' in keys[i] for i in range(36))
    assert all(k not in gen for k in ['secrets.GROK_API_KEY','secrets.OPENAI_API_KEY','secrets.ANTHROPIC_API_KEY','secrets.GEMINI_API_KEY'])
    assert 'secrets.' not in evaluation and evaluation.count('GH_TOKEN:')==1
    assert 'needs: mistral-main-overnight' in evaluation and 'max-parallel: 4' in evaluation
    assert gen.index('Preserve stable overnight prepared marker')<gen.index('Generate frozen Mistral main wave 0')
    assert 'continue-on-error' not in gen and "github.run_attempt == '1'" in gen
    others=text.split('jobs:',1)[1].split('  mistral-main-overnight:',1)[0]
    guards=[s for s in others.splitlines() if s.startswith('    if:')]
    assert len(guards)==13 and all('!inputs.verify_setup_only' in s or '!inputs.confirm_paid_generation' in s or '!inputs.continue_grok_budget' in s for s in guards)
