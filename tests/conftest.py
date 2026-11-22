import os
import sys
import tempfile
from pathlib import Path

# Tests must never touch the real ledger: point SQLite at a throwaway file BEFORE store is imported.
os.environ["PARTNERSCOUT_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
