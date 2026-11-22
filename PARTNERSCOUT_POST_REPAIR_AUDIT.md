# PartnerScout: post-repair audit

Audit date: 22 Nov 2026. Baseline commit: `5d80f3b` (`Redesign UI as a light enterprise intelligence product`). Repairs were made on branch `audit-repairs`; Git history is unchanged and nothing was rewritten.

This audit did **not** accept `PARTNERSCOUT_HACKATHON_JUDGE_REPORT.md` (the earlier 91.8/100 evaluation). Its claims were treated as unverified, checked against the code, the SQLite ledger and live runs, and several did not hold (section 2). The ratings below are **my own auditor ratings** using the official formula `Weighted score = (Rating / 5) x Weight`. They are judgements, not official scores.

Reproduce everything with the scripts named in each section. Raw experiment output is in `audit_results/`.

---

## 1. Baseline score (before any change)

| Criterion | Weight | Rating /5 | Points | Main reason |
|---|---:|---:|---:|---|
| End-to-end execution | 25 | 4.0 | 20.0 | Real live pipeline; but the shortlist moved between runs |
| Facts and verification | 20 | 3.5 | 14.0 | Quote check is sound; "High" confidence overstated, redirect URLs, evidence table overwritten across runs |
| Robustness and edge cases | 20 | 3.7 | 14.8 | Live crash/outage recovery proven; no input validation; no failure-mode tests; one uncaught crash path |
| Customer value and idea | 20 | 3.7 | 14.8 | Clear service replaced; economics are assumptions, none validated with a buyer |
| Demo and understanding | 15 | 3.8 | 11.4 | Strong UI; no recorded video and no hosted link at the time |
| **Total** | 100 | | **75.0** | |

## 2. Weaknesses found, and what the earlier report got wrong

| # | Finding | Evidence |
|---|---|---|
| W1 | **Shortlist instability.** Historical runs `demo1`-`demo4` share only 3 of 36 shortlist slots (8.3% mean pairwise overlap; the earlier report said 25-33%). Re-running only the screening of the then-current code ten times on one fixed candidate pool gives 73% mean pairwise top-6 overlap (min 50%), 11 different companies selected | `scripts/stability_screen.py`, `audit_results/stability_baseline_metrics.json` |
| W2 | **"High" evidence confidence was overstated.** The rule counted any verified claim that was not the company's own site as independent corroboration, including directory listings and the company's own LinkedIn posts. Of 30 investigated companies in five runs, 24 were rated High; none had regulator or news corroboration. The earlier report said High "strictly requires independent third-party corroboration" | `scripts/backfill_sources.py`, `audit_results/backfill_sources.json` |
| W3 | **Evidence ledger was not run-isolated (new bug).** The `evidence` table was keyed by `claim_id` alone, e.g. `7523-c1`, so the same company in a later run silently overwrote the earlier run's rows. The table held 34 verified rows for `demo3` against 78 in its saved result | direct SQL; test `test_same_claim_id_in_two_runs_does_not_overwrite_the_earlier_run` |
| W4 | Google redirect links were stored as citations (11 of 273 rows) | SQL on `evidence.source_url` |
| W5 | Decision-maker coverage 17/24 = 70.8% (accuracy of those 17 = 100%, copied from the API record). The fallback to Person Search did not exist | `scripts/people_coverage.py` |
| W6 | No input validation before the model or paid calls. A `200` response whose body was not JSON raised an uncaught `ValueError` in `crustdata.py` | code review; test `test_simulated_invalid_json...` |
| W7 | No tests for 401, 402, 403, 429, 5xx, timeouts, bounded retries, cache idempotency | `tests/` before this audit |
| W8 | **Economics claims in the earlier report are unsupported.** "~25 credits (~$2.50)" assumes about $0.10 per credit; no account pricing says so. "94.1% gross margin" depends on that and on unlisted costs. Its prices (Rs 4,999 / 29,999 / 89,999) disagree with the README (Rs 4,000 / 25,000). "Precision@5 90%" was judged by the same evaluator, with no labelled answer key | `README.md`, the earlier report |

Claims of the earlier report that **did** check out: all 255 `verified` rows carry both a quote and a source (0 exceptions, by SQL); 0 repeated paid Crustdata requests in the benchmark runs (`scripts/check_dupes.py`); rate limits are read from `/account/endpoints`.

