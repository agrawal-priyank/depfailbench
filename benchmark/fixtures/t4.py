from __future__ import annotations

import asyncio
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError

from benchmark.fixtures.common import AppSettings, client


class Charge(BaseModel):
    charge_id: str
    status: Literal["captured"]


def create_app(kind: Literal["reference_naive", "reference_resilient"], transport: httpx.AsyncBaseTransport,
               settings: AppSettings | None = None) -> FastAPI:
    cfg = settings or AppSettings()
    app = FastAPI()
    app.state.orders = {}

    @app.post("/orders/{order_id}/pay")
    async def pay(order_id: str):
        app.state.orders.setdefault(order_id, {"order_id": order_id, "status": "PENDING", "charge_id": None})
        attempts = 1 if kind == "reference_naive" else cfg.max_attempts
        stable_key = f"order:{order_id}" if kind == "reference_resilient" else None
        async with client(transport, cfg) as downstream:
            for attempt in range(attempts):
                headers = {"Idempotency-Key": stable_key} if stable_key else {}
                try:
                    response = await downstream.post("/charges", json={"order_id": order_id}, headers=headers)
                except httpx.HTTPError:
                    if attempt + 1 < attempts:
                        await asyncio.sleep(0)
                        continue
                    app.state.orders[order_id]["status"] = "UNRESOLVED"
                    raise HTTPException(503, "payment outcome unresolved")
                if response.status_code in {429, 502, 503, 504} and kind == "reference_resilient" and attempt + 1 < attempts:
                    await asyncio.sleep(0)
                    continue
                if response.status_code != 200:
                    app.state.orders[order_id]["status"] = "UNPAID"
                    raise HTTPException(503, "payment unavailable")
                try:
                    charge = Charge.model_validate(response.json())
                except (ValueError, ValidationError):
                    app.state.orders[order_id]["status"] = "UNRESOLVED"
                    raise HTTPException(502, "invalid payment response")
                app.state.orders[order_id].update(status="PAID", charge_id=charge.charge_id)
                return app.state.orders[order_id]
        raise HTTPException(503, "payment unavailable")

    return app

