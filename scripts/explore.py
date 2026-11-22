import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store
from crustdata import Crustdata


def short(o, n=2500):
    return json.dumps(o, indent=1, ensure_ascii=False)[:n]


store.create_run("explore", "explore")
cd = Crustdata("explore")
dom = sys.argv[1] if len(sys.argv) > 1 else "debilink.com"

print("=== IDENTIFY"); print(short(cd.company_identify(domains=[dom]), 1800))
print("=== ENRICH")
e = cd.company_enrich(domains=[dom], fields=["basic_info", "headcount", "funding", "people"])
print(short(e, 4500))
print("=== WEB SEARCH")
w = cd.web_search(f"{dom} banking financial services customers India", sources=["web", "news"])
print(short(w, 1800))
print("=== FETCH")
url = next((r["url"] for r in w.get("results", []) if r.get("url")), None)
if url:
    f = cd.web_fetch([url])
    print(url, [(x.get("success"), len(x.get("content") or "")) for x in f])
print(store.ledger_totals("explore"))
