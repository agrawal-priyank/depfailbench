from __future__ import annotations

import asyncio
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError

from benchmark.fixtures.common import AppSettings, client


class Product(BaseModel):
    id: int
    name: str
    price: float


def create_app(kind: Literal["reference_naive", "reference_resilient"], transport: httpx.AsyncBaseTransport,
               settings: AppSettings | None = None) -> FastAPI:
    cfg = settings or AppSettings()
    app = FastAPI()

    @app.get("/products/{product_id}")
    async def product(product_id: int):
        attempts = 1 if kind == "reference_naive" else cfg.max_attempts
        async with client(transport, cfg) as downstream:
            for attempt in range(attempts):
                try:
                    response = await downstream.get(f"/products/{product_id}")
                except httpx.HTTPError:
                    if attempt + 1 < attempts:
                        await asyncio.sleep(0)
                        continue
                    raise HTTPException(503, "catalog unavailable")
                if response.status_code == 404:
                    raise HTTPException(404, "product not found")
                retryable = response.status_code in {429, 502, 503, 504}
                if retryable and kind == "reference_resilient" and attempt + 1 < attempts:
                    await asyncio.sleep(0)
                    continue
                if response.status_code != 200:
                    raise HTTPException(503, "catalog unavailable")
                if kind == "reference_naive":
                    return response.json()
                try:
                    return Product.model_validate(response.json()).model_dump()
                except (ValueError, ValidationError):
                    raise HTTPException(502, "invalid catalog response")
        raise HTTPException(503, "catalog unavailable")

    return app

