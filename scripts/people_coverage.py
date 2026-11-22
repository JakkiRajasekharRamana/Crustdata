"""Decision-maker coverage: how many shortlisted companies in finished runs have a verified decision-maker with and without
the Person Search fallback. Makes LIVE Crustdata calls (0.13 credits each, only for companies with no people in their record).
usage: python scripts/people_coverage.py RUN [RUN ...]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pipeline
import store
from crustdata import Crustdata

cd = Crustdata("t-audit-people", credit_ceiling=20)
rows = []
for run in sys.argv[1:]:
    fin = store.get_stage(run, "final")
    for p in fin["ranked"]:
        if p.get("held_for_review"):
            continue
        co = p["company"]
        enr_has = bool(p.get("stakeholder"))
        rec = {"run": run, "company": co["name"], "id": co["id"], "before": enr_has, "fallback_used": False, "found": [], "n_returned": 0}
        if not enr_has:
            fb = store.get_stage("t-audit-people", "people", f"{run}:{co['id']}") or None
            if fb is None:
                fb = pipeline.find_people(cd, co["id"], {})
                store.put_stage("t-audit-people", "people", fb, item=f"{run}:{co['id']}")
            rec.update(fallback_used=True, found=fb["people"], n_returned=fb["n_returned"])
        rows.append(rec)
tot = len(rows)
before = sum(1 for r in rows if r["before"])
after = before + sum(1 for r in rows if r["fallback_used"] and r["found"])
print(json.dumps({"companies": tot, "coverage_before": f"{before}/{tot}", "coverage_after": f"{after}/{tot}",
                  "rows": [{k: r[k] for k in ("run", "company", "before", "n_returned", "found")} for r in rows if r["fallback_used"]]}, indent=1))
Path(__file__).resolve().parent.parent.joinpath("audit_results", "people_coverage.json").write_text(json.dumps(rows, indent=1))
