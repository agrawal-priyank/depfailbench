# Saved-record reproduction for the Array revision

The default computation consumes `Supplementary_Material_S2.zip`, SHA256 `4a70538f1fdf7efb6ad0a7186b9a8e3c044fd0d89b74e77969590bd081bc2bfa`. It does not require importing generated programs or fresh measurements. The ZIP is supplied separately as the versioned research dataset; it is intentionally absent from the wheel/source repository.

Use Python 3.12, dependencies pinned in `requirements.lock`, and NumPy 2.3.5 from `expanded_study/requirements-analysis.txt`. From the software source release run:

```sh
python reproduce_saved_analysis.py /path/to/Supplementary_Material_S2.zip --output reproduced_analysis.json
```

For a wheel installation, the same script is installed under `share/depfailbench/` in the environment prefix. Its path can be located with `python -c "import sysconfig; print(sysconfig.get_path('data'))"`; append `/share/depfailbench/reproduce_saved_analysis.py`. Run it from any working directory.

The script verifies 109,544 inventoried files and 38,880 expanded raw records, joins original collection/source identities, preserves all repeat flags, verifies rejection by the strict original reporting gate, and recomputes the authorized qualified post-review result fields. It also reproduces the separate historical common-guard statistics. It extracts trusted code from the archive to a temporary directory and executes only trusted statistical/validation functions. Generated source is read only as bytes. Network/API calls and generated-program execution are absent.

Use the exact code inside the dataset for reproducing the reported numbers: arbitrary installed future code may differ. The release's scientific manifest permits comparison with the executed source. A computational match checks consistency conditional on the supplied evidence; it is not independent human validation or proof of all semantic oracles.

The nine flagged programs, first-repeat selection and post-review authorization are data/provenance, not errors to clear. Failing outputs remain in the unconditional denominator. Do not run raw generation, collection or evaluation commands as a substitute for this analysis-only path.


## Separate historical design sensitivity

The additional retrospective historical sensitivity calculation is supplied under
`research/historical_sensitivity/`. Keep the wrapper, numerical helper and original
results together and use the portable wrapper rather than invoking the numerical
helper directly:

```sh
python research/historical_sensitivity/reproduce_historical_sensitivity.py \
  /path/to/Supplementary_Material_S2.zip --output new_sensitivity_results.json
```

The wheel installs the same sibling files under
`share/depfailbench/research/historical_sensitivity/` in the environment's data
prefix. Run its wrapper from any working directory. NumPy 2.3.5 is required. The
wrapper pins the same unchanged S2 archive, compares all 87 simulated grid rows
and their numerical summaries, and executes only the supplied trusted numerical
helper. Historical analysis source is read only for its provenance hash; no
archived analysis or generated service is executed. The empirical records and
frozen expanded analysis remain unchanged.

This is a retrospective, hypothetical sensitivity illustration with a 50% C0
probability on each fixed historical task and homogeneous positive effects.
Simulation assumptions, Monte Carlo uncertainty and the threshold-specific
interpretation are retained in the supplied instructions/results. It is not a
prospective sample-size justification or an observed-effect power estimate.
