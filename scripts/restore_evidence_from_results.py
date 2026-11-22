"""Rebuild the evidence table rows of finished runs from the claims stored inside each run's `final` result.
Needed once, because the old table key (claim_id only) let a later run overwrite an earlier run's rows.
usage: python scripts/restore_evidence_from_results.py [RUN ...]   (default: every run that has a final result)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store

runs = sys.argv[1:] or [r["run_id"] for r in store.query("SELECT DISTINCT run_id FROM stages WHERE stage='final'")]
for run in runs:
    fin = store.get_stage(run, "final")
    n = 0
    for p in fin["ranked"]:
        for c in p.get("claims", []):
            store.put_evidence({**c, "run_id": run})
            n += 1
    print(run, "restored", n, "evidence rows")
