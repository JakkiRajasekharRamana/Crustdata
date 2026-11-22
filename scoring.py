"""Transparent partner-fit scoring. Pure functions, no I/O, unit-tested.

Partner Fit = 0.30*Strategic + 0.25*Capability + 0.20*MarketAccess + 0.15*Trust + 0.10*Feasibility

Rules enforced here (from the product spec):
  * Unknown != zero. A component the evidence cannot establish is `None`; it is left out and the
    remaining weights are renormalised, and evidence confidence drops instead.
  * Evidence confidence is separate from fit.
  * Hard review flags override the number: a high score never hides a verification concern.
  * Competitive conflict is an explicit, visible penalty, never a silent change.
The weights are design assumptions, not validated values.
"""
from __future__ import annotations

WEIGHTS = {"strategic": 0.30, "capability": 0.25, "market_access": 0.20, "trust": 0.15, "feasibility": 0.10}
CONFLICT_PENALTY = {"none": 0, "low": 0, "medium": 8, "high": 20}  # points off Strategic Complementarity


def compute_fit(components: dict, conflict_level: str = "none") -> dict:
    """components: {name: {"score": 0-100 | None, ...}}. Returns score + the arithmetic behind it."""
    used, parts, unknown = {}, {}, []
    for name in WEIGHTS:
        s = (components.get(name) or {}).get("score")
        if s is None:
            unknown.append(name)
            continue
        s = max(0.0, min(100.0, float(s)))
        if name == "strategic":
            pen = CONFLICT_PENALTY.get(conflict_level, 0)
            if pen:
                parts["conflict_penalty"] = -pen
                s = max(0.0, s - pen)
        used[name] = s
    wsum = sum(WEIGHTS[n] for n in used)
    score = round(sum(WEIGHTS[n] / wsum * v for n, v in used.items()), 1) if wsum else None
    return {"score": score, "used": used, "unknown_components": unknown, "adjustments": parts,
            "weights_used": {n: round(WEIGHTS[n] / wsum, 3) for n in used} if wsum else {}}


def trust_score(identity_confidence: float | None, status_active: bool | None, domain_match: bool | None,
                adverse_verified: int, contradictions: int) -> int | None:
    """Deterministic trust component. None = identity could not be established (hard flag, not a zero)."""
    if identity_confidence is None or identity_confidence < 0.6:
        return None
    s = 70
    if identity_confidence >= 0.95:
        s += 10
    if status_active:
        s += 5
    if domain_match:
        s += 10
    s -= 25 * min(adverse_verified, 2)
    s -= 20 * min(contradictions, 2)
    return max(0, min(100, s))


def evidence_confidence(claims: list[dict]) -> dict:
    """High / Medium / Low from how much of what we claim is actually verified, and from how many kinds of source."""
    scored = [c for c in claims if c.get("status") in ("verified", "unverified", "contradicted")]
    verified = [c for c in scored if c["status"] == "verified"]
    coverage = len(verified) / len(scored) if scored else 0.0
    kinds = {c.get("confidence") for c in verified}
    key_cats = {c["category"] for c in verified}
    has_core = {"capability", "bfsi_presence"} <= key_cats
    # Independent corroboration. A verified claim from the company's own site proves "they say so", not that it is true, and
    # several directory sites often copy one another. So: strong corroboration = a regulatory or reputable-news source;
    # weaker = distinct third-party database DOMAINS (counted once per domain, so repeats of one listing do not add up).
    # Older rows without a classification fall back to the earlier rule (anything not self-reported / API).
    core = ("bfsi_presence", "distribution_channel", "competing_product", "capability")
    strong, weak_domains = set(), set()
    legacy = 0
    for c in verified:
        if c["category"] not in core:
            continue
        co = c.get("corroboration")
        if co == "independent":
            strong.add(c.get("source_org") or c.get("source_url"))
        elif co == "database_listing":
            weak_domains.add(c.get("source_org") or c.get("source_url"))
        elif co is None and not str(c.get("notes") or "").startswith(("Self-reported", "Crustdata API")):
            legacy += 1
    independent = list(strong) + (list(weak_domains) if len(weak_domains) >= 2 else []) + [None] * legacy
    if coverage >= 0.7 and has_core and len(verified) >= 6 and independent:
        level = "High"
    elif coverage >= 0.4 and len(verified) >= 3:
        level = "Medium"
    else:
        level = "Low"
    return {"level": level, "coverage": round(coverage, 2), "verified": len(verified), "total": len(scored),
            "has_core": has_core, "independent_sources": len(independent), "strong_independent_domains": len(strong), "database_domains": len(weak_domains), "kinds": sorted(k for k in kinds if k)}


def review_flags(identity_confidence, domain_match, contradictions: int, conflict_level: str,
                 unverified_key: bool, direct_competitor: bool = False) -> list[str]:
    flags = []
    if identity_confidence is None or identity_confidence < 0.6:
        flags.append("Company identity not resolved - manual review required")
    elif domain_match is False:
        flags.append("Domain and company name do not match - manual review required")
    if contradictions:
        flags.append("Conflicting information between sources - manual review required")
    if conflict_level in ("medium", "high"):
        flags.append(f"Strategic conflict: partner sells a competing product ({conflict_level} overlap)")
    if direct_competitor:
        # A serious conflict must be able to override a high score: a verified direct competitor needs a person's judgement first.
        flags.append("Direct competitor with a verified competing product - manual review required before any approach")
    if unverified_key:
        flags.append("Key claim could not be verified from available sources")
    return flags


def recommendation(fit: float | None, confidence: str, flags: list[str]) -> str:
    hard = [f for f in flags if "manual review" in f]
    if fit is None:
        return "Cannot rate - insufficient verified information"
    if hard:
        return "Manual review before any approach"
    if any(f.startswith("Strategic conflict") for f in flags):
        return "Approach with caution - competitive overlap"
    if fit >= 70 and confidence in ("High", "Medium"):
        return "Pursue"
    if fit >= 55:
        return "Worth a conversation" if confidence != "Low" else "Promising but under-evidenced"
    return "Deprioritise"
