"""Deterministic candidate pre-ranking.

Why this exists: the original screen asked the model for a 0-100 "relevance" per company in batches of 20. Many companies
tied at 85-100 and the model's numbers moved between identical runs, so the top-6 changed (see
PARTNERSCOUT_POST_REPAIR_AUDIT.md for the measured overlap). Here the ORDER of the pool is computed by code from the
company's own structured attributes and description and the parsed brief, identically for every candidate (no batches,
no per-batch calibration). The model is used only for categorical judgements (partner type, serves target segment,
sells a competing product), and its free-form 0-100 score no longer decides the order.

All weights are design assumptions, not validated values.
"""
from __future__ import annotations

import re

STOP = set("""the and for with that this from into their have has are our your you who which also can will more than not any all its
other such using use used within across over under between company companies solutions services service provider providers business
businesses india indian industry sector segment market markets customers customer capabilities capability technology technologies""".split())

# Synonym groups: a brief word in a group activates the whole group (so "banking" also matches "NBFC", "fintech", ...).
SYNONYMS = [
    {"bank", "banking", "banks", "bfsi", "financial", "finance", "nbfc", "insurance", "fintech", "payments", "lending", "fintechs", "bfsi"},
    {"cybersecurity", "security", "cyber", "infosec", "soc", "mssp", "siem", "compliance", "grc", "firewall", "threat", "vulnerability", "iam"},
    {"cloud", "devops", "infrastructure", "managed"},
    {"data", "analytics", "ai", "ml"},
]
# Signals that a company can actually carry a partnership of this kind (generic, not specific to one request).
PARTNER_SIGNALS = ["reseller", "system integrator", "systems integrator", "channel", "distributor", "distribution", "mssp",
                   "managed security", "managed service", "consulting", "consultancy", "implementation", "partner network",
                   "value added", "value-added", "oem", "alliances", "partnership", "integrator", "advisory"]
# Entities that cannot resell or integrate a product (excluded by the original prompt too).
NEGATIVE = ["association", "society", "chamber of commerce", "federation", "council", "forum", "institute of", "university", "college",
            "school of", "magazine", "publisher", "newspaper", "media house", "venture capital", "venture fund", "private equity",
            "investment fund", "incubator", "accelerator", "staffing", "recruitment", "manpower",
            "directory", "listing portal", "job portal", "physical security", "security guards", "guarding services",
            "electronic security", "cctv", "surveillance system", "access control system", "fire alarm", "alarm system"]
# Government bodies are NOT matched by words here ("recognised by the Ministry of ..." is a normal sentence about a real
# vendor); the model's categorical partner_type = not_a_partner handles them.
GENERIC = set("""existing client clients base designed digital expertise integration technical regulatory strong network assets experience
knowledge relationships distribution channel partners partner network access reach presence established significant large leading
financial finance bank banks banking software platform saas protect infrastructure devops cloud""".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in STOP}


def _expand(words: set[str]) -> set[str]:
    out = set(words)
    for grp in SYNONYMS:
        if words & grp:
            out |= grp
    return out


def brief_terms(brief: dict) -> dict[str, set[str]]:
    """Target-segment terms come from the target industry; capability terms from what the requester SELLS and the
    capabilities it asks for, minus the target-segment words (so a fintech is not mistaken for a security vendor)."""
    ind_words = _words(str(brief.get("target_industry") or ""))
    industry = _expand(ind_words | _words(str(brief.get("objective") or "")) & {"bank", "banking", "banks", "bfsi", "financial", "finance", "fintech"})
    offering = _words(str((brief.get("requester") or {}).get("offering") or "") + " " + " ".join(map(str, brief.get("required_capabilities") or [])))
    caps = _expand(offering) - industry - GENERIC
    caps -= {"bank", "banking", "banks", "bfsi", "financial", "finance", "fintech", "fintechs", "insurance", "nbfc", "lending", "payments"}
    return {"industry": industry, "caps": caps}


SIZE_POINTS = {"1-10": 0, "2-10": 0, "11-50": 6, "51-200": 10, "201-500": 10, "501-1000": 8, "1001-5000": 6, "5001-10000": 4, "10001+": 2}


def prescore(brief: dict, cand: dict, terms: dict | None = None) -> dict:
    """0-100 relevance from code only. Same inputs -> same output, for every candidate in the pool."""
    terms = terms or brief_terms(brief)
    name = str(cand.get("name") or "")
    text = f'{name} {cand.get("description") or ""}'.lower()
    words = _words(text)
    ind_hits = len(words & terms["industry"])
    cap_hits = len(words & terms["caps"])
    sig_hits = sum(1 for s in PARTNER_SIGNALS if s in text)
    head = f'{name} {str(cand.get("description") or "")[:220]}'.lower()
    neg_hits = [n for n in NEGATIVE if n in head]
    parts = {
        "serves_target_terms": min(ind_hits, 3) / 3 * 30,
        "capability_terms": min(cap_hits, 3) / 3 * 35,
        "partner_signals": min(sig_hits, 3) / 3 * 20,
        "size": SIZE_POINTS.get(str(cand.get("size") or ""), 4),
        "description_present": 5 if len(str(cand.get("description") or "")) > 80 else 0,
    }
    score = sum(parts.values()) - (40 if neg_hits else 0)
    return {"prescore": round(max(0.0, min(100.0, score)), 1), "parts": {k: round(v, 1) for k, v in parts.items()}, "negative": neg_hits}


SERVES = {"yes": 15, "likely": 8, "unknown": 0, "no": -25}
COMPETE = {"no": 0, "possible": -4, "yes": -10}
PTYPE = {"channel": 8, "distribution": 8, "technology": 6, "consulting": 4, "not_a_partner": -60}


def composite(pre: dict, llm: dict | None) -> float:
    """Prescore plus the model's CATEGORICAL judgements. The model's free-form 0-100 number is deliberately not used."""
    s = pre["prescore"]
    if llm:
        s += SERVES.get(str(llm.get("serves_target")), 0) + COMPETE.get(str(llm.get("sells_competing_product")), 0) + PTYPE.get(str(llm.get("partner_type")), 0)
    return round(max(0.0, min(100.0, s)), 1)


def order(cands: list[dict]) -> list[dict]:
    """Deterministic order: composite desc, then Crustdata's own search rank (position in the discover output)."""
    return sorted(cands, key=lambda c: (-(c.get("composite") or 0), c.get("_pos", 10**6)))
