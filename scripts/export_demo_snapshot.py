"""Export finished runs into a small committed SQLite snapshot used by the hosted read-only demo.
usage: python scripts/export_demo_snapshot.py demo1 demo-crash
Only the named runs are copied (runs, calls, stages, evidence). The response cache is NOT copied."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store

keep = sys.argv[1:]
if not keep:
    sys.exit("name at least one run id")
out = Path(__file__).resolve().parent.parent / "demo_data" / "demo.db"
out.parent.mkdir(exist_ok=True)
out.unlink(missing_ok=True)
dst = sqlite3.connect(out)
dst.executescript(store.SCHEMA)
for run in keep:
    for table, col in [("runs", "run_id"), ("calls", "run_id"), ("stages", "run_id"), ("evidence", "run_id")]:
        rows = store.query(f"SELECT * FROM {table} WHERE {col}=?", (run,))
        for r in rows:
            cols = r.keys()
            dst.execute(f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(r))
    print(run, "exported")
dst.commit()
dst.execute("VACUUM")
dst.close()
print(out, out.stat().st_size // 1024, "KB")
