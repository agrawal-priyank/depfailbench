# DepFailBench

DepFailBench checks saved Python/FastAPI backend services under controlled downstream dependency failures. Public responses, downstream attempts, committed effects, application state and observed request time are checked together. The software is a research tool, not a production-reliability certification.

Software **v1.2.0** and research dataset **v2.0.0** were published on 24 October 2026. Both version-specific archives are publicly accessible: [software DOI](https://doi.org/10.5281/zenodo.23627089), [research dataset DOI](https://doi.org/10.5281/zenodo.23626768) and [GitHub release](https://github.com/agrawal-priyank/depfailbench/releases/tag/v1.2.0). Priyank Agrawal is the sole author and maintainer. Software and documentation are MIT-licensed; research records use their separately scoped CC BY 4.0 notice in `DATA_LICENSE.md`.

## Reproduce the reported analysis first

Obtain the accompanying expanded research dataset archive, `Supplementary_Material_S2.zip`, from the version-specific dataset record [10.5281/zenodo.23626768](https://doi.org/10.5281/zenodo.23626768). Its SHA256 is `4a70538f1fdf7efb6ad0a7186b9a8e3c044fd0d89b74e77969590bd081bc2bfa`. It contains 4,320 outcomes, including one incomplete/no-source output; 4,319 source files; and 38,880 current measurements. Historical 320-program evidence is separately identified and must not be pooled with the expanded cohort.

Use Python 3.12 with the supplied evaluator dependency lock and `numpy==2.3.5`. After installing those dependencies:

```sh
python reproduce_saved_analysis.py /path/to/Supplementary_Material_S2.zip --output reproduced_analysis.json
```

This default route verifies saved-file hashes and source/record joins, then runs trusted analysis code on saved records. **It does not import or execute model-generated apps, contact model APIs, or need provider credentials.** It extracts only trusted benchmark/analysis source to a temporary directory and reads generated programs as bytes. See [reproduction details](docs/REPRODUCING_ARRAY_REVISION.md). The separate [historical sensitivity wrapper](research/historical_sensitivity/PORTABLE_REPRODUCTION.md) reproduces the disclosed retrospective, hypothetical four-task design calculation. It is not an original prospective power calculation and does not remeasure study programs.

Nine programs retain full-behavior repeat differences across 22 program-deadline entries. Primary pass/fail and functional-qualification outcomes are stable across repeats, but the original strict reporting guard still rejects these flagged rows. The disclosed qualified post-review wrapper retains the planned first repeat, all flags and original formulas under the recorded author approval. Do not describe this as unqualified frozen confirmatory reporting.

## Install and inspect the software

Python 3.12 is the reference interpreter. The exact main-study application environment is in `requirements.lock`; analysis adds the separately pinned NumPy requirement.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps .
.venv/bin/python -m pip install -r expanded_study/requirements-analysis.txt
.venv/bin/python -m benchmark.expanded preflight
```

Preflight reads the fixed task/prompt/allocation resources and makes no model call or program evaluation. The unchanged historical status string `local draft checked; not frozen or execution-authorized` describes the structural validator's limited role: it does not freeze a new study or grant execution permission. Completed-study status belongs in the accompanying data and release records. Installation from a wheel uses the same bundled resources and works outside the source checkout.

For an editable development install, use the `dev` and `analysis` extras. The retained tests use synthetic or handwritten controls and mock provider transports. No stored model-generated study corpus is bundled in the software repository or run by release CI. The separate external SDK classifier/summarizer unit checks require no SDK network access.

## What is included

- Unchanged historical T1/T2/T4/T5 modules and their original prompts, scaffolds and contracts.
- The E1–E8 implementation in `benchmark.expanded`, with exact executed prompts, numerical settings, task contracts, raw-record collection/reclassification, failure reporting, repeat comparison and analysis.
- Frozen main-plan and prompt-amendment files alongside the current study assets. `SCIENTIFIC_SOURCE_MANIFEST.json` pins their scientific source bytes to execution commit `5bbcb89261ae535bf85f99c148b7e4c02d3ddf2d`.
- The versioned [task-adapter interface](docs/ADDING_TASKS.md), including a manifest-backed out-of-tree handwritten example. Adapters supply their own scenarios and semantic oracles; registration does not validate an arbitrary new oracle automatically.
- The unchanged Stripe 15.6.1 / Seam 3.12.0 contract runner, classifier, summarizer and separate environment in `external_cases/`. This descriptive illustration uses fake credentials and loopback when explicitly rerun; it is distinct from both generated-program cohorts.
- General mock/provider, parsing, source-processing, authorization and spending-control modules. Their inclusion does not authorize fresh paid generation. Original campaign controllers and paid workflow entrypoints are omitted from this reusable release; complete original evidence remains in the dataset and execution history.

## Measurement and reuse boundaries

The primary pass outcome is binary: a saved output must pass construction/startup, functional qualification and every applicable fault check. Its primary pass rate is the percentage of all requested outcomes passing those checks; failures and incomplete outputs stay in the denominator. The implementation and saved data retain legacy field names such as `primary_pass` and `allpass`; [the data dictionary](docs/DATA_DICTIONARY.md) explains them.

Timing is observed under the pinned runtime with the recorded tolerance. Expanded same-source measurements use 1, 2 and 5-second deadlines and three repeats. Repeats and scenarios are not additional independent programs. The historical runtime/guard differs and remains separately identified. Results concern eight authored tasks and the exact tested configurations, not a provider ranking or arbitrary production systems.

Executing untrusted model-generated apps is outside the default analysis route. Any deliberate fresh evaluation belongs on isolated, credential-free Linux hosts, with one measurement per host at a time and all nine measurements of a program on the same host. Do not run the dataset's generated apps on a credentialed personal machine.

See [the expanded API and scope](docs/EXPANDED_STUDY.md), [the historical documentation guide](docs/HISTORICAL_GUIDE.md), [version preservation](docs/VERSION_PRESERVATION.md), [contributing](https://github.com/agrawal-priyank/depfailbench/blob/main/CONTRIBUTING.md) and [citation metadata](CITATION.cff). Historical releases and DOI records remain unchanged. Main can receive documentation and maintenance updates; use the fixed v1.2.0 tag, released commit `933b431e578896462ec970f2193d01d4e71840cd` and version-specific DOI records when reproducing or citing the release. The [dataset metadata guide](https://github.com/agrawal-priyank/depfailbench/blob/main/research_data/README.md) distinguishes preserved archival metadata from current publication status.
