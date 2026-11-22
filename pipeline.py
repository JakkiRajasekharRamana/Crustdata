"""PartnerScout orchestrator: DISCOVER -> INVESTIGATE -> VERIFY -> EVALUATE -> RECOMMEND.

One orchestrator, five agent roles. Each role is a prompted function over a shared LLM (llm.ask_json)
plus its own tools. Every stage output is checkpointed in SQLite keyed by (run_id, stage, item), so a
crash or a rate-limit stop resumes where it stopped and never repeats a paid call.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import uuid

import evidence as ev
import llm
import scoring
import store
from crustdata import BudgetExceeded, CreditsExhausted, Crustdata, CrustdataError

DEMO_REQUEST = (
    "We are a cybersecurity SaaS company looking to expand our distribution in India's banking and "
    "financial services sector. Identify five potential channel or technology partners that already serve "
    "financial institutions. Investigate their capabilities, assess strategic compatibility, identify "
    "decision-makers and recommend the strongest partnership opportunities."
)


class SimulatedCrash(Exception):
    """Used by the demo (--crash-after) to prove resume: the process dies, a rerun continues."""


def log(run_id: str, msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
    store.put_stage(run_id, "_log", {"t": time.time(), "msg": msg}, item=f"{time.time():.4f}")


def norm_domain(d: str | None) -> str:
    return re.sub(r"^(https?://)?(www\.)?", "", (d or "").strip().lower()).split("/")[0]


def norm_name(n: str | None) -> str:
    n = (n or "").lower()
    n = re.sub(r"\b(pvt|private|ltd|limited|llp|inc|corp|corporation|india|technologies|technology|solutions|services)\b", " ", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def stage(run_id: str, name: str, item: str, fn, crash_after: str | None = None):
    """Run fn() once per (run, stage, item). A finished stage is returned from the checkpoint."""
    done = store.get_stage(run_id, name, item)
    if done is not None:
        return done
    out = fn()
    store.put_stage(run_id, name, out, item=item)
    return out


# ============================ Orchestrator: understand the request ============================
def parse_brief(run_id: str, request: str) -> dict:
    system = "You are the orchestrator of a partnership-research agent. Output JSON only."
    prompt = f"""Read this partnership request and extract structured requirements.
REQUEST: {request}

Return JSON:
{{"requester": {{"name": string|null, "offering": "one sentence on what the requester sells", "segment": string}},
 "objective": string, "target_industry": string, "country": "full country name for filtering, e.g. India",
 "partner_types": [string], "required_capabilities": [string],
 "n_partners": integer,
 "search_queries": [3 distinct natural-language company-search queries, each describing the KIND OF COMPANY to find
   (e.g. 'managed security service provider serving banks'), not the requester],
 "missing_info": [anything vague that a human should confirm]}}"""
    return llm.ask_json(run_id, "parse_brief", system, prompt)


# ============================ Agent 1: Partner Discovery ============================
def discover(run_id: str, cd: Crustdata, brief: dict, per_query: int = 25) -> list[dict]:
    seen: dict[str, dict] = {}
    fields = ["basic_info.name", "basic_info.primary_domain", "basic_info.description", "basic_info.company_type",
              "basic_info.year_founded", "basic_info.employee_count_range", "locations.country", "locations.city"]
    for q in brief["search_queries"][:3]:
        r = cd.company_search(query=q, filters={"field": "locations.country", "type": "=", "value": brief["country"]},
                              fields=fields, limit=per_query)
        for c in r.get("companies", []):
            bi = c.get("basic_info", {})
            dom, nm = norm_domain(bi.get("primary_domain")), norm_name(bi.get("name"))
            key = dom or nm
            if not key:
                continue
            # duplicate handling: same domain OR same normalised name collapses to one record
            dup = next((k for k, v in seen.items() if (dom and v["domain"] == dom) or (nm and norm_name(v["name"]) == nm)), None)
            if dup:
                seen[dup]["found_by"].append(q)
                continue
            seen[key] = {"id": c["crustdata_company_id"], "name": bi.get("name"), "domain": dom,
                         "description": (bi.get("description") or "")[:900], "size": bi.get("employee_count_range"),
                         "year_founded": bi.get("year_founded"), "city": (c.get("locations") or {}).get("city"),
                         "found_by": [q]}
    return list(seen.values())


def screen(run_id: str, brief: dict, cands: list[dict]) -> list[dict]:
    """Cheap relevance screen over search results (descriptions only). No verification yet."""
    system = "You screen companies as potential strategic partners. Be skeptical and literal. JSON only."
    results = []
    for i in range(0, len(cands), 20):
        batch = cands[i:i + 20]
        listing = "\n".join(f'- id={c["id"]} | {c["name"]} | size {c["size"]} | {c["description"][:450]}' for c in batch)
        prompt = f"""Requester: {brief['requester']['offering']}. Objective: {brief['objective']}