---

## 3. Changes implemented: BEFORE -> CHANGE -> AFTER -> TEST EVIDENCE

### 3.1 Ranking stability (priority one)

**Root cause (measured, not assumed).** Discovery is stable (73-75 unique candidates, identical when cached). The instability came from the screening step: the model returned a free-form 0-100 "relevance" for batches of 20 companies with no cross-batch calibration, many ties at 85-100, and a model temperature above zero. The earlier tie-break by Crustdata rank reduced it but did not remove it.

**Change.** New `ranking.py`:
1. Duplicates collapsed deterministically (unchanged, `norm_domain` / `norm_name`).
2. A code-computed `prescore` for every candidate, identically, with no batches: target-segment terms from the parsed brief (up to 30 points), capability terms from what the requester *sells* minus the target-segment words (up to 35 points, so a fintech is not mistaken for a security vendor), partner-type signals (20), size (10) and a description-present bonus (5), minus a penalty for associations, media, investors, staffing and physical/electronic security.
3. The model is used only for **categorical** judgements at temperature 0 (partner type, serves target segment, sells a competing product). Its free-form 0-100 number is kept as `llm_relevance` but no longer decides the order.
4. `composite = prescore + categorical adjustments`; order = composite, then Crustdata search rank.
5. Deeper strategic evaluation (fit components, mutual value, conflict) still happens after investigation, using evidence.

**Measured result** (ten repeats of the ranking step on the same 73-company pool of `demo3`; this isolates model randomness from live-data change):

| Method | Top-6 mean pairwise overlap | Top-6 min | Top-5 mean | Distinct companies selected | Spearman (top 30)* | Kendall (top 30)* |
|---|---:|---:|---:|---:|---:|---:|
| Before (code at `5d80f3b`, 10 repeats) | 73% | 50% | 72% | 11 | 0.909 | 0.776 |
| After (10 repeats, 2 processes) | **100%** | 100% | 100% | 6 | 1.000 | 1.000 |
| After, final lexicon (5 repeats) | **100%** | 100% | 100% | 6 | 1.000 | 1.000 |

\* correlations are computed over the companies common to both top-30 lists.

