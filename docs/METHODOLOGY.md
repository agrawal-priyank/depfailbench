# Methodology

## Experimental unit

One independently generated `app.py` implementation is an experimental unit. Each model receives a single prompt, no tools, and no repair pass. The primary comparison is C0 versus C1 within each model family; provider effort labels are not treated as equivalent compute.

## Qualification and probing

Each artifact is loaded in isolation and first tested on the clean scenario. Clean-correct artifacts advance to fault probes. Clean-incorrect, syntactically invalid, import-invalid, and contract-invalid artifacts remain represented in CCR but are excluded from SRR and APR, as fixed before generation.

The downstream emulator uses a virtual clock, scripted responses, and stable payment-idempotency semantics. A fresh emulator and FastAPI application are constructed for every probe. This prevents cross-scenario contamination and makes all substantive observations deterministic. Wall latency is recorded separately and is not used for deterministic equality.

## Outcomes

- `resilient_success`: the endpoint returns the required valid result, within bounds, with correct state and side effects.
- `safe_failure`: the endpoint terminates within bounds without fabricating success, duplication, or inconsistent committed state.
- `unsafe_failure`: the endpoint exposes malformed data as success, duplicates an external effect, or creates an inconsistent outcome.
- `availability_failure`: an unhandled exception, deadline violation, or more than three attempts occurs.

For persistent dependency failure and malformed response scenarios, bounded safe failure satisfies the probe oracle. Scenarios with a recoverable transient sequence require resilient success.

## Measures

- **CCR:** clean-qualified artifacts divided by generated artifacts. Import and contract failures remain in the denominator.
- **SRR:** resilient-success fault probes divided by executed fault probes among clean-qualified artifacts.
- **APR:** clean-qualified artifacts satisfying every task-specific probe oracle divided by clean-qualified artifacts.
- **Retry amplification factor:** downstream attempts per logical application operation; the report gives the mean across executed probes.
- **Duplicate side effects:** committed external effects beyond the first for a logical operation.
- **State consistency:** T4 is consistent only when local payment state and external charge history agree, or the application safely preserves an explicit non-paid/unresolved outcome.

## Pilot analysis

The 16-artifact pilot is descriptive and feasibility-oriented. Report each artifact and scenario, then aggregate by model and condition. With only two independent generations per cell, avoid null-hypothesis significance tests and broad model rankings. The pilot determines whether the benchmark produces variation, whether C1 changes behavior, and whether the full six-task study is justified.

## Scope boundary

The pilot uses one generated service and one emulated dependency per probe. It does not measure concurrent requests, service chains, cascading or compound failures, orchestration platforms, or service meshes.
