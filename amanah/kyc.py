"""KYC document checks for Arabic / English identity and trade-licence text.

Input is document text (from OCR or a form). Fields are extracted by the LLM
when one is available, with a regex extractor as a fallback, then every
field is validated deterministically. The LLM never decides pass/fail.
"""
from __future__ import annotations

import re
from datetime import date

from .llm import get_llm
from .names import name_similarity

EID_RE = re.compile(r"784[-\s]?(\d{4})[-\s]?(\d{7})[-\s]?(\d)")
DATE_RE = r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})"

EXTRACT_PROMPT = """You extract fields from UAE KYC documents written in Arabic and/or English.
Return JSON only with keys: name_en, name_ar, emirates_id, dob, nationality, id_expiry,
trade_licence_no, licence_expiry, company_name. Dates as YYYY-MM-DD. Use null when a field is absent.
Never guess a value that is not in the text."""


def _to_iso(d: str | None) -> str | None:
    if not d:
        return None
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", d):
        dd, mm, yy = d.split("/")
        return f"{yy}-{mm}-{dd}"
    return d


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def regex_extract(text: str) -> dict:
    def grab(patterns):
        for p in patterns:
            m = re.search(p, text, re.I)
            if m:
                return m.group(1).strip()
        return None

    eid = EID_RE.search(text)
    return {
        "name_en": grab([r"Name\s*[:：]\s*([A-Za-z .'-]+)"]),
        "name_ar": grab([r"الاسم\s*[:：]\s*([؀-ۿ ]+)"]),
        "emirates_id": f"784-{eid.group(1)}-{eid.group(2)}-{eid.group(3)}" if eid else None,
        "dob": _to_iso(grab([rf"(?:Date of Birth|DOB)\s*[:：]\s*{DATE_RE}", rf"تاريخ الميلاد\s*[:：]\s*{DATE_RE}"])),
        "nationality": grab([r"Nationality\s*[:：]\s*([A-Za-z ]+?)\s*(?:\n|$)"]),
        "id_expiry": _to_iso(grab([rf"(?:Expiry Date|Expiry)\s*[:：]\s*{DATE_RE}", rf"تاريخ الانتهاء\s*[:：]\s*{DATE_RE}"])),
        "trade_licence_no": grab([r"Licen[cs]e\s*No\.?\s*[:：]\s*([A-Z0-9-]+)", r"رقم الرخصة\s*[:：]\s*([A-Z0-9-]+)"]),
        "licence_expiry": _to_iso(grab([rf"Licen[cs]e Expiry\s*[:：]\s*{DATE_RE}"])),
        "company_name": grab([r"Trade Name\s*[:：]\s*(.+)"]),
    }


def extract(text: str) -> tuple[dict, str]:
    llm = get_llm()
    if llm.available:
        data, _ = llm.chat_json(EXTRACT_PROMPT, text)
        if data:
            fallback = regex_extract(text)
            # LLM output is only trusted where it is well-formed; regex fills gaps
            for k, v in fallback.items():
                if not data.get(k) and v:
                    data[k] = v
            return data, f"llm:{llm.model}"
    return regex_extract(text), "regex"


def validate(fields: dict, application: dict | None = None, today: date | None = None) -> dict:
    """Deterministic checks. Returns issues with a severity the case agent can act on."""
    today = today or date.today()
    application = application or {}
    issues: list[dict] = []

    def issue(sev, msg):
        issues.append({"severity": sev, "issue": msg})

    for key in ("name_en", "emirates_id", "dob", "id_expiry"):
        if not fields.get(key):
            issue("high", f"Missing required field: {key}")

    eid = fields.get("emirates_id")
    if eid:
        digits = re.sub(r"\D", "", eid)
        if len(digits) != 15 or not digits.startswith("784"):
            issue("high", "Emirates ID is not in the 784-YYYY-NNNNNNN-C format")
        elif not luhn_valid(digits):
            issue("high", "Emirates ID check digit is invalid (possible typo or tampering)")
        elif fields.get("dob") and digits[3:7] != fields["dob"][:4]:
            issue("medium", "Birth year in Emirates ID does not match date of birth")

    for key, label in (("id_expiry", "Identity document"), ("licence_expiry", "Trade licence")):
        if fields.get(key):
            try:
                exp = date.fromisoformat(fields[key])
                if exp < today:
                    issue("high", f"{label} expired on {exp.isoformat()}")
                elif (exp - today).days < 30:
                    issue("low", f"{label} expires within 30 days")
            except ValueError:
                issue("medium", f"{label} expiry date unreadable")

    if fields.get("name_en") and fields.get("name_ar"):
        s = name_similarity(fields["name_en"], fields["name_ar"])
        if s < 80:
            issue("medium", f"Arabic and English names on the document do not agree (similarity {s:.0f}/100)")

    if application.get("name_en") and fields.get("name_en"):
        s = name_similarity(application["name_en"], fields["name_en"])
        if s < 85:
            issue("high", f"Name on document differs from application (similarity {s:.0f}/100)")
    if application.get("dob") and fields.get("dob") and application["dob"] != fields["dob"]:
        issue("high", "Date of birth on document differs from application")

    worst = max((i["severity"] for i in issues), key=["low", "medium", "high"].index, default=None)
    return {"fields": fields, "issues": issues,
            "status": "fail" if worst == "high" else "review" if worst == "medium" else "pass"}


def sample_document(customer: dict) -> str:
    """Render a customer record as bilingual ID-card text, as OCR would return it."""
    return (
        "UNITED ARAB EMIRATES — IDENTITY CARD\nبطاقة الهوية — الإمارات العربية المتحدة\n"
        f"ID Number: {customer['emirates_id']}\n"
        f"Name: {customer['name_en']}\n"
        + (f"الاسم: {customer['name_ar']}\n" if customer.get("name_ar") else "")
        + f"Date of Birth: {customer['dob']}\n"
        f"Nationality: {customer['nationality']}\n"
        f"Expiry Date: {customer['id_expiry']}\n"
    )
