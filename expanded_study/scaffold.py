from dataclasses import dataclass
import httpx
from fastapi import FastAPI

@dataclass(frozen=True)
class AppSettings:
    downstream_url: str = "http://dependency.test"
    timeout_s: float = 0.25
    max_attempts: int = 3
    deadline_s: float = 1.0

def create_app(transport: httpx.AsyncBaseTransport, settings=None) -> FastAPI:
    settings = settings or AppSettings()
    app = FastAPI()
    # Implement the task's public interface here.
    return app