Wanted partner types: {brief['partner_types']}. Target: {brief['target_industry']} in {brief['country']}.
Capabilities needed: {brief['required_capabilities']}

For EACH company decide only from its description:
- partner_type: channel | technology | distribution | consulting | not_a_partner
- relevance: 0-100 (does it plausibly serve the target segment AND could resell/integrate/refer the requester's offering?)
  Companies that are physical security, staffing, unrelated industries, or have no evidence of serving the target = low.
  Trade associations, industry bodies, chambers, directories, media/publishers, training institutes, government bodies and
  investors are NOT partners that can resell or integrate: set partner_type = not_a_partner and relevance <= 20.
- serves_target: yes | likely | unknown | no
- sells_competing_product: yes | possible | no  (does it appear to sell its OWN product that competes with the requester's offering?)
- reason: one short sentence quoting the description wording you relied on

Companies:
{listing}

Return {{"screened": [{{"id": int, "partner_type": str, "relevance": int, "serves_target": str,
"sells_competing_product": str, "reason": str}}]}}"""
        out = llm.ask_json(run_id, "screen", system, prompt)
        results += out.get("screened", [])
    by_id = {c["id"]: c for c in cands}
    merged = []
    for s in results:
        if s.get("id") in by_id:
            merged.append({**by_id[s["id"]], **{k: s.get(k) for k in
                           ("partner_type", "relevance", "serves_target", "sells_competing_product", "reason")}})
    merged.sort(key=lambda x: -(x.get("relevance") or 0))
    return merged


# ============================ Agent 2: Company Intelligence ============================
def resolve_identity(cd: Crustdata, cand: dict) -> dict:
    """Company Identify on the domain: is this record the company we think it is?"""
    r = cd.company_identify(domains=[cand["domain"]])
    matches = (r[0].get("matches") if r else None) or []
    if not matches:
        return {"resolved": False, "confidence": None, "reason": "no match for domain"}
    m = matches[0]
    bi = m["company_data"]["basic_info"]
    return {"resolved": True, "confidence": m.get("confidence_score"), "crustdata_company_id": m["company_data"]["crustdata_company_id"],
            "name": bi.get("name"), "primary_domain": norm_domain(bi.get("primary_domain")), "status": bi.get("status"),
            "domain_match": norm_domain(bi.get("primary_domain")) == cand["domain"] or cand["domain"] in [norm_domain(x) for x in bi.get("all_domains", [])],
            "name_match": norm_name(bi.get("name")) == norm_name(cand["name"]),
            "n_matches": len(matches), "website": bi.get("website")}


def compact_enrichment(company_data: dict) -> dict:
    bi = company_data.get("basic_info", {})
    hc = company_data.get("headcount", {}) or {}
    ts = hc.get("timeseries") or []
    people = company_data.get("people", {}) or {}
    pick = lambda lst: [{"id": p.get("crustdata_person_id"), "name": (p.get("basic_profile") or {}).get("name"),
                         "title": (p.get("basic_profile") or {}).get("current_title")} for p in (lst or [])[:8]]
    return {"name": bi.get("name"), "domain": norm_domain(bi.get("primary_domain")), "description": bi.get("description"),
            "year_founded": bi.get("year_founded"), "status": bi.get("status"), "company_type": bi.get("company_type"),
            "employee_count_range": bi.get("employee_count_range"), "headcount_total": hc.get("total"),
            "headcount_first_point": ts[-27] if len(ts) > 27 else None, "headcount_last_point": ts[-1] if ts else None,
            "funding_total_usd": (company_data.get("funding") or {}).get("total_investment_usd"),
            "professional_url": bi.get("professional_network_url"),
            # Privacy: only name + title + id are kept for decision-makers. Bios/summaries are dropped.
            "decision_makers": pick(people.get("decision_makers")), "founders": pick(people.get("founders")),
            "cxos": pick(people.get("cxos"))}


def research_sources(run_id: str, cd: Crustdata, c: dict, enr: dict) -> dict[str, dict]:
    """Collect the corpus the model may cite. Nothing outside this corpus can become a verified claim."""
    sources: dict[str, ev.Source] = {}
    n = 0

    def add(kind, url, ref, text, title="", published=None):
        nonlocal n
        if not text or len(text) < 20:
            return
        n += 1
        sources[f"S{n}"] = ev.Source(f"S{n}", kind, url, ref, text, title, published)

    add("crustdata_api", f"crustdata:company/{c['id']}", "basic_info.description", enr.get("description") or "")
    # first-party website (real URL; the search engine only returns opaque redirect links)
    try:
        pages = cd.web_fetch([f"https://{c['domain']}"])
        for p in pages:
            if p.get("success") and p.get("content"):
                add("first_party", p["url"], "page text", ev.html_to_text(p["content"])[:9000], p.get("title", ""))
    except CrustdataError as e:
        log(run_id, f"  fetch failed for {c['domain']}: {e} (kept as unresolved, not as 'no information')")
    for label, q, srcs in (("third-party", f'"{c["name"]}" banks financial institutions India', ["news", "web"]),
                           ("adverse", f'"{c["name"]}" fraud OR lawsuit OR penalty OR breach OR complaint', ["news", "web"])):
        try:
            r = cd.web_search(q, sources=srcs, location=None)
            for hit in (r.get("results") or [])[:6]:
                add("news" if hit.get("source") == "news" else "search_snippet", hit.get("url", ""), f"{label} search result",
                    f'{hit.get("title","")}. {hit.get("snippet","")}', hit.get("title", ""))
        except CrustdataError as e:
            log(run_id, f"  {label} search failed for {c['name']}: {e}")
    return {k: v.to_json() for k, v in sources.items()}


def extract_claims(run_id: str, brief: dict, c: dict, sources: dict[str, dict]) -> list[dict]:
    """Verification Agent: model proposes claims WITH verbatim quotes; code checks the quotes."""
    objs = {k: ev.Source.from_json(v) for k, v in sources.items()}
    corpus = "\n\n".join(f"[{s.sid}] kind={s.kind} url={s.url}\n{s.text[:5000]}" for s in objs.values())
    system = ("You extract EVIDENCE-BACKED claims about one company. A claim needs a verbatim quote copied from the cited source. "
              "Never use outside knowledge. If a source does not say it, do not claim it. JSON only.")
    prompt = f"""Company: {c['name']} ({c['domain']}). We are assessing it as a partner for: {brief['requester']['offering']}
Target segment: {brief['target_industry']} in {brief['country']}.

SOURCES:
{corpus}

Extract up to 14 claims. Categories: capability | bfsi_presence | distribution_channel | technology_integration |
competing_product | leadership | adverse_media | identity | other.
- "competing_product": the company itself sells a product/platform that competes with the requester's offering.
- "adverse_media": only if a source reports fraud, penalty, lawsuit, breach or serious complaint ABOUT THIS company (not a namesake, not an industry article).
- "bfsi_presence": ONLY if a source says the company serves banks/financial institutions (name clients only if named).
- Sources of kind search_snippet/news may be about a different company with a similar name: skip them unless clearly this company.
Each claim: {{"category": str, "claim": "one factual sentence", "source_id": "S#", "quote": "verbatim contiguous text from that source, 15-250 chars"}}.
You may add up to 3 inferences {{"type":"inference","category":...,"claim":...}} (no quote) that follow from the claims.
Also list contradictions BETWEEN two sources, each side with its own verbatim quote:
"conflicts": [{{"description": str, "severity": "material" | "minor",
                "a": {{"source_id": "S#", "quote": "verbatim"}}, "b": {{"source_id": "S#", "quote": "verbatim"}}}}]
  material = the sources disagree about what the company IS, who owns it, whether it operates, its scale by an order of
             magnitude, or whether it sells a competing product.
  minor    = founding-year or rounding differences, different brand names of the same firm, wording differences.
Do not list a conflict unless both quotes really say different things about the same fact.
Return {{"claims": [...], "conflicts": [...]}}"""
    out = llm.ask_json(run_id, "extract_claims", system, prompt)
    rows = ev.check_claims(run_id, str(c["id"]), out.get("claims", []), objs)
    for i, cf in enumerate(out.get("conflicts", []) or []):
        # A conflict is recorded only if BOTH quotes are really present in their cited sources.
        try:
            qa, qb = cf["a"], cf["b"]
            ok = (qa["source_id"] in objs and qb["source_id"] in objs and qa["source_id"] != qb["source_id"]
                  and ev.verify_quote(qa["quote"], objs[qa["source_id"]].text) and ev.verify_quote(qb["quote"], objs[qb["source_id"]].text))
        except (KeyError, TypeError):
            ok = False
        if not ok or not cf.get("description"):
            continue
        material = cf.get("severity") == "material"
        row = {"claim_id": f"{c['id']}-x{i+1}", "run_id": run_id, "company_id": str(c["id"]), "category": "conflict",
               "claim": cf["description"], "source_url": objs[qa["source_id"]].url, "source_ref": f"{qa['source_id']} vs {qb['source_id']}",
               "quote": f'A: "{qa["quote"][:200]}" / B: "{qb["quote"][:200]}"', "published_at": None, "retrieved_at": ev.now_iso(),
               # material -> contradicted (hard manual-review flag); minor -> needs_review (shown, but not a hard flag)
               "status": "contradicted" if material else "needs_review", "confidence": "low", "agent": "verification",
               "notes": "Sources disagree on a material fact; needs human review." if material else "Minor discrepancy between sources; noted, not blocking."}
        store.execute("INSERT OR REPLACE INTO evidence VALUES (:claim_id,:run_id,:company_id,:category,:claim,:source_url,"
                      ":source_ref,:quote,:published_at,:retrieved_at,:status,:confidence,:agent,:notes)", row)
        rows.append(row)
    return rows


def api_facts(run_id: str, c: dict, enr: dict, ident: dict) -> list[dict]:
    """Facts that come straight from API fields. The field value is the evidence."""
    cid, url, rows, n = str(c["id"]), f"crustdata:company/{c['id']}", [], 0

    def a(cat, claim, path, val):
        nonlocal n
        if val in (None, "", []):
            return
        n += 1
        rows.append(ev.api_claim(run_id, cid, n, cat, claim, path, val, url, agent="verification"))

    if ident.get("resolved"):
        a("identity", f"Identified as {ident['name']} (domain {ident['primary_domain']}), match confidence {ident['confidence']}",
          "company/identify.matches[0].confidence_score", ident["confidence"])
    a("identity", f"Registered company status: {enr.get('status')}", "basic_info.status", enr.get("status"))
    a("capability", f"Founded in {enr.get('year_founded')}", "basic_info.year_founded", enr.get("year_founded"))
    a("capability", f"Headcount about {enr.get('headcount_total')} (range {enr.get('employee_count_range')})", "headcount.total", enr.get("headcount_total"))
    for p in (enr.get("decision_makers") or [])[:4]:
        a("leadership", f"{p['name']} is listed as {p['title']}", "people.decision_makers[].basic_profile.current_title",
          f"{p['name']} - {p['title']}")
    return rows


# ============================ Agent 4/5: Strategic Fit + Partnership Strategist ============================
def assess(run_id: str, brief: dict, c: dict, enr: dict, claims: list[dict]) -> dict:
    usable = [x for x in claims if x.get("status") in ("verified", "inferred", "contradicted")]
    listing = "\n".join(
        f'- {x["claim_id"]} [{x["category"]}/{x["status"]}]'
        f'{" (SELF-REPORTED on own website - not independent proof)" if str(x.get("notes") or "").startswith("Self-reported") else ""} {x["claim"]}'
        for x in usable) or "(no verified claims)"
    people = [p for p in (enr.get("decision_makers") or [])] + [p for p in (enr.get("founders") or [])]
    people_txt = "\n".join(f'- person_id={p["id"]}: {p["name"]}, {p["title"]}' for p in people[:8]) or "(none found)"
    system = ("You are a strategic partnerships analyst. You may ONLY rely on the listed claims; cite claim ids. "
              "Missing evidence is UNKNOWN (score null), never zero and never negative. Mutual value is a hypothesis, "
              "not proof the partner is willing. Industry presence is NOT verified distribution capability: a company saying it "
              "'focuses on BFSI' is self-reported marketing, so word it as 'states that it ...' and keep market_access modest "
              "(<=70) unless a non-self-reported claim shows named clients or channel reach. JSON only.")
    prompt = f"""Requester offering: {brief['requester']['offering']}
Objective: {brief['objective']}. Target: {brief['target_industry']}, {brief['country']}.
Partner: {c['name']} ({c['domain']}), partner_type guess: {c.get('partner_type')}.

CLAIMS (the only facts you may use):
{listing}

DECISION-MAKERS from the API record (choose ONLY from these):
{people_txt}

Return JSON:
{{"components": {{
   "strategic": {{"score": 0-100|null, "why": str, "claim_ids": [..]}},   // complementarity: complementary not overlapping, customer overlap
   "capability": {{"score": 0-100|null, "why": str, "claim_ids": [..]}},  // can it actually deliver what the objective needs
   "market_access": {{"score": 0-100|null, "why": str, "claim_ids": [..]}}, // verified access to the target segment/distribution
   "feasibility": {{"score": 0-100|null, "why": str, "claim_ids": [..]}}}}, // size, stage, plausibility of a deal
 "competitive_overlap": {{"level": "none|low|medium|high", "why": str, "claim_ids": [..]}},
   // high = partner sells its own product that competes with the requester's offering (cite the competing_product claim)
 "mutual_value": {{"to_requester": [{{"point": str, "claim_ids": [..], "basis": "verified|inferred"}}],
                   "to_partner":   [{{"point": str, "claim_ids": [..], "basis": "verified|inferred"}}],
                   "rationale": str}},
 "partnership_model": {{"model": "reseller|referral|technology_integration|co-sell|MSSP_bundle|white_label|none", "why": str}},
 "stakeholder": {{"person_id": int|null, "why": str}},
 "open_questions": [str],  // what a human must still establish
 "proposal": {{"subject": str, "body": "short, specific, only verified facts, no promises, no invented relationship; sign as '[Your name], [Requester]'"}}}}"""
    return llm.ask_json(run_id, f"assess:{c['id']}", system, prompt)


def finalise(run_id: str, brief: dict, c: dict, enr: dict, ident: dict, claims: list[dict], a: dict) -> dict:
    by_id = {x["claim_id"]: x for x in claims}
    contradictions = sum(1 for x in claims if x["status"] == "contradicted")
    adverse = sum(1 for x in claims if x["category"] == "adverse_media" and x["status"] == "verified")
    comps = a.get("components", {})
    # Drop any citation to a claim id that does not exist: a citation must point at a real ledger row.
    for comp in comps.values():
        comp["claim_ids"] = [i for i in comp.get("claim_ids", []) if i in by_id]
    overlap = a.get("competitive_overlap", {}) or {}
    overlap["claim_ids"] = [i for i in overlap.get("claim_ids", []) if i in by_id]
    level = overlap.get("level", "none")
    if level == "high" and not any(by_id[i]["status"] == "verified" for i in overlap["claim_ids"]):
        overlap["level"] = level = "medium"  # a "high" conflict needs a verified claim behind it
        overlap["why"] = (overlap.get("why") or "") + " (downgraded: competing product not verified by a source)"
    trust = scoring.trust_score(ident.get("confidence"), ident.get("status") == "active" or enr.get("status") == "active",
                                ident.get("domain_match"), adverse, contradictions)
    comps["trust"] = {"score": trust, "why": "Computed from identity confidence, domain consistency, status, adverse media and contradictions.",
                      "claim_ids": [i for i, x in by_id.items() if x["category"] == "identity"]}
    fit = scoring.compute_fit(comps, level)
    conf = scoring.evidence_confidence(claims)
    key_unverified = not any(x["category"] == "bfsi_presence" and x["status"] == "verified" for x in claims)
    flags = scoring.review_flags(ident.get("confidence"), ident.get("domain_match"), contradictions, level, key_unverified)
    person = next((p for p in (enr.get("decision_makers") or []) + (enr.get("founders") or []) if p["id"] == (a.get("stakeholder") or {}).get("person_id")), None)
    return {"company": {"id": c["id"], "name": enr.get("name") or c["name"], "domain": c["domain"], "city": c.get("city"),
                        "size": enr.get("employee_count_range"), "description": (enr.get("description") or "")[:600],
                        "partner_type": c.get("partner_type"), "screen_relevance": c.get("relevance")},
            "identity": ident, "fit": fit, "components": comps, "evidence_confidence": conf, "flags": flags,
            "recommendation": scoring.recommendation(fit["score"], conf["level"], flags),
            "competitive_overlap": overlap, "mutual_value": a.get("mutual_value"), "partnership_model": a.get("partnership_model"),
            "stakeholder": {**(person or {}), "why": (a.get("stakeholder") or {}).get("why")} if person else None,
            "open_questions": a.get("open_questions", []), "proposal": {**(a.get("proposal") or {}), "status": "DRAFT - not sent. Requires human approval."},
            "claims": claims}


# ============================ Orchestration ============================
def run(run_id: str, request: str, *, n_report: int = 5, shortlist: int = 6, crash_after: str | None = None,
        credit_ceiling: float | None = None) -> dict:
    store.create_run(run_id, request)
    cd = Crustdata(run_id, credit_ceiling=credit_ceiling)
    log(run_id, f"run {run_id}: credits available {cd.balance():.1f}; ceiling {cd.credit_ceiling}")

    def checkpoint(name):
        if crash_after == name:
            raise SimulatedCrash(f"simulated crash after stage '{name}'")

    try:
        brief = stage(run_id, "brief", "_", lambda: parse_brief(run_id, request))
        log(run_id, f"[orchestrator] brief understood: {brief['partner_types']} in {brief['country']}")
        if brief.get("missing_info"):
            log(run_id, f"[orchestrator] noted for a human: {brief['missing_info']}")
        checkpoint("brief")

        cands = stage(run_id, "discover", "_", lambda: discover(run_id, cd, brief))
        log(run_id, f"[discovery] {len(cands)} unique candidates after duplicate resolution")
        checkpoint("discover")

        screened = stage(run_id, "screen", "_", lambda: screen(run_id, brief, cands))
        short = [c for c in screened if c.get("domain") and c.get("partner_type") != "not_a_partner"][:shortlist]
        log(run_id, "[discovery] shortlist: " + ", ".join(f'{c["name"]} ({c.get("relevance")})' for c in short))
        checkpoint("screen")

        results = {}
        for c in short:
            cid = str(c["id"])
            log(run_id, f"[intelligence] {c['name']}")
            try:
                ident = stage(run_id, "identity", cid, lambda: resolve_identity(cd, c))
                checkpoint("identity")
                enr_raw = stage(run_id, "enrich", cid, lambda: compact_enrichment(
                    (cd.company_enrich(domains=[c["domain"]], fields=["basic_info", "headcount", "funding", "people"])[0]["matches"] or [{}])[0].get("company_data", {})))
                checkpoint("enrich")
                sources = stage(run_id, "research", cid, lambda: research_sources(run_id, cd, c, enr_raw))
                checkpoint("research")
                claims = stage(run_id, "claims", cid, lambda: api_facts(run_id, c, enr_raw, ident) + extract_claims(run_id, brief, c, sources))
                log(run_id, f"[verification] {c['name']}: {sum(1 for x in claims if x['status']=='verified')} verified / {len(claims)} claims")
                checkpoint("claims")
                a = stage(run_id, "assess", cid, lambda: assess(run_id, brief, c, enr_raw, claims))
                results[cid] = stage(run_id, "result", cid, lambda: finalise(run_id, brief, c, enr_raw, ident, claims, a))
                log(run_id, f"[fit] {c['name']}: {results[cid]['fit']['score']} | confidence {results[cid]['evidence_confidence']['level']} | {results[cid]['recommendation']}")
            except (SimulatedCrash, BudgetExceeded, CreditsExhausted):
                raise
            except (CrustdataError, llm.LLMError, KeyError, IndexError, TypeError) as e:
                # A failure is never read as "nothing exists": the candidate is held for a person.
                log(run_id, f"[recovery] {c['name']} held for review: {type(e).__name__}: {str(e)[:160]}")
                results[cid] = store.get_stage(run_id, "result", cid) or {"company": {"id": c["id"], "name": c["name"], "domain": c["domain"]},
                                                                         "held_for_review": True, "error": str(e)[:300],
                                                                         "recommendation": "Held for review - data collection failed", "flags": ["Tool failure - not treated as absence of evidence"],
                                                                         "fit": {"score": None}, "claims": []}
                store.put_stage(run_id, "result", results[cid], item=cid)

        ranked = sorted(results.values(), key=lambda r: (r.get("fit", {}).get("score") is None, -(r.get("fit", {}).get("score") or 0)))
        final = {"run_id": run_id, "request": request, "brief": brief, "ranked": ranked[:max(n_report, 1)] + ranked[max(n_report, 1):],
                 "n_candidates": len(cands), "ledger": store.ledger_totals(run_id)}
        store.put_stage(run_id, "final", final)
        store.set_run_status(run_id, "complete")
        log(run_id, f"[done] ledger: {final['ledger']}")
        return final
    except SimulatedCrash as e:
        store.set_run_status(run_id, "crashed", str(e))
        log(run_id, f"[crash] {e}. Re-run with the same --run-id to resume.")
        raise
    except BudgetExceeded as e:
        store.set_run_status(run_id, "paused_budget", str(e))
        log(run_id, f"[paused] {e}. Resume with a higher ceiling.")
        raise
    except CreditsExhausted as e:
        store.set_run_status(run_id, "paused_credits", str(e))
        log(run_id, "[paused] out of credits (402). Retrying will not help; resume after topping up.")
        raise


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", default=DEMO_REQUEST)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--crash-after", default=None, help="brief|discover|screen|identity|enrich|research|claims")
    ap.add_argument("--credit-ceiling", type=float, default=None)
    ap.add_argument("--shortlist", type=int, default=6)
    args = ap.parse_args()
    rid = args.run_id or f"run-{uuid.uuid4().hex[:8]}"
    print("run id:", rid)
    try:
        run(rid, args.request, crash_after=args.crash_after, credit_ceiling=args.credit_ceiling, shortlist=args.shortlist)
    except (SimulatedCrash, BudgetExceeded, CreditsExhausted):
        raise SystemExit(2)  # already logged and recorded in the runs table; resumable with the same --run-id
