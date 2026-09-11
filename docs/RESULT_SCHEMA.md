# Result schemas

The release archive contains the completed full-study records described first below. The legacy pilot uses a different row-oriented schema, retained in the second half of this document.

## Completed full study

`data/artifacts/<artifact_id>/` contains the unchanged generated `app.py`, `metadata.json`, `prompt.txt`, and `raw_response.json` for each of the 320 independent generations. `metadata.json` records the task, condition, provider/model identity, generation index, timestamps, provider response identifier and usage, and prompt/scaffold/dependency hashes.

`data/evaluation1/`, `evaluation2/`, and `evaluation3/` contain one JSON file per generated program. The corresponding `frozen_evaluation*` directories preserve results from before the disclosed loader correction.

| Evaluation field | Meaning |
|---|---|
| `artifact_id`, `task`, `condition`, `model` | Experimental identity and cell |
| `metadata` | Preserved generation metadata |
| `clean_qualified` | Whether the clean functional contract passed |
| `primary_pass` | Whether the program clean-qualified and satisfied every applicable fault oracle |
| `observations` | Ordered clean and fault-scenario records; probing stops after a clean failure |
| `error` | Loader, construction, or execution error when present |

Each full-study observation records `scenario`, `outcome_class`, public response, exception, measured latency, downstream attempts, deadline status, side effects, task state, duplicate effects, and retry amplification. UUID-like values and measured latency can vary across executions; substantive comparison uses clean qualification, primary pass, scenario, outcome class, and error.

`data/analysis.json` records the total artifact count, completeness, repeated-outcome disagreements, per-model/per-cell counts and Wilson intervals, model-specific risk differences, permutation tests, bootstrap intervals, conservative simultaneous-Wilson bounds, and Holm-adjusted p-values. `loader_correction_changes.json` lists the five affected programs. Provider ledgers, `integrity_audit.json`, and `descriptive/` preserve generation accounting and supporting summaries.

## Legacy pilot

### Artifact manifest

`artifact_manifest.jsonl` contains one row for every planned slot, including missing or invalid artifacts.

| Field | Meaning |
|---|---|
| `artifact_id` | Unique immutable generation identifier |
| `task`, `condition`, `model`, `generation_index` | Experimental cell coordinates |
| `status` | `missing`, `evaluated`, or `evaluation_error` |
| `clean_qualified` | Whether the clean functional contract passed |
| `probes` | Number of recorded probes |
| `error_type`, `error_message` | Loader/contract failure, when applicable |

### Observation

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
