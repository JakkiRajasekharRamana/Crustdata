"""Offline tests: scoring rules, quote verification, duplicate handling. Run: python -m pytest -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import evidence as ev
import pipeline
import scoring


def comps(**kw):
    base = {"strategic": 80, "capability": 80, "market_access": 80, "feasibility": 80, "trust": 80}
    base.update(kw)
    return {k: {"score": v} for k, v in base.items()}


def test_weights_sum_to_one():
    assert abs(sum(scoring.WEIGHTS.values()) - 1) < 1e-9


def test_all_equal_scores_give_same_fit():
    assert scoring.compute_fit(comps())["score"] == 80.0


def test_unknown_component_is_excluded_not_zero():
    full = scoring.compute_fit(comps(market_access=60))["score"]
    unknown = scoring.compute_fit(comps(market_access=None))
    assert "market_access" in unknown["unknown_components"]
    assert unknown["score"] == 80.0  # renormalised over the known 80s; a zero would have dragged it to 64
    assert unknown["score"] > full - 1  # missing != negative


def test_conflict_penalty_is_visible_and_applied():
    clean = scoring.compute_fit(comps(), "none")["score"]
    hi = scoring.compute_fit(comps(), "high")
    assert hi["score"] < clean and hi["adjustments"]["conflict_penalty"] == -20


def test_unresolved_identity_gives_no_trust_and_hard_flag():
    assert scoring.trust_score(None, True, True, 0, 0) is None
    flags = scoring.review_flags(None, None, 0, "none", False)
    assert any("manual review" in f for f in flags)
    assert scoring.recommendation(95.0, "High", flags).startswith("Manual review")  # a high score cannot override


def test_high_fit_low_confidence_is_not_a_confident_recommendation():
    assert scoring.recommendation(85.0, "Low", []) != "Pursue"


def test_self_reported_claims_alone_cannot_give_high_confidence():
    own = [{"status": "verified", "category": c, "confidence": "medium", "notes": "Self-reported on the company's own website."}
           for c in ("capability", "bfsi_presence", "capability", "capability", "capability", "capability", "capability")]
    assert scoring.evidence_confidence(own)["level"] != "High"
    own.append({"status": "verified", "category": "bfsi_presence", "confidence": "medium", "notes": None})  # e.g. a news report
    assert scoring.evidence_confidence(own)["level"] == "High"


def test_competing_product_downgrades_recommendation():
    flags = scoring.review_flags(1.0, True, 0, "high", False)
    assert scoring.recommendation(90.0, "High", flags).startswith("Approach with caution")


def test_quote_verification_requires_the_source_to_say_it():
    src = ev.Source("S1", "first_party", "https://x.test", "page", "We secure core banking systems for 40 co-operative banks across India.")
    good = {"category": "bfsi_presence", "claim": "Serves co-op banks", "source_id": "S1", "quote": "secure core banking systems for 40 co-operative banks"}
    fake = {"category": "bfsi_presence", "claim": "Serves HDFC Bank", "source_id": "S1", "quote": "trusted by HDFC Bank and ICICI Bank nationwide"}
    nosrc = {"category": "capability", "claim": "x", "source_id": "S9", "quote": "anything at all goes here"}
    import store
    store.create_run("t-test", "t")
    rows = ev.check_claims("t-test", "co1", [good, fake, nosrc], {"S1": src})
    assert [r["status"] for r in rows] == ["verified", "unverified", "unverified"]
    assert "can't verify" in rows[1]["notes"]


def test_quote_matching_ignores_punctuation_and_case():
    assert ev.verify_quote("Secure Core-Banking, systems!", "we secure core banking systems for banks")


def test_duplicate_names_collapse():
    assert pipeline.norm_name("Acme Technologies Pvt. Ltd.") == pipeline.norm_name("ACME Technologies Private Limited")
    assert pipeline.norm_domain("https://www.Acme.com/about") == "acme.com"


def test_assess_keeps_the_median_sample(monkeypatch):
    import llm
    import pipeline

    def comp(v):
        return {"components": {k: {"score": v, "why": f"v{v}", "claim_ids": []} for k in ("strategic", "capability", "market_access", "feasibility")},
                "competitive_overlap": {"level": "none"}}

    draws = iter([comp(90), comp(60), comp(70)])
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: next(draws))
    brief = {"requester": {"offering": "x"}, "objective": "o", "target_industry": "t", "country": "India"}
    out = pipeline.assess("t-median", brief, {"id": 1, "name": "A", "domain": "a.com"}, {}, [])
    assert out["components"]["strategic"]["why"] == "v70"
    assert out["assessment_samples"] == {"n": 3, "scores": [60.0, 70.0, 90.0]}


def test_shortlist_ties_break_by_target_fit_then_crustdata_rank():
    import pipeline
    items = [{"id": 1, "relevance": 90, "serves_target": "likely"}, {"id": 2, "relevance": 90, "serves_target": "yes"},
             {"id": 3, "relevance": 90, "serves_target": "yes"}, {"id": 4, "relevance": 95, "serves_target": "unknown"}]
    shuffled = [items[3], items[1], items[0], items[2]]
    order = [1, 2, 3, 4]
    assert [x["id"] for x in pipeline.rank_screened(items, order)] == [4, 2, 3, 1] == [x["id"] for x in pipeline.rank_screened(shuffled, order)]
