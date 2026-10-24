"""Hand-written controls; never counted as model-generated study outputs."""

from __future__ import annotations

import asyncio
import hashlib
import math
from time import monotonic

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .contracts import Settings, TASKS


def integer(value):
    return type(value) is int


def text(value):
    return isinstance(value, str) and bool(value)


def quote_valid(row):
    return (isinstance(row, dict) and text(row.get("quote_id"))
            and integer(row.get("price_cents")) and row["price_cents"] >= 0
            and row.get("currency") == "USD"
            and integer(row.get("delivery_days")) and row["delivery_days"] > 0)


def create_reference(task_id, transport, settings=None, *, mutation=None):
    """A correct control and named deliberately faulty variants for oracle checks."""
    cfg = settings or Settings()
    app = FastAPI()
    app.state.orders = {}
    app.state.reservations = {}

    async def downstream(method, path, deadline, **kwargs):
        attempts = 1 if mutation == "no_retry" else cfg.max_attempts
        for index in range(attempts):
            remaining = deadline - monotonic() - .005
            if remaining <= 0:
                raise HTTPException(503, "request deadline exhausted")
            timeout = None if mutation == "no_timeout" else min(cfg.timeout_s, remaining)
            try:
                async with httpx.AsyncClient(transport=transport, base_url=cfg.downstream_url,
                                             timeout=timeout) as client:
                    response = await client.request(method, path, **kwargs)
            except httpx.HTTPError:
                if index + 1 == attempts:
                    raise HTTPException(503, "dependency unavailable")
                continue
            if response.status_code not in {429, 502, 503, 504}:
                return response
            if index + 1 == attempts:
                raise HTTPException(503, "dependency unavailable")
            try:
                wait = max(0.0, float(response.headers.get("Retry-After", "0")))
            except ValueError:
                wait = 0.0
            if not math.isfinite(wait) or wait >= deadline - monotonic() - .005:
                raise HTTPException(503, "retry cannot fit remaining deadline")
            await asyncio.sleep(wait)
        raise HTTPException(503, "dependency unavailable")

    def parsed(response):
        try:
            result = response.json()
        except ValueError:
            raise HTTPException(502, "invalid dependency JSON")
        if not isinstance(result, dict):
            raise HTTPException(502, "invalid dependency object")
        return result

    async def endpoint(request: Request):
        if mutation == "blocking":
            import time
            time.sleep(cfg.deadline_s * 4)
        deadline = monotonic() + cfg.deadline_s
        try:
            payload = await request.json() if TASKS[task_id].body is not None else None
        except ValueError:
            raise HTTPException(422, "invalid input")
        if payload is not None and not isinstance(payload, dict):
            raise HTTPException(422, "invalid input")
        suffix = request.url.path.split("/")[-1]
        try:
            if task_id == "E1":
                response = await downstream("GET", request.url.path, deadline)
                if response.status_code == 404:
                    raise HTTPException(404, "not found")
                data = parsed(response)
                price = data.get("price")
                if not (response.status_code == 200 and integer(data.get("id"))
                        and data["id"] == int(suffix) and isinstance(data.get("name"), str)
                        and type(price) in {int, float} and math.isfinite(price) and price >= 0):
                    raise HTTPException(502, "invalid product")
                result = {k: data[k] for k in ("id", "name", "price")}
            elif task_id == "E2":
                if not (text(payload.get("destination")) and len(payload["destination"]) <= 64
                        and integer(payload.get("weight_g")) and 1 <= payload["weight_g"] <= 100000
                        and set(payload) == {"destination", "weight_g"}):
                    raise HTTPException(422, "invalid quote request")
                response = await downstream("GET", "/quotes", deadline, params=payload)
                data = parsed(response)
                if response.status_code != 200 or not isinstance(data.get("quotes"), list):
                    raise HTTPException(502, "invalid quote collection")
                valid = {}
                for row in data["quotes"]:
                    if quote_valid(row):
                        normalized = {k: row[k] for k in ("quote_id", "price_cents", "currency", "delivery_days")}
                        if row["quote_id"] in valid and valid[row["quote_id"]] != normalized:
                            raise HTTPException(502, "conflicting quote")
                        valid[row["quote_id"]] = normalized
                if not valid:
                    raise HTTPException(404, "no valid quote")
                result = min(valid.values(), key=lambda x: (x["price_cents"], x["delivery_days"], x["quote_id"]))
            elif task_id in {"E3", "E4"}:
                cursor, seen_cursors, records = "0", set(), {}
                key = "items" if task_id == "E3" else "events"
                path = "/pages" if task_id == "E3" else "/activity/pages"
                while cursor is not None:
                    if not text(cursor) or cursor in seen_cursors or len(seen_cursors) >= 3:
                        raise HTTPException(502, "invalid continuation")
                    seen_cursors.add(cursor)
                    response = await downstream("GET", path, deadline, params={"cursor": cursor})
                    data = parsed(response)
                    if response.status_code != 200 or not isinstance(data.get(key), list) or "next_cursor" not in data:
                        raise HTTPException(502, "invalid page")
                    for row in data[key]:
                        if not isinstance(row, dict):
                            raise HTTPException(502, "invalid record")
                        if task_id == "E3":
                            valid = integer(row.get("id")) and isinstance(row.get("name"), str)
                            identity = row.get("id")
                            fields = ("id", "name")
                        else:
                            fields = ("event_id", "user_id", "event_type", "outcome")
                            valid = all(text(row.get(field)) for field in fields)
                            identity = row.get("event_id")
                        if not valid:
                            raise HTTPException(502, "invalid record fields")
                        normalized = {field: row[field] for field in fields}
                        if identity in records and records[identity] != normalized:
                            raise HTTPException(502, "conflicting duplicate")
                        if mutation == "double_count":
                            identity = f"{identity}-{len(records)}"
                        records[identity] = normalized
                    cursor = data["next_cursor"]
                    if mutation == "partial_pages":
                        break
                if task_id == "E3":
                    result = {"items": list(records.values())}
                else:
                    counts = {}
                    for row in records.values():
                        if row["event_type"] == "login" and row["outcome"] == "failure":
                            counts[row["user_id"]] = counts.get(row["user_id"], 0) + 1
                    result = {"failed_logins": [{"user_id": user, "count": counts[user]} for user in sorted(counts)]}
            elif task_id in {"E5", "E6"}:
                if task_id == "E5":
                    identity = request.url.path.split("/")[2]
                    state = app.state.orders
                    body = {"order_id": identity}
                    path = "/charges"
                    good_status = "PAID"
                    header = f"order:{identity}"
                else:
                    if not (text(payload.get("item_id")) and integer(payload.get("quantity"))
                            and 1 <= payload["quantity"] <= 100 and set(payload) == {"item_id", "quantity"}):
                        raise HTTPException(422, "invalid reservation")
                    identity, state, body, path = suffix, app.state.reservations, payload, "/reservations"
                    good_status, header = "RESERVED", identity
                old = state.get(identity)
                if old and old.get("request_payload") != body:
                    raise HTTPException(409, "identity conflict")
                state[identity] = {"status": "PENDING", "request_payload": dict(body)}
                headers = {} if mutation == "duplicate_action" else {"Idempotency-Key": header}
                try:
                    response = await downstream("POST", path, deadline, json=body, headers=headers)
                    if response.status_code == 409:
                        state[identity]["status"] = "REJECTED" if task_id == "E6" else "FAILED"
                        raise HTTPException(409, "business rejection")
                    data = parsed(response)
                    if task_id == "E5":
                        valid = text(data.get("charge_id")) and data.get("status") == "captured"
                        result = {"order_id": identity, "status": "PAID", "charge_id": data.get("charge_id")}
                    else:
                        valid = (text(data.get("reservation_id")) and data.get("request_id") == identity
                                 and data.get("item_id") == body["item_id"]
                                 and integer(data.get("quantity")) and data["quantity"] == body["quantity"]
                                 and data.get("status") == "reserved")
                        result = data
                    if response.status_code != 200 or not valid:
                        raise HTTPException(502, "invalid receipt")
                    state[identity] = {**state[identity], **result, "status": good_status}
                except HTTPException as exc:
                    if exc.status_code != 409:
                        state[identity]["status"] = "UNRESOLVED"
                    raise
            elif task_id == "E7":
                if set(payload) != {"content"} or not isinstance(payload["content"], str):
                    raise HTTPException(422, "invalid content")
                content = payload["content"].encode()
                key = "wrong.txt" if mutation == "wrong_key" else suffix
                response = await downstream("PUT", f"/objects/{key}", deadline, content=content)
                data = parsed(response)
                digest = hashlib.sha256(content).hexdigest()
                if response.status_code != 200 or data.get("key") != suffix or data.get("sha256") != digest:
                    raise HTTPException(502, "invalid object receipt")
                result = {"key": suffix, "sha256": digest}
            else:
                language = payload.get("language", "en")
                if (set(payload) - {"language", "email_notifications"} or type(language) is not str
                        or language not in {"en", "es", "fr"}):
                    raise HTTPException(422, "invalid preferences")
                if type(payload.get("email_notifications", True)) is not bool:
                    raise HTTPException(422, "invalid notification setting")
                complete = {"language": "en", "email_notifications": True, **payload}
                if mutation == "preference_patch":
                    complete = {**getattr(app.state, "last_preferences", {}), **payload}
                response = await downstream("PUT", request.url.path, deadline, json=complete)
                data = parsed(response)
                if response.status_code != 200 or data.get("user_id") != suffix or data.get("preferences") != complete:
                    raise HTTPException(502, "invalid preference receipt")
                app.state.last_preferences = dict(complete)
                result = {"user_id": suffix, "preferences": complete}
            if monotonic() > deadline:
                raise HTTPException(503, "deadline exhausted")
            return JSONResponse(result)
        except HTTPException:
            if mutation == "false_success":
                return JSONResponse({"success": True})
            raise

    route = {"E1": "/products/{product_id}", "E2": "/shipping/quote", "E3": "/catalog",
             "E4": "/activity/failed-logins", "E5": "/orders/{order_id}/pay",
             "E6": "/reservations/{request_id}", "E7": "/uploads/{object_key}",
             "E8": "/preferences/{user_id}"}[task_id]
    app.add_api_route(route, endpoint, methods=[TASKS[task_id].method])
    return app
