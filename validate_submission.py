"""Preflight the real NASA FIRMS data bundle before a submission or live demo.

This checks project provenance labels and the expected input/output structure. It cannot
independently authenticate the origin of a CSV; preserve the original NASA FIRMS downloads.
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
from pathlib import Path

from firepulse.config import CLEAN, EXTRA_SOURCES, RAW, SOURCES, WEB_DATA
from firepulse.schema import ORIGIN_FIRMS

REQUIRED_FIRMS_COLUMNS = {'latitude', 'longitude', 'acq_date'}


def _csv_header(path: Path, compressed: bool = False) -> set[str]:
    opener = gzip.open if compressed else open
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as handle:
        return {str(name).strip().lstrip('\ufeff') for name in next(csv.reader(handle), [])}


def _check_origin_file(path: Path, errors: list[str]) -> None:
    """Check every generated CSV.GZ for the NASA_FIRMS label and at least one row."""
    try:
        with gzip.open(path, 'rt', encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or 'data_origin' not in reader.fieldnames:
                errors.append(f'{path}: missing data_origin column')
                return
            rows = 0
            for row in reader:
                rows += 1
                if row.get('data_origin') != ORIGIN_FIRMS:
                    errors.append(f"{path}: found non-NASA provenance {row.get('data_origin')!r}")
                    return
            if rows == 0:
                errors.append(f'{path}: contains no cleaned detections')
    except (OSError, EOFError, csv.Error) as exc:
        errors.append(f'{path}: cannot read generated data ({exc})')


def check_submission_data() -> list[str]:
    errors: list[str] = []
    source_folders = {
        key: [SOURCES[key]] + [name for name, family in EXTRA_SOURCES.items() if family == key]
        for key in SOURCES
    }
    for sensor, folders in source_folders.items():
        candidates = [path for folder in folders for path in (RAW / folder).glob('*.csv') if path.is_file()]
        if not candidates:
            errors.append(f'No raw CSV input found for {sensor.upper()} under {RAW}.')
            continue
        for path in candidates:
            try:
                missing = REQUIRED_FIRMS_COLUMNS - _csv_header(path)
                if missing:
                    errors.append(f"{path}: not a recognized FIRMS CSV; missing columns {', '.join(sorted(missing))}.")
            except (OSError, StopIteration, csv.Error) as exc:
                errors.append(f'{path}: cannot read input header ({exc})')

    meta_path, cells_path = WEB_DATA / 'meta.json', WEB_DATA / 'cells.json'
    if not meta_path.is_file() or not cells_path.is_file():
        errors.append(f'Generated dashboard data is incomplete: expected {meta_path} and {cells_path}. Run python run_pipeline.py.')
    else:
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            if meta.get('data_origin') != ORIGIN_FIRMS or meta.get('demo'):
                errors.append(f"{meta_path}: dashboard data is not labeled {ORIGIN_FIRMS}; regenerate from NASA FIRMS inputs.")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f'{meta_path}: cannot read metadata ({exc})')
        try:
            json.loads(cells_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f'{cells_path}: cannot read generated cell data ({exc})')

    active_files = sorted(CLEAN.glob('*.csv.gz'))
    if not active_files:
        errors.append(f'No cleaned sensor data found under {CLEAN}; run python run_pipeline.py.')
    for path in active_files:
        _check_origin_file(path, errors)
    return errors


def main() -> int:
    print('FirePulse NASA FIRMS data preflight')
    errors = check_submission_data()
    if errors:
        for error in errors:
            print(f'FAIL: {error}', file=sys.stderr)
        print('\nSubmission preflight failed. Do not present synthetic or incomplete data as NASA observations.', file=sys.stderr)
        return 1
    print('PASS: raw FIRMS-format inputs, generated dashboard files, and cleaned sensor data are present and labeled NASA_FIRMS.')
    print('Note: this checks provenance labels and file structure, not independent authenticity of the original CSVs.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
