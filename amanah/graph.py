"""Amanah multi-agent workflow (LangGraph).

    START -> supervisor -> kyc_agent        -> supervisor
                        -> screening_agent  -> supervisor
                        -> monitoring_agent -> supervisor
                        -> case_agent (only when risk is found) -> human_review
                        -> human_review (low risk: proposed clearance)
             human_review -- interrupt(): waits for an investigator -- -> finalize -> END

The supervisor is a deterministic router: which checks run, and whether the
(slower, costlier) LLM case agent is needed at all, is decided by policy and
never by the model. The LLM only extracts, summarises and drafts. No agent can
freeze funds, file a report or close a case: every outcome passes through the
human_review interrupt, and every step is written to the audit trail.
"""
from __future__ import annotations

import json
import operator
import time
import uuid
from functools import lru_cache
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import kyc as kyc_mod
from . import monitoring as mon
from . import screening as scr
from .audit import Audit
from .llm import get_llm
from .rag import get_retriever

# Severity ladder. The LLM may raise a recommendation, never lower it below the policy floor.
RECOMMENDATIONS = ["clear", "request_information", "enhanced_due_diligence",
                   "escalate_str_review", "investigate_possible_match", "freeze_and_report"]

RISK_LEVEL = {"clear": "low", "request_information": "medium", "enhanced_due_diligence": "medium",
              "escalate_str_review": "high", "investigate_possible_match": "high", "freeze_and_report": "critical"}


class CaseState(TypedDict, total=False):
    case_id: str
    customer: dict
    document_text: str
    kyc: dict
    screening: dict
    monitoring: dict
    policy_floor: str
    case: dict
    decision: dict
    trace: Annotated[list[dict], operator.add]


# --- shared resources -------------------------------------------------------

class Context:
    def __init__(self):
        customers, tx = mon.load_data()
        raw = json.loads((mon.DATA_DIR / "customers.json").read_text(encoding="utf-8"))
        self.customers = {c["id"]: c for c in raw}
        self.features = mon.build_features(customers, tx)
        try:
            self.model = mon.RiskModel.load()
        except Exception:
            y = mon.labels(customers).reindex(self.features.index).fillna(0)
            self.model, _ = mon.RiskModel.train(self.features, y)
            self.model.save()
        self.audit = Audit()


@lru_cache(maxsize=1)
def ctx() -> Context:
    return Context()


def _step(agent: str, action: str, t0: float, model: str = "", **detail) -> dict:
    return {"agent": agent, "action": action, "latency_ms": int((time.perf_counter() - t0) * 1000),
            "model": model, **detail}


def _log(state: CaseState, step: dict) -> None:
    extra = {k: v for k, v in step.items() if k not in ("agent", "action", "latency_ms", "model")}
    ctx().audit.log(state["case_id"], step["agent"], step["action"], extra, step["latency_ms"], step["model"])


# --- agents -------------------------------------------------------------------

def supervisor(state: CaseState) -> Command:
    if "kyc" not in state:
        goto = "kyc_agent"
    elif "screening" not in state:
        goto = "screening_agent"
    elif "monitoring" not in state:
        goto = "monitoring_agent"
    else:
        floor = policy_floor(state)
        goto = "case_agent" if floor != "clear" else "human_review"
        step = {"agent": "supervisor", "action": f"route -> {goto}", "latency_ms": 0, "model": "",
                "policy_floor": floor}
        _log(state, step)
        update: dict[str, Any] = {"policy_floor": floor, "trace": [step]}
        if goto == "human_review":
            update["case"] = {
                "summary": "All checks passed: identity verified, no watchlist match, no transaction alerts.",
                "red_flags": [], "recommendation": "clear", "rationale": "No indicators under policy §1, §3 or §4.",
                "citations": [], "drafted_by": "template"}
        return Command(goto=goto, update=update)
    return Command(goto=goto)


def kyc_agent(state: CaseState) -> dict:
    t0 = time.perf_counter()
    fields, method = kyc_mod.extract(state["document_text"])
    result = kyc_mod.validate(fields, state["customer"])
    step = _step("kyc_agent", f"verified identity document ({result['status']})", t0,
                 model=method, issues=len(result["issues"]))
    _log(state, step)
    return {"kyc": {**result, "extraction": method}, "trace": [step]}


