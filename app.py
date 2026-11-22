"""PartnerScout UI. Run: streamlit run app.py

Four screens: Partnership Brief -> Intelligence Workspace -> Partner Dashboard -> Brief Generator.
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
import streamlit.components.v1 as components

import ecosystem
import geo
import report
import store
import validation
from pipeline import DEMO_REQUEST

ROOT = Path(__file__).parent
eco_map = components.declare_component("ecosystem_map", path=str(ROOT / "components" / "ecosystem_map"))
DEMO = store.DEMO_MODE
VERSION = "v0.1 · ContextCon 05 build"
st.set_page_config(page_title="PartnerScout", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

# ------------------------------------------------------------------ design tokens
T = {"ivory": "#F5F4EF", "white": "#FFFFFF", "navy": "#101F2C", "slate": "#62717D", "emerald": "#167C68", "mint": "#43B99B",
     "gold": "#D5A85B", "line": "#E4E8E5", "ok": "#16845B", "warn": "#C18A35", "err": "#C65353", "soft": "#E6F2EE", "grey": "#9AA6AF"}
REC_COLORS = {"pursue": T["emerald"], "worth": T["mint"], "caution": T["warn"], "manual": T["err"], "held": T["slate"], "depri": T["grey"]}
CORRO = {"self_reported": "self-reported by the company", "independent": "independent source", "database_listing": "directory listing (may copy other data)", "api_record": "Crustdata API record", "weak": "unclassified web page"}
STATUS_COLORS = {"verified": T["ok"], "inferred": "#5B7C99", "unverified": T["warn"], "needs_review": T["gold"], "contradicted": T["err"]}
COMP_NAMES = {"strategic": "Strategic", "capability": "Capability", "market_access": "Market access", "trust": "Trust", "feasibility": "Feasibility"}
COMP_WEIGHTS = {"strategic": 30, "capability": 25, "market_access": 20, "trust": 15, "feasibility": 10}

st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
.stApp, .stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5 {{ font-family: 'Inter', system-ui, sans-serif; }}
.stApp {{ background: {T['ivory']}; color: {T['navy']}; }}
.block-container {{ padding-top: 2rem; padding-bottom: 3rem; max-width: 1380px; }}
[data-testid="stHeader"] {{ background: transparent; }}
h1, h2, h3, h4 {{ letter-spacing: -0.02em; color: {T['navy']}; }}
/* sidebar */
[data-testid="stSidebar"] {{ background: {T['white']}; border-right: 1px solid {T['line']}; }}
[data-testid="stSidebar"] > div:first-child {{ padding-top: 1.1rem; }}
.ps-brand {{ display:flex; align-items:center; gap:10px; }}
.ps-logo {{ width:32px; height:32px; border-radius:9px; background:{T['emerald']}; display:flex; align-items:center; justify-content:center; font-weight:800; color:#fff; font-size:16px; }}
.ps-brand b {{ font-size:18px; letter-spacing:-0.02em; color:{T['navy']}; }}
.ps-tag {{ color:{T['slate']}; font-size:12.5px; margin: 6px 0 18px 42px; }}
[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{ padding: 9px 12px; border-radius: 9px; border: 1px solid transparent; width: 100%; cursor: pointer; transition: background .12s; }}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: {T['ivory']}; }}
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {{ display: none; }}
[data-testid="stSidebar"] [role="radiogroup"] label p {{ font-size: 14px; font-weight: 500; color: {T['slate']}; }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{ background: {T['soft']}; border-color: #CBE6DC; }}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ color: {T['emerald']}; font-weight: 700; }}
.ps-side-card {{ border:1px solid {T['line']}; border-radius:12px; padding:12px 14px; background:{T['ivory']}; margin-top:10px; }}
.ps-side-card .k {{ font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:{T['slate']}; font-weight:600; }}
.ps-side-card .v {{ font-size:14px; font-weight:600; margin-top:2px; }}
/* page header */
.ps-head h1 {{ font-size: 32px; font-weight: 800; margin: 0 0 6px; }}
.ps-head p {{ color: {T['slate']}; font-size: 15.5px; margin: 0 0 22px; max-width: 760px; line-height: 1.55; }}
.ps-eyebrow {{ color:{T['emerald']}; font-size:12px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; margin-bottom:6px; }}
/* cards */
.ps-card {{ background:{T['white']}; border:1px solid {T['line']}; border-radius:14px; padding:18px 20px; box-shadow: 0 1px 2px rgba(16,31,44,.04); }}
.ps-card h4 {{ margin:0 0 12px; font-size:12px; font-weight:700; color:{T['slate']}; text-transform:uppercase; letter-spacing:.09em; }}
.ps-kpi {{ background:{T['white']}; border:1px solid {T['line']}; border-radius:14px; padding:14px 18px; height:100%; box-shadow: 0 1px 2px rgba(16,31,44,.04); }}
.ps-kpi .l {{ font-size:11.5px; color:{T['slate']}; text-transform:uppercase; letter-spacing:.08em; font-weight:600; }}
.ps-kpi .v {{ font-size:30px; font-weight:800; letter-spacing:-0.03em; margin-top:2px; line-height:1.15; color:var(--c,{T['navy']}); }}
.ps-kpi .s {{ font-size:12.5px; color:{T['slate']}; margin-top:2px; }}
.ps-badge {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:600; border:1px solid; margin:0 6px 4px 0; white-space:nowrap; }}
.ps-risk {{ display:inline-block; padding:2px 9px; border-radius:7px; font-size:12px; font-weight:500; margin:0 5px 4px 0; background:#FBF1E0; color:#8A6420; border:1px solid #EBD5A8; }}
.ps-risk.red {{ background:#FBE9E9; color:{T['err']}; border-color:#F0C4C4; }}
.ps-risk.green {{ background:{T['soft']}; color:{T['emerald']}; border-color:#CBE6DC; }}
.ps-chip {{ font: 11px ui-monospace, Consolas, monospace; color:{T['slate']}; background:{T['ivory']}; border:1px solid {T['line']}; border-radius:6px; padding:1px 6px; margin-right:4px; }}
.ps-pill {{ display:inline-block; padding:1px 9px; border-radius:99px; font-size:11.5px; font-weight:600; background:{T['ivory']}; color:{T['slate']}; border:1px solid {T['line']}; }}
/* tracker */
.ps-track {{ display:flex; align-items:center; margin: 4px 0 6px; }}
.ps-node {{ display:flex; flex-direction:column; align-items:center; gap:6px; min-width:110px; }}
.ps-dot {{ width:30px; height:30px; border-radius:50%; border:2px solid {T['line']}; background:#fff; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; color:{T['slate']}; }}
.ps-node.done .ps-dot {{ background:{T['emerald']}; border-color:{T['emerald']}; color:#fff; }}
.ps-node.active .ps-dot {{ border-color:{T['emerald']}; color:{T['emerald']}; box-shadow:0 0 0 4px {T['soft']}; }}
.ps-node .nm {{ font-size:13px; font-weight:600; color:{T['slate']}; }}
.ps-node.done .nm, .ps-node.active .nm {{ color:{T['navy']}; }}
.ps-line {{ flex:1; height:2px; background:{T['line']}; margin-bottom:22px; }}
.ps-line.done {{ background:{T['emerald']}; }}
.ps-prog {{ height:6px; background:{T['line']}; border-radius:99px; overflow:hidden; }} .ps-prog > div {{ height:100%; background:{T['emerald']}; border-radius:99px; }}
/* timeline */
.ps-tl {{ display:flex; gap:14px; padding:12px 0; border-bottom:1px solid {T['line']}; }}
.ps-tl:last-child {{ border-bottom:0; }}
.ps-tl .ic {{ width:34px; height:34px; border-radius:10px; background:{T['soft']}; color:{T['emerald']}; display:flex; align-items:center; justify-content:center; font-weight:700; flex:none; }}
.ps-tl .b {{ flex:1; }} .ps-tl .t {{ font-weight:600; font-size:14.5px; }} .ps-tl .d {{ color:{T['slate']}; font-size:13px; margin-top:1px; }}
.ps-status {{ font-size:11.5px; font-weight:700; padding:2px 10px; border-radius:99px; height:fit-content; white-space:nowrap; }}
.s-completed {{ background:{T['soft']}; color:{T['emerald']}; }} .s-running {{ background:#E8EEF8; color:#3B5B8C; }}
.s-pending {{ background:{T['ivory']}; color:{T['slate']}; border:1px solid {T['line']}; }} .s-review {{ background:#FBF1E0; color:#8A6420; }} .s-failed {{ background:#FBE9E9; color:{T['err']}; }}
/* how it works */
.ps-step {{ display:flex; gap:14px; padding:9px 0; position:relative; }}
.ps-step .n {{ width:30px; height:30px; border-radius:50%; background:{T['soft']}; color:{T['emerald']}; font-weight:700; font-size:12px; display:flex; align-items:center; justify-content:center; flex:none; }}
.ps-step:not(:last-child):after {{ content:""; position:absolute; left:14px; top:40px; bottom:-8px; width:2px; background:{T['line']}; }}
.ps-step .t {{ font-weight:600; font-size:14px; }} .ps-step .d {{ color:{T['slate']}; font-size:13px; }}
.ps-guard {{ display:flex; gap:10px; padding:5px 0; font-size:13.5px; color:#2A3B49; }} .ps-guard .ck {{ color:{T['emerald']}; font-weight:800; }}
/* table */
table.ps-table {{ width:100%; border-collapse:separate; border-spacing:0; background:{T['white']}; border:1px solid {T['line']}; border-radius:14px; overflow:hidden; }}
.ps-table th {{ text-align:left; font-size:11.5px; text-transform:uppercase; letter-spacing:.08em; color:{T['slate']}; font-weight:600; padding:11px 14px; background:{T['ivory']}; border-bottom:1px solid {T['line']}; }}
.ps-table td {{ padding:13px 14px; border-bottom:1px solid {T['line']}; vertical-align:middle; font-size:13.5px; }}
.ps-table th:nth-child(1) {{ width:56px; }} .ps-table th:nth-child(2) {{ min-width:210px; }} .ps-table th:nth-child(3) {{ min-width:130px; }}
.ps-table th:nth-child(4) {{ min-width:130px; }} .ps-table th:nth-child(5) {{ min-width:220px; }} .ps-table th:nth-child(6) {{ min-width:190px; }} .ps-table th:nth-child(7) {{ min-width:150px; }}
.ps-tablewrap {{ overflow-x:auto; border-radius:14px; }}
.ps-table tr:last-child td {{ border-bottom:0; }} .ps-table tr:hover td {{ background:#FAFAF7; }}
.ps-rank {{ width:28px; height:28px; border-radius:8px; background:{T['ivory']}; font-weight:700; display:flex; align-items:center; justify-content:center; }}
.ps-rank.top {{ background:{T['gold']}33; color:#7A5A1A; }}
.ps-bar {{ height:7px; border-radius:99px; background:{T['line']}; overflow:hidden; margin-top:4px; width:110px; }} .ps-bar > div {{ height:100%; border-radius:99px; }}
.ps-conf {{ display:inline-flex; gap:3px; vertical-align:middle; margin-right:6px; }} .ps-conf i {{ width:7px; height:14px; border-radius:2px; background:{T['line']}; display:block; }}
/* components */
.ps-comp {{ padding:11px 0; border-bottom:1px solid {T['line']}; }} .ps-comp:last-child {{ border-bottom:0; }}
.ps-comp .h {{ display:flex; justify-content:space-between; font-weight:600; }} .ps-comp .w {{ color:{T['slate']}; font-size:12px; font-weight:500; }}
.ps-comp .why {{ color:#2A3B49; font-size:13px; line-height:1.5; margin-top:3px; }}
.ps-quote {{ border-left:3px solid {T['mint']}; padding:2px 12px; color:#3B4A57; font-size:13px; margin:6px 0; background:{T['ivory']}; border-radius:0 8px 8px 0; }}
.mv-wrap {{ display:grid; grid-template-columns: 1fr 54px 1fr; align-items:stretch; }}
.mv-col {{ background:{T['white']}; border:1px solid {T['line']}; border-radius:14px; padding:16px 18px; }}
.mv-col.l {{ border-top:3px solid {T['emerald']}; }} .mv-col.r {{ border-top:3px solid {T['gold']}; }}
.mv-col h5 {{ margin:0 0 10px; font-size:14px; }}
.mv-mid {{ display:flex; align-items:center; justify-content:center; color:{T['slate']}; font-size:22px; }}
.mv-item {{ margin-bottom:9px; font-size:13.5px; line-height:1.5; }}
.cf-box {{ border:1px solid #EBD5A8; background:#FBF6EA; border-radius:14px; padding:16px 18px; }}
.cf-box h5 {{ margin:0 0 6px; font-size:14.5px; color:#8A6420; }}
.ps-demo {{ padding:10px 14px; border-radius:12px; border:1px solid #CBE6DC; background:{T['soft']}; color:{T['emerald']}; font-size:13px; margin-bottom:14px; }}
div[data-testid="stExpander"] {{ background:{T['white']}; border:1px solid {T['line']}; border-radius:14px; }}
div[data-testid="stExpander"] summary {{ font-weight:600; }}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{ background:{T['emerald']}; color:#fff; border:0; font-weight:600; border-radius:10px; padding:.55rem 1.4rem; transition: background .12s; }}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {{ background:#126654; color:#fff; }}
.stButton > button, .stDownloadButton > button {{ border-radius:10px; }}
div[data-testid="stTabs"] button {{ font-weight:600; }}
textarea, input {{ border-radius: 10px !important; }}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers
def esc(x) -> str:
    return _html.escape(str(x if x is not None else ""))


def rec_key(rec) -> str:
    r = str(rec or "")
    for pre, k in (("Pursue", "pursue"), ("Worth", "worth"), ("Approach", "caution"), ("Manual", "manual"), ("Held", "held")):
        if r.startswith(pre):
            return k
    return "depri"


def badge(text, color) -> str:
    return f'<span class="ps-badge" style="color:{color};border-color:{color}55;background:{color}14">{esc(text)}</span>'


def kpi(label, value, sub="", color=T["navy"]) -> str:
    return f'<div class="ps-kpi" style="--c:{color}"><div class="l">{esc(label)}</div><div class="v">{esc(value)}</div><div class="s">{esc(sub)}</div></div>'


def header(title: str, sub: str, eyebrow: str = "") -> None:
    ey = f'<div class="ps-eyebrow">{esc(eyebrow)}</div>' if eyebrow else ""
    st.markdown(f'<div class="ps-head">{ey}<h1>{esc(title)}</h1><p>{esc(sub)}</p></div>', unsafe_allow_html=True)


def short_name(n: str) -> str:
    n = re.sub(r"\b(Pvt\.?|Private|Ltd\.?|Limited|LLP|India|Solutions|Services)\b\.?", "", n or "", flags=re.I)
    n = re.sub(r"[\s,\-]+$", "", re.sub(r"\s+", " ", n)).strip()
    return (n or "")[:26]


def fit_ring(score, color) -> str:
    s = 0 if score is None else max(0, min(100, float(score)))
    circ = 2 * 3.14159 * 42
    return (f'<svg width="112" height="112" viewBox="0 0 100 100"><circle cx="50" cy="50" r="42" stroke="{T["line"]}" stroke-width="9" fill="none"/>'
            f'<circle cx="50" cy="50" r="42" stroke="{color}" stroke-width="9" fill="none" stroke-linecap="round" '
            f'stroke-dasharray="{circ * s / 100:.1f} {circ:.1f}" transform="rotate(-90 50 50)"/>'
            f'<text x="50" y="53" text-anchor="middle" font-size="26" font-weight="800" fill="{T["navy"]}" font-family="Inter,sans-serif">{"-" if score is None else f"{s:.0f}"}</text>'
            f'<text x="50" y="67" text-anchor="middle" font-size="7.5" fill="{T["slate"]}" font-family="Inter,sans-serif">STRATEGIC FIT</text></svg>')


def conf_bars(level: str) -> str:
    n = {"High": 3, "Medium": 2, "Low": 1}.get(level, 0)
    col = {"High": T["ok"], "Medium": T["warn"], "Low": T["err"]}.get(level, T["grey"])
    bars = "".join(f'<i style="background:{col if i < n else T["line"]}"></i>' for i in range(3))
    return f'<span class="ps-conf">{bars}</span><span style="font-weight:600;color:{col}">{esc(level)}</span>'


def style_chart(ch, height=None):
    ch = ch.configure(background="rgba(0,0,0,0)").configure_view(strokeWidth=0).configure_axis(
        labelColor=T["slate"], titleColor=T["slate"], gridColor=T["line"], domainColor=T["line"], tickColor=T["line"], labelFontSize=12)
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
                    '<div class="ps-tag">Strategic Partnership Intelligence</div>', unsafe_allow_html=True)
PAGES = ["Brief", "Workspace", "Ecosystem", "Pipeline", "Partners", "Generator"]
NAV = {"Brief": "◧   Partnership Brief", "Workspace": "◔   Intelligence Workspace", "Ecosystem": "◎   Partner Ecosystem",
       "Pipeline": "☰   Partnership Pipeline", "Partners": "▥   Partner Dashboard", "Generator": "▤   Brief Generator"}
page = st.sidebar.radio("Screen", PAGES, label_visibility="collapsed", format_func=lambda p: NAV[p], key="nav")


def goto_profile(company_id: str) -> None:
    """Callback: open the full profile of an investigated company on the Partner Dashboard."""
    st.session_state["nav"] = "Partners"
    st.session_state["focus_company"] = str(company_id)


rs = runs()
labels = {r["run_id"]: f'{r["run_id"]}  ·  {r["status"]}' for r in rs}
HEADLINE_RUN = "demo6"  # the run produced by the post-repair code (see docs/engineering-audit.md)
st.sidebar.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
current = st.sidebar.selectbox("Research run", list(labels), format_func=lambda k: labels[k],
                               index=list(labels).index(HEADLINE_RUN) if HEADLINE_RUN in labels else 0) if rs else None
if "active" in st.session_state and st.session_state["active"] in labels:
    current = st.session_state["active"]
if current:
    _row = store.query("SELECT status FROM runs WHERE run_id=?", (current,))[0]
    _led = store.ledger_totals(current)
    _col = {"complete": T["ok"], "running": "#3B5B8C"}.get(_row["status"], T["warn"])
    st.sidebar.markdown(f'<div class="ps-side-card"><div class="k">Run status</div><div class="v" style="color:{_col}">● {esc(_row["status"]).capitalize()}</div></div>'
                        f'<div class="ps-side-card"><div class="k">API credits used</div><div class="v">{_led["credits"]:.2f} <span style="color:{T["slate"]};font-weight:500;font-size:12px">Crustdata</span></div></div>',
                        unsafe_allow_html=True)
if DEMO:
    st.sidebar.markdown('<div class="ps-demo" style="margin-top:10px">Read-only demo of saved real runs. New runs are disabled so nobody can spend API credits.</div>', unsafe_allow_html=True)
st.sidebar.markdown(f'<div style="color:{T["slate"]};font-size:11.5px;margin-top:14px">{VERSION}<br>Nothing is sent to anyone. Drafts stay drafts.</div>', unsafe_allow_html=True)

AGENTS = [("Discovery Agent", "D", "Finds and screens candidate companies"), ("Intelligence Agent", "I", "Collects company information"),
          ("Verification Agent", "V", "Checks identity and supporting evidence"), ("Strategic Fit Agent", "S", "Evaluates compatibility and mutual value"),
          ("Partnership Strategist", "P", "Prepares recommendations and drafts")]
STAGES5 = ["Discovery", "Investigation", "Verification", "Evaluation", "Recommendation"]


def agent_state(run_id: str, status: str) -> list[dict]:
    """Real execution state derived from the checkpoint tables. Nothing here is invented."""
    have = {r["stage"]: r["n"] for r in store.query("SELECT stage, COUNT(*) n FROM stages WHERE run_id=? GROUP BY stage", (run_id,))}
    fin = final_for(run_id)
    n = len(fin["ranked"]) if fin else max([have.get(k, 0) for k in ("identity", "enrich", "research", "claims", "assess", "result")] + [6])
    held = [p for p in (fin or {}).get("ranked", []) if p.get("held_for_review")]
    ev = {r["status"]: r["n"] for r in store.query("SELECT status, COUNT(*) n FROM evidence WHERE run_id=? GROUP BY status", (run_id,))}
    done_flags = [have.get("screen", 0) >= 1, have.get("research", 0) >= n, have.get("claims", 0) >= n, have.get("result", 0) >= n, bool(have.get("final"))]
    started = [have.get("brief", 0) >= 1, have.get("identity", 0) >= 1, have.get("claims", 0) >= 1, have.get("assess", 0) >= 1, have.get("result", 0) >= 1]
    detail = [f'{(have.get("discover") and (fin or {}).get("n_candidates")) or "…"} candidates discovered, screened and shortlisted' if done_flags[0] else "Searching and screening candidates",
              f'{min(have.get("identity", 0), have.get("research", 0)) if not fin else n - len(held)} of {n} companies researched',
              f'{ev.get("verified", 0)} claims verified, {ev.get("unverified", 0) + ev.get("needs_review", 0) + ev.get("contradicted", 0)} unresolved',
              f'{have.get("assess", 0) if not fin else n - len(held)} of {n} companies scored',
              "Ranked brief and draft messages ready" if done_flags[4] else "Waiting for evaluation"]
    out, first_open = [], True
    for i, (nm, ic, desc) in enumerate(AGENTS):
        if done_flags[i] and not (held and i in (1, 2)):
            s = "completed"
        elif held and i in (1, 2) and done_flags[i]:
            s = "review"
        elif first_open and status == "running":
            s = "running"
        elif first_open and status in ("crashed",):
            s = "failed"
        elif first_open and status in ("paused_budget", "paused_credits"):
            s = "review"
        elif started[i] and status == "running":
            s = "running"
        else:
            s = "pending"
        if not done_flags[i]:
            first_open = False
        out.append({"name": nm, "ic": ic, "desc": desc, "status": s, "detail": detail[i]})
    return out


STATUS_LABEL = {"completed": "Completed", "running": "Running", "pending": "Pending", "review": "Needs review", "failed": "Failed"}
STATUS_CLS = {"completed": "s-completed", "running": "s-running", "pending": "s-pending", "review": "s-review", "failed": "s-failed"}

# ================================================================== 1. BRIEF
if page == "Brief":
    header("Find the partners worth pursuing.", "Discover strategic opportunities, verify capabilities and understand the value behind every potential partnership.", "Partnership brief")
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("**Describe your partnership objective.**")
        req = st.text_area("Describe your partnership objective", DEMO_REQUEST, height=170, label_visibility="collapsed")
        with st.expander("Structured details (optional)"):
            c1, c2 = st.columns(2)
            company = c1.text_input("Requesting company")
            website = c1.text_input("Company website")
            industry = c1.text_input("Industry")
            geo_in = c1.text_input("Target geography")
            ptype = c2.text_input("Partnership type")
            caps = c2.text_input("Required capabilities")
            extra = c2.text_input("Preferred company size")
        st.markdown("**Execution settings**")
        c1, c2, c3 = st.columns(3)
        ceiling = c1.number_input("Credit ceiling", 20, 2000, 300, help="The run pauses before it would spend more than this.")
        crash = c2.selectbox("Demo: crash after stage", ["(none)", "discover", "screen", "enrich", "research", "claims"])
        fail = c3.selectbox("Demo: tool outage", ["(none)", "enrich"])
        if st.button("Run PartnerScout", type="primary", disabled=DEMO, help="Disabled in the read-only demo" if DEMO else None):
            structured = {"Requesting company": company, "Company website": website, "Target industry": industry, "Geography": geo_in,
                          "Partner type": ptype, "Required capabilities": caps, "Constraints": extra}
            parts = [req] + [f"{k}: {v}" for k, v in structured.items() if v]
            verdict = validation.validate_request(" ".join(parts), structured)
            if not verdict.ok:  # nothing is sent to the model or to Crustdata for an invalid request
                for e_ in verdict.errors:
                    st.error(e_)
                for q_ in verdict.clarifications:
                    st.warning("Please clarify: " + q_)
                st.stop()
            for w_ in verdict.warnings:
                st.info(w_)
            rid = f"run-{uuid.uuid4().hex[:6]}"
            store.create_run(rid, " | ".join(parts))
            launch(rid, " | ".join(parts), ceiling, None if crash == "(none)" else crash, None if fail == "(none)" else fail)
            st.session_state["active"] = rid
            st.success(f"Started {rid}. Open the Intelligence Workspace to follow it.")
        if DEMO:
            st.markdown('<div class="ps-demo" style="margin-top:12px">Read-only demo: pick a saved run in the sidebar, then open the <b>Partner Dashboard</b> to explore real results.</div>', unsafe_allow_html=True)
    with right:
        steps = [("01", "Discover", "Find relevant companies."), ("02", "Investigate", "Research business capabilities."), ("03", "Verify", "Validate important claims."),
                 ("04", "Evaluate", "Assess strategic compatibility and mutual value."), ("05", "Recommend", "Generate a ranked partnership brief.")]
        st.markdown('<div class="ps-card"><h4>How PartnerScout works</h4>' + "".join(
            f'<div class="ps-step"><div class="n">{n}</div><div><div class="t">{t}</div><div class="d">{d}</div></div></div>' for n, t, d in steps) + "</div>", unsafe_allow_html=True)
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        guards = ["Every important claim has a source.", "Unknown information is never treated as negative evidence.", "Potential conflicts are identified.",
                  "External communication is never sent automatically.", "API costs are tracked on every call."]
        st.markdown('<div class="ps-card"><h4>Guardrails</h4>' + "".join(f'<div class="ps-guard"><span class="ck">✓</span><span>{g}</span></div>' for g in guards) + "</div>", unsafe_allow_html=True)

# ================================================================== 2. WORKSPACE
elif page == "Workspace":
    header("Intelligence workspace", "A live view of what each agent has done on this research request, read from the run's real execution state.", "Workspace")
    if not current:
        st.info("No runs yet. Start one from the Partnership Brief.")
        st.stop()
    r = store.query("SELECT * FROM runs WHERE run_id=?", (current,))[0]
    led = store.ledger_totals(current)
    ags = agent_state(current, r["status"])
    done_n = sum(1 for a in ags if a["status"] == "completed")
    st.markdown(f'<div class="ps-card"><h4>Current research request</h4><div style="font-size:14.5px;line-height:1.55">{esc(r["request"])}</div></div>', unsafe_allow_html=True)
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    nodes = []
    for i, nm in enumerate(STAGES5):
        cls = "done" if ags[i]["status"] == "completed" else "active" if ags[i]["status"] in ("running", "review", "failed") else ""
        nodes.append(f'<div class="ps-node {cls}"><div class="ps-dot">{"✓" if cls == "done" else i + 1}</div><div class="nm">{nm}</div></div>')
        if i < 4:
            nodes.append(f'<div class="ps-line {"done" if cls == "done" else ""}"></div>')
    st.markdown(f'<div class="ps-card"><h4>Overall progress · {done_n} of 5 stages complete</h4><div class="ps-track">{"".join(nodes)}</div>'
                f'<div class="ps-prog"><div style="width:{done_n * 20}%"></div></div></div>', unsafe_allow_html=True)
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    ev = {x["status"]: x["n"] for x in store.query("SELECT status, COUNT(*) n FROM evidence WHERE run_id=? GROUP BY status", (current,))}
    fin_now = final_for(current)
    ncand = (fin_now or {}).get("n_candidates") or len(store.get_stage(current, "discover") or [])
    ninv = len(store.query("SELECT 1 FROM stages WHERE run_id=? AND stage='identity'", (current,)))
    k = st.columns(5)
    k[0].markdown(kpi("Companies discovered", ncand, "after duplicate resolution"), unsafe_allow_html=True)
    k[1].markdown(kpi("Investigated", ninv, "identity-resolved so far"), unsafe_allow_html=True)
    k[2].markdown(kpi("Verified claims", ev.get("verified", 0), "quote found in its source", T["emerald"]), unsafe_allow_html=True)
    k[3].markdown(kpi("Unresolved claims", ev.get("unverified", 0) + ev.get("needs_review", 0) + ev.get("contradicted", 0), "unverified, conflicting or needs review", T["warn"]), unsafe_allow_html=True)
    k[4].markdown(kpi("API credits", f'{led["credits"]:.2f}', f'{led["calls"]} calls · ${led["usd"]:.3f} model cost'), unsafe_allow_html=True)
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    if r["error"]:
        st.warning(r["error"])
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
        rows = "".join(f'<div class="ps-tl"><div class="ic">{a["ic"]}</div><div class="b"><div class="t">{a["name"]}</div><div class="d">{esc(a["detail"])}</div></div>'
                       f'<span class="ps-status {STATUS_CLS[a["status"]]}">{STATUS_LABEL[a["status"]]}</span></div>' for a in ags)
        st.markdown(f'<div class="ps-card"><h4>Agent activity</h4>{rows}</div>', unsafe_allow_html=True)
    with right:
        logs = store.query("SELECT output_json FROM stages WHERE run_id=? AND stage='_log' ORDER BY item", (current,))
        lines = [esc(json.loads(x["output_json"])["msg"]) for x in logs[-9:]]
        st.markdown(f'<div class="ps-card"><h4>Latest log entries</h4><div style="font:12px/1.65 ui-monospace,Consolas,monospace;color:#2A3B49;white-space:pre-wrap">{"<br>".join(lines) or "(waiting)"}</div></div>', unsafe_allow_html=True)
        by = store.query("SELECT endpoint, SUM(credits) c, COUNT(*) n FROM calls WHERE run_id=? AND service='crustdata' GROUP BY endpoint ORDER BY c DESC", (current,))
        if by:
            st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
            df = pd.DataFrame([dict(x) for x in by])
            ch = alt.Chart(df).mark_bar(cornerRadiusEnd=5, color=T["emerald"], size=16).encode(
                y=alt.Y("endpoint:N", sort="-x", title=None), x=alt.X("c:Q", title="credits"), tooltip=["endpoint", alt.Tooltip("c:Q", title="credits"), alt.Tooltip("n:Q", title="calls")])
            st.markdown('<div class="ps-card"><h4>Where the credits went</h4>', unsafe_allow_html=True)
            st.altair_chart(style_chart(ch, 150), width="stretch")
            st.markdown("</div>", unsafe_allow_html=True)
    with st.expander("Evidence and sources (real source records for this run)"):
        evd = store.query("SELECT claim_id, status, category, claim, source_url, canonical_url, source_class, corroboration, quote FROM evidence WHERE run_id=? ORDER BY claim_id LIMIT 400", (current,))
        if evd:
            st.dataframe(pd.DataFrame([dict(x) for x in evd]), width="stretch", hide_index=True, height=280)
        else:
            st.caption("No evidence recorded yet.")
    with st.expander("Call ledger (every Crustdata and model call, retries included)"):
        calls = store.query("SELECT ts, service, endpoint, status, credits, cost_usd, latency_ms, cached, attempt, error FROM calls WHERE run_id=? ORDER BY id DESC LIMIT 100", (current,))
        if calls:
            ldf = pd.DataFrame([dict(c) for c in calls])
            ldf["ts"] = ldf["ts"].map(lambda t: time.strftime("%H:%M:%S", time.localtime(t)))
            st.dataframe(ldf, width="stretch", hide_index=True, height=280)
    if r["status"] == "running":
        time.sleep(3)
        st.rerun()

# ================================================================== 3a. PARTNER ECOSYSTEM
elif page == "Ecosystem":
    header("Partner ecosystem", "Where the discovered companies are and how far each has been investigated. Click a marker or choose a company; the list and the map stay in sync.", "Partner ecosystem")
    if not current:
        st.info("No runs yet. Start one from the Partnership Brief.")
        st.stop()
    companies = ecosystem.build_companies(current)
    if not companies:
        st.info("This run has not discovered any companies yet.")
        st.stop()
    city_opts = sorted({c["location"][0] for c in companies if c["location"]}) + [ecosystem.NOT_MAPPABLE]
    ptype_opts = sorted({c["partner_type"] or "unscreened" for c in companies})
    f1, f2, f3, f4 = st.columns([2, 2, 2, 2])
    cities = f1.multiselect("Geography (city)", city_opts, key="eco_cities", help="Approximate city centres matched from each company's saved city text.")
    sigs = f2.multiselect("Industry signals", list(ecosystem.SIGNALS), key="eco_sigs", help="Keywords found in the company's own description. A hint, not a verified fact.")
    ptypes = f3.multiselect("Partner type", ptype_opts, key="eco_ptypes", help="Screened by the model from the description. Not verified.")
    with f4:
        fit_rng = st.slider("Fit score", 0, 100, (0, 100), key="eco_fit", help="Only investigated companies have a fit score.")
        inc_unscored = st.checkbox("Include companies without a fit score", value=True, key="eco_unscored")
    q = st.text_input("Search by name, domain or city", key="eco_q", label_visibility="collapsed", placeholder="Search by name, domain or city")
    shown = sorted(ecosystem.filter_companies(companies, cities=cities, signals=sigs, ptypes=ptypes, fit_range=fit_rng if fit_rng != (0, 100) else (0, 100),
                                              include_unscored=inc_unscored, text=q), key=ecosystem.sort_key)
    pts, skipped = ecosystem.map_points(shown)
    k = st.columns(4)
    k[0].markdown(kpi("Companies shown", f"{len(shown)} / {len(companies)}", "after the filters above"), unsafe_allow_html=True)
    k[1].markdown(kpi("On the map", len(pts), "approximate city centres", T["emerald"]), unsafe_allow_html=True)
    k[2].markdown(kpi("Not mappable", skipped, "city text matched no known city", T["warn"]), unsafe_allow_html=True)
    k[3].markdown(kpi("Investigated", sum(1 for c in shown if c["investigated"]), "have evidence and a fit score"), unsafe_allow_html=True)
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    ids = [c["id"] for c in shown]
    if st.session_state.get("eco_sel") not in ids:
        st.session_state["eco_sel"] = None
    mcol, lcol = st.columns([3, 2], gap="large")
    with mcol:
        val = eco_map(points=pts, selected=st.session_state.get("eco_sel"), height=470, key="eco_map_comp", default=None,
                      note="No links between companies are drawn: this build has no source that records relationships.")
        if val and val.get("t") != st.session_state.get("eco_map_t"):
            st.session_state["eco_map_t"] = val["t"]
            if val["id"] in ids:
                st.session_state["eco_sel"] = val["id"]
            st.rerun()
        st.caption("Coverage: only companies found by this run's searches are shown (73 to 75 per run), not the whole market. "
                   "Locations are city-level and approximate; markers are spread slightly inside a city so they stay visible.")
    with lcol:
        st.selectbox("Selected company", ids, index=None, key="eco_sel", placeholder="Click a marker or choose here",
                     format_func=lambda i, _n={c["id"]: c["name"] for c in shown}: _n.get(i, str(i)))
        rows = []
        for c in shown[:120]:
            on = c["id"] == st.session_state.get("eco_sel")
            sc = f'{c["fit"]:.0f}' if c["fit"] is not None else ("" if c["screen_relevance"] is None else f'~{c["screen_relevance"]:.0f}')
            rows.append(f'<div style="display:flex;justify-content:space-between;gap:8px;padding:7px 10px;border-radius:9px;'
                        f'{"background:" + T["soft"] + ";border:1px solid #CBE6DC;" if on else "border:1px solid transparent;"}">'
                        f'<div><div style="font-weight:{700 if on else 600};font-size:13.5px">{esc(c["name"])}</div>'
                        f'<div style="color:{T["slate"]};font-size:11.5px">{esc(c["city"] or "city not recorded")} · {esc(c["partner_type"] or "unscreened")}</div></div>'
                        f'<div style="text-align:right"><div style="font-weight:700;font-size:13px">{sc}</div>'
                        f'<div style="font-size:11px;color:{ecosystem.STAGE_COLORS[c["stage"]]};font-weight:600">{esc(c["stage"])}</div></div></div>')
        st.markdown(f'<div class="ps-card" style="max-height:370px;overflow:auto;padding:8px"><h4 style="padding:4px 8px 0">Company list ({len(shown)})</h4>{"".join(rows) or "<div style=padding:10px>No company matches these filters.</div>"}'
                    f'{"<div style=padding:8px;color:" + T["slate"] + ">Showing the first 120.</div>" if len(shown) > 120 else ""}</div>', unsafe_allow_html=True)
        st.caption("~ marks screening relevance (a model judgement from the description); a plain number is a fit score from an investigated company.")
    sel = next((c for c in shown if c["id"] == st.session_state.get("eco_sel")), None)
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    if sel is None:
        st.markdown(f'<div class="ps-card"><h4>Partner details</h4><div style="color:{T["slate"]}">Select a company on the map or in the list to see its saved details.</div></div>', unsafe_allow_html=True)
    else:
        loc = sel["location"]
        sigs_html = "".join(badge(s, T["slate"]) for s in sel["signals"]) or '<span style="color:' + T["slate"] + '">no industry keywords found in the description</span>'
        score = (f'Fit {sel["fit"]:.1f} · evidence confidence {esc(sel["evidence_confidence"])}' if sel["fit"] is not None
                 else (f'Screening relevance ~{sel["screen_relevance"]:.0f} (model judgement from the description; not a fit score)' if sel["screen_relevance"] is not None else "No score yet"))
        st.markdown(
            f'<div class="ps-card"><h4>Partner details</h4><div style="font-size:22px;font-weight:800;letter-spacing:-0.02em">{esc(sel["name"])}</div>'
            f'<div style="color:{T["slate"]};font-size:13px;margin:2px 0 10px">{esc(sel["domain"])} · {esc(sel["size"])} employees</div>'
            f'{badge(sel["stage"] + (" (set by a person)" if sel["stage_set_by_person"] else ""), ecosystem.STAGE_COLORS[sel["stage"]])}'
            f'{badge("type: " + (sel["partner_type"] or "unscreened"), T["slate"])}'
            f'<div style="margin-top:8px;font-size:13.5px;line-height:1.6"><b>City</b> {esc(sel["city"] or "not recorded")}'
            f'{" · mapped to " + esc(loc[0]) + " (approximate)" if loc else " · cannot be mapped from this text, so it is not on the map"}<br>'
            f'<b>Relevance</b> {score}<br><b>Industry signals</b> {sigs_html}</div>'
            f'<div style="margin-top:8px;font-size:13.5px;line-height:1.55;color:#2A3B49">{esc((sel["description"] or "No description saved.")[:700])}</div>'
            f'<div style="margin-top:8px;color:{T["slate"]};font-size:12px">Industry signals and partner type come from the description and a model screen; they are not verified. '
            f'{"" if sel["investigated"] else "This company has not been investigated yet, so it has no verified evidence."}</div></div>', unsafe_allow_html=True)
        b1, b2, b3 = st.columns([2, 2, 3])
        with b1:
            new_stage = st.selectbox("Pipeline stage", ecosystem.STAGES, index=ecosystem.STAGES.index(sel["stage"]), key=f"eco_stage_{sel['id']}")
        with b2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("Save stage", key=f"eco_save_{sel['id']}") and new_stage != sel["stage"]:
                ecosystem.set_stage(current, sel["id"], new_stage)
                st.rerun()
        with b3:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if sel["investigated"]:
                st.button("Open full profile", type="primary", key=f"eco_open_{sel['id']}", on_click=goto_profile, args=(sel["id"],))
            else:
                st.caption("Only investigated companies have a full profile.")

# ================================================================== 3b. PARTNERSHIP PIPELINE
elif page == "Pipeline":
    header("Partnership pipeline", "Every discovered company, by stage. Stage changes you make are saved in SQLite. Nothing is ever sent to anyone.", "Partnership pipeline")
    if not current:
        st.info("No runs yet. Start one from the Partnership Brief.")
        st.stop()
    companies = ecosystem.build_companies(current)
    if not companies:
        st.info("This run has not discovered any companies yet.")
        st.stop()
    by = {s: [] for s in ecosystem.STAGES}
    for c in sorted(companies, key=ecosystem.sort_key):
        by[c["stage"]].append(c)
    cols = st.columns(len(ecosystem.STAGES))
    for col, s in zip(cols, ecosystem.STAGES):
        items = by[s]
        cards = "".join(f'<div style="background:{T["white"]};border:1px solid {T["line"]};border-left:3px solid {ecosystem.STAGE_COLORS[s]};border-radius:9px;padding:7px 9px;margin-bottom:6px">'
                        f'<div style="font-weight:600;font-size:12.5px;line-height:1.3">{esc(c["name"])}</div>'
                        f'<div style="color:{T["slate"]};font-size:11px">{esc(c["city"] or "—")}'
                        f'{" · fit " + format(c["fit"], ".0f") if c["fit"] is not None else ""}{" · set by a person" if c["stage_set_by_person"] else ""}</div></div>' for c in items[:8])
        more = f'<div style="color:{T["slate"]};font-size:11.5px">+ {len(items) - 8} more</div>' if len(items) > 8 else ""
        col.markdown(f'<div style="border-top:3px solid {ecosystem.STAGE_COLORS[s]};padding-top:6px"><div style="display:flex;justify-content:space-between;font-weight:700;font-size:13px;margin-bottom:8px">'
                     f'<span>{s}</span><span style="color:{T["slate"]}">{len(items)}</span></div>{cards or "<div style=color:" + T["slate"] + ";font-size:12px>empty</div>"}{more}</div>', unsafe_allow_html=True)
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="ps-card"><h4>Move a company</h4>', unsafe_allow_html=True)
    with st.form("move_stage", clear_on_submit=False):
        m1, m2, m3 = st.columns([3, 2, 3])
        who = m1.selectbox("Company", [c["id"] for c in sorted(companies, key=ecosystem.sort_key)], format_func=lambda i, _n={c["id"]: f'{c["name"]}  ·  {c["stage"]}' for c in companies}: _n.get(i, str(i)))
        to = m2.selectbox("Move to stage", ecosystem.STAGES)
        note = m3.text_input("Note (optional)")
        go = st.form_submit_button("Save stage", type="primary")
    if go:
        ecosystem.set_stage(current, who, to, note or None)
        st.success("Saved.")
        st.rerun()
    cur = next(c for c in companies if c["id"] == who)
    if cur["stage_set_by_person"] and st.button("Reset this company to its derived stage"):
        ecosystem.clear_stage(current, who)
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    st.caption("Derived by the app from the run: Discovered (found by search), Investigating (identity or research started, or a tool failed), Verified (investigated, not recommended), "
               "Shortlisted (recommended: Pursue or Worth a conversation), Approved (a draft was approved in the Brief Generator). Outreach Drafted and Archived are set by a person. "
               "Approving a draft only records a decision. In the read-only demo, changes are kept only for the current session.")

# ================================================================== 3. PARTNER DASHBOARD
elif page == "Partners":
    fin = final_for(current)
    if not fin:
        st.info("This run has no final result yet.")
        st.stop()
    ranked = fin["ranked"]
    done = [p for p in ranked if not p.get("held_for_review")]
    conflicts = [p for p in done if (p.get("competitive_overlap") or {}).get("level") in ("medium", "high") or any(c["status"] == "contradicted" for c in p["claims"])]
    good = [p for p in done if rec_key(p.get("recommendation")) in ("pursue", "worth")]
    brief = fin.get("brief", {})
    header("Your partnership landscape", f'{brief.get("objective") or ""} · target: {brief.get("target_industry")}, {brief.get("country")} · run {current}', "Partner dashboard")
    k = st.columns(4)
    k[0].markdown(kpi("Companies discovered", fin.get("n_candidates", 0), "unique, duplicates collapsed"), unsafe_allow_html=True)
    k[1].markdown(kpi("Companies verified", f"{len(done)}", "identity resolved, claims checked against sources"), unsafe_allow_html=True)
    k[2].markdown(kpi("Recommended partners", len(good), "Pursue or Worth a conversation", T["emerald"]), unsafe_allow_html=True)
    k[3].markdown(kpi("Potential conflicts", len(conflicts), "competitive overlap or conflicting sources", T["warn"]), unsafe_allow_html=True)
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    # ---- ranked comparison table
    rows_html = []
    for i, p in enumerate(ranked, 1):
        co = p["company"]
        if p.get("held_for_review"):
            rows_html.append(f'<tr><td><div class="ps-rank">{i}</div></td><td><b>{esc(co["name"])}</b></td><td colspan="5"><span class="ps-risk">Held for review: a tool failed, not treated as "no evidence"</span></td></tr>')
            continue
        key = rec_key(p.get("recommendation"))
        col = REC_COLORS[key]
        sc = p["fit"]["score"] or 0
        ov = p.get("competitive_overlap") or {}
        risks = []
        if ov.get("level") in ("medium", "high"):
            risks.append(f'<span class="ps-risk{" red" if ov.get("level") == "high" else ""}">Competitive overlap · {esc(ov.get("level"))}</span>')
        for f in p.get("flags", []):
            if "Strategic conflict" in f:
                continue
            risks.append(f'<span class="ps-risk red">{esc(f.split(" - ")[0][:44])}</span>')
        if not risks:
            risks.append('<span class="ps-risk green">No material risk found</span>')
        mv = ((p.get("mutual_value") or {}).get("to_requester") or [{}])[0].get("point", "")
        conf = (p.get("evidence_confidence") or {}).get("level", "-")
        rows_html.append(
            f'<tr><td><div class="ps-rank{" top" if i == 1 else ""}">{i}</div></td>'
            f'<td><div style="font-weight:700">{esc(co["name"])}</div><div style="color:{T["slate"]};font-size:12px">{esc(co.get("domain"))} · {esc(co.get("city"))} · {esc(co.get("size"))}</div></td>'
            f'<td><div style="font-weight:800;font-size:16px;color:{col}">{sc:.0f}</div><div class="ps-bar"><div style="width:{sc}%;background:{col}"></div></div></td>'
            f'<td>{conf_bars(conf)}</td><td style="max-width:260px;color:#2A3B49">{esc(mv[:105])}{"…" if len(mv) > 105 else ""}</td>'
            f'<td>{"".join(risks)}</td><td>{badge(p.get("recommendation"), col)}</td></tr>')
    st.markdown('<div class="ps-tablewrap"><table class="ps-table"><thead><tr><th>Rank</th><th>Company</th><th>Strategic fit</th><th>Evidence confidence</th><th>Mutual value</th><th>Risk indicators</th><th>Recommendation</th></tr></thead><tbody>'
                + "".join(rows_html) + "</tbody></table></div>", unsafe_allow_html=True)
    st.caption("Strategic fit and evidence confidence are separate: a high fit with low confidence is not a firm recommendation. Open a profile below for the reasons and sources.")
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    # ---- map + matrix
    cands = store.get_stage(current, "discover") or []
    pts, placed, unplaced = geo.build_points(ranked, cands, REC_COLORS, rec_key)
    mcol, hcol = st.columns([1, 1], gap="large")
    with mcol:
        st.markdown('<div class="ps-card" style="padding-bottom:8px"><h4>Where the partners are</h4>', unsafe_allow_html=True)
        st.iframe(geo.map_html(pts), height=380)
        st.caption(f"{placed} placed by city, {unplaced} not placed (city text matched no known city; we never guess). Markers are jittered inside the city.")
        st.markdown("</div>", unsafe_allow_html=True)
    with hcol:
        st.markdown('<div class="ps-card" style="padding-bottom:8px"><h4>Compatibility matrix · score by component</h4>', unsafe_allow_html=True)
        recs_l = []
        for p in done:
            for ck, cn in COMP_NAMES.items():
                v = (p["components"].get(ck) or {}).get("score")
                recs_l.append({"Partner": short_name(p["company"]["name"]), "Component": f"{cn.replace('Market access', 'Market')} {COMP_WEIGHTS[ck]}%", "Score": v, "Label": "-" if v is None else f"{v:.0f}"})
        if recs_l:
            hm = pd.DataFrame(recs_l)
            order = [f"{cn.replace('Market access', 'Market')} {COMP_WEIGHTS[ck]}%" for ck, cn in COMP_NAMES.items()]
            h = alt.Chart(hm).encode(x=alt.X("Component:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, orient="top", labelLimit=100, labelOverlap=False, labelFontSize=10.5)),
                                     y=alt.Y("Partner:N", sort=[short_name(p["company"]["name"]) for p in done], title=None, axis=alt.Axis(labelLimit=150)))
            rect = h.mark_rect(cornerRadius=5, stroke="#FFFFFF", strokeWidth=3).encode(
                color=alt.condition("isValid(datum.Score)", alt.Color("Score:Q", scale=alt.Scale(domain=[30, 60, 90], range=["#F1C9C9", "#F4E3BE", "#43B99B"]), legend=None), alt.value("#EEF0EC")),
                tooltip=["Partner", "Component", "Label"])
            txt = h.mark_text(color=T["navy"], fontWeight="bold").encode(text="Label:N")
            st.altair_chart(style_chart(rect + txt, 60 + 38 * len(done)), width="stretch")
            st.caption("Unknown is shown as '-' and left out of the weighted total; it is never counted as zero.")
        st.markdown("</div>", unsafe_allow_html=True)

    # ---- detailed profiles
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.markdown("### Partner profiles")
    for i, p in enumerate(ranked, 1):
        co = p["company"]
        if p.get("held_for_review"):
            with st.expander(f'#{i}  {co["name"]}  ·  Held for review'):
                st.error(f'A tool failed while collecting data: {p.get("error")}. This is not evidence that the company lacks capability. Retry from the Workspace.')
            continue
        key = rec_key(p.get("recommendation"))
        col = REC_COLORS[key]
        conf = (p.get("evidence_confidence") or {}).get("level", "-")
        ov = p.get("competitive_overlap") or {}
        by_cat = {}
        for c in p["claims"]:
            by_cat.setdefault(c["category"], []).append(c)
        with st.expander(f'#{i}  {co["name"]}  ·  {p.get("recommendation")}  ·  fit {p["fit"]["score"]}  ·  evidence {conf}', expanded=(str(co["id"]) == st.session_state.get("focus_company")) if st.session_state.get("focus_company") else (i == 1)):
            h1, h2 = st.columns([1, 6])
            h1.markdown(fit_ring(p["fit"]["score"], col), unsafe_allow_html=True)
            flags = "".join(f'<span class="ps-risk red">{esc(f)}</span>' for f in p.get("flags", []))
            h2.markdown(f'<div style="font-size:22px;font-weight:800;letter-spacing:-0.02em">{esc(co["name"])}</div>'
                        f'<div style="color:{T["slate"]};font-size:13px;margin:2px 0 8px">{esc(co.get("domain"))} · {esc(co.get("city"))} · {esc(co.get("size"))} employees</div>'
                        f'{badge(p.get("recommendation"), col)}{badge("Evidence confidence: " + str(conf), T["slate"])}<div style="margin-top:4px">{flags}</div>', unsafe_allow_html=True)
            st.markdown("**A. Company overview**")
            st.write(co.get("description") or "I can't verify a description from the available sources.")
            st.markdown("**B. Capability intelligence**")
            capc = [c for c in p["claims"] if c["category"] in ("capability", "bfsi_presence", "technology_integration", "distribution_channel") and c["status"] in ("verified", "inferred")]
            if capc:
                for c in capc[:6]:
                    q = f'<div class="ps-quote">“{esc(str(c.get("quote") or "")[:230])}”</div>' if c.get("quote") else ""
                    st.markdown(f'<div style="margin-bottom:8px">{badge(c["status"], STATUS_COLORS.get(c["status"], T["slate"]))}<span class="ps-pill">{esc(c["category"])}</span> '
                                f'<span class="ps-chip">{esc(c["claim_id"])}</span><div style="font-size:14px;margin-top:3px">{esc(c["claim"])}</div>{q}'
                                f'<div style="font-size:11.5px;color:{T["slate"]}">{esc(c.get("canonical_url") or ("redirect link, destination unresolved" if "google." in str(c.get("source_url")) else c.get("source_url")) or "")}'
                                f'{" · " + esc(CORRO.get(c.get("corroboration") or "", "")) if c.get("corroboration") else ""}</div></div>', unsafe_allow_html=True)
            else:
                st.caption("I can't verify specific capabilities from the available sources.")
            st.markdown("**C. Strategic compatibility**")
            blocks = []
            for ck, cn in COMP_NAMES.items():
                v = (p["components"].get(ck) or {})
                sc = v.get("score")
                colr = T["emerald"] if (sc or 0) >= 70 else T["warn"] if (sc or 0) >= 50 else T["err"]
                ids = "".join(f'<span class="ps-chip">{esc(x)}</span>' for x in v.get("claim_ids", []))
                blocks.append(f'<div class="ps-comp"><div class="h"><span>{cn} <span class="w">weight {COMP_WEIGHTS[ck]}%</span></span><span style="color:{colr}">{"unknown" if sc is None else f"{sc:.0f}"}</span></div>'
                              f'<div class="ps-bar" style="width:100%"><div style="width:{0 if sc is None else sc}%;background:{colr}"></div></div><div class="why">{esc(v.get("why"))}</div><div style="margin-top:4px">{ids}</div></div>')
            st.markdown(f'<div class="ps-card">{"".join(blocks)}</div>', unsafe_allow_html=True)
            rel = p.get("relationship") or {}
            if rel:
                dims = [("Product complementarity", "product_complementarity", "level"), ("Customer overlap", "customer_overlap", "level"),
                        ("Distribution complementarity", "distribution_complementarity", "level"), ("Technology compatibility", "technology_compatibility", "level"),
                        ("Competition", "competition_type", "type"), ("Feasibility", "feasibility", "level")]
                rows = "".join(f'<div class="ps-comp"><div class="h"><span>{n}</span><span style="color:{T["emerald"]}">{esc((rel.get(k) or {}).get(f) or "unknown")}</span></div>'
                               f'<div class="why">{esc((rel.get(k) or {}).get("why"))}</div></div>' for n, k, f in dims if rel.get(k))
                inc = rel.get("strategic_incompatibility") or {}
                if inc.get("present"):
                    rows += f'<div class="ps-comp"><div class="h"><span>Strategic incompatibility</span><span style="color:{T["err"]}">present</span></div><div class="why">{esc(inc.get("why"))}</div></div>'
                st.markdown(f'<div class="ps-card" style="margin-top:10px"><h4>Relationship dimensions</h4>{rows}</div>', unsafe_allow_html=True)
            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            st.markdown("**D. Mutual value analysis**")
            mv = p.get("mutual_value") or {}

            def mv_items(lst):
                return "".join(f'<div class="mv-item">• {esc(x["point"])} {badge("verified" if x.get("basis") == "verified" else "inferred", T["ok"] if x.get("basis") == "verified" else "#5B7C99")}</div>' for x in lst) or "—"
            st.markdown(f'<div class="mv-wrap"><div class="mv-col l"><h5 style="color:{T["emerald"]}">Value to your company</h5>{mv_items(mv.get("to_requester", []))}</div>'
                        f'<div class="mv-mid">⇄</div><div class="mv-col r"><h5 style="color:#8A6420">Value to the potential partner</h5>{mv_items(mv.get("to_partner", []))}</div></div>', unsafe_allow_html=True)
            st.markdown(f'<div style="color:#2A3B49;font-size:13.5px;margin:10px 0 4px"><b>Why it could work.</b> {esc(mv.get("rationale"))}</div>'
                        f'<div style="color:{T["slate"]};font-size:12px">A hypothesis, not confirmed interest: inferred items are not evidence that the partner is willing, and none is a confirmed revenue figure.</div>', unsafe_allow_html=True)
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
            st.markdown("**E. Trust and risk assessment**")
            ident = p.get("identity") or {}
            st.markdown(f'<div class="ps-card"><div style="font-size:14px;line-height:1.7">Identity: <b>{"resolved" if ident.get("resolved") else "unresolved"}</b> '
                        f'(match confidence {esc(ident.get("confidence"))}, domain {"matches" if ident.get("domain_match") else "does not match"})</div></div>', unsafe_allow_html=True)
            cfl = [c for c in p["claims"] if c["status"] in ("contradicted", "needs_review", "unverified")]
            if ov.get("level") in ("low", "medium", "high"):
                comp = [c for c in p["claims"] if c["category"] == "competing_product"]
                adj = (p["fit"].get("adjustments") or {})
                evd = ""
                for c in comp[:2]:
                    evd += f'<div class="ps-quote">“{esc(str(c.get("quote") or "")[:220])}”<br><span style="color:{T["slate"]};font-size:11.5px">{esc(c.get("source_url"))}</span></div>'
                effect = (f"Recommendation set to “{esc(p.get('recommendation'))}” and {abs(adj.get('conflict_penalty', 0))} points taken off Strategic fit." if adj.get("conflict_penalty")
                          else "No penalty applied: the overlap is low. It is a point to clarify, not a reason to rule the company out.")
                if ov.get("level") in ("medium", "high"):
                    st.markdown(f'<div class="cf-box" style="margin-top:10px"><h5>Potential competitive overlap detected</h5><div style="font-size:13.5px;line-height:1.55;color:#2A3B49">'
                                f'<b>What overlaps.</b> {esc(ov.get("why"))}<br><b>Why it matters.</b> A partner with its own competing product may favour it over the requester’s, so channel terms need care.<br>'
                                f'<b>Effect on the recommendation.</b> {effect}<br><span style="color:{T["slate"]}">This does not mean the company is untrustworthy.</span></div>{evd}</div>', unsafe_allow_html=True)
            if cfl:
                with st.expander(f"Conflicting or unverified information ({len(cfl)})"):
                    for c in cfl:
                        st.markdown(f'{badge(c["status"], STATUS_COLORS.get(c["status"], T["slate"]))} {esc(c["claim"])}<div style="color:{T["slate"]};font-size:12px">{esc(str(c.get("quote") or "")[:300])}</div>', unsafe_allow_html=True)
            st.markdown("**F. Decision-makers**")
            s = p.get("stakeholder")
            if s:
                st.markdown(f'<div class="ps-card"><div style="font-size:16px;font-weight:700">{esc(s.get("name"))}</div><div style="color:{T["slate"]}">{esc(s.get("title"))}</div>'
                            f'<div style="margin-top:6px;font-size:13px">{esc(s.get("why"))}</div><div style="margin-top:6px;font-size:12px;color:{T["slate"]}">Source: Crustdata company record. Professional background is intentionally not collected (privacy).</div></div>', unsafe_allow_html=True)
            else:
                st.info("I can't verify a decision-maker from the available sources.")
            st.markdown("**G. Recommended partnership model**")
            pm = p.get("partnership_model") or {}
            st.markdown(f'<div class="ps-card">{badge((pm.get("model") or "none").replace("_", " "), T["emerald"])}<div style="margin-top:6px;font-size:14px;color:#2A3B49">{esc(pm.get("why"))}</div></div>', unsafe_allow_html=True)
            with st.expander(f"Evidence register ({len(p['claims'])} claims)"):
                st.dataframe(pd.DataFrame([{k2: c.get(k2) for k2 in ("claim_id", "status", "category", "claim", "source_url", "canonical_url", "source_class", "corroboration", "quote")} for c in p["claims"]]), width="stretch", hide_index=True)

# ================================================================== 4. BRIEF GENERATOR
else:
    fin = final_for(current)
    if not fin:
        st.info("This run has no final result yet.")
        st.stop()
    header("Partnership brief generator", "An executive intelligence document built from the verified evidence of this run. Every claim in it links to its source.", "Brief generator")
    html_doc = report.build_report(fin)
    done = [p for p in fin["ranked"] if not p.get("held_for_review")]
    head = next((p for p in done if rec_key(p.get("recommendation")) in ("pursue", "worth")), done[0] if done else None)
    a, b = st.columns([3, 2], gap="large")
    with a:
        if head:
            col = REC_COLORS[rec_key(head.get("recommendation"))]
            mv = head.get("mutual_value") or {}
            st.markdown(f'<div class="ps-card" style="border-top:3px solid {T["gold"]}"><h4>Headline recommendation</h4>'
                        f'<div style="font-size:24px;font-weight:800;letter-spacing:-0.02em">{esc(head["company"]["name"])}</div>'
                        f'<div style="margin:8px 0">{badge(head.get("recommendation"), col)}{badge("fit " + str(head["fit"]["score"]), T["navy"])}{badge("evidence " + str((head.get("evidence_confidence") or {}).get("level")), T["slate"])}</div>'
                        f'<div style="font-size:14px;line-height:1.6;color:#2A3B49">{esc(mv.get("rationale"))}</div></div>', unsafe_allow_html=True)
    with b:
        st.markdown(f'<div class="ps-card"><h4>Export</h4>', unsafe_allow_html=True)
        st.download_button("Download report (HTML)", html_doc, file_name=f"{current}.html", mime="text/html", type="primary")
        st.caption("To get a PDF, open the downloaded file and use your browser’s Print → Save as PDF; the report has a print layout.")
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.markdown("### Outreach drafts and approval gate")
    st.caption("Drafts are never sent. Approving records a person's decision and contacts no one.")
    for p in fin["ranked"]:
        if p.get("held_for_review") or not p.get("proposal"):
            continue
        cid = str(p["company"]["id"])
        done_ap = store.query("SELECT 1 FROM approvals WHERE run_id=? AND company_id=?", (current, cid))
        c1, c2 = st.columns([6, 1])
        with c1:
            with st.expander(f'{p["company"]["name"]}  ·  {p.get("recommendation")}  ·  “{p["proposal"].get("subject")}”'):
                st.caption(p["proposal"].get("status"))
                st.code(f'Subject: {p["proposal"].get("subject")}\n\n{p["proposal"].get("body")}', language=None, wrap_lines=True)
        if done_ap:
            c2.markdown(badge("approved · not sent", T["ok"]), unsafe_allow_html=True)
        elif c2.button("Approve draft", key=f"ap{cid}"):
            store.execute("INSERT INTO approvals(run_id,company_id,action,ts,note) VALUES (?,?,?,?,?)", (current, cid, "approve_draft", time.time(), "recorded only; nothing sent"))
            ecosystem.set_stage(current, cid, "Approved", "draft approved; nothing was sent")
            st.rerun()
    st.markdown("### Report preview")
    st.iframe(html_doc, height=900)
