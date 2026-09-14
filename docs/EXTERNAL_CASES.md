# Externally sourced contract cases

The external panel evaluates unchanged Stripe Python 15.6.1 and Seam Python 3.12.0 SDKs against behavior frozen from their version-pinned upstream documentation, source, and tests. It uses fake credentials and a temporary loopback server; no live provider account or model call is required.

From the v1.1.0 source checkout, install the separate pinned dependencies from `external_cases/requirements-lock.txt`, then run:

```sh
python -m external_cases.run_cases \
  --contract external_cases/contract.json \
  --all-output external-results

python -m external_cases.summarize_results \
  external-results external_cases/contract.json \
  --json-output external-results/independent-summary.json \
  --csv-output external-results/independent-results.csv
```

The formal study contains 18 cases, each executed three times in a fresh subprocess. Expected output is 54 passing records with no categorical, attempt-count, commitment-count, or pass-status disagreement. Raw records retain ordered attempts, methods, paths, request-body hashes, one-way idempotency-key hashes, timings, exception types, and the server commitment ledger.

This is an externally sourced contract case study, not validation or endorsement by Stripe or Seam and not execution against their live services. It is separate from the 320 generated-program experiment.
