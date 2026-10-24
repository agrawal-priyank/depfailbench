# Verification of the v1.2.0 software candidate

The candidate was assembled from the complete 261-file Git tree of execution
commit `5bbcb89261ae535bf85f99c148b7e4c02d3ddf2d`. All 89 files under
`src/benchmark/` and `expanded_study/` match that source byte for byte. The source
manifest pins each SHA256. Campaign-specific dispatch/continuation scripts and
their tests are retained in original history/data, but omitted from this reusable
software copy. `RELEASE_SCOPE.json` gives the selected test files, exclusions and
reasons. This is a new release check, distinct from the historical 319-test gate.

The 21 retained software test modules passed 354 tests with no failures or skips;
four expected FastAPI `on_event` deprecation warnings remain. They use synthetic
or handwritten fixtures and mock transports. The two external SDK classifier and
saved-summary modules passed 13 additional unit tests. No model calls, SDK network
calls, saved model-generated corpus evaluation or empirical remeasurement were
performed for these release checks.

The source distribution and wheel were built offline using setuptools 84.1.0.
The declared build minimum is 77.0.3, supporting the PEP 639 license metadata used
by this package. Both archives preserve the scientific source, three frozen-plan
and prompt-amendment JSON resources, and the standalone saved-analysis tools.
They omit campaign controllers, original paid workflows and workspace results.
The sole release CI workflow runs software/mock/handwritten checks without
provider credentials; dependency installation itself may use the package index.

The wheel was installed into a separate Python 3.12.14 environment, then inspected
from an unrelated working directory. Imports and data resources came from that
installation, including the three frozen/amendment JSON files. Dependencies were
supplied through a read-only link to the exact existing reference environment:
this verifies an actual wheel installation, but is not a clean network-resolver
installation test. The pinned main runtime versions were FastAPI 0.141.1,
Starlette 1.6.0, HTTPX 0.28.1, Pydantic 2.13.5 and Uvicorn 0.52.4; analysis used
NumPy 2.3.5. Generic dependency ranges support reuse, while the lock files identify
the specific reported runtime. The separate SDK lock is not merged into it.

The installed saved-record reproducer verified the unchanged S2 archive's
109,544 inventoried files and 38,880 expanded records, then matched every original
numeric result field and the historical common-guard statistics. It also retained
all nine repeat flags and verified that the original strict reporting guard
rejects them. The authorized qualified post-review analysis remains explicitly
identified. Generated programs were read only as bytes, never imported or run.
The separate historical sensitivity wrapper and reviewed proof files are bundled
together; its numerical simulation is distinct from empirical study evaluation.

These checks establish packaging and computational consistency for the supplied
evidence and reference environment. They are not independent human scientific
review, proof of every oracle, a cross-platform timing validation, or evidence
for a new runtime or future dependency release. No DOI or publication date is
claimed before the release and dataset records are actually published.
