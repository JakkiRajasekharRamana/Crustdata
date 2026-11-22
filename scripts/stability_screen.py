"""Ranking-stability experiment. Re-runs ONLY the screening/ranking step N times on the SAME candidate pool
(the cached `discover` output of a finished run), so any difference between repeats is caused by the screening
method itself (LLM randomness etc.), not by changing live data.
usage: python scripts/stability_screen.py SOURCE_RUN N LABEL"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store
import pipeline

src, n, label = sys.argv[1], int(sys.argv[2]), sys.argv[3]
brief = store.get_stage(src, "brief")
cands = store.get_stage(src, "discover")
out = Path(__file__).resolve().parent.parent / "audit_results" / f"stability_{label}.json"
runs = json.loads(out.read_text()) if out.exists() else []
for k in range(len(runs), n):
    rid = f"t-audit-{label}-{k}"
    screened = pipeline.screen(rid, brief, cands)
    ranking = [c["id"] for c in screened if c.get("domain") and c.get("partner_type") != "not_a_partner"]
    short = ranking[:6]
    runs.append({"k": k, "ranking": ranking, "shortlist": short, "names": {str(c["id"]): c["name"] for c in screened}})
    out.write_text(json.dumps(runs))
    print(label, "repeat", k, "done; shortlist:", [next(c["name"] for c in screened if c["id"] == i)[:18] for i in short], flush=True)
