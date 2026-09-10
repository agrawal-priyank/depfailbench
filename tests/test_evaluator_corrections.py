from contextlib import asynccontextmanager
import httpx
import pytest
from fastapi import FastAPI
from benchmark.runner import run_probe
from benchmark.oracle import classify


@pytest.mark.parametrize('legacy', [False, True])
async def test_probe_runs_startup_and_shutdown(legacy):
    events = []
    def factory(transport, settings):
        async def startup():
            events.append('start')
            app.state.client = httpx.AsyncClient(transport=transport, base_url='http://catalog')
        async def shutdown():
            await app.state.client.aclose()
            events.append('stop')
        @asynccontextmanager
        async def lifespan(app):
            await startup()
            yield
            await shutdown()
        app = FastAPI() if legacy else FastAPI(lifespan=lifespan)
        if legacy:
            app.on_event('startup')(startup)
            app.on_event('shutdown')(shutdown)
        @app.get('/products/{product_id}')
        async def product(product_id: int):
            return (await app.state.client.get(f'/products/{product_id}')).json()
        return app
    row = await run_probe('T1', 'lifecycle', 'clean', factory)
    assert row.outcome_class == 'resilient_success'
    assert events == ['start', 'stop']


@pytest.mark.parametrize('label', ['PAYMENT_FAILED', 'DECLINED', 'CUSTOM_NONPAID'])
def test_no_charge_failure_does_not_require_hidden_state_labels(label):
    outcome, _ = classify('T4', 'persistent_503', 502, {'detail':'failed'}, 1, False, None, [], {'status': label})
    assert outcome == 'safe_failure'


@pytest.mark.parametrize('state,charges,status', [
    ({'status':'PAYMENT_FAILED'}, [{'charge_id':'ch_1'}], 502),
    ({'status':'PAID'}, [], 200),
    ({'status':'PENDING'}, [{'charge_id':'ch_1'}, {'charge_id':'ch_2'}], 502),
    ({'status':'PAYMENT_FAILED'}, [], 200),
])
def test_unsafe_payment_outcomes_are_not_relaxed(state, charges, status):
    outcome, _ = classify('T4', 'committed_response_lost', status, {}, 1, False, None, charges, state)
    assert outcome == 'unsafe_failure'
