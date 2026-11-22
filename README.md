# PartnerScout

**An agent that discovers, evaluates and ranks strategic business partners, verifies their capabilities, identifies mutual business opportunities and generates evidence-backed partnership recommendations.**

Built for ContextCon 05 (BITS Pilani x Crustdata), theme *Services, Replaced*, combining **Revenue** (primary), **Research and markets** and **Trust and compliance**.

## 1. The service it replaces

| | |
|---|---|
| **Service** | Strategic partnership research: finding, vetting and prioritising channel, reseller and technology partners. |
| **Who does it today** | Corporate-development and partnerships teams, business-development agencies, and strategy consultancies. |
| **Who pays** | B2B SaaS and technology companies entering a new industry or geography, which pay for weeks of analyst time per shortlist. |
| **The job PartnerScout completes** | One request in, a decision-ready partnership brief out: ranked partners, verified facts, the competitive-conflict check, mutual-value analysis, the right stakeholder and a draft first message, all with sources. |

It is deliberately **not** a lead-generation or outbound-sales tool. Lead tools answer "who could buy?". PartnerScout answers "which relationships are worth pursuing, why would they work for **both** sides, and what could make them a bad idea?".

## 2. What it does now

`DISCOVER -> INVESTIGATE -> VERIFY -> EVALUATE -> RECOMMEND`

1. **Orchestrator** turns a natural-language request into a structured brief (partner types, target segment, capabilities, search plan) and notes what a human should confirm.
2. **Partner Discovery** runs ranked Crustdata company searches, collapses duplicates (domain and normalised name) and screens for relevance.
3. **Company Intelligence** resolves identity (`/company/identify`), enriches (`/company/enrich`: headcount, funding, key people), fetches the company's own website and searches news and adverse media.
4. **Trust and Verification** extracts claims with **verbatim quotes**. Code checks every quote against the source text. Unsupported claims become *"I can't verify this from the available sources"*. Disagreeing sources force manual review.
5. **Strategic Fit** scores four explainable components, adds a computed trust component, applies a visible conflict penalty and writes the **Mutual Value Analysis**.
6. **Partnership Strategist** proposes a model (reseller, referral, integration...), picks a decision-maker **only from the API record**, and writes a proposal **draft**.

