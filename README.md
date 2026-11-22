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

### Business case (assumptions, not validated)

* **Buyer:** a partnerships or corporate-development lead at a B2B SaaS company opening a new industry or geography, or a BD agency serving several such clients.
* **Today:** an analyst spends days to weeks per shortlist (our estimate; we did not interview buyers).
* **Proposed price:** about **Rs 4,000 per partnership brief** (up to 5 vetted partners), or Rs 25,000 a month for 10 briefs. These are our own proposal and have not been tested with anyone. No gross margin is claimed: Crustdata's price per credit and hosting costs are not known to us, so only the credit count and the model cost are measured.
* **What one job costs us to run** (measured on run `demo3`, 6 companies investigated): **24.8 Crustdata credits** plus about **US$0.085** of model usage at list price (the free tier billed US$0). At an assumed Rs 90 per US$ that is roughly Rs 8 of model cost. Crustdata's price per credit is not stated in the event material we have, so the data cost is `credits x your plan's price per credit`; the credit count is the number to use. Every run reports its own credits in the report footer and the Workspace ledger.
* **Margin check:** the price is dominated by the human review the product still asks for, not by the cost of the run.

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

### Partner Ecosystem and Partnership Pipeline

* **Partner Ecosystem screen.** A map with clickable company markers and a company list that stay in sync: clicking a marker selects the company in the list and opens its details, and choosing a company in the selector highlights its marker. Filters: geography (city), industry signals, screened partner type and fit score (with a switch for companies that have no fit score yet).
* **Partner details.** Saved city, partner type, description, fit (investigated companies) or screening relevance (the others, clearly marked as a model judgement), current stage, and an *Open full profile* button for investigated companies.
* **Partnership Pipeline screen.** Stages: Discovered, Investigating, Verified, Shortlisted, Outreach Drafted, Approved, Archived. It lists every discovered candidate and every investigated partner. Stage changes are saved in SQLite (`pipeline_stages`). The first four stages and Approved are derived from the run (search, identity/research started or a tool failed, evidence checked, recommended, draft approved); Outreach Drafted and Archived are set by a person.
* **Grounded data, with fallbacks.** Locations are approximate city centres matched by keyword from the saved city text (`geo.py`); companies whose text matches no known city are counted as *not mappable* and not drawn, never guessed. "Industry signals" are keywords from the company's own description and are labelled as hints, not verified facts. The map says that no relationships between companies are drawn because this build has no source for them, and that coverage is limited to the companies this run's searches found, not the whole market.
* **Draft-only approvals.** Approving a draft records the decision in the `approvals` table and moves the company to Approved. It does not send anything; there is no "sent" stage.
* **Files.** `ecosystem.py` (data layer), `components/ecosystem_map/index.html` (the two-way map component, Leaflet with OpenStreetMap tiles, needs internet), `tests/test_ecosystem.py` (synthetic fixtures, labelled as such).

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
* **Evidence confidence** (High/Medium/Low) is separate from fit. A high fit with low confidence is not presented as a firm recommendation. Every source is classified (company's own site, regulator, reputable news, third-party directory, Crustdata record, unclassified page). **High** needs a regulator or reputable-news corroboration, or two different directory domains; a company's own marketing, or one directory repeated, can only reach Medium. A re-evaluation of the first 24 investigated companies under this rule moved 18 of them from High to Medium (none had regulator or news corroboration), so earlier "High" ratings were overstated.
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

Sample request: *"We are a cybersecurity SaaS company looking to expand our distribution in India's banking and financial services sector. Identify five potential channel or technology partners..."* All companies below came from live Crustdata responses on 22 Nov 2026; nothing is mocked. We ran the sample request four times (`demo1` to `demo4`), plus a crash test (`demo-crash`). `demo3` is the headline run: it used the final scoring code and also carries the failure-recovery test. Reproduce the numbers with `python scripts/evaluate.py <run_id>`.

**Automated measurements (run `demo3`)**

| Metric | Result |
|---|---|
| Unique candidates discovered (after duplicate resolution) | 73 |
| Companies investigated end to end | 6 |
| Identity resolved (confidence >= 0.95, domain matches) | 6/6 |
| Duplicates in the shortlist | 0 |
| Claims recorded | 81 (78 verified, 0 unverified, 0 inferred, 1 contradicted, 2 needs_review) |
| Evidence coverage = verified / (verified + unverified + contradicted) | 78/79 = 99% |
| Verified claims that carry both a source and a quote | 78/78 |
| Score citations that point at a real ledger claim | 77/77 |
| Candidates with a decision-maker taken from the API record | 4/6 (the others read "I can't verify a decision-maker") |
| Recommendations | 2 Pursue, 2 Approach with caution (competitive overlap), 1 Manual review, 1 Deprioritise |
| Evidence confidence | 6 High (not audited: the High rule may be too generous for small firms) |
| Crustdata credits for the whole run, every attempt included | 24.80 (about 4 per company) |
| Model cost, estimated at list price (the free tier billed $0) | about $0.085 |

**Hand-checked.** Evidence coverage only proves a quote *exists* in its source, not that it supports the claim. We read 15 randomly sampled verified claims next to their quotes (`scripts/sample_claims.py`, fixed seed) on `demo3`, and earlier 15 on `demo1`: all 30 were supported by their quote, although a few were thin marketing labels (for example "Deploy Advanced Anti-Fraud"). The reviewer was the builder, not an independent party, and the sample is small.

**The hard cases the product met (all in `demo3`).**
* *Strong capability match, competing product:* Finonyx has 15 years serving banks, but its own "DocSecure" document-protection product overlaps the requester's offering. A verified claim backs the conflict, so the recommendation is *Approach with caution*, and the fit score carries a visible penalty.
* *Namesake:* two sources for "Airtree Ventures" describe different entities (an Indian technology services firm and an Australian venture fund). Each side is a verbatim quote, the conflict is recorded as *contradicted*, and the recommendation is *Manual review before any approach* instead of a score-based pick.
* *Too new to trust:* Dvion's registration number carries 2026 while its site claims a financial-sector focus. The disagreement is flagged *needs_review* and the company is deprioritised, not dismissed.

**Recovery.**
* *Crash (run `demo-crash`).* We killed the run right after the first company's enrichment (`--crash-after enrich`) and restarted with the same run id. The restart skipped finished stages and made **0 repeated paid requests** (`scripts/check_dupes.py`: 13 paid Crustdata calls, no identical request twice).
* *Tool outage (run `demo3`, `--simulate-failure enrich`).* The first company's enrichment failed once. The company was **held for review**, not scored as "no evidence", and the other five finished. Re-running the same run id retried only the held company: 23 paid Crustdata calls for the whole run, 0 identical paid requests repeated. Testing this found a bug: a held company was saved as a final result and would never have been retried; fixed.
* Model overload (HTTP 503) was handled by rotating models and retrying, and a time ceiling once stopped a run cleanly before its last company, after which it resumed.

**Run-to-run variation (the honest weak spot).** The same request produced four different shortlists, because the model's screening scores for about 75 candidates are noisy and many tie at 85 to 100:

| Run | Shortlist (investigated) | Top fit |
|---|---|---|
| `demo1` | SEA Infonet, Sectonics, TechBox7, eCAPS, Multify, BlueEarth | 76.8 |
| `demo2` | SEA Infonet, eCAPS, Nexviax, CyberVAD, JGD CyberScuti, RankSecure | 80.8 |
| `demo3` | iValue Group, DebiLink, Cycops, Finonyx, Dvion, Airtree | 79.8 |
| `demo4` | Infonet Solutions, Varathra, Interface India, Interland, iValue Group, Letsfin | 65.3 |

Discovery itself is stable (73 to 75 unique candidates each time); the screening step is not. Within one run, scoring the same evidence three times (median kept) gave identical scores for 4 of 5 companies and a 4.7-point spread for the fifth, so scoring is steadier than shortlisting. SEA Infonet's recommendation also moved from "caution" (`demo1`) to "Pursue" (`demo2`) between runs. A bigger shortlist (`--shortlist 12`) should raise overlap between runs; we did not measure it. Treat a run's ranking as a research starting point, not a stable answer.

**Targets from the spec that are NOT met or NOT measured**
* **Scoring consistency (target 90%): not met across runs** (see above). Median-of-3 assessments are built, but a full repeat-run consistency percentage was not computed.
* **Candidate relevance Precision@5: not measured.** It needs an independent, manually labelled answer key.
* **Decision-maker accuracy: not independently checked.** Names and titles are copied from the Crustdata record, so they are only as current as that record.
* **Workflow completion and recovery rates:** four full runs and two induced failures; too few to report a percentage. `demo4` was made after a shortlist-ordering experiment that we then reverted because it gave weaker results.

**Mistakes found by testing, and fixed**
* A company got *High* confidence from its own marketing page alone. High first required a source that was not the company's own site; the post-repair audit found that still let directory listings count as independent, so the rule was tightened again (see PARTNERSCOUT_POST_REPAIR_AUDIT.md).
* A founding-year mismatch (2011 vs 2012) forced manual review. A conflict now needs a verbatim quote from both sides, and only material conflicts block a recommendation.
* A trade association was shortlisted as a partner in an earlier run. The screening prompt now excludes associations, directories, media and government bodies; none appeared in the shortlists of `demo1` to `demo4`.
* A held company would never have been retried on resume (found while testing the outage, fixed).

A finished report for the post-repair run `demo6` is committed at [docs/sample_report_demo6.html](docs/sample_report_demo6.html) (open it in a browser; every claim links to its source in the last section); the app can generate one for any run.

**Post-repair audit.** An independent-style audit after these results (`PARTNERSCOUT_POST_REPAIR_AUDIT.md`) found and fixed: shortlist instability (screening now ranks by a deterministic code-computed score; 100% top-6 overlap over 10 repeats on a fixed pool, versus 73%), overstated "High" confidence (all 30 evaluated companies are now Medium under a source-quality rule), an evidence-table key that let later runs overwrite earlier runs, Google redirect citations, missing input validation and an uncaught invalid-JSON path. Decision-maker coverage did not improve (the people are not in the data). The post-repair run is `demo6`; whole-run scores still vary between runs.

## 7. Limitations
* Company descriptions in the data graph are marketing text; a verified claim from a company's own website means "the company says so".
* Small or new companies often have no third-party coverage. That yields low evidence confidence, not rejection.
* Web search may surface namesake companies; claims from search snippets are only kept when they clearly refer to the candidate.
* Single run is rate-limited by the key (5 req/min on company endpoints), so a run takes minutes.
* The requester's own product details come only from the request; competitive overlap is judged against that one sentence.

## 8. Roadmap (and why not today)
Ongoing monitoring of partners (Watcher), CRM export, multi-client tenancy, and outreach after approval. Held back because each needs a person-in-the-loop design and none changes the core research quality we could verify in one day.

## 9. Try it

**Hosted read-only demo:** _link added after deployment_ (see below). It browses saved results of real runs (`demo1` to `demo4`, `demo-crash`) on live Crustdata data, with all four screens, the evidence tables and the downloadable report. Starting new runs is disabled there on purpose, so a public link cannot spend API credits.

**Full run with your own keys:** see section 10.

**Deploying the demo yourself** (Streamlit Community Cloud, free): point a new app at this repo, main file `app.py`, and set **no secrets**. With no `CRUSTDATA_API_KEY` the app automatically opens the committed snapshot `demo_data/demo.db` (regenerate it with `python scripts/export_demo.py demo1 demo2 demo3 demo4 demo-crash`).

## 10. Run it from a fresh clone

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

Resume demo: `python pipeline.py --run-id demo2 --crash-after enrich`, then run it again with the same `--run-id`; finished stages are not repeated and no paid call is made twice. Tool-outage demo: `python pipeline.py --run-id demo5 --simulate-failure enrich` holds the first company for review; running the same command again retries only that company.

## 11. Declaration
Nothing was written before 10:15 AM on 22 Nov 2026 except the product brief (a text document describing the concept, scoring model and architecture), which is declared on the submission form.
