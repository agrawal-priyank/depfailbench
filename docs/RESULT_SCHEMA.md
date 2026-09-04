# Result schema

## Artifact manifest

`artifact_manifest.jsonl` contains one row for every planned slot, including missing or invalid artifacts.

| Field | Meaning |
|---|---|
| `artifact_id` | Unique immutable generation identifier |
| `task`, `condition`, `model`, `generation_index` | Experimental cell coordinates |
| `status` | `missing`, `evaluated`, or `evaluation_error` |
| `clean_qualified` | Whether the clean functional contract passed |
| `probes` | Number of recorded probes |
| `error_type`, `error_message` | Loader/contract failure, when applicable |

## Observation

`observations.jsonl` contains one row per executed probe. `observations.csv` is a spreadsheet-friendly representation with nested values serialized as JSON.

| Field | Meaning |
|---|---|
| `response_status`, `response_json` | Application response |
| `latency_s` | Observed wall-clock latency |
| `attempts` | Ordered downstream attempts with virtual start/completion timestamps, method, path, status/error, and idempotency key |
| `deadline_violated` | Whether virtual execution exceeded the one-second application deadline |
| `unhandled_exception` | Captured application exception, if any |
| `side_effects` | Committed downstream effects |
| `final_state` | Final inspectable application state |
| `outcome_class` | Four-way oracle classification |
| `retry_amplification_factor` | Downstream attempts per logical operation |
| `duplicate_side_effects` | Effects beyond the first |
| `notes` | Oracle explanation or consistency warning |

`summary.json` includes overall and model-by-condition metrics plus their definitions. JSON `null` is used when a denominator is zero; missing evidence is never encoded as zero performance.
