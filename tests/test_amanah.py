import json
import os
from datetime import date

import pytest

os.environ["AMANAH_LLM"] = "none"
os.environ["AMANAH_EMBEDDINGS"] = "off"

from amanah import graph, kyc  # noqa: E402
from amanah.llm import LLM, LLMResult, set_llm  # noqa: E402
from amanah.names import canonical, name_similarity, normalise_arabic  # noqa: E402
from amanah.rag import Retriever  # noqa: E402
from amanah.screening import disposition, load_watchlist, screen  # noqa: E402
from amanah.synth import luhn_check_digit  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def isolated_db(tmp_path_factory):
    import amanah.audit as audit

    audit.DB_PATH = tmp_path_factory.mktemp("db") / "test.db"
    set_llm(LLM("none"))
    yield


# --- names ------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("محمد عبد الله", "Mohammed Abdullah"),
    ("عمر الهاشمي", "Omar Al-Hashimi"),
    ("Mohamad Abdalla", "Muhammad Abd Allah"),
    ("يوسف بن راشد", "Yousef bin Rashid"),
    ("Sheikh Khaled Al Mansoori", "Khalid Al-Mansouri"),
])
def test_same_person_across_scripts_and_spellings(a, b):
    assert name_similarity(a, b) >= 90


def test_different_people_score_low():
    assert name_similarity("John Smith", "Muhammad Ali") < 60


def test_arabic_normalisation_removes_diacritics_and_alef_variants():
    assert normalise_arabic("أَحْمَد") == normalise_arabic("احمد")


def test_canonical_collapses_spelling_families():
    assert canonical("Mohammed") == canonical("Muhammad") == "muhammad"


# --- screening ---------------------------------------------------------------

def test_listed_person_found_in_arabic_script():
    entry = load_watchlist()[0]
    hits = screen("", entry["name_ar"], entry["dob"], entry["nationality"])
    assert hits and hits[0].watchlist_id == entry["id"]
    assert disposition(hits) == "likely_match"


def test_date_of_birth_mismatch_lowers_confidence():
    entry = load_watchlist()[0]
    same = screen(entry["name_en"], dob=entry["dob"])[0].confidence
    other = screen(entry["name_en"], dob="1901-01-01")[0].confidence
    assert other < same


# --- KYC --------------------------------------------------------------------

def test_emirates_id_check_digit():
    body = "78419901234567"
    good = f"784-1990-1234567-{luhn_check_digit(body)}"
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    base = {"name_en": "Ali Hasan", "dob": "1990-05-01", "id_expiry": "2030-01-01"}
    assert kyc.validate({**base, "emirates_id": good}, today=date(2026, 1, 1))["status"] == "pass"
    res = kyc.validate({**base, "emirates_id": bad}, today=date(2026, 1, 1))
    assert res["status"] == "fail" and any("check digit" in i["issue"] for i in res["issues"])


def test_expired_document_fails():
    body = "78419901234567"
    fields = {"name_en": "Ali Hasan", "dob": "1990-05-01", "id_expiry": "2025-01-01",
              "emirates_id": f"784-1990-1234567-{luhn_check_digit(body)}"}
    assert kyc.validate(fields, today=date(2026, 1, 1))["status"] == "fail"


def test_regex_extraction_reads_bilingual_card():
    c = graph.ctx().customers["C00001"]
    fields, method = kyc.extract(kyc.sample_document(c))
    assert method == "regex"
    assert fields["emirates_id"] == c["emirates_id"] and fields["dob"] == c["dob"]


# --- RAG ---------------------------------------------------------------------

def test_policy_retrieval_english_and_arabic():
    r = Retriever(use_embeddings=False)
    assert "§4" in r.search("cash deposits below reporting threshold", 1)[0][0].citation
    top = r.search("التجزئة إيداعات نقدية", 1, lang="ar")[0][0]
    assert top.lang == "ar" and "§4" in top.citation


# --- multi-agent graph -------------------------------------------------------

def _customer(pred):
    return next(k for k, v in graph.ctx().customers.items() if pred(v))


def test_watchlist_customer_is_frozen_pending_human_review():
    cid = _customer(lambda v: v["watchlist_ref"])
    r = graph.start_case(cid)
    assert r["pending"]
    assert r["state"]["case"]["recommendation"] in ("freeze_and_report", "investigate_possible_match")
    assert graph.ctx().audit.case(r["case_id"])["status"] == "awaiting_review"


def test_nothing_closes_without_a_human():
    cid = _customer(lambda v: not v["typologies"] and not v["watchlist_ref"])
    r = graph.start_case(cid)
    assert graph.ctx().audit.case(r["case_id"])["status"] == "awaiting_review"
    graph.review_case(r["case_id"], "approve", "tester", "ok")
    closed = graph.ctx().audit.case(r["case_id"])
    assert closed["status"] == "closed" and closed["reviewer"] == "tester"
    agents = [e["agent"] for e in graph.ctx().audit.events(r["case_id"])]
    assert agents[:3] == ["kyc_agent", "screening_agent", "monitoring_agent"] and agents[-1] == "investigator"


def test_llm_cannot_downgrade_policy_or_invent_citations():
    class LenientLLM(LLM):
        available = True
        model = "fake"

        def chat(self, system, user, temperature=0.1, json_mode=False):
            return LLMResult(json.dumps({
                "summary": "Looks fine to me.", "red_flags": [], "recommendation": "clear",
                "rationale": "No issue.", "citations": ["made_up_policy §99"]}), "fake", "fake", 5, True)

    set_llm(LenientLLM("ollama"))
    try:
        cid = _customer(lambda v: v["watchlist_ref"])
        case = graph.start_case(cid)["state"]["case"]
    finally:
        set_llm(LLM("none"))
    assert case["recommendation"] == "freeze_and_report"
    assert "made_up_policy §99" not in case["citations"]
    assert any("below policy floor" in g for g in case["guardrails"])


# --- API ---------------------------------------------------------------------

def test_api_open_and_review_case():
    from fastapi.testclient import TestClient

    from amanah.api import api

    client = TestClient(api)
    assert client.get("/health").json()["status"] == "ok"
    opened = client.post("/cases", json={"customer_id": "C00002"}).json()
    assert opened["status"] == "awaiting_review"
    reviewed = client.post(f"/cases/{opened['case_id']}/review",
                           json={"decision": "escalate", "reviewer": "api-tester"}).json()
    assert reviewed["status"] == "closed" and reviewed["decision"] == "escalate"
    assert client.post(f"/cases/{opened['case_id']}/review",
                       json={"decision": "approve", "reviewer": "x2"}).status_code == 409
    assert "typologies" not in client.get("/customers/C00002").json()
