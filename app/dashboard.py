"""Investigator dashboard.  Run:  streamlit run app/dashboard.py"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from amanah import graph  # noqa: E402
from amanah.llm import get_llm  # noqa: E402
from amanah.screening import disposition, screen  # noqa: E402

st.set_page_config(page_title="Amanah — AML & KYC Copilot", page_icon="🛡️", layout="wide")

REC_LABEL = {
    "clear": ("Clear", "green"), "request_information": ("Request information", "orange"),
    "enhanced_due_diligence": ("Enhanced due diligence", "orange"),
    "escalate_str_review": ("Escalate for STR review", "red"),
    "investigate_possible_match": ("Investigate possible match", "red"),
    "freeze_and_report": ("Freeze & report (TFS)", "red"),
}


@st.cache_resource(show_spinner="Loading data and models…")
def context():
    return graph.ctx()


ctx = context()
llm = get_llm()

st.title("🛡️ Amanah")
st.caption("Agentic AML & KYC investigation copilot · Arabic–English · every decision approved by a human")
st.sidebar.markdown(f"**LLM:** {llm.provider + ' · ' + llm.model if llm.available else 'none — template mode'}")
st.sidebar.info("All data is synthetic. No real customers or sanctions records.")

tab_case, tab_screen, tab_audit, tab_eval = st.tabs(["Investigate", "Name screening", "Audit trail", "Evaluation"])

# --- investigate --------------------------------------------------------------
with tab_case:
    customers = ctx.customers
    demo = {
        "Watchlist match example": next(k for k, v in customers.items() if v["watchlist_ref"]),
        "Suspicious activity example": next(k for k, v in customers.items() if v["typologies"] and not v["watchlist_ref"]),
        "Clean customer example": next(k for k, v in customers.items() if not v["typologies"] and not v["watchlist_ref"]),
    }
    c1, c2 = st.columns([2, 3])
    pick = c1.radio("Demo shortcuts", list(demo), horizontal=False)
    cid = c2.text_input("Customer ID", demo[pick])

    if cid in customers:
        c = customers[cid]
        st.markdown(f"**{c['name_en']}** {('· ' + c['name_ar']) if c['name_ar'] else ''} · DOB {c['dob']} · "
                    f"{c['nationality']} · {c['segment'].upper()} · {c['occupation']} · "
                    f"declared income AED {c['declared_monthly_income']:,}/month")
        if st.button("▶ Run agents", type="primary"):
            with st.spinner("Agents working…"):
                st.session_state["run"] = graph.start_case(cid)

    run = st.session_state.get("run")
    if run:
        s = run["state"]
        case = s["case"]
        label, color = REC_LABEL[case["recommendation"]]
        st.subheader(f"{run['case_id']} — :{color}[{label}]")

        st.markdown("##### Agent trace")
        st.dataframe(pd.DataFrame(s["trace"])[["agent", "action", "latency_ms", "model"]],
                     hide_index=True, use_container_width=True)

        a, b, m = st.columns(3)
        with a:
            st.markdown("##### 🪪 KYC")
            st.write(f"Status: **{s['kyc']['status']}** · extraction: {s['kyc']['extraction']}")
            for i in s["kyc"]["issues"]:
                st.write(f"- `{i['severity']}` {i['issue']}")
        with b:
            st.markdown("##### 🔎 Screening")
            st.write(f"Disposition: **{s['screening']['disposition']}**")
            for h in s["screening"]["hits"][:3]:
                st.write(f"- {h['listed_name']} · {h['listed_name_ar']} · {h['list_name']} · "
                         f"confidence **{h['confidence']}**  \n  _{h['reason']}_")
        with m:
            st.markdown("##### 📈 Transactions")
            mon = s["monitoring"]
            st.metric("Risk score", f"{mon['risk_score']:.2f}", "ALERT" if mon["alert"] else "no alert",
                      delta_color="inverse" if mon["alert"] else "off")
            for f in mon["indicators"]:
                st.write(f"- 🚩 {f}")
            if mon.get("drivers"):
                st.caption("Top SHAP drivers")
                st.bar_chart(pd.DataFrame(mon["drivers"]).set_index("feature")["impact"])

        st.markdown("##### 📝 Case draft")
        st.write(case["summary"])
        if case.get("red_flags"):
            st.write("**Red flags:** " + "; ".join(case["red_flags"]))
        if case.get("legitimate_explanations_to_check"):
            st.write("**Check for legitimate explanations:** " + "; ".join(case["legitimate_explanations_to_check"]))
        st.write(f"**Rationale:** {case.get('rationale', '')}")
        if case.get("citations"):
            st.caption("Policy cited: " + ", ".join(case["citations"]))
        if case.get("guardrails"):
            st.warning("Guardrails applied: " + "; ".join(case["guardrails"]))

        st.markdown("##### ✅ Investigator decision")
        record = ctx.audit.case(run["case_id"])
        if record and record["status"] == "awaiting_review":
            reviewer = st.text_input("Reviewer", "investigator.demo")
            note = st.text_area("Note", "")
            d1, d2, d3 = st.columns(3)
            for col, dec in ((d1, "approve"), (d2, "reject"), (d3, "escalate")):
                if col.button(dec.capitalize(), use_container_width=True):
                    graph.review_case(run["case_id"], dec, reviewer, note)
                    st.rerun()
        elif record:
            st.success(f"Closed · {record['decision']} by {record['reviewer']} at {record['decided_at']}")

# --- screening playground -------------------------------------------------------
with tab_screen:
    from amanah.screening import load_watchlist

    samples = load_watchlist()[:3]
    st.markdown("Type a listed name in Arabic, English or a different spelling. Names on the synthetic list include: "
                + " · ".join(f"`{e['name_en']}` / `{e['name_ar']}`" for e in samples))
    q1, q2, q3 = st.columns(3)
    name_en = q1.text_input("Name (English)", "")
    name_ar = q2.text_input("الاسم (Arabic)", "")
    dob = q3.text_input("DOB (YYYY-MM-DD, optional)", "")
    if name_en or name_ar:
        hits = screen(name_en, name_ar, dob or None)
        st.write(f"Disposition: **{disposition(hits)}**")
        st.dataframe(pd.DataFrame([h.as_dict() for h in hits]), hide_index=True, use_container_width=True)

# --- audit ----------------------------------------------------------------------------
with tab_audit:
    cases = ctx.audit.cases()
    if cases:
        df = pd.DataFrame(cases).drop(columns=["payload"])
        st.dataframe(df, hide_index=True, use_container_width=True)
        sel = st.selectbox("Case", [c["case_id"] for c in cases])
        st.dataframe(pd.DataFrame(ctx.audit.events(sel)), hide_index=True, use_container_width=True)
    else:
        st.info("No cases yet.")

# --- evaluation -------------------------------------------------------------------------
with tab_eval:
    path = ROOT / "eval" / "results.json"
    if path.exists():
        res = json.loads(path.read_text())
        st.json(res)
    else:
        st.info("Run `python -m eval.run_eval` to generate evaluation results.")
