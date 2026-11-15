# Real NASA data preflight

FirePulse can generate an explicitly labeled synthetic demo with `--demo`; that mode is for software testing only.
Before a NASA Space Apps presentation, generate the normal dashboard from NASA FIRMS Standard Processing inputs and run:

```sh
python run_pipeline.py
python validate_submission.py
python serve.py
```

The preflight fails if raw FIRMS-format input files are missing, the generated dashboard metadata is marked synthetic,
or the cleaned sensor files contain a non-NASA provenance label. Do not use the synthetic demo as submission evidence.

This check verifies project provenance labels and expected file structure. It cannot cryptographically prove that a CSV came
from NASA or independently validate the observations. Retain the original FIRMS downloads, inspect `data/clean/cleaning_report.json`
and the coverage status, and follow the NASA attribution and limitations already shown in the dashboard.
