"""Re-evaluate finished runs with the improved evidence model: resolve Google redirect citations to their real destination,
classify every source, and recompute evidence confidence with the source-quality-aware rule. Reports before/after.
Network use: one HTTP request per distinct Google redirect link (Location header only; destination pages are not fetched).
usage: python scripts/backfill_sources.py RUN [RUN ...]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import evidence as ev
import scoring
import store

cache = {}
report = []
for run in sys.argv[1:]:
    fin = store.get_stage(run, "final")
    cands = {str(c["id"]): c for c in (store.get_stage(run, "discover") or [])}
    for p in fin["ranked"]:
        if p.get("held_for_review"):
            continue
        cid = str(p["company"]["id"])
        domain = (cands.get(cid) or {}).get("domain") or p["company"].get("domain") or ""
        before_claims = [dict(c, corroboration=None) for c in p["claims"]]
        before = scoring.evidence_confidence(before_claims)["level"]
        for c in p["claims"]:
            url = c.get("source_url") or ""
            if url.startswith("crustdata:"):
                kind, canon = "crustdata_api", None
            else:
                if "google." in ev.host_of(url):
                    if url not in cache:
                        cache[url] = ev.canonicalize(url)
                    canon = cache[url]
                else:
                    canon = ev.strip_tracking(url) if url else None
                kind = "first_party" if str(c.get("notes") or "").startswith("Self-reported") else "search_snippet"
            if c["status"] == "verified" and (url or canon):
                cls, corro = ev.classify_source(canon or url, kind, domain)
                c.update(canonical_url=canon, source_class=cls, source_org=ev.host_of(canon or url) or None, corroboration=corro)
            elif c["status"] == "contradicted" or c["category"] == "conflict":
                c.update(corroboration="contradiction")
            else:
                c.update(corroboration={"unverified": "unverified", "inferred": "inference"}.get(c["status"]))
            store.execute("UPDATE evidence SET canonical_url=?, source_class=?, source_org=?, corroboration=? WHERE run_id=? AND claim_id=?",
                          (c.get("canonical_url"), c.get("source_class"), c.get("source_org"), c.get("corroboration"), run, c["claim_id"]))
        conf = scoring.evidence_confidence(p["claims"])
        p["evidence_confidence"] = conf
        p["recommendation"] = scoring.recommendation(p["fit"]["score"], conf["level"], p.get("flags", []))
        report.append({"run": run, "company": p["company"]["name"], "confidence_before": before, "confidence_after": conf["level"],
                       "strong_independent_domains": conf["strong_independent_domains"], "database_domains": conf["database_domains"]})
    store.put_stage(run, "final", fin)
    for p in fin["ranked"]:  # keep the per-company result checkpoints consistent with the final
        if not p.get("held_for_review"):
            store.put_stage(run, "result", p, item=str(p["company"]["id"]))
google_total = sum(1 for k in cache)
resolved = sum(1 for v in cache.values() if v)
print(json.dumps({"google_redirect_links": google_total, "resolved_to_destination": resolved, "unresolved": google_total - resolved,
                  "confidence_changes": [r for r in report if r["confidence_before"] != r["confidence_after"]],
                  "unchanged": sum(1 for r in report if r["confidence_before"] == r["confidence_after"]), "total": len(report)}, indent=1))
Path(__file__).resolve().parent.parent.joinpath("audit_results", "backfill_sources.json").write_text(json.dumps(report, indent=1))
