from __future__ import annotations

import httpx
from fastapi import FastAPI

from benchmark.fixtures.common import AppSettings


def create_app(transport: httpx.AsyncBaseTransport, settings: AppSettings | None = None) -> FastAPI:
    """Implement the task here. The signature is part of the benchmark contract."""
    raise NotImplementedError