### Where a person is still required
* Approving any outreach. Drafts are never sent; the approve button only records intent (`approvals` table).
* Confirming vague parts of the brief (e.g. the requester's exact product niche).
* Any candidate flagged *manual review* (unresolved identity, conflicting sources) or *held for review* (a tool failed).
* Confirming real partner interest. Mutual value is a hypothesis, never evidence of willingness.

## 3. How it is built

See [docs/architecture.md](docs/architecture.md) for the diagram.

* One **orchestrator** plus five agent roles. They are prompted functions over one shared model, not five separate systems (simpler, cheaper, easier to test).
* **Crustdata** (`crustdata.py`): every call goes through one client that rate-limits to the key's real per-endpoint limits, retries 429s using `x-ratelimit-reset`, treats 402 as fatal, enforces a credit and time ceiling *before* each call, caches raw responses and logs the `X-Credits-Used` of each call.
* **Model**: Gemini (free tier) through `llm.py`, behind one function, with model rotation on overload. Model calls land in the same ledger.
* **State**: SQLite (call ledger, response cache, stage checkpoints, evidence ledger, approvals).
* **UI**: Streamlit with four screens; **report**: self-contained HTML (print to PDF).

### Sources and checks
| Source | Used for |
|---|---|
| Crustdata `/company/search` | candidate discovery (ranked search, country filter) |
| Crustdata `/company/identify` | identity resolution, match confidence, domain consistency |
| Crustdata `/company/enrich` | profile, headcount, funding, decision-makers/founders |
| Crustdata `/web/enrich/live` | the candidate's own website (first-party claims, labelled self-reported) |
| Crustdata `/web/search/live` | third-party mentions and adverse media |

Privacy: for people we keep only name, title and the Crustdata id. Bios, summaries and contact details are discarded and never requested.

### Credit and cost ledger
Every call is stored in `calls` (endpoint, credits from `X-Credits-Used`, latency, retries, cache hit, estimated model cost). The Workspace screen shows it live and the report footer states the run total. See section 6 for measured numbers.

## 4. Scoring

`Fit = 0.30 Strategic + 0.25 Capability + 0.20 Market access + 0.15 Trust + 0.10 Feasibility`

* Every component has a written reason and cites ledger claim ids.
* **Unknown is not zero**: an unestablished component is dropped and the other weights renormalised; evidence confidence falls instead.
* **Evidence confidence** (High/Medium/Low) is separate from fit. A high fit with low confidence is not presented as a firm recommendation.
* **Hard flags** (unresolved identity, domain mismatch, contradictions) override the number.
* **Competitive conflict** (a partner that sells its own competing product) is an explicit, shown penalty and changes the recommendation to "Approach with caution".
* The weights are design assumptions, not validated values.

## 5. Approaches considered

| Approach | Verdict |
|---|---|
| A. Plain LLM "who are good partners?" | Rejected: answers from model memory, no sources, invents partners. |
| B. Search + LLM summary | Rejected: cites pages that do not say the claim; no identity or conflict check. |
| C. Five independent LLM agents (LangGraph) | Rejected for a 7h45m build: more failure modes, harder resume, no accuracy gain. |
| D. **One orchestrator, staged pipeline, quote-verified evidence ledger** | **Chosen.** Deterministic checkpoints, verifiable claims, cheap to resume. |

What worked: quote verification (it catches fabricated "clients"), checkpointed stages (resume is free), renormalising unknown components. What did not: web-search URLs are opaque redirect links, so first-party evidence comes from fetching the company's own site; the free model tier is sometimes overloaded, hence model rotation.

## 6. Evaluation (measured, not claimed)

Sample request: *"We are a cybersecurity SaaS company looking to expand our distribution in India's banking and financial services sector. Identify five potential channel or technology partners..."* All companies below came from live Crustdata responses on 22 Nov 2026; nothing is mocked.

Reproduce the numbers with `python scripts/evaluate.py <run_id>`.

**Automated measurements (run `demo1`)**

| Metric | Result |
|---|---|
| Unique candidates discovered (after duplicate resolution) | 74 |
| Companies investigated end to end | 6 |
| Identity resolved (confidence >= 0.95, domain matches) | 6/6 |
| Duplicates in the shortlist | 0 |
| Claims recorded | 73 (65 verified, 2 unverified, 4 inferred, 0 contradicted, 2 needs_review) |
| Evidence coverage = verified / (verified + unverified + contradicted) | 65/67 = 97% |
| Verified claims that carry both a source and a quote | 65/65 |
| Score citations that point at a real ledger claim | 78/78 |
| Candidates with a decision-maker taken from the API record | 4/6 (the other two read "I can't verify a decision-maker") |
| Evidence confidence | 3 High, 3 Medium |
| Crustdata credits for the whole run, every attempt included | 31.45 (about 5 per company) |
| Model cost, estimated at list price (the free tier billed $0) | about $0.11 |

**Hand-checked.** Evidence coverage only proves a quote *exists* in its source, not that it supports the claim. We read 15 randomly sampled verified claims next to their quotes (`scripts/sample_claims.py`, fixed seed): 15 of 15 were supported by their quote. The reviewer was the builder, not an independent party, and the sample is small.

**Recovery (run `demo-crash`).** We killed the run on purpose right after the first company's enrichment (`--crash-after enrich`), then restarted with the same run id. The restart skipped the finished stages, did the rest, and made **0 repeated paid requests** (`scripts/check_dupes.py`: 13 paid Crustdata calls in total, no identical request twice; same check on `demo1`: 33 calls, 0 repeats). Model overload (HTTP 503) was handled by rotating models and retrying, and a time ceiling stopped `demo1` cleanly before its last company, after which it resumed.

**Targets from the spec that are NOT met or NOT measured**
* **Scoring consistency (target 90%): not met.** Re-running assessments on the same evidence moved scores by up to about 6.5 points and changed the middle of the ranking (SEA Infonet stayed first and BlueEarth last). The model is the source of the variance. Taking the median of several assessments would reduce it; we did not build that.
* **Candidate relevance Precision@5: not measured.** It needs an independent, manually labelled answer key.
* **Decision-maker accuracy: not independently checked.** Names and titles are copied from the Crustdata record, so they are only as current as that record.
* **Workflow completion and recovery rates** were exercised on two runs, which is too few to report a percentage.

**Mistakes found by testing, and fixed**
* A company got *High* confidence from its own marketing page alone. High now requires corroboration from a source that is not the company's own site.
* A founding-year mismatch (2011 vs 2012) forced manual review. A conflict now needs a verbatim quote from both sides, and only material conflicts block a recommendation.
* A trade association was shortlisted as a partner in the `demo-crash` run. The screening prompt now excludes associations, directories, media and government bodies (prompt changed; not yet re-run to confirm).

A finished report for `demo1` is committed at [docs/sample_report_demo1.html](docs/sample_report_demo1.html) (open it in a browser; every claim links to its source in section 14).

## 7. Limitations
* Company descriptions in the data graph are marketing text; a verified claim from a company's own website means "the company says so".
* Small or new companies often have no third-party coverage. That yields low evidence confidence, not rejection.
* Web search may surface namesake companies; claims from search snippets are only kept when they clearly refer to the candidate.
* Single run is rate-limited by the key (5 req/min on company endpoints), so a run takes minutes.
* The requester's own product details come only from the request; competitive overlap is judged against that one sentence.

## 8. Roadmap (and why not today)
Ongoing monitoring of partners (Watcher), CRM export, multi-client tenancy, and outreach after approval. Held back because each needs a person-in-the-loop design and none changes the core research quality we could verify in one day.

## 9. Run it from a fresh clone

```powershell
git clone <repo> ; cd partnerscout
python -m venv .venv ; .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env     # then fill CRUSTDATA_API_KEY and GEMINI_API_KEY
python pipeline.py --run-id demo                   # CLI run of the sample request
python report.py demo                              # writes out/demo.html
streamlit run app.py                               # the UI
python -m pytest -q tests                          # offline tests
```

Resume demo: `python pipeline.py --run-id demo2 --crash-after enrich`, then run it again with the same `--run-id`; finished stages are not repeated and no paid call is made twice.

## 10. Declaration
Nothing was written before 10:15 AM on 22 Nov 2026 except the product brief (a text document describing the concept, scoring model and architecture), which is declared on the submission form.
