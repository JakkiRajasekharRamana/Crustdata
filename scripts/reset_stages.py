"""Delete model-only stages of a run so they are recomputed (no Crustdata calls are repeated).
usage: python scripts/reset_stages.py RUN_ID [stage ...]   (default: assess result final)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store

run = sys.argv[1]
stages = sys.argv[2:] or ["assess", "result", "final"]
for s in stages:
    n = store.execute("DELETE FROM stages WHERE run_id=? AND stage=?", (run, s)).rowcount
    print(f"deleted {n} rows of stage '{s}'")
if "claims" in stages:  # claims are recomputed, so drop the stale evidence rows too
    print("deleted", store.execute("DELETE FROM evidence WHERE run_id=?", (run,)).rowcount, "evidence rows")
store.set_run_status(run, "running")
