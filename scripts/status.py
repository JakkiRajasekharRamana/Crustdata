import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store

run = sys.argv[1] if len(sys.argv) > 1 else "demo1"
print("now", time.strftime("%H:%M:%S"))
for r in store.query(
    "select id, ts, service, endpoint, status, credits, latency_ms, attempt, substr(coalesce(error,''),1,140) e "
    "from calls where run_id=? order by id desc limit 10", (run,)):
    d = dict(r)
    d["ts"] = time.strftime("%H:%M:%S", time.localtime(d["ts"]))
    print(d)
print(store.ledger_totals(run))
