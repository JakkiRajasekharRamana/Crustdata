"""Audit regression tests.

Everything here that talks to "Crustdata" uses a SIMULATED session (fault injection) and says so in its name. These are
not live API responses and must never be reported as such. Live evidence lives in audit_results/ and the run databases.
"""
import json
import uuid

import pytest
import requests

import crustdata
import evidence as ev
import pipeline
import ranking
import scoring
import store
import validation


class FakeResp:
    def __init__(self, status=200, body=None, headers=None, text=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeSession:
    """SIMULATED transport: replays a scripted list of responses/exceptions and counts calls."""

    def __init__(self, script):
        self.script, self.calls = list(script), 0
        self.headers = {}

    def post(self, url, json=None, timeout=None):
        self.calls += 1
        item = self.script.pop(0) if self.script else FakeResp(200, {"ok": True})
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, *a, **k):
        raise AssertionError("no GET expected")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CRUSTDATA_API_KEY", "simulated-key")
    monkeypatch.setattr(crustdata.Crustdata, "_load_limits", lambda self: None)
    slept = []
    monkeypatch.setattr(crustdata.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(crustdata.Crustdata, "_throttle", lambda self, path: None)
    n = {"i": 0}

    def make(script, run="t-sim"):
        c = crustdata.Crustdata(f"{run}-{uuid.uuid4().hex[:8]}", credit_ceiling=1000, time_ceiling=10_000)
        c.s = FakeSession(script)
        c.slept = slept
        return c
    return make


def ledger(run):
    return [dict(r) for r in store.query("SELECT status, credits, cached, attempt FROM calls WHERE run_id=? ORDER BY id", (run,))]


# ----------------------------------------------------------------- Crustdata client: failure modes (SIMULATED)
def test_simulated_401_is_fatal_and_not_retried(client):
    c = client([FakeResp(401, {"error": "bad key"})])
    with pytest.raises(crustdata.CrustdataError):
        c.call("/company/search", {"a": 1})
    assert c.s.calls == 1


def test_simulated_403_is_fatal_and_not_retried(client):
    c = client([FakeResp(403, {"error": "no permission"})])
    with pytest.raises(crustdata.CrustdataError):
        c.call("/person/search", {"a": 1})
    assert c.s.calls == 1


def test_simulated_402_raises_credits_exhausted_without_retry(client):
    c = client([FakeResp(402, {"error": "no credits"})])
    with pytest.raises(crustdata.CreditsExhausted):
        c.call("/company/enrich", {"a": 1})
    assert c.s.calls == 1


def test_simulated_429_waits_for_reset_header_then_succeeds(client):
    c = client([FakeResp(429, {"error": "slow"}, {"x-ratelimit-reset": "7"}), FakeResp(200, {"ok": 1}, {"X-Credits-Used": "2.0"})])
    assert c.call("/company/enrich", {"a": uuid.uuid4().hex}) == {"ok": 1}
    assert 7.0 in c.slept
    rows = ledger(c.run_id)
    assert [r["status"] for r in rows] == [429, 200] and rows[1]["credits"] == 2.0


def test_simulated_503_retries_are_bounded(client):
    c = client([FakeResp(503, {"error": "down"})] * 10)
    with pytest.raises(crustdata.CrustdataError):
        c.call("/company/search", {"a": 3}, max_attempts=4)
    assert c.s.calls == 4  # never more than max_attempts


def test_simulated_timeout_is_retried_then_recovers(client):
    c = client([requests.Timeout("simulated"), FakeResp(200, {"ok": 1}, {"X-Credits-Used": "1"})])
    assert c.call("/web/enrich/live", {"a": uuid.uuid4().hex}) == {"ok": 1}
    assert c.s.calls == 2 and ledger(c.run_id)[0]["status"] is None


def test_simulated_invalid_json_on_200_is_not_cached_and_is_bounded(client):
    c = client([FakeResp(200, None, text="<html>oops</html>")] * 6)
    with pytest.raises(crustdata.CrustdataError):
        c.call("/company/search", {"a": 5}, max_attempts=3)
    assert c.s.calls == 3
    assert store.query("SELECT 1 FROM cache WHERE endpoint='/company/search' AND key=?", (c._key("/company/search", {"a": 5}),)) == []


def test_simulated_repeat_call_is_served_from_cache_with_zero_credits(client):
    c = client([FakeResp(200, {"ok": 1}, {"X-Credits-Used": "3.5"})])
    body = {"a": "repeat-" + uuid.uuid4().hex}
    c.call("/company/enrich", body)
    c.call("/company/enrich", body)
    rows = ledger(c.run_id)
    assert c.s.calls == 1 and [r["cached"] for r in rows] == [0, 1] and sum(r["credits"] for r in rows) == 3.5


def test_simulated_credit_ceiling_blocks_before_the_call(client):
    c = client([FakeResp(200, {"ok": 1}, {"X-Credits-Used": "5"})] * 3)
    c.credit_ceiling = 4
    c.call("/company/enrich", {"a": 7})
    with pytest.raises(crustdata.BudgetExceeded):
        c.call("/company/enrich", {"a": 8})
    assert c.s.calls == 1


# ----------------------------------------------------------------- exactly-once stage checkpoints
def test_stage_runs_its_function_once_per_run_stage_item():
    n = {"calls": 0}

    def work():
        n["calls"] += 1
        return {"v": n["calls"]}
    a = pipeline.stage("t-stage", "enrich", "42", work)
    b = pipeline.stage("t-stage", "enrich", "42", work)
    assert a == b == {"v": 1} and n["calls"] == 1


# ----------------------------------------------------------------- input validation
@pytest.mark.parametrize("text", ["", "   ", "find partners", "x" * 5000, "!!! ??? 123 456 789 000 111 222 333 444"])
def test_invalid_requests_are_rejected(text):
    assert not validation.validate_request(text).ok


def test_request_that_asks_for_automatic_outreach_is_rejected():
    v = validation.validate_request("We sell payments software in India. Find resellers and email them automatically without approval.")
    assert not v.ok and any("never contacts" in e for e in v.errors)


def test_missing_geography_asks_for_clarification():
    v = validation.validate_request("We sell a cybersecurity platform to banks. Find reseller partners for our product line.")
    assert not v.ok and any("country" in q for q in v.clarifications)


def test_demo_request_is_valid():
    assert validation.validate_request(pipeline.DEMO_REQUEST).ok


def test_rejected_request_spends_nothing(monkeypatch):
    monkeypatch.setattr(crustdata.Crustdata, "__init__", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be created")))
    with pytest.raises(pipeline.InvalidRequest):
        pipeline.run("t-rejected", "too short")
    assert store.query("SELECT status FROM runs WHERE run_id='t-rejected'")[0]["status"] == "rejected"
    assert store.query("SELECT 1 FROM calls WHERE run_id='t-rejected'") == []


# ----------------------------------------------------------------- source classification and canonical URLs
def test_source_classes():
    c = ev.classify_source
    assert c("https://www.zaubacorp.com/x", "search_snippet", "acme.com") == ("third_party_business_database", "database_listing")
    assert c("https://acme.com/about", "search_snippet", "acme.com") == ("official_company_source", "self_reported")
    assert c("https://blog.acme.com/x", "news", "acme.com")[1] == "self_reported"
    assert c("https://www.livemint.com/a", "news", "acme.com") == ("independent_news_source", "independent")
    assert c("https://www.rbi.org.in/x", "news", "acme.com") == ("official_regulatory_source", "independent")
    assert c("https://random-blog.example/x", "search_snippet", "acme.com")[1] == "weak"
    assert c("https://www.linkedin.com/company/acme", "search_snippet", "acme.com") == ("company_social_profile", "self_reported")  # self-published
    assert c("crustdata:company/1", "crustdata_api", "acme.com")[1] == "api_record"


class FakeRedirectSession:
    """SIMULATED redirect chain for the canonical-URL resolver."""

    def __init__(self, chain):
        self.chain, self.requested = dict(chain), []

    def get(self, url, allow_redirects=False, timeout=None, headers=None):
        assert allow_redirects is False
        self.requested.append(url)
        nxt = self.chain.get(url)
        if nxt is None:
            return FakeResp(404, {}, {})
        return FakeResp(302, {}, {"location": nxt})


def test_canonical_url_follows_only_google_redirects_and_never_fetches_the_destination():
    s = FakeRedirectSession({"https://www.google.com/goto?url=AAA": "https://tracxn.com/d/x?utm_source=g&id=7"})
    out = ev.canonicalize("https://www.google.com/goto?url=AAA", session=s)
    assert out == "https://tracxn.com/d/x?id=7"
    assert s.requested == ["https://www.google.com/goto?url=AAA"]  # the destination page was not requested


def test_canonical_url_unresolvable_returns_none_not_a_guess():
    assert ev.canonicalize("https://www.google.com/goto?url=ZZZ", session=FakeRedirectSession({})) is None


def test_canonical_url_rejects_non_http_redirect_targets():
    s = FakeRedirectSession({"https://www.google.com/goto?url=B": "javascript:alert(1)"})
    assert ev.canonicalize("https://www.google.com/goto?url=B", session=s) is None


def test_direct_url_passes_through_without_any_request():
    class Boom:
        def get(self, *a, **k):
            raise AssertionError("no request expected")
    assert ev.canonicalize("https://example.com/a?utm_medium=x", session=Boom()) == "https://example.com/a"


# ----------------------------------------------------------------- source-quality-aware confidence
def _claim(i, cat, corro, org, status="verified", notes=None):
    return {"claim_id": f"c{i}", "category": cat, "status": status, "corroboration": corro, "source_org": org, "notes": notes, "confidence": "medium"}


def test_company_marketing_alone_cannot_reach_high_confidence():
    claims = [_claim(i, "capability" if i % 2 else "bfsi_presence", "self_reported", "acme.com", notes="Self-reported on the company's own website.") for i in range(8)]
    assert scoring.evidence_confidence(claims)["level"] != "High"


def test_one_directory_site_repeated_does_not_add_up_to_high():
    claims = [_claim(i, "capability" if i % 2 else "bfsi_presence", "database_listing", "tracxn.com") for i in range(8)]
    assert scoring.evidence_confidence(claims)["level"] != "High"


def test_independent_news_or_regulatory_source_can_reach_high():
    claims = [_claim(i, "capability" if i % 2 else "bfsi_presence", "self_reported", "acme.com") for i in range(7)]
    claims.append(_claim(9, "bfsi_presence", "independent", "livemint.com"))
    assert scoring.evidence_confidence(claims)["level"] == "High"


def test_evidence_rows_keep_source_class_and_canonical_url():
    src = ev.Source("S1", "search_snippet", "https://www.google.com/goto?url=Q", "third-party search result",
                    "Acme Bank Services serves leading banks. Acme secures banks.", "t")
    src.canonical_url = "https://www.zaubacorp.com/acme"
    rows = ev.check_claims("t-ev", "9", [{"category": "bfsi_presence", "claim": "Acme serves banks", "source_id": "S1", "quote": "Acme secures banks"}], {"S1": src}, "acme.com")
    r = rows[0]
    assert r["status"] == "verified" and r["canonical_url"].endswith("/acme") and r["source_class"] == "third_party_business_database"
    assert r["corroboration"] == "database_listing" and "not strong corroboration" in r["notes"]
    saved = store.query("SELECT canonical_url, source_class, source_org FROM evidence WHERE claim_id='9-c1' AND run_id='t-ev'")[0]
    assert saved["source_org"] == "zaubacorp.com"


# ----------------------------------------------------------------- decision-maker fallback
def test_person_filter_keeps_only_senior_relevant_titles_and_never_invents():
    profs = [{"crustdata_person_id": 1, "basic_profile": {"name": "A One", "current_title": "Research And Development Specialist"}},
             {"crustdata_person_id": 2, "basic_profile": {"name": "B Two", "current_title": "Head of Partnerships and Alliances"}},
             {"crustdata_person_id": 3, "basic_profile": {"name": "C Three", "current_title": "Co-Founder & CEO"}},
             {"crustdata_person_id": 4, "basic_profile": {"name": "", "current_title": "Director"}},
             {"crustdata_person_id": 5, "basic_profile": {"name": "E Five", "current_title": None}}]
    out = pipeline.pick_decision_makers(profs)
    assert [p["id"] for p in out] == [2, 3]  # partnership role first, then the top executive; the specialist is excluded
    assert all(set(p) == {"id", "name", "title", "source"} for p in out)  # name, title, id only


def test_person_fallback_not_used_when_company_record_already_has_people():
    class NoCall:
        def person_search_company(self, *a, **k):
            raise AssertionError("must not call Person Search")
    assert pipeline.find_people(NoCall(), 1, {"decision_makers": [{"id": 1}]}) == {"used": False, "people": [], "n_returned": 0}


# ----------------------------------------------------------------- ranking determinism
BRIEF = {"requester": {"offering": "a cybersecurity SaaS platform"}, "objective": "expand distribution to banks",
         "target_industry": "Banking and financial services", "required_capabilities": ["managed security services", "compliance expertise"], "country": "India"}


def _cands():
    return [{"id": 1, "name": "SecureBank MSSP", "description": "Managed security service provider (MSSP) and system integrator for banks, NBFCs and insurance companies. SOC, SIEM and compliance services.", "size": "51-200"},
            {"id": 2, "name": "Rupee Wealth Platform", "description": "We build wealth and lending software for fintechs and NBFCs with a modern cloud platform for mutual fund distributors.", "size": "11-50"},
            {"id": 3, "name": "Trade Forum of India", "description": "An association and industry forum for banks and financial institutions across India.", "size": "11-50"},
            {"id": 4, "name": "Tiny Shop", "description": "", "size": "1-10"}]


def test_prescore_is_deterministic_and_discriminates():
    a = [ranking.prescore(BRIEF, c)["prescore"] for c in _cands()]
    b = [ranking.prescore(BRIEF, c)["prescore"] for c in _cands()]
    assert a == b
    assert a[0] > a[1] > a[3] and a[0] > a[2]  # the security MSSP beats a fintech software firm, an association and an empty record


def test_ordering_is_independent_of_input_order_and_model_noise():
    base = []
    for pos, c in enumerate(_cands()):
        pre = ranking.prescore(BRIEF, c)
        llm = {"serves_target": "likely", "sells_competing_product": "no", "partner_type": "channel"}
        base.append({**c, "_pos": pos, "composite": ranking.composite(pre, llm)})
    order1 = [c["id"] for c in ranking.order(base)]
    order2 = [c["id"] for c in ranking.order(list(reversed(base)))]
    assert order1 == order2 and order1[0] == 1


def test_not_a_partner_judgement_removes_an_association_from_the_top():
    pre = ranking.prescore(BRIEF, _cands()[2])
    assert ranking.composite(pre, {"partner_type": "not_a_partner", "serves_target": "no"}) < ranking.composite(pre, {"partner_type": "channel", "serves_target": "yes"})


# ----------------------------------------------------------------- relationship dimensions / direct competition override
def test_verified_direct_competitor_forces_manual_review_even_with_a_high_score():
    flags = scoring.review_flags(1.0, True, 0, "high", False, direct_competitor=True)
    assert scoring.recommendation(92.0, "High", flags) == "Manual review before any approach"


def test_unverified_direct_competition_claim_does_not_trigger_the_override():
    flags = scoring.review_flags(1.0, True, 0, "medium", False, direct_competitor=False)
    assert scoring.recommendation(92.0, "High", flags).startswith("Approach with caution")


def test_annotate_claims_labels_old_rows_without_network_access():
    claims = [{"claim_id": "1", "status": "verified", "category": "capability", "source_url": "https://www.zaubacorp.com/x", "notes": None},
              {"claim_id": "2", "status": "verified", "category": "capability", "source_url": "https://www.google.com/goto?url=ABC", "notes": None},
              {"claim_id": "3", "status": "unverified", "category": "capability", "source_url": None, "notes": None}]
    out = ev.annotate_claims(claims, "acme.com")
    assert [c["corroboration"] for c in out] == ["database_listing", "weak", "unverified"]  # an unresolved redirect is 'weak', never strong


# ----------------------------------------------------------------- evidence ledger isolation between runs (bug found in the audit)
def test_same_claim_id_in_two_runs_does_not_overwrite_the_earlier_run():
    base = {"company_id": "77", "category": "capability", "claim": "x", "source_url": "u", "source_ref": "r", "quote": "q", "published_at": None,
            "retrieved_at": "2026-11-22", "status": "verified", "confidence": "medium", "agent": "a", "notes": None}
    store.put_evidence({**base, "claim_id": "77-c1", "run_id": "t-iso-a", "claim": "from run A"})
    store.put_evidence({**base, "claim_id": "77-c1", "run_id": "t-iso-b", "claim": "from run B"})
    rows = {r["run_id"]: r["claim"] for r in store.query("SELECT run_id, claim FROM evidence WHERE claim_id='77-c1'")}
    assert rows == {"t-iso-a": "from run A", "t-iso-b": "from run B"}
