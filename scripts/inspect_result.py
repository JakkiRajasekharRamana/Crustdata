import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store

run = sys.argv[1]
which = sys.argv[2] if len(sys.argv) > 2 else None
for item, r in store.list_stage(run, "result").items():
    if which and which.lower() not in r["company"]["name"].lower():
        continue
    print("=" * 90)
    print(r["company"]["name"], r["company"].get("domain"), "| fit", r["fit"].get("score"), "|", r.get("evidence_confidence", {}).get("level"),
          "|", r.get("recommendation"))
    print("flags:", r.get("flags"))
    print("overlap:", json.dumps(r.get("competitive_overlap"), ensure_ascii=False)[:300])
    for k, v in r.get("components", {}).items():
        print(f"  {k}: {v.get('score')} - {str(v.get('why'))[:140]}")
    print("stakeholder:", r.get("stakeholder"))
    for c in r.get("claims", []):
        print(f"  [{c['status']:11}] {c['category']:22} {c['claim'][:95]} | q={str(c.get('quote'))[:60]!r}")
