"""Prove exactly-once: no identical paid Crustdata request was made twice in a run (cache hits excluded)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store

run = sys.argv[1]
rows = store.query("SELECT endpoint, request_json, COUNT(*) n, SUM(credits) c FROM calls WHERE run_id=? AND service='crustdata' "
                   "AND status=200 AND cached=0 GROUP BY endpoint, request_json HAVING n>1", (run,))
paid = store.query("SELECT COUNT(*) n, COALESCE(SUM(credits),0) c FROM calls WHERE run_id=? AND service='crustdata' AND status=200 AND cached=0", (run,))[0]
print(f"run {run}: {paid['n']} paid Crustdata calls, {paid['c']:.2f} credits")
print("identical paid requests repeated:", len(rows))
for r in rows:
    print(" ", r["endpoint"], r["request_json"][:80], "x", r["n"])
