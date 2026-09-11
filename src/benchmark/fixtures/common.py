from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class AppSettings:
    downstream_url: str = "http://dependency.test"
    timeout_s: float = 0.25
    max_attempts: int = 3
    deadline_s: float = 1.0


def client(transport: httpx.AsyncBaseTransport, settings: AppSettings) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport, base_url=settings.downstream_url,
                             timeout=httpx.Timeout(settings.timeout_s))

