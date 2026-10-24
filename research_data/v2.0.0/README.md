# DepFailBench research dataset 2.0.0

**Version:** 2.0.0  
**Dataset identifier:** [10.5281/zenodo.23626768](https://doi.org/10.5281/zenodo.23626768)  
**Dataset concept:** [10.5281/zenodo.22699094](https://doi.org/10.5281/zenodo.22699094)  
**Record date:** 24 October 2026  
**Companion software:** [DepFailBench v1.2.0, 10.5281/zenodo.23627089](https://doi.org/10.5281/zenodo.23627089)

This version extends the existing research-dataset series. The historical v1.1.0
object remains separately identified by
[10.5281/zenodo.22759501](https://doi.org/10.5281/zenodo.22759501); its files,
meaning and identifier are retained.

## Content and scope

The expanded main cohort contains **4,320 requested outcome coordinates**, with
**4,319 source programs and one accepted incomplete/no-source response**. Every
requested outcome remains in the unconditional denominator. Each has three
deadline measurements (1, 2 and 5 seconds), each repeated three times, giving
**38,880 current-version records**. Six model versions in nine configurations
cover eight fixed backend tasks, two instruction conditions and thirty requested
outputs per task/configuration/condition cell. Unsuccessful, refused, truncated,
syntax-invalid and no-source outcomes are study outcomes, not replacement
candidates.

The historical 320-program cohort and its common-guard reanalysis remain
separate. The archive includes historical v1.1.0 and 2,880 later common-guard
records. Validation evidence and the superseded 1,440-output Mistral cohort are
not pooled into the expanded main cohort; excluded evidence remains separately
preserved in the project.

The dataset's main asset is the **unchanged**
`Supplementary_Material_S2.zip`:

```text
SHA-256  4a70538f1fdf7efb6ad0a7186b9a8e3c044fd0d89b74e77969590bd081bc2bfa
Bytes    746832022
```

This ZIP preserves the exact scientific code snapshot, prompts, scaffold,
sources, raw provider responses/usage metadata, measurement records, collection
manifests, analysis outputs, qualified-reporting receipt and file inventory. Its
internal README was written at the **local author-review candidate stage**. That
old status text, stored field names and original file paths are preserved
provenance, not a claim about the eventual deposit's publication status. Do not
rewrite the archive merely to update that label.

## Uploaded files and relationships

| File | Purpose |
|---|---|
| `Supplementary_Material_S2.zip` | Original frozen research archive; supplied separately without rewriting or a duplicate local staging copy. |
| `Reporting_Additions_2026-10-24.zip` | Later historical probe-inventory evidence and a clearly hypothetical, retrospective four-task sensitivity calculation, including its portable reproducer and computational review/proofs. It changes no saved outcome or frozen analysis. |
| `Supplementary_File_S3_Scenario_Outcomes.csv` | 5,400 scenario summaries, with all-generated and reached denominators. |
| `Supplementary_File_S4_Task_Outcomes.csv` | 432 task/configuration/condition/deadline cells, counts and Wilson intervals. |
| `Supplementary_File_S5_Deadline_Transitions.csv` | 36 paired transitions from one second to two/five seconds for the same programs. |
| `Supplementary_File_S6_Repeat_Outcomes.csv` | 162 repeat summaries; repeated measurements are not additional programs. |
| `DATA_DICTIONARY.md` | Coordinates, unchanged stored fields, CSV columns and denominator rules. |
| `DATA_LICENSE.md` | Scoped research-record licensing and retained software/third-party rights. |
| `CITATION.cff` | Dataset citation using this exact version-specific identifier; cite the software version separately. |
| `VERSION_PRESERVATION.md` | Project policy for new corrections, prior versions and exact-version citations. |
| `SHA256SUMS.txt` | Checksums for the upload payload, including the unchanged S2 asset. |

The CSVs are byte-identical to the corresponding original S2 members named
`tables/Supplementary_Table_Sn_...csv`. The external `Supplementary_File` names
distinguish CSV attachments from numbered tables in narrative supplementary
material. See the exact mapping in the data dictionary.

## Read saved evidence; do not execute generated programs by default

The default computational reproduction reads saved data and trusted statistical
code. It does **not** import or execute the generated `app.py` files and requires
no model credentials or model calls. The unchanged S2 README gives the exact
saved-analysis command and environment. The separately versioned companion [DepFailBench software v1.2.0](https://doi.org/10.5281/zenodo.23627089)
documents the corresponding installed-software entry points.

For the added historical sensitivity calculation, see
`historical_primary_sensitivity/PORTABLE_REPRODUCTION.md` inside the reporting
additions ZIP. It uses NumPy 2.3.5, the supplied verified helper/results and the
unchanged S2 archive. It stages a historical analysis file as **bytes for a hash
check only**. It never imports or executes that archived file or a generated
program.

Generated sources are untrusted research subjects. Re-executing them is a
separate activity requiring the documented isolated, credential-free environment
and fixed measurement rules; it is not part of the deposit's default reproduction
path.

## Interpretation and retained qualifications

The formal expanded analysis is **qualified post-review inference**, with the
planned first repeat and every record and flag retained. Nine programs have
full-behavior differences across 22 program-deadline entries, while primary and
functional pass/fail outcomes are stable across repeats. The unchanged frozen
analysis still rejects flagged rows; the explicit reviewed reporting wrapper is
separate. Do not remove repeat flags or substitute favourable repeats.

Pass rates describe these fixed tasks, exact model configurations, instruction
packages and fault oracles. They are not provider/family rankings, population
effects over arbitrary backends or production-reliability guarantees. Repeats,
scenarios and tasks do not increase the number of independent requested outputs.
The later historical sensitivity is an illustrative design calculation under
independence, 50% baseline task probabilities and homogeneous effects; it is not
an original prospective justification, an estimate of achieved power or a new
empirical result.

## Citation and future versions

Cite dataset **[version 2.0.0](https://doi.org/10.5281/zenodo.23626768)** and the
exact software version/commit used for an analysis. The companion software is
**[v1.2.0](https://doi.org/10.5281/zenodo.23627089)**. The concept DOI additionally
identifies the evolving dataset series; it does not replace the fixed-version
citation. A later journal-article identifier should be linked only after one
actually exists.

Future changes should receive a new, clearly described dataset/software version.
Project policy preserves previous files, hashes, tags and exact-version
identifiers; it does not promise absolute platform permanence or override a
repository's withdrawal and correction policies. See `VERSION_PRESERVATION.md`.
