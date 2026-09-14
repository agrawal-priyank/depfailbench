import httpx
from fastapi import FastAPI, HTTPException


def create_app(transport: httpx.AsyncBaseTransport, settings=None) -> FastAPI:
    app = FastAPI()

    @app.get("/lookup/{record_id}")
    async def lookup(record_id: str):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://dependency.test",
            timeout=settings.timeout_s,
        ) as client:
            for attempt in range(2):
                try:
                    response = await client.get(f"/records/{record_id}")
                except httpx.HTTPError:
                    if attempt == 1:
                        raise HTTPException(503, "dependency unavailable")
                    continue
                if response.status_code == 200:
                    payload = response.json()
                    if payload == {"id": record_id, "value": 42}:
                        return {"record": payload}
                    raise HTTPException(502, "invalid record")
                if response.status_code != 503 or attempt == 1:
                    raise HTTPException(503, "dependency unavailable")
        raise HTTPException(503, "dependency unavailable")

    return app
