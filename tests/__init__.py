"""Test package. Importing it puts the scripts and this folder on sys.path, so both
`python -m unittest discover -s tests` and `python -m unittest tests.test_grading` work."""

import sys

# Importing the scripts must not drop __pycache__/ into Profile/data/scripts/.
sys.dont_write_bytecode = True
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "Profile" / "data" / "scripts"
for p in (str(SCRIPTS), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)
