import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store
from crustdata import Crustdata

store.create_run("explore", "explore")
cd = Crustdata("explore")
dom = "debilink.com"
e = cd.company_enrich(domains=[dom], fields=["basic_info", "headcount", "funding", "people"])
cdta = e[0]["matches"][0]["company_data"]
print("keys:", list(cdta.keys()))
print(json.dumps(cdta.get("people"), indent=1, ensure_ascii=False)[:2500])
print("funding:", json.dumps(cdta.get("funding"))[:400])

print("=== site search (first-party)")
w = cd.web_search("banks financial institutions clients compliance", sources=["web"], location=None, site=dom)
for r in w.get("results", [])[:5]:
    print(r.get("url"), "|", (r.get("snippet") or "")[:140])
print("=== news")
n = cd.web_search('"DebiLink" cybersecurity', sources=["news"], location=None)
for r in n.get("results", [])[:5]:
    print(r.get("url"), "|", r.get("title"))
print(store.ledger_totals("explore"))
