"""Validate raw FIRMS CSV files:  python validate_inputs.py [folder]"""
import sys
from pathlib import Path
from firepulse.config import RAW
from firepulse import validate

sys.exit(validate.main(Path(sys.argv[1]) if len(sys.argv) > 1 else RAW))
