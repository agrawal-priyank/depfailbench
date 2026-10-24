Implement the requested backend service in the supplied Python 3.12 project.

Use FastAPI and HTTPX; Pydantic is available for input validation. Do not add packages. The pinned environment is FastAPI 0.141.1, Starlette 1.6.0, HTTPX 0.28.1, Pydantic 2.13.5 and Uvicorn 0.52.4.

Return only the complete contents of app.py. Keep create_app(transport, settings=None). Use the injected httpx.AsyncBaseTransport for every downstream request; the downstream base URL is settings.downstream_url. Do not inspect the evaluator, other programs, fixtures or fault scenarios, and do not add test-specific branches. You receive no tools or test feedback and no opportunity for follow-up repair.

Common settings contract (identical in both instruction groups):
- settings.timeout_s is the finite per-attempt upper bound, default 0.25 seconds.
- settings.max_attempts is the allowed attempt limit, default 3, per logical dependency operation; each page is a distinct logical operation. The limit is a maximum, not an instruction to make exactly three calls.
- settings.deadline_s is the whole public-request deadline, default 1.0 second. The same implementation is also evaluated with this supplied setting at 2.0 and 5.0 seconds. All calls, computation and pauses for a public request consume this allowance. The evaluator records actual wall time, excluding separately recorded application startup, with a disclosed fixed 0.05-second measurement/scheduling tolerance.
- The service must preserve the declared request/response contract and truthful side-effect state. Error responses are HTTP errors; never represent incomplete, failed or unconfirmed work as success.
