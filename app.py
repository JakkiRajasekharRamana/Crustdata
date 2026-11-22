"""PartnerScout UI. Run: streamlit run app.py

Four screens: Brief -> Workspace -> Partners (dashboard) -> Brief Generator.
The UI only reads SQLite; the pipeline runs as a separate process, so a crash never takes the UI down
and any run can be resumed with the same run id.
"""
import html as _html
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import geo
import report
import store
from pipeline import DEMO_REQUEST

ROOT = Path(__file__).parent
DEMO = store.DEMO_MODE
st.set_page_config(page_title="PartnerScout", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

# ------------------------------------------------------------------ theme
C = {"bg": "#0B1020", "card": "#121A30", "line": "#22304F", "text": "#E5EDFF", "mute": "#8FA3C8", "accent": "#22D3A7"}
REC_COLORS = {"pursue": "#22D3A7", "worth": "#60A5FA", "caution": "#F59E0B", "manual": "#F87171", "held": "#A78BFA", "depri": "#64748B"}
STATUS_COLORS = {"verified": "#22D3A7", "inferred": "#60A5FA", "unverified": "#F59E0B", "needs_review": "#FB923C", "contradicted": "#F87171"}
COMP_NAMES = {"strategic": "Strategic", "capability": "Capability", "market_access": "Market access", "trust": "Trust", "feasibility": "Feasibility"}
COMP_WEIGHTS = {"strategic": 30, "capability": 25, "market_access": 20, "trust": 15, "feasibility": 10}

st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
.stApp, .stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5 {{ font-family: 'Inter', system-ui, sans-serif; }}
.block-container {{ padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1500px; }}
[data-testid="stSidebar"] {{ background: #0A0F1D; border-right: 1px solid {C['line']}; }}
[data-testid="stHeader"] {{ background: transparent; }}
h1, h2, h3 {{ letter-spacing: -0.02em; }}
.ps-brand {{ display:flex; align-items:center; gap:10px; margin: 2px 0 2px; }}
.ps-logo {{ width:34px; height:34px; border-radius:10px; background:linear-gradient(135deg,#22D3A7,#6366F1); display:flex; align-items:center; justify-content:center; font-weight:800; color:#06101c; font-size:18px; }}
.ps-brand b {{ font-size:19px; letter-spacing:-0.02em; }}
.ps-tag {{ color:{C['mute']}; font-size:12px; margin: 0 0 14px; }}
.ps-hero {{ padding: 26px 30px; border-radius: 18px; border:1px solid {C['line']};
  background: radial-gradient(1200px 300px at 0% 0%, rgba(34,211,167,.16), transparent 60%), radial-gradient(900px 300px at 100% 0%, rgba(99,102,241,.18), transparent 60%), {C['card']}; margin-bottom: 18px; }}
.ps-hero h1 {{ margin:0 0 6px; font-size: 34px; font-weight: 800; }}
.ps-hero p {{ margin:0; color:{C['mute']}; font-size:15px; max-width: 900px; line-height:1.55; }}
.ps-card {{ background:{C['card']}; border:1px solid {C['line']}; border-radius:16px; padding:16px 18px; }}
.ps-card h4 {{ margin:0 0 10px; font-size:13px; font-weight:600; color:{C['mute']}; text-transform:uppercase; letter-spacing:.08em; }}
.ps-kpi {{ background:{C['card']}; border:1px solid {C['line']}; border-radius:16px; padding:14px 16px; height:100%; position:relative; overflow:hidden; }}
.ps-kpi:before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--accent,{C['accent']}); }}
.ps-kpi .l {{ font-size:11.5px; color:{C['mute']}; text-transform:uppercase; letter-spacing:.08em; font-weight:600; }}
.ps-kpi .v {{ font-size:28px; font-weight:800; letter-spacing:-0.03em; margin-top:2px; line-height:1.15; }}
.ps-kpi .s {{ font-size:12px; color:{C['mute']}; margin-top:2px; }}
.ps-badge {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:12px; font-weight:600; border:1px solid; margin:0 6px 4px 0; white-space:nowrap; }}
.ps-flag {{ display:inline-block; padding:3px 10px; border-radius:8px; font-size:12px; background:rgba(248,113,113,.12); color:#FCA5A5; border:1px solid rgba(248,113,113,.35); margin:0 6px 4px 0; }}
.ps-steps {{ display:flex; gap:8px; margin: 4px 0 18px; }}
.ps-step {{ flex:1; padding:12px 14px; border-radius:14px; border:1px solid {C['line']}; background:{C['card']}; }}
.ps-step .n {{ font-size:11px; color:{C['mute']}; font-weight:700; letter-spacing:.1em; }}
.ps-step .t {{ font-size:15px; font-weight:700; margin-top:2px; }}
.ps-step .d {{ font-size:11.5px; color:{C['mute']}; margin-top:2px; }}
.ps-step.done {{ border-color: rgba(34,211,167,.55); background: linear-gradient(180deg, rgba(34,211,167,.10), {C['card']}); }}
.ps-step.done .n {{ color:{C['accent']}; }}
.ps-step.active {{ border-color:#60A5FA; box-shadow:0 0 0 1px rgba(96,165,250,.4), 0 0 24px rgba(96,165,250,.18); }}
.ps-step.active .n {{ color:#60A5FA; }}
.ps-log {{ background:#070B16; border:1px solid {C['line']}; border-radius:14px; padding:14px 16px; font: 12.5px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color:#B8C7E8; max-height:360px; overflow:auto; white-space:pre-wrap; }}
.ps-log .a {{ color:{C['accent']}; }} .ps-log .w {{ color:#F59E0B; }} .ps-log .e {{ color:#F87171; }}
.ps-bar {{ height:8px; border-radius:99px; background:#1B2744; overflow:hidden; margin:6px 0 4px; }}
.ps-bar > div {{ height:100%; border-radius:99px; }}
.ps-comp {{ padding:10px 0; border-bottom:1px solid {C['line']}; }}
.ps-comp:last-child {{ border-bottom:0; }}
.ps-comp .h {{ display:flex; justify-content:space-between; font-weight:600; }}
.ps-comp .w {{ color:{C['mute']}; font-size:12px; font-weight:500; }}
.ps-comp .why {{ color:#B8C7E8; font-size:13px; line-height:1.5; }}
.ps-chip {{ font: 11px ui-monospace, Consolas, monospace; color:{C['mute']}; background:#0B1226; border:1px solid {C['line']}; border-radius:6px; padding:1px 6px; margin-right:4px; }}
.ps-quote {{ border-left:3px solid {C['accent']}; padding:2px 12px; color:#B8C7E8; font-size:13px; margin:6px 0; }}
.ps-pill {{ display:inline-block; padding:2px 10px; border-radius:99px; font-size:11.5px; font-weight:700; background:#1B2744; color:#C9D6F2; }}
.ps-demo {{ padding:10px 14px; border-radius:12px; border:1px solid rgba(96,165,250,.45); background:rgba(96,165,250,.08); color:#BBD3FF; font-size:13px; margin-bottom:14px; }}
div[data-testid="stTabs"] button {{ font-weight:600; }}
.stButton > button[kind="primary"] {{ background: linear-gradient(135deg,#22D3A7,#3B82F6); color:#04121c; border:0; font-weight:700; border-radius:12px; padding:.55rem 1.3rem; }}
.stButton > button {{ border-radius:12px; }}
[data-testid="stMetric"] {{ background:{C['card']}; border:1px solid {C['line']}; border-radius:14px; padding:10px 14px; }}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers
def esc(x) -> str:
    return _html.escape(str(x if x is not None else ""))


def rec_key(rec) -> str:
    r = str(rec or "")
    if r.startswith("Pursue"):
        return "pursue"
    if r.startswith("Worth"):
        return "worth"
    if r.startswith("Approach"):
        return "caution"
    if r.startswith("Manual"):
        return "manual"
    if r.startswith("Held"):
        return "held"
    return "depri"


def badge(text, color) -> str:
    return f'<span class="ps-badge" style="color:{color};border-color:{color}55;background:{color}18">{esc(text)}</span>'


def kpi(label, value, sub="", accent=C["accent"]) -> str:
    return f'<div class="ps-kpi" style="--accent:{accent}"><div class="l">{esc(label)}</div><div class="v">{esc(value)}</div><div class="s">{esc(sub)}</div></div>'


def short_name(n: str) -> str:
    n = re.sub(r"\b(Pvt\.?|Private|Ltd\.?|Limited|LLP|India|Solutions|Services)\b\.?", "", n or "", flags=re.I)
    n = re.sub(r"[\s,\-]+$", "", re.sub(r"\s+", " ", n)).strip()
    return (n or "")[:26]


def fit_ring(score, color) -> str:
    s = 0 if score is None else max(0, min(100, float(score)))
    circ = 2 * 3.14159 * 42
    return (f'<svg width="120" height="120" viewBox="0 0 100 100"><circle cx="50" cy="50" r="42" stroke="#1B2744" stroke-width="9" fill="none"/>'
            f'<circle cx="50" cy="50" r="42" stroke="{color}" stroke-width="9" fill="none" stroke-linecap="round" '
            f'stroke-dasharray="{circ * s / 100:.1f} {circ:.1f}" transform="rotate(-90 50 50)"/>'
            f'<text x="50" y="52" text-anchor="middle" font-size="25" font-weight="800" fill="#E5EDFF" font-family="Inter,sans-serif">{"-" if score is None else f"{s:.0f}"}</text>'
            f'<text x="50" y="66" text-anchor="middle" font-size="7.5" fill="#8FA3C8" font-family="Inter,sans-serif">FIT SCORE</text></svg>')


def style_chart(ch, height=None):
    ch = ch.configure(background="rgba(0,0,0,0)").configure_view(strokeWidth=0).configure_axis(
        labelColor="#8FA3C8", titleColor="#8FA3C8", gridColor="#1B2744", domainColor="#22304F", tickColor="#22304F", labelFontSize=12)
    return ch.properties(height=height) if height else ch


def launch(run_id: str, request: str, ceiling: float, crash_after: str | None = None, simulate_failure: str | None = None) -> None:
    cmd = [sys.executable, str(ROOT / "pipeline.py"), "--run-id", run_id, "--request", request, "--credit-ceiling", str(ceiling)]
    if crash_after:
        cmd += ["--crash-after", crash_after]
    if simulate_failure:
        cmd += ["--simulate-failure", simulate_failure]
    subprocess.Popen(cmd, cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def runs() -> list:
    return store.query("SELECT run_id, created_at, status, request FROM runs WHERE run_id NOT IN ('smoke','explore') "
                       "AND run_id NOT LIKE 't-%' ORDER BY created_at DESC")


def final_for(run_id):
    return store.get_stage(run_id, "final") if run_id else None


# ------------------------------------------------------------------ sidebar
st.sidebar.markdown('<div class="ps-brand"><div class="ps-logo">P</div><b>PartnerScout</b></div>'
                    '<div class="ps-tag">Strategic partnership intelligence<br>discover · verify · evaluate · recommend</div>', unsafe_allow_html=True)
PAGES = ["Brief", "Workspace", "Partners", "Brief generator"]
page = st.sidebar.radio("Screen", PAGES, label_visibility="collapsed",
                        format_func=lambda p: {"Brief": "1 · Partnership brief", "Workspace": "2 · Intelligence workspace",
                                               "Partners": "3 · Partner dashboard", "Brief generator": "4 · Brief generator"}[p])
rs = runs()
labels = {r["run_id"]: f'{r["run_id"]}  ·  {r["status"]}' for r in rs}
st.sidebar.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
HEADLINE_RUN = "demo3"  # the run the README reports on
current = st.sidebar.selectbox("Run", list(labels), format_func=lambda k: labels[k],
                               index=list(labels).index(HEADLINE_RUN) if HEADLINE_RUN in labels else 0) if rs else None
if "active" in st.session_state and st.session_state["active"] in labels:
    current = st.session_state["active"]
if DEMO:
    st.sidebar.markdown('<div class="ps-demo">Read-only demo of saved real runs. New runs are disabled so nobody can spend API credits.</div>', unsafe_allow_html=True)
st.sidebar.caption("Nothing is sent to anyone. Drafts stay drafts; approving only records a person's decision.")

PIPE = [("01", "Discover", "ranked search, dedupe, screen"), ("02", "Investigate", "identity, enrich, site, news"),
        ("03", "Verify", "quote-checked evidence ledger"), ("04", "Evaluate", "fit score + mutual value"), ("05", "Recommend", "ranked brief + drafts")]


def stepper(states: list[str]) -> None:
    cells = "".join(f'<div class="ps-step {s}"><div class="n">{n}</div><div class="t">{t}</div><div class="d">{d}</div></div>'
                    for (n, t, d), s in zip(PIPE, states))
    st.markdown(f'<div class="ps-steps">{cells}</div>', unsafe_allow_html=True)


def run_states(run_id: str, status: str) -> list[str]:
    if status == "complete":
        return ["done"] * 5
    have = {r["stage"]: r["n"] for r in store.query("SELECT stage, COUNT(*) n FROM stages WHERE run_id=? GROUP BY stage", (run_id,))}
    expect = 6
    marks = [have.get("screen", 0) >= 1, have.get("research", 0) >= expect, have.get("claims", 0) >= expect, have.get("result", 0) >= expect, bool(have.get("final"))]
    states, seen_active = [], False
    for m in marks:
        if m:
            states.append("done")
        elif not seen_active and status == "running":
            states.append("active")
            seen_active = True
        else:
            states.append("")
    return states


# ================================================================== 1. BRIEF
if page == "Brief":
    st.markdown('<div class="ps-hero"><h1>Find the partners worth pursuing, and prove why.</h1>'
                '<p>Describe the partnership you want. PartnerScout discovers candidates on live company data, checks every claim against its source, '
                'detects competitive conflicts and writes a mutual-value brief with a draft first message. It never contacts anyone.</p></div>', unsafe_allow_html=True)
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("##### Your request")
        req = st.text_area("Request", DEMO_REQUEST, height=150, label_visibility="collapsed")
        with st.expander("Structured fields (optional, appended to the request)"):
            c1, c2 = st.columns(2)
            company = c1.text_input("Requesting company / website")
            industry = c1.text_input("Target industry")
            geo_in = c1.text_input("Geography")
            ptype = c2.text_input("Desired partner type")
            caps = c2.text_input("Required capabilities")
            extra = c2.text_input("Size or other constraints")
        c1, c2, c3 = st.columns(3)
        ceiling = c1.number_input("Credit ceiling for this run", 20, 2000, 300)
        crash = c2.selectbox("Demo: crash after stage", ["(none)", "discover", "screen", "enrich", "research", "claims"])
        fail = c3.selectbox("Demo: tool outage", ["(none)", "enrich"])
        if st.button("Run PartnerScout", type="primary", disabled=DEMO, help="Disabled in the read-only demo" if DEMO else None):
            parts = [req] + [f"{k}: {v}" for k, v in [("Requesting company", company), ("Target industry", industry), ("Geography", geo_in),
                                                      ("Partner type", ptype), ("Required capabilities", caps), ("Constraints", extra)] if v]
            rid = f"run-{uuid.uuid4().hex[:6]}"
            store.create_run(rid, " | ".join(parts))
            launch(rid, " | ".join(parts), ceiling, None if crash == "(none)" else crash, None if fail == "(none)" else fail)
            st.session_state["active"] = rid
            st.success(f"Started {rid}. Open the Intelligence workspace to watch it work.")
        if DEMO:
            st.markdown('<div class="ps-demo">This is a read-only demo. Pick a saved run in the sidebar, then open <b>Partner dashboard</b> to explore the real results.</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="ps-card"><h4>How a job runs</h4>'
                    '<div style="line-height:1.9;font-size:14px">'
                    '<b style="color:#22D3A7">01 Discover</b> &nbsp;ranked company search, duplicates collapsed<br>'
                    '<b style="color:#22D3A7">02 Investigate</b> &nbsp;identity, enrichment, own site, news<br>'
                    '<b style="color:#22D3A7">03 Verify</b> &nbsp;every claim needs a verbatim quote that exists in its source<br>'
                    '<b style="color:#22D3A7">04 Evaluate</b> &nbsp;5-part fit score, conflict check, mutual value<br>'
                    '<b style="color:#22D3A7">05 Recommend</b> &nbsp;ranked brief, decision-maker, draft message</div></div>', unsafe_allow_html=True)
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        st.markdown('<div class="ps-card"><h4>Guardrails</h4><div style="line-height:1.8;font-size:13.5px;color:#B8C7E8">'
                    '• Unknown is never scored as zero; confidence is separate from fit<br>'
                    '• A tool failure holds a company for review, it is never read as "no evidence"<br>'
                    '• Per-run credit and time ceilings; every paid call is in the ledger<br>'
                    '• Crash? Re-run the same id: finished stages are not repeated<br>'
                    '• Drafts only. Approval records intent, nothing is sent</div></div>', unsafe_allow_html=True)

# ================================================================== 2. WORKSPACE
elif page == "Workspace":
    st.markdown("## Intelligence workspace")
    if not current:
        st.info("No runs yet.")
        st.stop()
    r = store.query("SELECT * FROM runs WHERE run_id=?", (current,))[0]
    led = store.ledger_totals(current)
    stepper(run_states(current, r["status"]))
    c1, c2, c3, c4, c5 = st.columns(5)
    status_color = {"complete": "#22D3A7", "running": "#60A5FA"}.get(r["status"], "#F59E0B")
    c1.markdown(kpi("Status", r["status"], current, status_color), unsafe_allow_html=True)
    c2.markdown(kpi("Crustdata credits", f'{led["credits"]:.2f}', "every attempt counted"), unsafe_allow_html=True)
    c3.markdown(kpi("Logged calls", led["calls"], "Crustdata + model", "#6366F1"), unsafe_allow_html=True)
    c4.markdown(kpi("Served from cache", int(led["cache_hits"]), "no credits spent", "#60A5FA"), unsafe_allow_html=True)
    c5.markdown(kpi("Model cost", f'${led["usd"]:.3f}', "list price; free tier billed $0", "#F59E0B"), unsafe_allow_html=True)
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    if r["error"]:
        st.warning(r["error"])
    fin_now = final_for(current)
    held = [p["company"]["name"] for p in (fin_now or {}).get("ranked", []) if p.get("held_for_review")]
    if held:
        st.warning(f"Held for review because a tool failed (not treated as 'no evidence'): {', '.join(held)}")
    if not DEMO:
        if r["status"] in ("crashed", "paused_budget", "paused_credits") and st.button("Resume this run (continues from the last checkpoint, no repeated paid calls)"):
            launch(current, r["request"], 300)
            st.rerun()
        if held and st.button("Retry held candidates (finished stages are not repeated)"):
            launch(current, r["request"], 300)
            st.rerun()
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("##### Execution log")
        logs = store.query("SELECT output_json FROM stages WHERE run_id=? AND stage='_log' ORDER BY item", (current,))
        lines = []
        for x in logs[-60:]:
            m = esc(json.loads(x["output_json"])["msg"])
            cls = "e" if any(k in m for k in ("[crash]", "failed")) else "w" if any(k in m for k in ("[recovery]", "[paused]")) else "a" if m.startswith(("[done]", "[fit]")) else ""
            lines.append(f'<span class="{cls}">{m}</span>' if cls else m)
        st.markdown(f'<div class="ps-log">{"<br>".join(lines) or "(waiting)"}</div>', unsafe_allow_html=True)
    with right:
        st.markdown("##### Where the credits went")
        by = store.query("SELECT endpoint, SUM(credits) c, COUNT(*) n FROM calls WHERE run_id=? AND service='crustdata' GROUP BY endpoint ORDER BY c DESC", (current,))
        if by:
            df = pd.DataFrame([dict(x) for x in by])
            ch = alt.Chart(df).mark_bar(cornerRadiusEnd=5, color=C["accent"]).encode(
                y=alt.Y("endpoint:N", sort="-x", title=None), x=alt.X("c:Q", title="credits"), tooltip=["endpoint", alt.Tooltip("c:Q", title="credits"), alt.Tooltip("n:Q", title="calls")])
            st.altair_chart(style_chart(ch, 230), width="stretch")
        else:
            st.caption("No paid calls yet.")
    st.markdown("##### Call ledger")
    calls = store.query("SELECT ts, service, endpoint, status, credits, cost_usd, latency_ms, cached, attempt, error FROM calls WHERE run_id=? ORDER BY id DESC LIMIT 80", (current,))
    if calls:
        ldf = pd.DataFrame([dict(c) for c in calls])
        ldf["ts"] = ldf["ts"].map(lambda t: time.strftime("%H:%M:%S", time.localtime(t)))
        st.dataframe(ldf, width="stretch", hide_index=True, height=300)
    if r["status"] == "running":
        time.sleep(3)
        st.rerun()

# ================================================================== 3. PARTNER DASHBOARD
elif page == "Partners":
    fin = final_for(current)
    if not fin:
        st.info("This run has no final result yet.")
        st.stop()
    ranked = fin["ranked"]
    done = [p for p in ranked if not p.get("held_for_review")]
    claims_all = [c for p in done for c in p["claims"]]
    ver = sum(1 for c in claims_all if c["status"] == "verified")
    checkable = ver + sum(1 for c in claims_all if c["status"] in ("unverified", "contradicted"))
    top = done[0] if done else None
    led = fin.get("ledger", {})
    brief = fin.get("brief", {})

    st.markdown(f'<div class="ps-hero" style="padding:20px 26px"><h1 style="font-size:28px">Partner dashboard</h1>'
                f'<p>{esc(brief.get("objective") or "")} &nbsp;·&nbsp; target: {esc(brief.get("target_industry"))}, {esc(brief.get("country"))} &nbsp;·&nbsp; run <b>{esc(current)}</b></p></div>', unsafe_allow_html=True)
    k = st.columns(5)
    k[0].markdown(kpi("Candidates discovered", fin.get("n_candidates", 0), "unique, duplicates collapsed"), unsafe_allow_html=True)
    k[1].markdown(kpi("Investigated", f"{len(done)}/{len(ranked)}", "identity-resolved, evidence-checked", "#6366F1"), unsafe_allow_html=True)
    k[2].markdown(kpi("Claims verified", f"{ver}", f"{100 * ver / max(checkable, 1):.0f}% of checkable claims have a matching quote", "#22D3A7"), unsafe_allow_html=True)
    k[3].markdown(kpi("Top fit", f'{top["fit"]["score"]:.1f}' if top else "-", short_name(top["company"]["name"]) if top else "", "#60A5FA"), unsafe_allow_html=True)
    k[4].markdown(kpi("Cost of this job", f'{led.get("credits", 0):.1f} credits', f'+ ~${led.get("usd", 0):.3f} model usage', "#F59E0B"), unsafe_allow_html=True)
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ---- map + leaderboard
    cands = store.get_stage(current, "discover") or []
    pts, placed, unplaced = geo.build_points(ranked, cands, REC_COLORS, rec_key)
    mcol, lcol = st.columns([3, 2], gap="large")
    with mcol:
        st.markdown("##### Where the partners are")
        st.iframe(geo.map_html(pts), height=440)
        st.caption(f"{placed} placed by city; {unplaced} not placed because their city text did not match a known city (we never guess). "
                   "Markers are jittered inside the city, so this shows city, not address.")
    with lcol:
        st.markdown("##### Ranking")
        rows = [{"Partner": short_name(p["company"]["name"]), "Fit": p["fit"]["score"], "Recommendation": p.get("recommendation") or "",
                 "Confidence": (p.get("evidence_confidence") or {}).get("level", "-"), "key": rec_key(p.get("recommendation"))}
                for p in done]
        if rows:
            df = pd.DataFrame(rows)
            recs = list(dict.fromkeys(df["Recommendation"]))
            scale = alt.Scale(domain=recs, range=[REC_COLORS[rec_key(x)] for x in recs])
            order_p = list(df.sort_values("Fit", ascending=False)["Partner"])
            base = alt.Chart(df).encode(y=alt.Y("Partner:N", sort=order_p, title=None, axis=alt.Axis(labelLimit=170)),
                                        x=alt.X("Fit:Q", scale=alt.Scale(domain=[0, 100]), title="fit score (0-100)"))
            bars = base.mark_bar(cornerRadiusEnd=6, size=22).encode(color=alt.Color("Recommendation:N", scale=scale, legend=alt.Legend(orient="bottom", title=None, labelColor="#B8C7E8", labelLimit=300, columns=1)),
                                                                     tooltip=["Partner", "Fit", "Recommendation", "Confidence"])
            value_labels = base.mark_text(align="left", dx=5, color="#E5EDFF", fontWeight="bold").encode(text=alt.Text("Fit:Q", format=".0f"))
            st.altair_chart(style_chart(bars + value_labels, 300), width="stretch")

    # ---- funnel + heatmap
    f1, f2 = st.columns([2, 3], gap="large")
    with f1:
        st.markdown("##### From discovery to recommendation")
        screened = store.get_stage(current, "screen") or []
        useful = sum(1 for p in done if rec_key(p.get("recommendation")) in ("pursue", "worth"))
        fun = pd.DataFrame([{"Step": "1 Discovered", "n": fin.get("n_candidates", 0)}, {"Step": "2 Screened", "n": len(screened)},
                            {"Step": "3 Investigated", "n": len(done)}, {"Step": "4 Worth pursuing", "n": useful}])
        ch = alt.Chart(fun).mark_bar(cornerRadiusEnd=6, size=26, color="#6366F1").encode(
            y=alt.Y("Step:N", sort=None, title=None), x=alt.X("n:Q", title=None), tooltip=["Step", "n"])
        tx = alt.Chart(fun).mark_text(align="left", dx=5, color="#E5EDFF", fontWeight="bold").encode(y=alt.Y("Step:N", sort=None), x="n:Q", text="n:Q")
        st.altair_chart(style_chart(ch + tx, 200), width="stretch")
    with f2:
        st.markdown("##### Score matrix (every number has a written reason in the profile)")
        recs_l = []
        for p in done:
            for ck, cn in COMP_NAMES.items():
                v = (p["components"].get(ck) or {}).get("score")
                recs_l.append({"Partner": short_name(p["company"]["name"]), "Component": f"{cn.replace('Market access', 'Market')} {COMP_WEIGHTS[ck]}%", "Score": v, "Label": "-" if v is None else f"{v:.0f}"})
        if recs_l:
            hm = pd.DataFrame(recs_l)
            order = [f"{cn.replace('Market access', 'Market')} {COMP_WEIGHTS[ck]}%" for ck, cn in COMP_NAMES.items()]
            h = alt.Chart(hm).encode(x=alt.X("Component:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, orient="top", labelLimit=110, labelOverlap=False, labelFontSize=11)),
                                     y=alt.Y("Partner:N", sort=[short_name(p["company"]["name"]) for p in done], title=None, axis=alt.Axis(labelLimit=160)))
            rect = h.mark_rect(cornerRadius=5, stroke="#0B1020", strokeWidth=3).encode(
                color=alt.condition("isValid(datum.Score)", alt.Color("Score:Q", scale=alt.Scale(domain=[30, 60, 90], range=["#7F1D1D", "#92400E", "#0F766E"]), legend=None), alt.value("#1E293B")),
                tooltip=["Partner", "Component", "Label"])
            txt = h.mark_text(color="#E5EDFF", fontWeight="bold").encode(text="Label:N")
            st.altair_chart(style_chart(rect + txt, 60 + 34 * len(done)), width="stretch")
            st.caption("Unknown is shown as '-' and left out of the weighted total; it is never counted as zero.")

    # ---- partner profile
    st.markdown("---")
    names = [p["company"]["name"] for p in ranked]
    pick = st.selectbox("Open partner profile", names, label_visibility="visible")
    p = ranked[names.index(pick)]
    if p.get("held_for_review"):
        st.error(f'Held for review: {p.get("error")}')
        st.stop()
    key = rec_key(p.get("recommendation"))
    col = REC_COLORS[key]
    co = p["company"]
    conf = (p.get("evidence_confidence") or {}).get("level", "-")
    h1, h2 = st.columns([1, 5])
    h1.markdown(fit_ring(p["fit"]["score"], col), unsafe_allow_html=True)
    flags = "".join(f'<span class="ps-flag">{esc(f)}</span>' for f in p.get("flags", []))
    ov = p.get("competitive_overlap") or {}
    h2.markdown(f'<div style="font-size:26px;font-weight:800;letter-spacing:-0.02em">{esc(co["name"])}</div>'
                f'<div style="color:{C["mute"]};font-size:13px;margin:2px 0 8px">{esc(co.get("domain"))} · {esc(co.get("city"))} · {esc(co.get("size"))} employees · {esc((p.get("partnership_model") or {}).get("model") or "")}</div>'
                f'{badge(p.get("recommendation"), col)}{badge("Evidence confidence: " + str(conf), "#60A5FA")}{badge("Conflict: " + str(ov.get("level", "none")), "#F59E0B" if ov.get("level") in ("medium", "high") else "#64748B")}'
                f'<div style="margin-top:6px">{flags}</div>', unsafe_allow_html=True)
    if co.get("description"):
        st.caption(co["description"][:420])
    t1, t2, t3, t4 = st.tabs(["Why this score", "Mutual value", "Evidence", "Decision-maker & draft"])
    with t1:
        blocks = []
        for ck, cn in COMP_NAMES.items():
            v = (p["components"].get(ck) or {})
            sc = v.get("score")
            colr = "#22D3A7" if (sc or 0) >= 70 else "#F59E0B" if (sc or 0) >= 50 else "#F87171"
            width = 0 if sc is None else sc
            ids = "".join(f'<span class="ps-chip">{esc(i)}</span>' for i in v.get("claim_ids", []))
            blocks.append(f'<div class="ps-comp"><div class="h"><span>{cn} <span class="w">weight {COMP_WEIGHTS[ck]}%</span></span><span style="color:{colr}">{"unknown" if sc is None else f"{sc:.0f}"}</span></div>'
                          f'<div class="ps-bar"><div style="width:{width}%;background:{colr}"></div></div><div class="why">{esc(v.get("why"))}</div><div style="margin-top:4px">{ids}</div></div>')
        st.markdown(f'<div class="ps-card">{"".join(blocks)}</div>', unsafe_allow_html=True)
        adj = (p["fit"].get("adjustments") or {})
        st.markdown(f'<div class="ps-card" style="margin-top:10px"><h4>Competitive conflict</h4><div style="font-size:14px">'
                    f'<b>{esc(ov.get("level", "none"))}</b>{" · penalty " + str(adj.get("conflict_penalty")) + " points off Strategic" if adj.get("conflict_penalty") else ""} — {esc(ov.get("why"))}</div></div>', unsafe_allow_html=True)
    with t2:
        mv = p.get("mutual_value") or {}
        a, b = st.columns(2)
        for colw, title, key2 in ((a, "Value to the requester", "to_requester"), (b, "Value to the partner", "to_partner")):
            items = "".join(f'<div style="margin-bottom:8px">• {esc(x["point"])} {badge(x.get("basis", "inferred"), "#22D3A7" if x.get("basis") == "verified" else "#60A5FA")}</div>' for x in mv.get(key2, []))
            colw.markdown(f'<div class="ps-card"><h4>{title}</h4><div style="font-size:14px;line-height:1.6">{items or "—"}</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="ps-card" style="margin-top:10px"><h4>Rationale (a hypothesis, not confirmed interest)</h4><div style="font-size:14px;line-height:1.6">{esc(mv.get("rationale"))}</div></div>', unsafe_allow_html=True)
    with t3:
        cl = p["claims"]
        cnt = pd.DataFrame([{"status": s, "n": sum(1 for c in cl if c["status"] == s)} for s in STATUS_COLORS if any(c["status"] == s for c in cl)])
        e1, e2 = st.columns([1, 2], gap="large")
        with e1:
            if len(cnt):
                arc = alt.Chart(cnt).mark_arc(innerRadius=58, stroke="#0B1020", strokeWidth=2).encode(
                    theta="n:Q", color=alt.Color("status:N", scale=alt.Scale(domain=list(STATUS_COLORS), range=list(STATUS_COLORS.values())), legend=alt.Legend(orient="bottom", title=None, labelColor="#B8C7E8")),
                    tooltip=["status", "n"])
                st.altair_chart(style_chart(arc, 250), width="stretch")
            ec = p.get("evidence_confidence") or {}
            st.caption(f'Evidence confidence {conf}: {ec.get("verified", 0)} verified of {ec.get("total", 0)} scored claims '
                       f'(coverage {100 * (ec.get("coverage") or 0):.0f}%), {ec.get("independent_sources", 0)} independent source(s). '
                       'High needs independent corroboration, not just the company\'s own website.')
        with e2:
            for c in cl[:40]:
                sc = STATUS_COLORS.get(c["status"], "#64748B")
                q = f'<div class="ps-quote">“{esc(str(c.get("quote") or "")[:260])}”</div>' if c.get("quote") else ""
                src = esc(c.get("source_url") or "")
                st.markdown(f'<div style="margin-bottom:10px">{badge(c["status"], sc)}<span class="ps-pill">{esc(c["category"])}</span> '
                            f'<span class="ps-chip">{esc(c["claim_id"])}</span><div style="font-size:14px;margin-top:3px">{esc(c["claim"])}</div>{q}'
                            f'<div style="font-size:11.5px;color:{C["mute"]}">{src}</div></div>', unsafe_allow_html=True)
    with t4:
        s = p.get("stakeholder")
        pr = p.get("proposal") or {}
        if s:
            st.markdown(f'<div class="ps-card"><h4>Decision-maker (from the Crustdata record)</h4><div style="font-size:16px;font-weight:700">{esc(s.get("name"))}</div>'
                        f'<div style="color:{C["mute"]}">{esc(s.get("title"))}</div><div style="margin-top:6px;font-size:13px">{esc(s.get("why"))}</div></div>', unsafe_allow_html=True)
        else:
            st.info("I can't verify a decision-maker from the available sources.")
        st.markdown(f'<div class="ps-card" style="margin-top:10px"><h4>Draft first message · {esc(pr.get("status"))}</h4>'
                    f'<div style="font-weight:700;margin-bottom:6px">{esc(pr.get("subject"))}</div><div style="white-space:pre-wrap;font-size:14px;line-height:1.6">{esc(pr.get("body"))}</div></div>', unsafe_allow_html=True)
        oq = p.get("open_questions") or []
        if oq:
            st.markdown('<div class="ps-card" style="margin-top:10px"><h4>A person still has to establish</h4><div style="font-size:14px;line-height:1.7">' + "".join(f"• {esc(x)}<br>" for x in oq) + "</div></div>", unsafe_allow_html=True)

# ================================================================== 4. BRIEF GENERATOR
else:
    fin = final_for(current)
    if not fin:
        st.info("This run has no final result yet.")
        st.stop()
    st.markdown("## Brief generator")
    html_doc = report.build_report(fin)
    done = [p for p in fin["ranked"] if not p.get("held_for_review")]
    head = next((p for p in done if rec_key(p.get("recommendation")) in ("pursue", "worth")), done[0] if done else None)
    a, b = st.columns([3, 2], gap="large")
    with a:
        if head:
            col = REC_COLORS[rec_key(head.get("recommendation"))]
            mv = head.get("mutual_value") or {}
            st.markdown(f'<div class="ps-card" style="border-color:{col}88"><h4>Headline recommendation</h4>'
                        f'<div style="font-size:24px;font-weight:800">{esc(head["company"]["name"])}</div>'
                        f'<div style="margin:6px 0">{badge(head.get("recommendation"), col)}{badge("fit " + str(head["fit"]["score"]), "#60A5FA")}{badge("evidence " + str((head.get("evidence_confidence") or {}).get("level")), "#22D3A7")}</div>'
                        f'<div style="font-size:14px;line-height:1.6;color:#B8C7E8">{esc(mv.get("rationale"))}</div></div>', unsafe_allow_html=True)
    with b:
        st.download_button("Download HTML report (print to PDF from the browser)", html_doc, file_name=f"{current}.html", mime="text/html", type="primary")
        st.caption("Every claim in the report links to its source and quote. Drafts are labelled DRAFT, not sent.")
    st.markdown("##### Approval gate")
    st.caption("Proposal drafts are never sent. Approving records a person's decision and contacts no one.")
    for p in fin["ranked"]:
        if p.get("held_for_review") or not p.get("proposal"):
            continue
        cid = str(p["company"]["id"])
        done_ap = store.query("SELECT 1 FROM approvals WHERE run_id=? AND company_id=?", (current, cid))
        c1, c2 = st.columns([5, 1])
        with c1:
            with st.expander(f'{p["company"]["name"]}  ·  {p.get("recommendation")}  ·  “{p["proposal"].get("subject")}”'):
                st.markdown(f'<div style="white-space:pre-wrap;font-size:14px;line-height:1.6">{esc(p["proposal"].get("body"))}</div>', unsafe_allow_html=True)
        if done_ap:
            c2.markdown(badge("approved · not sent", "#22D3A7"), unsafe_allow_html=True)
        elif c2.button("Approve draft", key=f"ap{cid}"):
            store.execute("INSERT INTO approvals(run_id,company_id,action,ts,note) VALUES (?,?,?,?,?)", (current, cid, "approve_draft", time.time(), "recorded only; nothing sent"))
            st.rerun()
    st.markdown("##### Report preview")
    st.iframe(html_doc, height=900)
