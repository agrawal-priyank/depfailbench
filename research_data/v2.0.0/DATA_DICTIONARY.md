# Data dictionary and coordinate relationships

This draft dataset deposit describes the unchanged research archive. An expanded outcome coordinate is one independently requested output identified by `artifact_id`, task E1–E8, exact `configuration_id`, condition C0/C1, coverage `round` and generation index. There are 9 configurations × 8 tasks × 2 conditions × 30 requested outputs = 4,320 outcomes. Exactly one accepted incomplete response has no source; 4,319 generated `app.py` files exist. All requested outcomes remain in denominators.

Each outcome has 1, 2 and 5-second measurements, each repeated three times: 38,880 current records. `deadline_s` and `evaluation_repeat` distinguish repeated measurements of the same source. Primary reporting uses the prespecified one-second deadline and first repeat. Source SHA256, record/file hashes, run fingerprints and original collection manifests preserve provenance; portable mappings join original absolute cloud locators to archive members. Absolute paths retained in receipts are historical locators, not required portable execution paths.

`primary_pass` / exported `allpass` encode the binary primary pass outcome: construction/startup, functional qualification and all applicable fault checks must pass. `clean_qualified` / exported `functional` encode functional qualification. A percentage uses all requested outputs as its denominator. The human term primary pass rate does not rename stored fields or alter any scores.

A scenario observation records `scenario`, `pass`, `outcome_class`, watchdog status, public responses, dependency attempts/effects and application state. Failed qualification can stop later probing; a missing probe is not a successful probe. Per-scenario columns are `generated_n`, `reached_n`, `passed_n`, `rate_among_reached` (undefined when reached_n=0), and `rate_all_generated`. Mutually exclusive priority-failure counts reconcile with failed outputs; overlapping flags must not be added as disjoint counts.

Supplementary File S3 has 5,400 scenario rows; S4 has 432 task/configuration/condition/deadline cells with 30 outcomes and descriptive Wilson intervals; S5 has 36 paired deadline-transition rows; S6 has 162 configuration/condition/deadline/repeat rows. Current external CSV names use `Supplementary_File_Sn_...csv`; the immutable archive retains `tables/Supplementary_Table_Sn_...csv`. These are byte-identical pairs, distinct from numbered tables inside the narrative supplement S1.

Nine programs have full-behavior repeat flags across 22 program-deadline entries, although primary/functional pass-fail outcomes are stable across repeats. The qualified post-review analysis retains every flag and the planned first repeat. A single E4 Luna-low C1 output changes from primary failure at one second to pass at two/five seconds. Repeated measurements, tasks and scenarios are not independent extra programs.

Historical 320-program data, original versus common-guard measurements, the first-720 recorder correction, validation outputs and the superseded 1,440-output Mistral cohort have separate provenance and scopes. They must not be pooled into the expanded 4,320 main-outcome analysis. Known-usage token costs and conservative unknown-usage allowances are operational estimates, not verified invoices or software performance endpoints.

## Expanded coordinate and record files

The ZIP prefix is `DepFailBench_Array_Revision/`. `data/coordinate_inventory.json`
joins each `artifact_id` to its task/configuration/condition, original generation
and measurement provenance, hashes and portable `source_path`. The source path
is absent for the one retained incomplete/no-source outcome. The original cloud
paths retained in receipts are historical locators, not a requirement to recreate
the author's filesystem.

`data/generated/{artifact_id}/` retains exact request/response evidence and
metadata, plus `app.py` when extracted source exists. A generation index identifies
a requested output within a task/configuration/condition cell; coverage rounds
supply five C0 and five C1 outputs per block. A failed or incomplete output remains
an outcome rather than a request for replacement.

`data/records/{artifact_id}/deadline_D_repeat_R.json` contains wrapper fields
`artifact_id`, `deadline_s`, `evaluation_repeat`, `record_sha256`,
`source_sha256`, `run_fingerprint`, `synthetic_data` and `result`. `result`
contains the preserved measurement result, including `task`, `condition`,
`metadata`, `primary_pass`, `clean_qualified`, scenario execution counts and
`observations`. `record_sha256` preserves the original measurement-file hash;
use the archive's file inventory for the hash of the delivered wrapper file.
The source hash identifies the exact generated source bytes, not repaired code.

The binary primary outcome requires startup/construction, functional qualification
and every applicable fault oracle to pass. A row's false outcome does not identify
how many checks failed. Diagnostic causes and raw observations retain that detail.
Pass/fail fields are Boolean; stored CSV counts are integers; rates and interval
bounds are proportions on [0,1], not percentages, unless a display explicitly says
otherwise. Deadlines are seconds. Public prose may express rate differences in
percentage points without changing stored fractional values.

