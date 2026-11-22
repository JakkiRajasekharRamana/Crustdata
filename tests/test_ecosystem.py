"""Ecosystem map and pipeline tests. Fixtures are SYNTHETIC (invented companies written into a temporary test database);
they are not Crustdata data and are never mixed with real run data."""
import time

import pytest

import ecosystem
import store

RUN = "t-eco-synthetic"


@pytest.fixture(scope="module", autouse=True)
def synthetic_run():
    cands = [
        {"id": 1, "name": "Alpha Secure", "domain": "alpha.test", "description": "Managed security provider and system integrator for banks and NBFCs.", "size": "51-200", "city": "Mumbai"},
        {"id": 2, "name": "Beta Pay", "domain": "beta.test", "description": "Payments fintech platform.", "size": "11-50", "city": "Bengaluru Urban"},
        {"id": 3, "name": "Gamma Unknown", "domain": "gamma.test", "description": "We do things.", "size": "2-10", "city": "Millenium Business Park"},
        {"id": 4, "name": "Delta Nowhere", "domain": "delta.test", "description": "Insurance consulting.", "size": "11-50", "city": "Atlantis Lane"},
        {"id": 5, "name": "Epsilon Held", "domain": "eps.test", "description": "Cloud infrastructure.", "size": "51-200", "city": "Pune"},
    ]
    store.put_stage(RUN, "discover", cands)
    store.put_stage(RUN, "screen", [{**c, "partner_type": "channel" if c["id"] == 1 else None, "composite": 80.0 - c["id"], "relevance": 80.0 - c["id"]} for c in cands])
    ranked = [
        {"company": {"id": 1, "name": "Alpha Secure", "domain": "alpha.test", "city": "Mumbai", "size": "51-200", "description": "Managed security provider.", "partner_type": "channel"},
         "fit": {"score": 81.0}, "recommendation": "Pursue", "evidence_confidence": {"level": "Medium"}, "claims": [], "proposal": {"subject": "s", "body": "b"}},
        {"company": {"id": 2, "name": "Beta Pay", "domain": "beta.test", "city": "Bengaluru Urban", "size": "11-50", "description": "Payments."},
         "fit": {"score": 40.0}, "recommendation": "Deprioritise", "evidence_confidence": {"level": "Medium"}, "claims": []},
        {"company": {"id": 5, "name": "Epsilon Held", "domain": "eps.test"}, "held_for_review": True, "fit": {"score": None}, "claims": []},
    ]
    store.put_stage(RUN, "final", {"run_id": RUN, "ranked": ranked, "n_candidates": 5, "brief": {}, "ledger": {}})
    store.put_stage(RUN, "identity", {"resolved": True}, item="5")
    store.execute("DELETE FROM pipeline_stages WHERE run_id=?", (RUN,))
    store.execute("DELETE FROM approvals WHERE run_id=?", (RUN,))


def by_name():
    return {c["name"]: c for c in ecosystem.build_companies(RUN)}


def test_every_discovered_company_is_listed_once_and_stages_are_derived_from_the_run():
    cs = by_name()
    assert len(cs) == 5
    assert cs["Alpha Secure"]["stage"] == "Shortlisted"      # investigated and recommended
    assert cs["Beta Pay"]["stage"] == "Verified"             # investigated, not recommended
    assert cs["Epsilon Held"]["stage"] == "Investigating"    # a tool failed: never silently treated as "nothing found"
    assert cs["Gamma Unknown"]["stage"] == "Discovered"


def test_locations_are_matched_from_saved_text_and_never_guessed():
    cs = by_name()
    assert cs["Alpha Secure"]["location"][0] == "Mumbai"
    assert cs["Beta Pay"]["location"][0] == "Bengaluru"
    assert cs["Gamma Unknown"]["location"][0] == "Navi Mumbai"     # "Millenium Business Park" is a known Navi Mumbai locality
    assert cs["Delta Nowhere"]["location"] is None                  # unknown place: not drawn
    pts, skipped = ecosystem.map_points(list(cs.values()))
    assert skipped == 1 and "Delta Nowhere" not in {p["name"] for p in pts}


def test_fit_exists_only_for_investigated_companies_and_screening_relevance_is_kept_separate():
    cs = by_name()
    assert cs["Alpha Secure"]["fit"] == 81.0
    assert cs["Gamma Unknown"]["fit"] is None and cs["Gamma Unknown"]["screen_relevance"] is not None
    assert cs["Epsilon Held"]["fit"] is None


def test_filters_geography_signals_type_and_fit():
    cs = list(by_name().values())
    assert {c["name"] for c in ecosystem.filter_companies(cs, cities=["Mumbai"])} == {"Alpha Secure"}
    assert {c["name"] for c in ecosystem.filter_companies(cs, cities=[ecosystem.NOT_MAPPABLE])} == {"Delta Nowhere"}
    assert "Alpha Secure" in {c["name"] for c in ecosystem.filter_companies(cs, signals=["Cybersecurity"])}
    assert {c["name"] for c in ecosystem.filter_companies(cs, ptypes=["channel"])} == {"Alpha Secure"}
    scored_only = ecosystem.filter_companies(cs, fit_range=(50, 100), include_unscored=False)
    assert {c["name"] for c in scored_only} == {"Alpha Secure"}
    assert len(ecosystem.filter_companies(cs, fit_range=(50, 100), include_unscored=True)) == 4  # all but the low-fit Beta Pay


def test_industry_signals_come_from_the_description_only():
    assert "Insurance" in ecosystem.signals_for("Insurance consulting")
    assert ecosystem.signals_for("We do things.") == []


def test_a_stage_set_by_a_person_is_saved_in_sqlite_and_can_be_reset():
    ecosystem.set_stage(RUN, "3", "Archived", "not relevant")
    assert by_name()["Gamma Unknown"]["stage"] == "Archived" and by_name()["Gamma Unknown"]["stage_set_by_person"]
    row = store.query("SELECT stage, note FROM pipeline_stages WHERE run_id=? AND company_id='3'", (RUN,))[0]
    assert (row["stage"], row["note"]) == ("Archived", "not relevant")
    ecosystem.clear_stage(RUN, "3")
    assert by_name()["Gamma Unknown"]["stage"] == "Discovered"


def test_unknown_stage_is_rejected():
    with pytest.raises(ValueError):
        ecosystem.set_stage(RUN, "3", "Sent")  # there is no "sent" stage: PartnerScout never sends outreach


def test_approval_moves_a_company_to_approved_and_sends_nothing():
    store.execute("INSERT INTO approvals(run_id,company_id,action,ts,note) VALUES (?,?,?,?,?)", (RUN, "1", "approve_draft", time.time(), "recorded only; nothing sent"))
    assert by_name()["Alpha Secure"]["stage"] == "Approved"
    assert "Sent" not in ecosystem.STAGES and "Contacted" not in ecosystem.STAGES


def test_sort_is_deterministic_and_puts_investigated_partners_first():
    cs = list(by_name().values())
    assert [c["name"] for c in sorted(cs, key=ecosystem.sort_key)] == [c["name"] for c in sorted(reversed(cs), key=ecosystem.sort_key)]
    assert sorted(cs, key=ecosystem.sort_key)[0]["name"] == "Alpha Secure"
