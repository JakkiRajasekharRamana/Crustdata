"""PartnerScout UI. Run: streamlit run app.py

Four screens: Partnership Brief -> Intelligence Workspace -> Partner Comparison -> Brief Generator.
The UI only reads SQLite; the pipeline runs as a separate process, so a crash never takes the UI down
and any run can be resumed with the same run id.
"""
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import report
import store
from pipeline import DEMO_REQUEST

ROOT = Path(__file__).parent
st.set_page_config(page_title="PartnerScout", layout="wide")

st.markdown("""<style>.block-container{padding-top:1.6rem}
.flag{background:#fde2e1;color:#8c1d18;padding:2px 8px;border-radius:8px;font-size:12px}
.ok{background:#dcf3e4;color:#14633a;padding:2px 8px;border-radius:8px;font-size:12px}</style>""", unsafe_allow_html=True)


def launch(run_id: str, request: str, ceiling: float, crash_after: str | None = None) -> None:
    cmd = [sys.executable, str(ROOT / "pipeline.py"), "--run-id", run_id, "--request", request, "--credit-ceiling", str(ceiling)]
    if crash_after:
        cmd += ["--crash-after", crash_after]
    subprocess.Popen(cmd, cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def runs() -> list:
    return store.query("SELECT run_id, created_at, status, request FROM runs WHERE run_id NOT IN ('smoke','explore') "
                       "AND run_id NOT LIKE 't-%' ORDER BY created_at DESC")


DEMO = store.DEMO_MODE
if DEMO:
    st.info("**Read-only demo.** You are browsing saved results of real runs on live Crustdata data (22 Nov 2026). "
            "New runs are disabled here so the hosted demo cannot spend API credits. Run it yourself with your own keys: see the README.")

st.sidebar.title("PartnerScout")
st.sidebar.caption("Strategic partnership intelligence - discover, verify, evaluate, recommend.")
page = st.sidebar.radio("Screen", ["1. Partnership Brief", "2. Intelligence Workspace", "3. Partner Comparison", "4. Brief Generator"])
rs = runs()
labels = {r["run_id"]: f'{r["run_id"]} - {r["status"]}' for r in rs}
current = st.sidebar.selectbox("Run", list(labels), format_func=lambda k: labels[k]) if rs else None
if "active" in st.session_state and st.session_state["active"] in labels:
    current = st.session_state["active"]


def final_for(run_id):
    return store.get_stage(run_id, "final") if run_id else None


# ---------------------------------------------------------------- 1
if page.startswith("1"):
    st.header("Partnership Brief")
    st.write("Describe the partnership you want, in your own words or with the structured fields.")
    req = st.text_area("Request", DEMO_REQUEST, height=140)
    with st.expander("Structured fields (optional - appended to the request)"):
        c1, c2 = st.columns(2)
        company = c1.text_input("Requesting company / website")
        industry = c1.text_input("Target industry")
        geo = c1.text_input("Geography")
        ptype = c2.text_input("Desired partner type")
        caps = c2.text_input("Required capabilities")
        extra = c2.text_input("Size or other constraints")
    c1, c2, c3 = st.columns(3)
    ceiling = c1.number_input("Credit ceiling for this run", 20, 2000, 300)
    crash = c2.selectbox("Demo: simulate a crash after stage", ["(none)", "discover", "screen", "enrich", "research", "claims"])
    if st.button("Run PartnerScout", type="primary", disabled=DEMO, help="Disabled in the read-only demo" if DEMO else None):
        parts = [req] + [f"{k}: {v}" for k, v in [("Requesting company", company), ("Target industry", industry), ("Geography", geo),
                                                  ("Partner type", ptype), ("Required capabilities", caps), ("Constraints", extra)] if v]
        rid = f"run-{uuid.uuid4().hex[:6]}"
        store.create_run(rid, " | ".join(parts))
        launch(rid, " | ".join(parts), ceiling, None if crash == "(none)" else crash)
        st.session_state["active"] = rid
        st.success(f"Started {rid}. Open 'Intelligence Workspace' to watch it work.")
    st.caption("Nothing is sent to anyone. Proposal drafts stay drafts until a person approves them, and approval only records intent.")

# ---------------------------------------------------------------- 2
elif page.startswith("2"):
    st.header("Intelligence Workspace")
    if not current:
        st.info("No runs yet.")
        st.stop()
    r = store.query("SELECT * FROM runs WHERE run_id=?", (current,))[0]
    led = store.ledger_totals(current)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", r["status"])
    c2.metric("Crustdata credits", f'{led["credits"]:.2f}')
    c3.metric("Logged calls", led["calls"])
    c4.metric("Served from cache", int(led["cache_hits"]))
    if r["error"]:
        st.warning(r["error"])
    if r["status"] in ("crashed", "paused_budget", "paused_credits") and not DEMO:
        if st.button("Resume this run (continues from the last checkpoint, no repeated paid calls)"):
            launch(current, r["request"], 300)
            st.rerun()
    fin_now = final_for(current)
    held = [p["company"]["name"] for p in (fin_now or {}).get("ranked", []) if p.get("held_for_review")]
    if held:
        st.warning(f"Held for review because a tool failed (not treated as 'no evidence'): {', '.join(held)}")
        if not DEMO and st.button("Retry held candidates (finished stages are not repeated)"):
            launch(current, r["request"], 300)
            st.rerun()
    logs = store.query("SELECT output_json FROM stages WHERE run_id=? AND stage='_log' ORDER BY item", (current,))
    import json
    msgs = [json.loads(x["output_json"])["msg"] for x in logs]
    st.subheader("Execution log")
    st.code("\n".join(msgs[-40:]) or "(waiting)")
    st.subheader("Call ledger")
    calls = store.query("SELECT ts, service, endpoint, status, credits, cost_usd, latency_ms, cached, attempt, error FROM calls WHERE run_id=? ORDER BY id DESC LIMIT 60", (current,))
    if calls:
        st.dataframe(pd.DataFrame([dict(c) for c in calls]), use_container_width=True, hide_index=True)
    if r["status"] == "running":
        time.sleep(3)
        st.rerun()

# ---------------------------------------------------------------- 3
elif page.startswith("3"):
    st.header("Partner Comparison")
    fin = final_for(current)
    if not fin:
        st.info("This run has no final result yet.")
        st.stop()
    rows = []
    for i, p in enumerate(fin["ranked"], 1):
        rows.append({"#": i, "Company": p["company"]["name"], "Fit": p["fit"].get("score"), "Confidence": p.get("evidence_confidence", {}).get("level"),
                     "Recommendation": p.get("recommendation"), "Model": (p.get("partnership_model") or {}).get("model"),
                     "Overlap": (p.get("competitive_overlap") or {}).get("level"), "Flags": "; ".join(p.get("flags", [])),
                     "Decision-maker": f'{p["stakeholder"]["name"]} ({p["stakeholder"]["title"]})' if p.get("stakeholder") else "not verified"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    pick = st.selectbox("Open partner profile", [p["company"]["name"] for p in fin["ranked"]])
    p = next(x for x in fin["ranked"] if x["company"]["name"] == pick)
    if p.get("held_for_review"):
        st.error(f'Held for review: {p.get("error")}')
        st.stop()
    st.subheader(f'{pick}  -  fit {p["fit"]["score"]}  -  {p["evidence_confidence"]["level"]} confidence')
    st.write(p["company"].get("description"))
    for f in p.get("flags", []):
        st.markdown(f'<span class="flag">{f}</span>', unsafe_allow_html=True)
    a, b = st.columns(2)
    with a:
        st.markdown("**Strategic fit (explainable)**")
        for k, v in p["components"].items():
            st.write(f'**{k}**: {v.get("score") if v.get("score") is not None else "unknown"} - {v.get("why")}  `{", ".join(v.get("claim_ids", []))}`')
        co = p.get("competitive_overlap") or {}
        st.write(f'**Competitive overlap**: {co.get("level")} - {co.get("why")}')
    with b:
        mv = p.get("mutual_value") or {}
        st.markdown("**Mutual value (hypothesis, not confirmed interest)**")
        st.write("To requester:")
        for x in mv.get("to_requester", []):
            st.write(f'- {x["point"]} *({x.get("basis")})*')
        st.write("To partner:")
        for x in mv.get("to_partner", []):
            st.write(f'- {x["point"]} *({x.get("basis")})*')
        st.write(mv.get("rationale"))
    st.markdown("**Evidence**")
    st.dataframe(pd.DataFrame([{k: c.get(k) for k in ("claim_id", "status", "category", "claim", "source_url", "quote", "retrieved_at")} for c in p["claims"]]),
                 use_container_width=True, hide_index=True)

# ---------------------------------------------------------------- 4
else:
    st.header("Partnership Brief Generator")
    fin = final_for(current)
    if not fin:
        st.info("This run has no final result yet.")
        st.stop()
    html_doc = report.build_report(fin)
    st.download_button("Download HTML report (print to PDF from the browser)", html_doc, file_name=f"{current}.html", mime="text/html")
    st.subheader("Approval gate")
    st.caption("Proposal drafts are never sent. Approving records a person's decision and contacts no one.")
    for p in fin["ranked"]:
        if p.get("held_for_review") or not p.get("proposal"):
            continue
        cid = str(p["company"]["id"])
        done = store.query("SELECT 1 FROM approvals WHERE run_id=? AND company_id=?", (current, cid))
        c1, c2 = st.columns([4, 1])
        c1.write(f'**{p["company"]["name"]}** - {p["proposal"].get("subject")}')
        if done:
            c2.markdown('<span class="ok">approved (recorded, not sent)</span>', unsafe_allow_html=True)
        elif c2.button("Approve draft", key=f"ap{cid}"):
            store.execute("INSERT INTO approvals(run_id,company_id,action,ts,note) VALUES (?,?,?,?,?)", (current, cid, "approve_draft", time.time(), "recorded only; nothing sent"))
            st.rerun()
    components.html(html_doc, height=900, scrolling=True)