## Common CSV coordinate columns

| Column | Meaning |
|---|---|
| `task` | Fixed expanded task E1–E8. |
| `configuration_id` | Exact recorded model/setting configuration, not a provider-family ranking. |
| `condition` | C0 baseline instruction package or C1 that package plus the common resilience requirements. |
| `deadline_s` | Nominal deadline in seconds; 1, 2 or 5, except S5 targets only 2 or 5 relative to 1. |

S3–S5 use the planned first repeat. S6 enumerates all three repeats. Repeated
records are linked observations of the same unchanged source.

## Supplementary File S3: scenario outcomes (5,400 rows)

One row per task/configuration/condition/scenario/deadline combination.

| Additional column | Type and interpretation |
|---|---|
| `scenario` | Scenario identifier in that task's exact contract. |
| `generated_n` | Integer all-generated denominator, 30 for each condition cell. |
| `reached_n` | Integer count actually reaching this scenario after qualification. |
| `passed_n` | Integer count passing the scenario among those reached. |
| `rate_among_reached` | `passed_n / reached_n`; empty when `reached_n` is zero because the rate is undefined. |
| `rate_all_generated` | `passed_n / generated_n`; missing opportunities are not counted as successful probes. |

The task/scenario inventory determines which rows exist; unrelated scenarios are
not silently invented for tasks that do not define them.

## Supplementary File S4: task outcomes (432 rows)

One row per task/configuration/condition/deadline cell.

| Additional column | Type and interpretation |
|---|---|
| `n` | Integer outcome count; 30. |
| `allpass` | Integer primary pass count, using the archive's unchanged field name. |
| `functional` | Integer count satisfying functional qualification. |
| `rate` | `allpass / n`, a proportion. |
| `wilson95` | JSON two-element list of lower/upper unadjusted per-cell Wilson 95% bounds, as proportions. |
| `disjoint_failure_counts` | JSON object mapping mutually exclusive priority causes to integer counts; values sum to `n - allpass`. |
| `overlapping_failure_counts` | JSON object of diagnostic counts which can overlap; do not sum as distinct failed programs. |

The fixed priority causes are generation-output, startup, functional,
hanging-guard, deadline, safe termination where recovery was required,
unsafe-oracle and other failure. Unadjusted cell intervals are distinct from the
aggregate multiplicity-aware or conservative bounds in the saved analysis.

## Supplementary File S5: paired deadline transitions (36 rows)

One row per configuration/condition/target deadline, pooled over the same eight
tasks (240 outcomes per row). The baseline is each program's one-second primary
outcome; the target is its two- or five-second outcome, using the first repeat.

| Additional column | Integer count |
|---|---|
| `0_to_0` | Primary failure at both baseline and target deadlines. |
| `0_to_1` | Primary failure at one second, pass at target deadline. |
| `1_to_0` | Primary pass at one second, failure at target deadline. |
| `1_to_1` | Primary pass at both deadlines. |

The four counts sum to 240. A deadline transition is not a newly generated output.

## Supplementary File S6: repeat outcomes (162 rows)

One row per configuration/condition/deadline/repeat, pooled over the eight tasks.
`repeat` is 1, 2 or 3; `n` is 240; `allpass` and `functional` are integer primary
and functional pass counts. Identical aggregate Boolean results do not mean
literal equality of traces, state values, watchdog events or every diagnostic
flag; retained raw records and repeat-difference evidence must also be consulted.

## Exact external-to-archive CSV mapping

| External file | Member relative to `DepFailBench_Array_Revision/` |
|---|---|
| `Supplementary_File_S3_Scenario_Outcomes.csv` | `tables/Supplementary_Table_S3_Scenario_Outcomes.csv` |
| `Supplementary_File_S4_Task_Outcomes.csv` | `tables/Supplementary_Table_S4_Task_Outcomes.csv` |
| `Supplementary_File_S5_Deadline_Transitions.csv` | `tables/Supplementary_Table_S5_Deadline_Transitions.csv` |
| `Supplementary_File_S6_Repeat_Outcomes.csv` | `tables/Supplementary_Table_S6_Repeat_Outcomes.csv` |

These pairs are byte-identical. The reporting additions ZIP supplies later
technical reporting documentation and an illustrative simulated sensitivity
calculation; it adds no empirical output coordinate or measurement record.
