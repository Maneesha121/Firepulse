# FirePulse dashboard finalization

The existing analysis and scientific processing are preserved. When served with `python serve.py`, the existing dashboard receives a lightweight responsive stylesheet and an in-page navigation bar for the hotspot map, fire calendar, anomalies, sensor comparison and area statistics. The server also supplies the missing `baseNote` status node referenced by the existing frontend script, preventing null-element errors in date-baseline updates.

The pipeline now stops if any requested NASA FIRMS download windows fail and does not proceed using partial or stale inputs. A regular non-demo pipeline run checks that the configured NASA source CSVs exist first. For submission checks use `python validate_submission.py`; it rejects synthetic provenance and empty cleaned outputs.

These changes do not authenticate the provenance of user-supplied CSVs. Preserve official NASA FIRMS downloads and inspect the coverage, quality and summary reports before interpreting results.
