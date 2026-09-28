"""REST API: open cases, review them, read the audit trail.

Run:  uvicorn amanah.api:api --reload
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import graph, overview
from .hardening import AccessLog, RateLimit, SecurityHeaders, warm_up
from .llm import get_llm
from .rag import get_retriever
from .screening import disposition, screen


@asynccontextmanager
async def lifespan(_app):
    if os.getenv("AMANAH_WARMUP", "1") == "1":
        warm_up()
    yield


api = FastAPI(title="Amanah — AML & KYC Investigation Copilot", version="1.1.0", lifespan=lifespan,
              description="Multi-agent AML/KYC copilot with human approval on every decision.")
api.add_middleware(GZipMiddleware, minimum_size=1000)
api.add_middleware(SecurityHeaders)
api.add_middleware(RateLimit, reads_per_min=int(os.getenv("AMANAH_READS_PER_MIN", "240")),
                   writes_per_min=int(os.getenv("AMANAH_WRITES_PER_MIN", "30")))
api.add_middleware(AccessLog)

CUSTOMER_ID = r"^C\d{5}$"


class OpenCase(BaseModel):
    customer_id: str = Field(pattern=CUSTOMER_ID, examples=["C00007"])
    document_text: str | None = Field(None, max_length=5000, description="OCR text of the identity document; generated if omitted")


class Review(BaseModel):
    decision: str = Field(pattern="^(approve|reject|escalate)$")
    reviewer: str = Field(min_length=2, max_length=60)
    note: str = Field("", max_length=1000)


class ScreenRequest(BaseModel):
    name_en: str = Field("", max_length=120)
    name_ar: str = Field("", max_length=120)
    dob: str | None = Field(None, pattern=r"^\d{4}(-\d{2}-\d{2})?$")
    nationality: str | None = Field(None, max_length=40)


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
def policy_search(q: str = Query(..., max_length=200), k: int = Query(3, ge=1, le=10)):
    return [{"citation": p.citation, "score": round(s, 3), "text": p.text} for p, s in get_retriever().search(q, k)]


# --- data views for the web app --------------------------------------------------

@api.get("/api/stats")
def api_stats():
    llm = get_llm()
    return {**overview.stats(), "llm": f"{llm.provider} · {llm.model}" if llm.available else None}


@api.get("/api/examples")
def api_examples():
    return overview.examples()


@api.get("/api/customers")
def api_customers(q: str = Query("", max_length=80), risk: str = Query("", pattern="^(|low|medium|high)$"),
                  watch: str = Query("", pattern="^(|hit)$"), sort: str = Query("risk", pattern="^(risk|name|income)$"),
                  page: int = Query(1, ge=1, le=10000), size: int = Query(25, ge=1, le=100)):
    return overview.query_customers(q, risk, watch, sort, page, size)


@api.get("/api/customers/{customer_id}")
def api_customer(customer_id: str):
    d = overview.customer_detail(customer_id)
    if not d:
        raise HTTPException(404, "customer not found")
    return d


@api.get("/api/watchlist")
def api_watchlist(q: str = Query("", max_length=80)):
    return overview.watchlist(q)


@api.get("/api/eval")
def api_eval():
    return overview.eval_results() or {}


WEB = Path(__file__).resolve().parent.parent / "web"
if WEB.exists():
    api.mount("/", StaticFiles(directory=WEB, html=True), name="web")
