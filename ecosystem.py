"""Data layer for the Partner Ecosystem map and the Partnership Pipeline.

Everything here is grounded in what a run actually saved: the discovered candidates, the screening output, the investigated
results, the approvals table and the pipeline stages a person set. Nothing is invented:
* locations are approximate city centres matched from the saved city text (`geo.locate`); a company whose text matches no known
  city is reported as not mappable and is not drawn;
* "industry signals" are keywords found in the company's own description, not verified facts;
* no relationships between companies are drawn, because no source in this build records them.
"""
from __future__ import annotations

import store
import geo

STAGES = ["Discovered", "Investigating", "Verified", "Shortlisted", "Outreach Drafted", "Approved", "Archived"]
STAGE_COLORS = {"Discovered": "#8A97A3", "Investigating": "#5B7C99", "Verified": "#43B99B", "Shortlisted": "#167C68",
                "Outreach Drafted": "#D5A85B", "Approved": "#16845B", "Archived": "#B9C0C6"}

SIGNALS = {
    "Banking / BFSI": ["bank", "bfsi", "nbfc", "financial institution", "lending", "financial services"],
    "Fintech / payments": ["fintech", "payment", "upi", "wallet", "neobank"],
    "Insurance": ["insurance", "insurtech"],
    "Cybersecurity": ["cyber", "security", "mssp", "infosec", "soc ", "siem", "threat", "vulnerab"],
    "Cloud / infrastructure": ["cloud", "infrastructure", "devops", "data cent"],
    "IT services / consulting": ["consult", "system integrator", "it services", "implementation", "managed service", "advisory"],
    "Data / analytics / AI": ["analytics", "data science", "machine learning", " ai ", "artificial intelligence"],
}
NOT_MAPPABLE = "Not mappable"


def signals_for(text: str | None) -> list[str]:
    """Keywords found in the company's own description. A description-based hint, not a verified fact."""
    low = f" {(text or '').lower()} "
    return [name for name, kws in SIGNALS.items() if any(k in low for k in kws)]


def _result_stage(p: dict) -> str:
    rec = str(p.get("recommendation") or "")
    return "Shortlisted" if rec.startswith(("Pursue", "Worth")) else "Verified"


def build_companies(run_id: str) -> list[dict]:
    """Every company the run knows about: discovered, screened and investigated, merged on the Crustdata company id."""
    cands = store.get_stage(run_id, "discover") or []
    screened = {c["id"]: c for c in (store.get_stage(run_id, "screen") or [])}
    fin = store.get_stage(run_id, "final") or {}
    ranked = {str(p["company"]["id"]): (i, p) for i, p in enumerate(fin.get("ranked", []), 1)}
    started = {r["item"] for r in store.query("SELECT item FROM stages WHERE run_id=? AND stage='identity'", (run_id,))}
    approved = {r["company_id"] for r in store.query("SELECT company_id FROM approvals WHERE run_id=?", (run_id,))}
    overrides = {r["company_id"]: dict(r) for r in store.query("SELECT company_id, stage, updated_at, note FROM pipeline_stages WHERE run_id=?", (run_id,))}
    seen, out = set(), []
    pool = list(cands) + [p["company"] for _, p in ranked.values() if str(p["company"]["id"]) not in {str(c["id"]) for c in cands}]
    for c in pool:
        cid = str(c["id"])
        if cid in seen:
            continue
        seen.add(cid)
        s = screened.get(c["id"], {})
        rank, res = ranked.get(cid, (None, None))
        held = bool(res and res.get("held_for_review"))
        investigated = bool(res and not held)
        if cid in approved:
            default = "Approved"
        elif investigated:
            default = _result_stage(res)
        elif held or cid in started:
            default = "Investigating"
        else:
            default = "Discovered"
        ov = overrides.get(cid)
        co = (res or {}).get("company", {}) if res else {}
        desc = (co.get("description") if co else None) or c.get("description") or ""
        city = co.get("city") or c.get("city")
        loc = geo.locate(city)
        out.append({
            "id": cid, "name": co.get("name") or c.get("name"), "domain": co.get("domain") or c.get("domain"), "city": city,
            "size": co.get("size") or c.get("size"), "description": desc, "location": loc,
            "partner_type": s.get("partner_type") or co.get("partner_type"),
            "screen_relevance": s.get("composite") if s.get("composite") is not None else (s.get("relevance") if s else co.get("screen_relevance")),
            "fit": ((res or {}).get("fit") or {}).get("score") if investigated else None,
            "recommendation": (res or {}).get("recommendation") if res else None,
            "evidence_confidence": ((res or {}).get("evidence_confidence") or {}).get("level") if investigated else None,
            "investigated": investigated, "held": held, "rank": rank,
            "signals": signals_for(f"{c.get('name')} {desc}"),
            "default_stage": default, "stage": ov["stage"] if ov else default, "stage_set_by_person": bool(ov),
            "stage_note": ov.get("note") if ov else None,
        })
    return out


def filter_companies(companies: list[dict], *, cities=None, signals=None, ptypes=None, fit_range=None,
                     include_unscored=True, stages=None, text: str = "") -> list[dict]:
    out = []
    for c in companies:
        city = c["location"][0] if c["location"] else NOT_MAPPABLE
        if cities and city not in cities:
            continue
        if signals and not (set(signals) & set(c["signals"])):
            continue
        if ptypes and (c["partner_type"] or "unscreened") not in ptypes:
            continue
        if stages and c["stage"] not in stages:
            continue
        if fit_range is not None:
            lo, hi = fit_range
            if c["fit"] is None:
                if not include_unscored:
                    continue
            elif not lo <= c["fit"] <= hi:
                continue
        if text and text.lower() not in f'{c["name"]} {c["domain"]} {c["city"]}'.lower():
            continue
        out.append(c)
    return out


def sort_key(c: dict):
    """Investigated partners first by fit, then the rest by screening relevance, then name (deterministic)."""
    return (0 if c["fit"] is not None else 1, -(c["fit"] or 0), -(c["screen_relevance"] or 0), str(c["name"]))


def map_points(companies: list[dict]) -> tuple[list[dict], int]:
    """Markers for the map component. Returns (points, number_not_drawn). Positions are approximate city centres."""
    pts, skipped = [], 0
    for c in companies:
        if not c["location"]:
            skipped += 1
            continue
        city, lat, lon = c["location"]
        d_lat, d_lon = geo._jitter(("e" if c["investigated"] else "c") + c["id"], 0.1 if c["investigated"] else 0.22)
        score = c["fit"] if c["fit"] is not None else c["screen_relevance"]
        pts.append({"id": c["id"], "name": c["name"], "city": city, "lat": lat + d_lat, "lon": lon + d_lon, "stage": c["stage"],
                    "color": STAGE_COLORS.get(c["stage"], "#8A97A3"), "investigated": c["investigated"],
                    "score": None if score is None else round(float(score), 1), "score_kind": "fit" if c["fit"] is not None else "screen relevance"})
    return pts, skipped


def set_stage(run_id: str, company_id: str, stage: str, note: str | None = None) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    store.set_pipeline_stage(run_id, str(company_id), stage, note)


def clear_stage(run_id: str, company_id: str) -> None:
    store.execute("DELETE FROM pipeline_stages WHERE run_id=? AND company_id=?", (run_id, str(company_id)))
