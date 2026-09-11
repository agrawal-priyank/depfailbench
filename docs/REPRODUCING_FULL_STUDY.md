# Reproducing the completed study

The study archive contains sibling `source/` and `data/` directories. Use Python 3.12 and the pinned requirements. From `source/`:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps .
.venv/bin/python -m pip install numpy==2.3.5
.venv/bin/python -m pytest -q tests
```

## Recompute statistics

Create a sibling `replay/` directory next to `source/`, then copy `../data/evaluation1`, `../data/evaluation2`, and `../data/evaluation3` into `../replay/`. Keep the original archive immutable. Then run:

```sh
.venv/bin/python -m benchmark.full_analysis ../replay
```

Compare `../replay/analysis.json` with `../data/analysis.json`. Expected primary counts are OpenAI 39/80 and 68/80, Anthropic 59/80 and 78/80, for C0 and C1 respectively. There should be 320 artifacts and no repeated-outcome disagreements. NumPy 2.3.5 reproduces the saved seeded analysis.

## Fresh execution of saved programs

Create a sibling `fresh/` directory next to `source/` containing a copy of `../data/artifacts/`, without any evaluation directories. Run:

```sh
.venv/bin/python -m benchmark.full_batch_eval --root ../fresh --repetitions 3
.venv/bin/python -m benchmark.full_analysis ../fresh
```

Use the paths appropriate to your extraction directory. Batch evaluation skips existing result files, so a directory containing old evaluation records is not a fresh run. Exact latency values vary; compare clean qualification, primary pass, scenario outcome categories, and errors. Fresh applications and subprocess timeouts limit execution duration; subprocesses are not a security sandbox. Execute generated source only in an appropriately isolated, credential-free environment.

## Single saved artifact

```sh
.venv/bin/python -m benchmark.full_eval ../data/artifacts/full_v1_T1_C1_openai_gpt56sol_g01 ../single.json
```

This full-study command differs from the legacy `depfailbench evaluate` pilot interface. Keep pilot results separate. Full-study generation remains a checkout-oriented research workflow and is not needed here.

## Traceability

`full_study/release_manifest.json` records the frozen pre-generation protocol implementation, using paths from the original generation checkout. It is provenance rather than an integrity inventory for the current `source/` tree, and it intentionally excludes its own digest because embedding that digest would be self-referential. Use the archive-level SHA-256 manifest supplied with the release to verify the current source and data. `frozen_evaluation*` are pre-loader-correction results; `evaluation*` are corrected results. `loader_correction_changes.json` identifies five affected programs. Distinguish 320 generated programs from their repeated executions. Do not treat repeated scenarios as independent generations.
