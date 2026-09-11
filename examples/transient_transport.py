"""Credential-free transport extension; not part of the frozen study."""
import asyncio
import json
import httpx
from benchmark.fixtures.t1 import create_app

class OneTransientFailure(httpx.AsyncBaseTransport):
    def __init__(self):
        self.calls = 0
    async def handle_async_request(self, request):
        self.calls += 1
        status = 503 if self.calls == 1 else 200
        return httpx.Response(status, json={} if status == 503 else
                              {'id': 1, 'name': 'Example', 'price': 9.5}, request=request)

async def main():
    results = []
    for kind in ['reference_naive', 'reference_resilient']:
        transport = OneTransientFailure()
        app = create_app(kind, transport)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response = await client.get('/products/1')
        results.append({'control': kind, 'status': response.status_code,
                        'dependency_calls': transport.calls, 'body': response.json()})
    assert [(x['status'], x['dependency_calls']) for x in results] == [(503, 1), (200, 2)]
    print(json.dumps(results, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
