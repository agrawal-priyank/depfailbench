You are implementing one benchmark artifact in a fixed Python 3.12 project.

Rules:

- Use FastAPI and httpx only; do not add packages.
- Edit only `app.py`.
- Keep the supplied `create_app(transport, settings=None)` factory and public HTTP contract.
- Use the injected `httpx.AsyncBaseTransport` for every dependency request so the benchmark can observe calls.
- Do not inspect or modify the benchmark, fault scenarios, tests, or other artifacts.
- Do not add test-specific branches or identify fault scenarios.
- Return only the complete contents of `app.py`.