def screening_agent(state: CaseState) -> dict:
    t0 = time.perf_counter()
    c = state["customer"]
    hits = scr.screen(c.get("name_en", ""), c.get("name_ar", ""), c.get("dob"), c.get("nationality"))
    disp = scr.disposition(hits)
    step = _step("screening_agent", f"screened against watchlists ({disp})", t0, hits=len(hits))
    _log(state, step)
    return {"screening": {"disposition": disp, "hits": [h.as_dict() for h in hits]}, "trace": [step]}


def monitoring_agent(state: CaseState) -> dict:
    t0 = time.perf_counter()
    c = ctx()
    result = mon.assess(state["customer"]["id"], c.features, c.model)
    step = _step("monitoring_agent", f"scored transactions (risk {result['risk_score']:.2f})", t0,
                 alert=result["alert"])
    _log(state, step)
    return {"monitoring": result, "trace": [step]}


def policy_floor(state: CaseState) -> str:
    s, m, k = state["screening"]["disposition"], state["monitoring"], state["kyc"]["status"]
    if s == "likely_match":
        return "freeze_and_report"
    if s == "possible_match":
        return "investigate_possible_match"
    if m["alert"] and m["indicators"]:
        return "escalate_str_review"
    if m["alert"]:
        return "enhanced_due_diligence"
    if k in ("fail", "review"):
        return "request_information"
    return "clear"


CASE_PROMPT = """You are an AML investigations assistant at a UAE bank. Draft a case summary for a human investigator.
Use ONLY the facts and policy passages provided. Do not invent transactions, names or amounts.
Return JSON with keys:
  summary (3-5 sentences, plain English),
  red_flags (list of short strings),
  legitimate_explanations_to_check (list of short strings),
  recommendation (one of: {options}),
  rationale (2-3 sentences citing policy sections like "aml_policy_en §4"),
  citations (list of the policy citations you relied on).
The recommendation must be at least as severe as the policy floor: {floor}."""


def _facts(state: CaseState) -> str:
    c, k, s, m = state["customer"], state["kyc"], state["screening"], state["monitoring"]
    lines = [f"Customer {c['id']}: {c.get('name_en')} ({c.get('name_ar') or 'no Arabic name'}), "
             f"DOB {c.get('dob')}, nationality {c.get('nationality')}, {c.get('segment')} segment, "
             f"occupation {c.get('occupation')}, declared monthly income AED {c.get('declared_monthly_income'):,}."]
    lines.append(f"KYC status: {k['status']}. Issues: " + ("; ".join(i["issue"] for i in k["issues"]) or "none"))
    if s["hits"]:
        h = s["hits"][0]
        lines.append(f"Top watchlist hit: {h['listed_name']} on {h['list_name']} (confidence {h['confidence']}): {h['reason']}.")
    else:
        lines.append("No watchlist hits.")
    lines.append(f"Transaction risk score {m['risk_score']} (alert={m['alert']}). Indicators: "
                 + ("; ".join(m["indicators"]) or "none"))
    if m.get("drivers"):
        lines.append("Top model drivers: " + "; ".join(f"{d['feature']}={d['value']} ({d['direction']})" for d in m["drivers"]))
    return "\n".join(lines)


def _template_case(state: CaseState, passages) -> dict:
    s, m, k = state["screening"], state["monitoring"], state["kyc"]
    flags = [i["issue"] for i in k["issues"]] + m["indicators"]
    if s["hits"]:
        flags.insert(0, f"Watchlist hit: {s['hits'][0]['listed_name']} ({s['hits'][0]['reason']})")
    floor = state["policy_floor"]
    return {
        "summary": f"Customer {state['customer']['id']} requires review: " + (flags[0] if flags else "model risk alert") + ".",
        "red_flags": flags or ["Elevated transaction risk score"],
        "legitimate_explanations_to_check": ["Source of funds documentation", "Recent life or business events"],
        "recommendation": floor,
        "rationale": f"Policy floor '{floor}' applies based on the findings above.",
        "citations": [p.citation for p, _ in passages],
        "drafted_by": "template",
    }


