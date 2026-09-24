"""REST API: open cases, review them, read the audit trail.

Run:  uvicorn amanah.api:api --reload
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import graph
from .llm import get_llm
from .rag import get_retriever
from .screening import disposition, screen

api = FastAPI(title="Amanah — AML & KYC Investigation Copilot", version="1.0.0",
              description="Multi-agent AML/KYC copilot with human approval on every decision.")


class OpenCase(BaseModel):
    customer_id: str = Field(examples=["C00007"])
    document_text: str | None = Field(None, description="OCR text of the identity document; generated if omitted")


class Review(BaseModel):
    decision: str = Field(pattern="^(approve|reject|escalate)$")
    reviewer: str = Field(min_length=2)
    note: str = ""


class ScreenRequest(BaseModel):
    name_en: str = ""
    name_ar: str = ""
    dob: str | None = None
    nationality: str | None = None


@api.get("/health")
def health():
    llm = get_llm()
    return {"status": "ok", "llm": llm.provider if llm.available else "none (template mode)",
            "model": llm.model if llm.available else None, "retriever": get_retriever().mode}


@api.get("/customers/{customer_id}")
def customer(customer_id: str):
    c = graph.ctx().customers.get(customer_id)
    if not c:
        raise HTTPException(404, "customer not found")
    return {k: v for k, v in c.items() if k not in ("typologies", "watchlist_ref")}  # hide ground-truth labels


@api.post("/cases")
def open_case(req: OpenCase):
    if req.customer_id not in graph.ctx().customers:
        raise HTTPException(404, "customer not found")
    r = graph.start_case(req.customer_id, req.document_text)
    s = r["state"]
    return {"case_id": r["case_id"], "status": "awaiting_review" if r["pending"] else "closed",
            "recommendation": s["case"]["recommendation"], "policy_floor": s["policy_floor"],
            "case": s["case"], "kyc": s["kyc"], "screening": s["screening"], "monitoring": s["monitoring"],
            "trace": s["trace"]}


@api.post("/cases/{case_id}/review")
def review(case_id: str, req: Review):
    c = graph.ctx().audit.case(case_id)
    if not c:
        raise HTTPException(404, "case not found")
    if c["status"] != "awaiting_review":
        raise HTTPException(409, f"case is {c['status']}")
    graph.review_case(case_id, req.decision, req.reviewer, req.note)
    return graph.ctx().audit.case(case_id)


@api.get("/cases")
def list_cases(status: str | None = None):
    return [{k: v for k, v in c.items() if k != "payload"} for c in graph.ctx().audit.cases(status)]


@api.get("/cases/{case_id}")
def get_case(case_id: str):
    c = graph.ctx().audit.case(case_id)
    if not c:
        raise HTTPException(404, "case not found")
    c["payload"] = json.loads(c["payload"]) if c.get("payload") else None
    return c


@api.get("/cases/{case_id}/audit")
def audit_trail(case_id: str):
    return graph.ctx().audit.events(case_id)


@api.post("/screen")
def screen_name(req: ScreenRequest):
    hits = screen(req.name_en, req.name_ar, req.dob, req.nationality)
    return {"disposition": disposition(hits), "hits": [h.as_dict() for h in hits]}


@api.get("/policy/search")
def policy_search(q: str, k: int = 3):
    return [{"citation": p.citation, "score": round(s, 3), "text": p.text} for p, s in get_retriever().search(q, k)]