Target (>= 90% agreement) is **met for the shortlist step under this definition**. Honest limits:
- Same pool, one model family, one afternoon. It says nothing about model-version changes, or about live data changing between days (that would legitimately change the pool).
- A full pipeline was **not** repeated ten times (about 10 minutes per cold run at the key's 5 requests/minute). Whole-run scores still vary: for the four companies shared by `demo3` and `demo6`, scores moved by 1.0, 3.3, 8.6 and 11.6 points (mean 6.1) and the order of two of them swapped (Spearman 0.8, n = 4). Airtree moved most because `demo6` flagged it as a direct competitor. **Full-run score consistency is not at 90%.**
- **Relevance was not independently measured.** I inspected the top 12: iValue, DebiLink, Cycops, ATOP (managed security + GRC) look right. The first version also ranked a physical-security firm (Infoniks) fourth; I added "electronic security" / CCTV terms after seeing it. That change was made after looking at this one pool, which is an **overfitting risk**. Rupiyo Digital (a fintech enabler) still ranks sixth. Under the old method DebiLink was selected in 5/10 repeats and Cycops in 10/10; under the new one both are in 10/10.

### 3.2 Evidence verification

**Before.** `verify_quote` proves only that a quote exists in the fetched text. "Independent" meant "not self-reported".
**Change** (`evidence.py`, `scoring.py`, `store.py`, `pipeline.py`, `report.py`, `app.py`):
- Every evidence row now keeps `canonical_url`, `source_class`, `source_org` (domain) and `corroboration`, besides claim id, company id, text, category, source URL, quote, retrieval date, status and confidence.
- Source classes: official company, official regulatory, independent news, third-party business database, company social profile, unclassified web page. Class "verified partner/customer source" **cannot be assigned by code** (a person must confirm a page is a named customer's own statement), so the code never assigns it.
- Corroboration labels: `self_reported`, `independent` (regulator or reputable news only), `database_listing`, `api_record`, `weak`, plus `contradiction`, `unverified`, `inference`.
- Confidence rule: **High** needs a regulator/news corroboration **or** two different directory **domains** (counted once per domain, so repeats of one listing do not add up), plus coverage >= 0.7, core categories and >= 6 verified claims. Everything else is Medium or Low.
- Canonical URLs: Google "goto" links are opaque tokens, so the destination can only be read from the redirect's `Location` header. `canonicalize()` follows at most 3 hops, only while the URL is still a Google link, never requests the destination page, rejects non-http targets and strips tracking parameters. If it cannot resolve, the report says "redirect link, destination could not be resolved" and the source is classed unclassified, never "verified canonical".
- Fixed in the same pass: the evidence table key is now `(run_id, claim_id)` with an automatic, lossless migration; `scripts/rebuild_evidence.py` restored every run's rows from the saved results.
- A bug in my own first rule was caught on live data: LinkedIn was counted as a directory, so `demo6` DebiLink became High on LinkedIn posts plus Justdial. LinkedIn is now "company social profile" (self-reported).

**After (measured).**
- Re-evaluating 30 investigated companies (`demo1`-`demo4`, `demo6`) under the new rule: **High 24 -> 0, Medium 6 -> 30**. No recommendation changed, because "Pursue" accepts Medium. **A caution:** with this rule the confidence label no longer separates companies in this data, because none has regulator or news corroboration. It remains a safe floor, not a ranking signal.
- Redirect links: of the 11 stored citation rows, 8 resolved on the first pass; a later pass resolved all 13 distinct links found across five runs. In `demo6`'s own run 3 of 6 resolved at collection time. Resolution by Google is intermittent, so unresolved links stay labelled rather than cited.
- `demo6` (post-repair, live): 78 verified of 80 checkable claims (98%); 78/78 verified claims carry a source and a quote; 73/73 score citations point at real claims.
- Not re-done after the repairs: the manual hand-check of sampled claims (the earlier 30/30 was done by the builder; it is a small sample and not independent).

Tests: `test_source_classes`, the four `canonical_url` tests, `test_company_marketing_alone_cannot_reach_high_confidence`, `test_one_directory_site_repeated_does_not_add_up_to_high`, `test_independent_news_or_regulatory_source_can_reach_high`, `test_evidence_rows_keep_source_class_and_canonical_url`, `test_annotate_claims_labels_old_rows_without_network_access`.

### 3.3 Decision-maker coverage

**Before.** Only the company record. Coverage 17/24 = 70.8%, accuracy 17/17.
**Change.** `find_people()` runs only when the record lists no decision-makers, founders or C-level people. It calls `POST /person/search` filtered on `experience.employment_details.current.company_id` (the filter field comes from the API's own error message listing supported fields; checked live), requests only name, title and id, and keeps a person only if the **title** is senior and relevant (partnership/BD/strategy roles first, then top executives). Checkpointed as stage `people`, so it is not repeated on resume.
**After (live, `scripts/people_coverage.py`, 0.13 credits per lookup).** For the 7 companies without a decision-maker, Person Search returned 0-4 current people each: sales managers, developers, network administrators, an R&D specialist. **None had a relevant senior title, so 0 were added.** Coverage stays **17/24 = 70.8%**; accuracy stays 100% (nothing was invented or padded). `demo6`: 4/6 (66.7%). I report this as no coverage gain: the people are not in the data, and lowering the title bar would have raised coverage by lowering accuracy.

### 3.4 Input validation

**Before.** Any string reached the model. **Change.** `validation.py` (plain dataclass + regex; Pydantic is not installed and would add a dependency for a few rules). It rejects empty, very short (<40 chars or <7 words), over-long (>4000), mostly-symbol requests, requests asking to send messages automatically, and partner counts outside 1-15; it asks for clarification when the partnership type, country/region or what the company sells is missing. It runs in `pipeline.run` (status `rejected`, exit code 3) and in the UI before a run is created. **After.** A rejected request makes no model call and no Crustdata call (`test_rejected_request_spends_nothing`). 9 tests. Limit: it is a heuristic; "contradictory requirements" detection is minimal (one pattern).

### 3.5 Credit accounting

**Method.** `scripts/reconcile_credits.py` compares the ledger with the authoritative `GET /account/credits` (free).
**Result.** Stated starting balance 15,200 (event 15,000 + 200 top-up). API balance now 15,073.66, so 126.34 spent. The ledger sums to 126.21 over 162 Crustdata rows (31 cache hits at 0 credits, 0 non-200 rows with a cost). **Difference 0.13 credits**, which is exactly my own manual `/person/search` probe made outside the central client during this audit. Credits come from the `X-Credits-Used` header. Every pipeline call goes through `Crustdata.call`.
**Cost separation.** (1) Crustdata credits: `demo3` (cold cache) 24.8; `demo6` 11.53 only because it reused cached responses, so do not quote it as a per-job cost. (2) Crustdata money: **unknown**, no per-credit price is documented for this account. (3) Model tokens: **not stored** (only call count and an estimate), a gap. (4) Model money: about $0.085-0.106 per run at an assumed list price; the free tier billed $0. (5) Hosting: not measured. (6) Total cost per brief in money: **cannot be stated honestly**. The README now says no margin is claimed. The earlier "94% margin" is withdrawn.

### 3.6 Robustness

**Change.** A `200` with a non-JSON body is now logged, never cached, retried (bounded); previously uncaught. All other paths were reviewed: 401/403 fatal, 402 `CreditsExhausted`, 429 waits for `x-ratelimit-reset`, 5xx and timeouts back off, retries capped at `max_attempts`, credit ceiling checked **before** each attempt.
**After.** 9 fault-injection tests (all **simulated**, using a scripted fake session; none is a live Crustdata response): 401, 403, 402, 429 with reset header, 503 bounded at exactly 4 attempts, timeout then recovery, invalid JSON not cached and bounded, repeat call served from cache at 0 credits, credit ceiling blocks the next call. Exactly-once stage checkpointing has a unit test.
**Live evidence (earlier and this audit):** `demo-crash` killed after enrichment and resumed with 0 repeated paid calls; `demo3` tool outage held one company for review and retried only that one on resume (found and fixed a bug there: held results were never retried); `demo6` ran clean end to end with 0 repeated paid calls (`check_dupes`).
**Not tested:** SQLite failure/locking, a power-loss style kill during a write, concurrent writers beyond WAL mode, and Gemini failure paths beyond the existing model rotation.

### 3.7 Strategic intelligence

**Before.** A single competitive-overlap level and a mutual-value hypothesis. **Change.** The assessment now also returns separate judgements, each with cited claim ids and "unknown" when unsupported: product complementarity, customer overlap, distribution complementarity, technology compatibility, competition type (none / indirect / direct), strategic incompatibility and feasibility. Citations to non-existent claims are dropped. A **verified direct competitor** now forces "Manual review before any approach" regardless of score (`review_flags(..., direct_competitor=True)`), so a high-scoring candidate with a serious conflict can no longer be presented as "Pursue". UI profile and report show the dimensions and the evidence behind them. Tests: the override and its negative case.
**After (live, `demo6`).** All six companies returned populated dimensions with honest "unknown"s (for example technology compatibility unknown for five of six). Airtree came back `direct` competition and `strategic incompatibility: true` and landed on Manual review, consistent with its identity conflict. Hypothetical value stays labelled inferred. **Limit:** the quality of these judgements was not scored against an answer key.

### 3.8 Deliverable

The report now has a source-type column, canonical links, an explicit key to what each source type can prove, a print layout, and the relationship dimensions in the profile. It keeps the existing 14 sections. A regenerated report for `demo6` is in `docs/sample_report_demo6.html`.

---

## 4. Files modified or added

Modified: `pipeline.py`, `crustdata.py`, `evidence.py`, `scoring.py`, `store.py`, `report.py`, `app.py`, `README.md`, `demo_data/demo.db`.
Added: `ranking.py`, `validation.py`, `tests/test_audit.py`, `scripts/stability_screen.py`, `scripts/stability_metrics.py`, `scripts/people_coverage.py`, `scripts/reconcile_credits.py`, `scripts/backfill_sources.py`, `scripts/rebuild_evidence.py`, `audit_results/*.json`, `docs/sample_report_demo6.html`.
Historical results of runs `demo1`-`demo4` were re-evaluated in place by `backfill_sources.py` (confidence and recommendation recomputed from the same claims; scores untouched).

## 5. Tests executed

`python -m pytest -q tests` -> **50 passed** (13 original + 37 new). New tests cover: nine simulated Crustdata failure modes, exactly-once stage, nine validation cases, source classes, four canonical-URL cases, three confidence-rule cases, evidence row fields, evidence isolation between runs, decision-maker title filtering and no-call-when-people-exist, three ranking determinism cases, the direct-competitor override, annotate-without-network. Streamlit `AppTest` rendered all four screens in demo mode with no exceptions.
Live (real Crustdata and Gemini): the ranking experiments (25 repeats), `demo6` end to end (a first attempt, `demo5`, was stopped on purpose after the ranking fix and is marked `superseded`), `people_coverage` on 24 companies, the credit reconciliation, the redirect resolution.
Simulated (labelled as such): all fault-injection and redirect-chain tests.
Requested but **not done**: ten full-pipeline repeats; SQLite failure tests; a hand-labelled Precision@5; an independent re-check of sampled claims.

## 6. Before and after

| Metric | Before | After |
|---|---:|---:|
| Shortlist top-6 mean pairwise overlap, same pool, 10 repeats | 73% (min 50%) | 100% (min 100%) |
| Shortlist overlap across the four historical full runs | 8.3% | not re-measured end to end |
| Companies rated High confidence (of 30 evaluated) | 24 | 0 |
| Verified claims with quote and source | 255/255 | 78/78 in `demo6` |
| Google redirect citations | 11 of 273 unresolved | resolved or labelled unresolved |
| Decision-maker coverage / accuracy | 70.8% / 100% | 70.8% / 100% (no gain) |
| Input validation before paid calls | none | yes |
| Failure-mode tests | 0 | 9 simulated + exactly-once |
| Ledger vs account balance | not reconciled | within 0.13 credits (explained) |
| Evidence table isolation between runs | broken | fixed and migrated |

Things that got **worse or stayed weak**: confidence labels now carry little information (all Medium); full-run score variance (mean 6.1 points between `demo3` and `demo6`) is unchanged; decision-maker coverage did not improve.

## 7. Remaining limitations

- Ranking stability is measured for the screening step on one pool; relevance has no independent answer key; the lexicon was tuned after viewing that pool.
- Verification still proves a quote exists in the fetched text. It does not prove the statement is true. "Independent" evidence is rare for small firms in this data.
- Redirect resolution depends on Google responding.
- Decision-maker coverage is capped by what Crustdata holds.
- No money cost per brief can be stated; model tokens are not stored.
- The business case (price, buyers, frequency) is untested with any customer.
- No continuous-monitoring feature; no CRM export.

## 8. Official rubric after repair (auditor ratings)

| Criterion | Weight | Rating /5 | Points | Change vs baseline |
|---|---:|---:|---:|---|
| End-to-end execution | 25 | 4.2 | 21.0 | stable shortlist, validation, fallback; full-run scores still vary |
| Facts and verification | 20 | 4.0 | 16.0 | source classes, canonical URLs, honest confidence, ledger bug fixed |
| Robustness and edge cases | 20 | 4.3 | 17.2 | validation, fault-injection suite, JSON guard; SQLite untested |
| Customer value and idea | 20 | 3.7 | 14.8 | unchanged; economics now stated honestly, still unvalidated |
| Demo and understanding | 15 | 3.8 | 11.4 | unchanged here; no video or hosted link yet |
| **Total** | 100 | | **80.4** | **+5.4** |

The earlier 91.8 is not reproduced. The differences: it counted High confidence as proven corroboration (W2), accepted an unsupported 94% margin and price list (W8), took a builder-judged Precision@5 as measured, and rated the demo before any video or deployment existed.

## 9. Honest competition readiness

The engineering core is strong and now better evidenced: live autonomous execution, quote-checked claims, conflict detection, mutual value, resumable runs, a reconciled credit ledger and a reproducible shortlist. It is a credible finalist on execution, facts and robustness. The weakest points a judge can press are the business case (no customer evidence, unknown credit price), whole-run score variance, the all-Medium confidence label, and decision-maker coverage. What is still outstanding for the submission itself is outside this audit: the 2-minute video, a hosted demo link, the submission form, and the declaration of the pre-10:15 brief.
