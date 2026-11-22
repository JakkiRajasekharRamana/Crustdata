"""Measure what can be measured automatically from a finished run. Human-judged metrics are NOT computed here.
usage: python scripts/evaluate.py RUN_ID   -> prints a markdown table (paste into README)"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import store
from pipeline import norm_domain, norm_name

run = sys.argv[1]
fin = store.get_stage(run, "final")
ranked = [r for r in fin["ranked"] if not r.get("held_for_review")]
n = len(ranked)

ident_ok = sum(1 for r in ranked if r["identity"].get("resolved") and r["identity"].get("domain_match") and (r["identity"].get("confidence") or 0) >= 0.95)
claims = [c for r in ranked for c in r["claims"]]
status = Counter(c["status"] for c in claims)
checkable = status["verified"] + status["unverified"] + status["contradicted"]
quoted_verified = sum(1 for c in claims if c["status"] == "verified" and c.get("quote") and c.get("source_url"))
dups = n - len({(norm_domain(r["company"]["domain"]), norm_name(r["company"]["name"])) for r in ranked}) + \
       n - len({norm_domain(r["company"]["domain"]) for r in ranked})
with_dm = sum(1 for r in ranked if r.get("stakeholder"))
conf = Counter(r["evidence_confidence"]["level"] for r in ranked)
recs = Counter(r["recommendation"] for r in ranked)
cited_ok = 0
cited_all = 0
for r in ranked:
    ids = {c["claim_id"] for c in r["claims"]}
    for comp in r["components"].values():
        for i in comp.get("claim_ids", []):
            cited_all += 1
            cited_ok += i in ids
led = fin["ledger"]
calls = store.query("SELECT service, COUNT(*) n, COALESCE(SUM(credits),0) c, SUM(CASE WHEN error IS NOT NULL AND error!='' THEN 1 ELSE 0 END) errs, "
                    "COALESCE(SUM(cached),0) hits FROM calls WHERE run_id=? GROUP BY service", (run,))
by = {r["service"]: dict(r) for r in calls}
rec_err = by.get("crustdata", {}).get("errs", 0)
t = store.query("SELECT MIN(ts) a, MAX(ts) b FROM calls WHERE run_id=?", (run,))[0]

print(f"## Automated measurements, run `{run}`\n")
print("| Metric | Result |\n|---|---|")
print(f"| Unique candidates discovered | {fin['n_candidates']} |")
print(f"| Companies investigated end to end | {n} |")
print(f"| Identity resolved (confidence >= 0.95, domain matches) | {ident_ok}/{n} |")
print(f"| Duplicates in the shortlist | {dups} |")
print(f"| Claims recorded | {len(claims)} (verified {status['verified']}, unverified {status['unverified']}, inferred {status['inferred']}, "
      f"contradicted {status['contradicted']}, needs_review {status['needs_review']}) |")
print(f"| Evidence coverage = verified / (verified+unverified+contradicted) | {status['verified']}/{checkable} = {100*status['verified']/max(checkable,1):.0f}% |")
print(f"| Verified claims carrying a source and a quote | {quoted_verified}/{status['verified']} |")
print(f"| Score citations that point at a real ledger claim | {cited_ok}/{cited_all} |")
print(f"| Candidates with a decision-maker taken from the API record | {with_dm}/{n} |")
print(f"| Evidence confidence | {dict(conf)} |")
print(f"| Recommendations | {dict(recs)} |")
print(f"| Crustdata credits (whole run, all attempts) | {led['credits']:.2f} |")
print(f"| Estimated model cost (list price; free tier billed $0) | ${led['usd']:.3f} |")
print(f"| Logged calls | {sum(v['n'] for v in by.values())} (crustdata {by.get('crustdata',{}).get('n',0)}, llm {by.get('llm',{}).get('n',0)}) |")
print(f"| Crustdata calls with an error row (retried or failed) | {rec_err} |")
print(f"| Wall-clock span of logged calls | {(t['b']-t['a'])/60:.1f} min (includes pauses and resumes) |")
