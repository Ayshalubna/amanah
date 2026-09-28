"""Read-only data views for the web app: customer book, transactions, watchlist, stats.

Every customer gets two pre-computed signals so the customer table is useful at a glance:
  * risk score from the transaction model (the same model the monitoring agent uses)
  * watchlist check from the screening engine (the same engine the screening agent uses)
Ground-truth labels from the synthetic generator are never shown, except to pick the
three "try an example" customers on the home page.
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path

from . import graph
from . import monitoring as mon
from .screening import disposition, load_watchlist, screen
from .synth import HIGH_RISK_COUNTRIES

ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"
EVAL_RESULTS = Path(__file__).resolve().parent.parent / "eval" / "results.json"
_lock = threading.Lock()

COUNTRY = {
    "AE": "UAE", "SA": "Saudi Arabia", "EG": "Egypt", "JO": "Jordan", "LB": "Lebanon", "PK": "Pakistan",
    "IN": "India", "SY": "Syria", "IQ": "Iraq", "YE": "Yemen", "GB": "United Kingdom", "RU": "Russia",
    "PH": "Philippines", "CN": "China", "IR": "Iran", "KP": "North Korea", "MM": "Myanmar", "AF": "Afghanistan",
    "HK": "Hong Kong", "TR": "Turkey", "CY": "Cyprus",
}

TX_LABEL = {"card": "Card payment", "transfer_in": "Money received", "transfer_out": "Money sent",
            "cash_in": "Cash deposit", "cash_out": "Cash withdrawal"}


def risk_level(score: float, threshold: float) -> str:
    if score >= max(0.5, threshold * 4):
        return "high"
    if score >= threshold:
        return "medium"
    return "low"


@lru_cache(maxsize=1)
def _risk_scores() -> dict[str, float]:
    c = graph.ctx()
    scores = c.model.score(c.features)
    return {cid: round(float(s), 4) for cid, s in zip(c.features.index, scores, strict=True)}


def _screening_all() -> dict[str, dict]:
    """Screen every customer once and cache to disk (takes a few seconds the first time)."""
    cache = ARTIFACTS / "screening_cache.json"
    wl = ARTIFACTS.parent / "amanah" / "data" / "watchlist.json"
    stamp = str(wl.stat().st_mtime) if wl.exists() else "x"
    with _lock:
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("stamp") == stamp:
                return data["results"]
        results = {}
        for cid, cust in graph.ctx().customers.items():
            hits = screen(cust.get("name_en", ""), cust.get("name_ar", ""), cust.get("dob"), cust.get("nationality"))
            results[cid] = {"disposition": disposition(hits),
                            "top": hits[0].listed_name if hits else None,
                            "confidence": hits[0].confidence if hits else 0.0}
        ARTIFACTS.mkdir(exist_ok=True)
        cache.write_text(json.dumps({"stamp": stamp, "results": results}), encoding="utf-8")
        return results


_screen_cache: dict | None = None


def screening_all() -> dict[str, dict]:
    global _screen_cache
    if _screen_cache is None:
        _screen_cache = _screening_all()
    return _screen_cache


def customer_rows() -> list[dict]:
    c = graph.ctx()
    risk = _risk_scores()
    scr = screening_all()
    thr = c.model.threshold
    rows = []
    for cid, cust in c.customers.items():
        r = risk.get(cid, 0.0)
        s = scr.get(cid, {"disposition": "no_match"})
        rows.append({
            "id": cid, "name_en": cust["name_en"], "name_ar": cust.get("name_ar", ""),
            "nationality": COUNTRY.get(cust["nationality"], cust["nationality"]),
            "segment": "Business" if cust["segment"] == "sme" else "Personal",
            "occupation": cust["occupation"], "income": cust["declared_monthly_income"],
            "risk": r, "risk_level": risk_level(r, thr), "watchlist": s["disposition"],
        })
    return rows


def query_customers(q: str = "", risk: str = "", watch: str = "", sort: str = "risk",
                    page: int = 1, size: int = 25) -> dict:
    rows = customer_rows()
    if q:
        ql = q.lower().strip()
        rows = [r for r in rows if ql in r["name_en"].lower() or ql in r["name_ar"] or ql in r["id"].lower()
                or ql in r["nationality"].lower() or ql in r["occupation"].lower()]
    if risk:
        rows = [r for r in rows if r["risk_level"] == risk]
    if watch == "hit":
        rows = [r for r in rows if r["watchlist"] != "no_match"]
    if sort == "risk":
        rows.sort(key=lambda r: (r["watchlist"] == "no_match", -r["risk"]))
    elif sort == "name":
        rows.sort(key=lambda r: r["name_en"])
    elif sort == "income":
        rows.sort(key=lambda r: -r["income"])
    total = len(rows)
    start = (max(page, 1) - 1) * size
    return {"total": total, "page": page, "size": size, "rows": rows[start:start + size]}


def customer_detail(cid: str) -> dict | None:
    c = graph.ctx()
    cust = c.customers.get(cid)
    if not cust:
        return None
    tx = c.tx[c.tx.customer_id == cid].sort_values("timestamp")
    txs = []
    for t in tx.itertuples(index=False):
        flags = []
        if t.type == "cash_in" and 40_000 <= t.amount_aed < 55_000:
            flags.append("Just under the AED 55,000 cash reporting level")
        if t.counterparty_country in HIGH_RISK_COUNTRIES:
            flags.append(f"Sent to a high-risk country ({COUNTRY.get(t.counterparty_country, t.counterparty_country)})")
        if t.amount_aed >= 50_000 and t.amount_aed % 10_000 == 0:
            flags.append("Large round amount")
        if t.amount_aed >= 5 * max(cust["declared_monthly_income"], 1) and t.type in ("transfer_in", "cash_in"):
            flags.append("Much bigger than this customer's monthly income")
        txs.append({"id": t.tx_id, "date": t.timestamp.strftime("%Y-%m-%d %H:%M"), "type": TX_LABEL[t.type],
                    "kind": t.type, "amount": round(float(t.amount_aed), 2),
                    "country": COUNTRY.get(t.counterparty_country, t.counterparty_country), "flags": flags})
    f = c.features.loc[cid] if cid in c.features.index else None
    risk = _risk_scores().get(cid, 0.0)
    total_in = float(f.total_in) if f is not None else 0.0
    total_out = float(f.total_out) if f is not None else 0.0
    return {
        "id": cid, "name_en": cust["name_en"], "name_ar": cust.get("name_ar", ""), "dob": cust["dob"],
        "nationality": COUNTRY.get(cust["nationality"], cust["nationality"]),
        "segment": "Business" if cust["segment"] == "sme" else "Personal", "occupation": cust["occupation"],
        "income": cust["declared_monthly_income"], "emirates_id": cust["emirates_id"], "id_expiry": cust["id_expiry"],
        "risk": risk, "risk_level": risk_level(risk, c.model.threshold),
        "watchlist": screening_all().get(cid, {}).get("disposition", "no_match"),
        "summary": {"transactions": len(txs), "money_in": round(total_in), "money_out": round(total_out),
                    "flagged": sum(1 for t in txs if t["flags"])},
        "transactions": txs,
    }


def examples() -> dict:
    c = graph.ctx()
    risk = _risk_scores()
    watch = [k for k, v in c.customers.items() if v["watchlist_ref"]]
    sus = sorted((k for k, v in c.customers.items() if v["typologies"] and not v["watchlist_ref"]),
                 key=lambda k: -risk.get(k, 0))
    clean = [k for k, v in c.customers.items() if not v["typologies"] and not v["watchlist_ref"]
             and risk.get(k, 1) < c.model.threshold / 4]
    pick = lambda ids: ids[0] if ids else None  # noqa: E731
    out = {}
    for key, cid in (("sanctions", pick(watch)), ("suspicious", pick(sus)), ("clean", pick(clean))):
        if cid:
            out[key] = {"id": cid, "name": c.customers[cid]["name_en"]}
    return out


def watchlist(q: str = "") -> list[dict]:
    rows = []
    for e in load_watchlist():
        rows.append({"id": e["id"], "name_en": e["name_en"], "name_ar": e.get("name_ar", ""),
                     "aliases": e.get("aliases", []), "dob": e.get("dob", ""),
                     "nationality": COUNTRY.get(e.get("nationality", ""), e.get("nationality", "")),
                     "list": e.get("list_name", "").replace("SAMPLE-", "").replace("-", " ").title(),
                     "reason": e.get("reason", "")})
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["name_en"].lower() or ql in r["name_ar"] or any(ql in a.lower() for a in r["aliases"])]
    return rows


def stats() -> dict:
    c = graph.ctx()
    rows = customer_rows()
    return {
        "customers": len(rows), "transactions": int(len(c.tx)), "watchlist": len(load_watchlist()),
        "high_risk": sum(r["risk_level"] == "high" for r in rows),
        "medium_risk": sum(r["risk_level"] == "medium" for r in rows),
        "watchlist_hits": sum(r["watchlist"] != "no_match" for r in rows),
        "cases_open": len(c.audit.cases("awaiting_review")), "cases_closed": len(c.audit.cases("closed")),
    }


def eval_results() -> dict | None:
    if EVAL_RESULTS.exists():
        return json.loads(EVAL_RESULTS.read_text(encoding="utf-8"))
    return None


def features_for(cid: str) -> dict:
    c = graph.ctx()
    if cid not in c.features.index:
        return {}
    f = c.features.loc[cid]
    return {mon.FEATURE_LABELS[k]: round(float(f[k]), 2) for k in mon.FEATURES}
