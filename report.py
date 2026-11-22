"""Self-contained HTML partnership intelligence report (print to PDF from the browser)."""
from __future__ import annotations

import html
from urllib.parse import quote
import sys
from pathlib import Path

import store

CSS = """
html{background:#F5F4EF;color-scheme:light}
body{font:15px/1.6 Inter,system-ui,Segoe UI,sans-serif;color:#101F2C;background:#fff;max-width:960px;margin:24px auto;padding:44px 52px;border:1px solid #E4E8E5;border-radius:6px}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.02em;color:#101F2C}
h2{margin-top:38px;border-bottom:1px solid #E4E8E5;padding-bottom:8px;font-size:19px;letter-spacing:-.01em;color:#101F2C}
h2:before{content:"";display:inline-block;width:4px;height:16px;background:#167C68;border-radius:2px;margin-right:10px;vertical-align:-2px}
h3{margin-bottom:4px;color:#101F2C}
.sub{color:#62717D}.card{border:1px solid #E4E8E5;border-radius:10px;padding:16px 18px;margin:16px 0;background:#fff}
table{border-collapse:collapse;width:100%;font-size:13.5px}th,td{border-bottom:1px solid #E4E8E5;padding:7px 8px;text-align:left;vertical-align:top}
th{background:#F5F4EF;color:#62717D;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.pill{display:inline-block;padding:1px 10px;border-radius:99px;font-size:12px;font-weight:600}
.High,.verified,.Pursue{background:#E3F2EC;color:#167C68}.Medium,.inferred{background:#F8EFDC;color:#8A6420}
.Low,.unverified{background:#FBE9E9;color:#C65353}.contradicted,.flag{background:#FBE9E9;color:#C65353}
.score{font-size:28px;font-weight:700;color:#167C68}.muted{color:#62717D}.q{color:#3B4A57;font-style:italic}
.draft{background:#FBF7EC;border-left:4px solid #D5A85B;padding:10px 14px;white-space:pre-wrap}
.banner{background:#E3F2EC;border:1px solid #BFE3D6;border-radius:8px;padding:10px 14px;margin:12px 0}
small{color:#62717D}
@media print{html{background:#fff}body{border:0;margin:0;padding:0}}
"""


def e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def pill(text, cls=None) -> str:
    return f'<span class="pill {e(cls or text)}">{e(text)}</span>'


def claim_ref(ids, idx) -> str:
    return " ".join(f"<small>[{e(i)}]</small>" for i in ids or [] if i in idx)


