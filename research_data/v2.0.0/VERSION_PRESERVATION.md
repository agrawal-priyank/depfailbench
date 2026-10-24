# Version and identifier preservation policy

This is the project's preservation policy for DepFailBench dataset 2.0.0, not a guarantee that an external hosting platform can never change or
withdraw an object.

1. **Keep prior versions identifiable.** Historical dataset v1.1.0 remains
   [10.5281/zenodo.22759501](https://doi.org/10.5281/zenodo.22759501); v1.0.2
   remains [10.5281/zenodo.22699095](https://doi.org/10.5281/zenodo.22699095).
   The Dataset concept is
   [10.5281/zenodo.22699094](https://doi.org/10.5281/zenodo.22699094). Dataset
   [2.0.0](https://doi.org/10.5281/zenodo.23626768) identifies a new version in
   that series, not an overwrite of an old one.
2. **Use exact versions in the Array record.** Cite dataset
   [2.0.0](https://doi.org/10.5281/zenodo.23626768), the separate software
   [v1.2.0](https://doi.org/10.5281/zenodo.23627089), and the exact software
   commit used. Keep version-specific citations when newer versions appear; the
   concept DOI may be added for discovery.
3. **Treat new corrections as new versions.** Preserve prior source files,
   outputs, prompt versions, raw measurement versions, repeat flags and manifests.
   Explain changed measurement or interpretation without silently replacing the
   scientific meaning of a historical file or identifier. Never regenerate a
   consumed coordinate or remove an unsuccessful outcome to improve a result.
4. **Do not move historical Git tags or replace release assets.** Publish new
   tags/versions for changes. Retain downloaded copies and checksums independently
   of the hosted release. Software and data are versioned separately and linked
   to each other, so a software update does not silently change a cited dataset.
5. **Preserve the S2 scientific archive.** Its exact SHA-256 is
   `4a70538f1fdf7efb6ad0a7186b9a8e3c044fd0d89b74e77969590bd081bc2bfa`.
   The later reporting additions are a separate asset with their own inventory
   and hash; they do not rewrite S2, original programs or measurements.
6. **Keep cohort and repeated-measure relationships.** Historical and expanded
   cohorts, corrected/original measurements, validation and superseded evidence
   remain distinguishable. Dataset versions do not create new independent
   observations, and old/new protocols must not be pooled silently.
7. **Describe platform limits honestly.** Hosted repositories may have exceptional
   withdrawal, access-restriction or correction procedures. The project will
   favour new versions and retain manifests and local copies, without promising
   perpetual availability or claiming a platform can never change an asset.

Future Software Impacts or Data in Brief articles, if pursued, should identify
the exact software/data versions they describe. These research materials do not
start or submit either article and do not imply that the Array revision has
been resubmitted or accepted.
