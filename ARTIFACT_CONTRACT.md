# Generated Artifact Contract

Each independent generation occupies `artifacts/<artifact_id>/app.py`. Its immutable metadata is stored beside it as `metadata.json` with: artifact ID, task, condition, model provider/family/version, generation index, sampling parameters, generation timestamp, and provider request or response identifier when available.

`app.py` must export:

```python
def create_app(
    transport: httpx.AsyncBaseTransport,
    settings: AppSettings | None = None,
) -> FastAPI: ...
```

The harness injects a fresh dependency transport and creates a fresh app for every probe. T4 state must be exposed as the `app.state.orders` mapping on the returned application instance so the harness can inspect final state without process-global contamination. This is part of the visible task contract in both conditions. Generated code may edit only `app.py`; the runtime, dependencies, scaffold, prompts, and harness are fixed across conditions and model families.

Clean qualification always runs first. Only artifacts producing the required result on the clean scenario enter the resilience analysis. Clean failures remain in the denominator of CCR but not SRR or APR.