def build_report(final: dict) -> str:
    brief, ranked, led = final["brief"], final["ranked"], final["ledger"]
    idx = {c["claim_id"]: c for r in ranked for c in r.get("claims", [])}
    ok = [r for r in ranked if not r.get("held_for_review")]
    # headline pick = best candidate that is actually actionable (not blocked by a flag), else best overall
    top = next((r for r in ok if r.get("recommendation") in ("Pursue", "Worth a conversation")), ok[0] if ok else None)
    h = [f"<!doctype html><meta charset=utf-8><title>PartnerScout report {e(final['run_id'])}</title><style>{CSS}</style>"]
    h.append(f"<h1>PartnerScout - Partnership Intelligence Report</h1><div class=sub>Run {e(final['run_id'])} - generated from live Crustdata data</div>")
    h.append('<div class="banner"><b>How to read this.</b> Every claim is tied to a source in the Evidence Register (section 14). '
             'A claim is <b>verified</b> only if its quote appears in the cited source. Mutual value is an analytical hypothesis, '
             'not evidence that any company is willing to partner. Proposal drafts are <b>not sent</b> and need human approval.</div>')

    h.append("<h2>1. Executive summary</h2>")
    if top:
        h.append(f"<p>From <b>{final['n_candidates']}</b> unique companies discovered, <b>{len(ranked)}</b> were investigated in depth. "
                 f"Strongest actionable candidate: <b>{e(top['company']['name'])}</b> (fit {e(top['fit']['score'])}, evidence confidence {e(top['evidence_confidence']['level'])}) - {e(top['recommendation'])}.</p>")
    h.append("<ul>" + "".join(
        f"<li><b>{e(r['company']['name'])}</b>: {e(r.get('recommendation'))}"
        + (f" - flags: {e('; '.join(r.get('flags', [])))}" if r.get("flags") else "") + "</li>" for r in ranked) + "</ul>")

    rq = brief.get("requester", {})
    h.append(f"<h2>2. Requesting company</h2><p>{e(rq.get('offering'))} <span class=muted>(segment: {e(rq.get('segment'))})</span></p>")
    h.append(f"<h2>3. Partnership objective</h2><p>{e(brief.get('objective'))}<br><span class=muted>Partner types sought: {e(', '.join(brief.get('partner_types', [])))}. "
             f"Required capabilities: {e(', '.join(brief.get('required_capabilities', [])))}.</span></p>")
    if brief.get("missing_info"):
        h.append(f"<p class=muted>Needs human confirmation: {e('; '.join(brief['missing_info']))}</p>")
    h.append(f"<h2>4. Methodology</h2><p>Discovery by ranked company search over Crustdata, duplicate resolution by domain and normalised name, a relevance screen, "
             f"then per candidate: identity resolution, enrichment, first-party website fetch, third-party and adverse-media search, quote-verified claim extraction, "
             f"scoring. Run cost: <b>{led['credits']:.2f}</b> Crustdata credits across {led['calls']} logged calls "
             f"({int(led['cache_hits'])} served from cache); estimated model cost ${led['usd']:.4f}.</p>")

    h.append("<h2>5. Ranked potential partners</h2><table><tr><th>#</th><th>Company</th><th>Fit</th><th>Evidence confidence</th><th>Recommendation</th><th>Model</th><th>Risk flags</th></tr>")
    for i, r in enumerate(ranked, 1):
        pm = (r.get("partnership_model") or {}).get("model", "")
        h.append(f"<tr><td>{i}</td><td><b>{e(r['company']['name'])}</b><br><small>{e(r['company'].get('domain'))}</small></td>"
                 f"<td>{e(r['fit'].get('score'))}</td><td>{pill(r.get('evidence_confidence', {}).get('level', 'n/a'))}</td>"
                 f"<td>{e(r.get('recommendation'))}</td><td>{e(pm)}</td><td>{''.join(pill(f, 'flag') + '<br>' for f in r.get('flags', []))}</td></tr>")
    h.append("</table>")

    h.append("<h2>6-11. Partner profiles</h2>")
    for i, r in enumerate(ranked, 1):
        c = r["company"]
        h.append(f'<div class="card"><h3>{i}. {e(c["name"])} <small>{e(c.get("domain"))} - {e(c.get("city"))} - size {e(c.get("size"))}</small></h3>')
        if r.get("held_for_review"):
            h.append(f"<p>{pill('Held for review', 'flag')} {e(r.get('error'))}<br><small>A tool failure is not read as an absence of evidence; a person should rerun or review.</small></p></div>")
            continue
        h.append(f"<div><span class=score>{e(r['fit']['score'])}</span> fit &nbsp; {pill(r['evidence_confidence']['level'])} evidence confidence "
                 f"<small>({r['evidence_confidence']['verified']}/{r['evidence_confidence']['total']} claims verified)</small> &nbsp; <b>{e(r['recommendation'])}</b></div>")
        h.append(f"<p class=muted>{e(c.get('description'))}</p>")
        h.append("<b>Strategic fit analysis</b><table><tr><th>Component</th><th>Score</th><th>Why</th><th>Evidence</th></tr>")
        for name, comp in r["components"].items():
            sc = comp.get("score")
            h.append(f"<tr><td>{e(name)}</td><td>{e(sc) if sc is not None else 'unknown'}</td><td>{e(comp.get('why'))}</td><td>{claim_ref(comp.get('claim_ids'), idx)}</td></tr>")
        h.append("</table>")
        fit = r["fit"]
        h.append(f"<small>Weights used (renormalised if a component is unknown): {e(fit.get('weights_used'))}. Adjustments: {e(fit.get('adjustments'))}. Unknown: {e(fit.get('unknown_components'))}.</small>")
        co = r.get("competitive_overlap") or {}
        h.append(f"<p><b>Competitive overlap / conflict:</b> {pill(co.get('level', 'none'), 'flag' if co.get('level') in ('medium', 'high') else 'verified')} {e(co.get('why'))} {claim_ref(co.get('claim_ids'), idx)}</p>")
        mv = r.get("mutual_value") or {}
        h.append("<b>Mutual value analysis</b> <small>(hypothesis - not confirmed partner interest)</small><table><tr><th>Value to requester</th><th>Value to partner</th></tr><tr><td><ul>"
                 + "".join(f"<li>{e(p.get('point'))} {pill(p.get('basis', 'inferred'))} {claim_ref(p.get('claim_ids'), idx)}</li>" for p in mv.get("to_requester", []))
                 + "</ul></td><td><ul>" + "".join(f"<li>{e(p.get('point'))} {pill(p.get('basis', 'inferred'))} {claim_ref(p.get('claim_ids'), idx)}</li>" for p in mv.get("to_partner", []))
                 + f"</ul></td></tr></table><p>{e(mv.get('rationale'))}</p>")
        pm = r.get("partnership_model") or {}
        h.append(f"<p><b>Suggested partnership model:</b> {e(pm.get('model'))} - {e(pm.get('why'))}</p>")
        st = r.get("stakeholder")
        h.append(f"<p><b>Decision-maker to approach:</b> {e(st['name'])}, {e(st['title'])} <small>({e(st.get('why'))})</small></p>" if st
                 else "<p><b>Decision-maker:</b> I can't verify a suitable decision-maker from the available sources.</p>")
        if r.get("open_questions"):
            h.append("<b>Open questions for a human</b><ul>" + "".join(f"<li>{e(q)}</li>" for q in r["open_questions"]) + "</ul>")
        pr = r.get("proposal") or {}
        h.append(f"<b>Proposal draft</b> {pill('DRAFT - not sent', 'Medium')}<div class=draft><b>{e(pr.get('subject'))}</b>\n\n{e(pr.get('body'))}</div></div>")

    h.append("<h2>13. Unverified information</h2><ul>")
    for r in ranked:
        for c in r.get("claims", []):
            if c["status"] in ("unverified", "contradicted", "needs_review"):
                h.append(f"<li><b>{e(r['company']['name'])}</b> [{e(c['claim_id'])}] {pill(c['status'])} {e(c['claim'])} <small>{e(c.get('notes'))}</small></li>")
    h.append("</ul>")

    h.append("<h2>14. Evidence and source register</h2><p class=sub>Source type says what the source can prove: <b>self-reported</b> = the company's own statement; "
             "<b>independent</b> = regulator or reputable news; <b>directory listing</b> = a third-party site that may copy other data; "
             "<b>API record</b> = data held by Crustdata. A search-result redirect link is shown with its real destination when it could be resolved; "
             "otherwise it is marked unresolved and is not treated as a canonical source.</p>"
             "<table><tr><th>ID</th><th>Company</th><th>Status</th><th>Claim</th><th>Source</th><th>Source type</th><th>Quote</th><th>Retrieved</th></tr>")
    names = {str(r["company"]["id"]): r["company"]["name"] for r in ranked}
    LABEL = {"self_reported": "self-reported", "independent": "independent", "database_listing": "directory listing", "api_record": "API record",
             "weak": "unclassified web page", "contradiction": "conflict between sources", "unverified": "unverified", "inference": "inference"}
    for r in ranked:
        for c in r.get("claims", []):
            raw = c.get("source_url") or ""
            canon = c.get("canonical_url")
            if canon:
                link = f'<a href="{e(canon)}">{e(canon[:70])}</a>'
            elif "google." in raw:
                link = "redirect link, destination could not be resolved"
            else:
                link = f'<a href="{e(raw)}">{e(raw[:70])}</a>' if raw.startswith("http") else e(raw)
            target = canon or (raw if raw.startswith("http") and "google." not in raw else "")
            if target and c.get("status") == "verified" and c.get("quote"):
                # Text-fragment link: supporting browsers scroll to and highlight the exact quoted passage on the page.
                frag = quote(" ".join(str(c["quote"]).split()[:9]), safe="")
                link += f'<br><a href="{e(target.split("#")[0])}#:~:text={frag}"><small>open at the quoted passage</small></a>'
            elif raw.startswith("crustdata:"):
                link += f'<br><small>field {e(c.get("source_ref"))}</small>'
            stype = LABEL.get(c.get("corroboration") or "", "")
            h.append(f"<tr><td>{e(c['claim_id'])}</td><td>{e(names.get(str(r['company']['id'])))}</td><td>{pill(c['status'])}</td><td>{e(c['claim'])}</td>"
                     f"<td>{link}<br><small>{e(c.get('source_ref'))}</small></td><td><small>{e(stype)}</small></td><td class=q>{e(c.get('quote') or '')}</td><td>{e(c.get('retrieved_at'))}</td></tr>")
    h.append("</table>")
    return "".join(h)


def write_report(run_id: str, out_dir: str | Path = "out") -> Path:
    final = store.get_stage(run_id, "final")
    if not final:
        raise SystemExit(f"run {run_id} has no final result yet")
    p = Path(out_dir) / f"{run_id}.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(build_report(final), encoding="utf-8")
    return p


if __name__ == "__main__":
    print(write_report(sys.argv[1]))
