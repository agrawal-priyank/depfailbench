from contextlib import asynccontextmanager
from dataclasses import dataclass
import asyncio
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
    ({'status':'UNPAID'}, [{'charge_id':'ch_1'}], 502),
    ({'status':'PENDING'}, [{'charge_id':'ch_1'}], 502),
    ({'status':'PAID'}, [], 200),
    ({'status':'PENDING'}, [{'charge_id':'ch_1'}, {'charge_id':'ch_2'}], 502),
    ({'status':'PAYMENT_FAILED'}, [], 200),
])
def test_unsafe_payment_outcomes_are_not_relaxed(state, charges, status):
    outcome, _ = classify('T4', 'committed_response_lost', status, {}, 1, False, None, charges, state)
    assert outcome == 'unsafe_failure'


def test_committed_charge_may_remain_explicitly_unresolved():
    outcome, _ = classify(
        'T4',
        'committed_response_lost',
        502,
        {'detail':'unresolved'},
        1,
        False,
        None,
        [{'charge_id':'ch_1'}],
        {'status':'UNRESOLVED'},
    )
    assert outcome == 'safe_failure'


async def test_dataclass_order_state_is_normalized():
    @dataclass
    class Order:
        order_id: str
        status: str
        charge_id: str | None = None

    def factory(transport, settings):
        app = FastAPI()
        app.state.orders = {}

        @app.post('/orders/{order_id}/pay')
        async def pay(order_id: str):
            async with httpx.AsyncClient(
                transport=transport,
                base_url=settings.downstream_url,
                timeout=settings.timeout_s,
            ) as client:
                response = await client.post(
                    '/charges',
                    json={'order_id': order_id},
                    headers={'Idempotency-Key': f'order:{order_id}'},
                )
            receipt = response.json()
            state = Order(order_id, 'PAID', receipt['charge_id'])
            app.state.orders[order_id] = state
            return state

        return app

    row = await run_probe('T4', 'dataclass_state', 'clean', factory)
    assert row.outcome_class == 'resilient_success', row
    assert row.final_state == {'order_id': 'order-1', 'status': 'PAID', 'charge_id': 'ch_1'}


def test_float_product_id_is_not_an_integer_contract_match():
    outcome, _ = classify(
        'T1',
        'clean',
        200,
        {'id': 7.0, 'name': 'Keyboard', 'price': 49.5},
        1,
        False,
        None,
        [],
        {},
    )
    assert outcome == 'unsafe_failure'


async def test_virtual_dependency_and_real_backoff_share_one_deadline():
    def factory(transport, settings):
        app = FastAPI()

        @app.get('/products/{product_id}')
        async def product(product_id: int):
            async with httpx.AsyncClient(
                transport=transport,
                base_url=settings.downstream_url,
                timeout=settings.timeout_s,
            ) as client:
                for _ in range(settings.max_attempts):
                    try:
                        response = await client.get(f'/products/{product_id}')
                    except httpx.HTTPError:
                        await asyncio.sleep(0.15)
                        continue
                    if response.status_code == 200:
                        return response.json()
            return JSONResponse({'detail': 'unavailable'}, status_code=503)

        return app

    from fastapi.responses import JSONResponse

    row = await run_probe('T1', 'combined_deadline', 'timeout', factory)
    assert row.deadline_violated
    assert row.outcome_class == 'availability_failure'
    assert row.wall_latency_s > 0.4
    assert row.virtual_dependency_time_s > 0.7
    assert row.effective_latency_s > 1.0