def case_agent(state: CaseState) -> dict:
    t0 = time.perf_counter()
    floor = state["policy_floor"]
    query = " ".join(state["monitoring"]["indicators"] + [floor.replace("_", " "), "sanctions" if state["screening"]["hits"] else ""])
    passages = get_retriever().search(query or "customer due diligence", k=3)
    llm = get_llm()
    policy_text = "\n\n".join(f"[{p.citation}]\n{p.text}" for p, _ in passages)
    draft, res = llm.chat_json(CASE_PROMPT.format(options=", ".join(RECOMMENDATIONS), floor=floor),
                               f"FACTS:\n{_facts(state)}\n\nPOLICY PASSAGES:\n{policy_text}")
    guardrail_notes = []
    if draft and isinstance(draft, dict) and draft.get("summary"):
        rec = draft.get("recommendation")
        if rec not in RECOMMENDATIONS:
            guardrail_notes.append(f"invalid recommendation '{rec}' replaced by policy floor")
            rec = floor
        elif RECOMMENDATIONS.index(rec) < RECOMMENDATIONS.index(floor):
            guardrail_notes.append(f"recommendation '{rec}' below policy floor, raised to '{floor}'")
            rec = floor
        allowed = {p.citation for p, _ in passages}
        cites = [c for c in draft.get("citations", []) if c in allowed]
        if len(cites) < len(draft.get("citations", [])):
            guardrail_notes.append("removed citations not present in retrieved policy")
        case = {**draft, "recommendation": rec, "citations": cites or sorted(allowed),
                "drafted_by": f"llm:{res.model}", "guardrails": guardrail_notes}
    else:
        case = _template_case(state, passages)
    step = _step("case_agent", f"drafted case ({case['recommendation']})", t0,
                 model=case["drafted_by"], guardrails=guardrail_notes, citations=case["citations"])
    _log(state, step)
    return {"case": case, "trace": [step]}


def human_review(state: CaseState) -> dict:
    case = state["case"]
    audit = ctx().audit
    audit.propose(state["case_id"], case["recommendation"], RISK_LEVEL[case["recommendation"]], case["summary"],
                  {k: state.get(k) for k in ("kyc", "screening", "monitoring", "case", "policy_floor")})
    decision = interrupt({"case_id": state["case_id"], "recommendation": case["recommendation"],
                          "summary": case["summary"], "message": "Investigator approval required"})
    step = {"agent": "investigator", "action": f"{decision.get('decision')} ({decision.get('reviewer', 'unknown')})",
            "latency_ms": 0, "model": "", "note": decision.get("note", "")}
    _log(state, step)
    return {"decision": decision, "trace": [step]}


def finalize(state: CaseState) -> dict:
    d = state["decision"]
    ctx().audit.decide(state["case_id"], d.get("decision", "unknown"), d.get("reviewer", "unknown"), d.get("note", ""))
    return {}


def build_graph(checkpointer=None):
    g = StateGraph(CaseState)
    g.add_node("supervisor", supervisor, destinations=("kyc_agent", "screening_agent", "monitoring_agent",
                                                       "case_agent", "human_review"))
    g.add_node("kyc_agent", kyc_agent)
    g.add_node("screening_agent", screening_agent)
    g.add_node("monitoring_agent", monitoring_agent)
    g.add_node("case_agent", case_agent)
    g.add_node("human_review", human_review)
    g.add_node("finalize", finalize)
    g.add_edge(START, "supervisor")
    for agent in ("kyc_agent", "screening_agent", "monitoring_agent"):
        g.add_edge(agent, "supervisor")
    g.add_edge("case_agent", "human_review")
    g.add_edge("human_review", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


# --- convenience API ------------------------------------------------------------

@lru_cache(maxsize=1)
def app():
    return build_graph()


def start_case(customer_id: str, document_text: str | None = None) -> dict:
    c = ctx().customers[customer_id]
    case_id = f"CASE-{uuid.uuid4().hex[:8].upper()}"
    ctx().audit.open_case(case_id, customer_id)
    config = {"configurable": {"thread_id": case_id}}
    state = app().invoke({"case_id": case_id, "customer": c, "trace": [],
                          "document_text": document_text or kyc_mod.sample_document(c)}, config)
    return {"case_id": case_id, "state": state, "pending": bool(state.get("__interrupt__"))}


def review_case(case_id: str, decision: str, reviewer: str, note: str = "") -> dict:
    if decision not in ("approve", "reject", "escalate"):
        raise ValueError("decision must be approve, reject or escalate")
    config = {"configurable": {"thread_id": case_id}}
    return app().invoke(Command(resume={"decision": decision, "reviewer": reviewer, "note": note}), config)
