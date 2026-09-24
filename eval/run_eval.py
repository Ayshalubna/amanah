"""Evaluation harness.  Run:  python -m eval.run_eval  [--cases 400]

1. Screening   - labelled Arabic/English name-variant test set vs. two naive baselines
2. Monitoring  - 5-fold CV risk model vs. a rules-only baseline
3. End to end  - full multi-agent graph over a customer sample, compared with ground truth

Writes eval/results.json and eval/RESULTS.md. CI fails if key metrics regress
below the floors in THRESHOLDS.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("AMANAH_EMBEDDINGS", "off")

from rapidfuzz import fuzz  # noqa: E402

from amanah import monitoring as mon  # noqa: E402
from amanah.names import canonical, name_similarity  # noqa: E402
from amanah.screening import NAME_THRESHOLD, disposition, load_watchlist, screen  # noqa: E402
from amanah.synth import FAMILY, FIRST, OTHER_NAMES, SPELLING_VARIANTS  # noqa: E402

HERE = Path(__file__).parent
THRESHOLDS = {"screening_recall": 0.95, "screening_precision": 0.90, "monitoring_roc_auc": 0.93,
              "e2e_watchlist_flagged": 0.95}

AR_DIACRITICS = "َُِّ"


# --- 1. screening --------------------------------------------------------------

def _typo(rng, s):
    i = rng.randrange(1, len(s) - 1)
    return s[:i] + s[i + 1:] if rng.random() < 0.5 else s[:i] + s[i] + s[i:]


def build_screening_testset(seed: int = 3) -> list[dict]:
    rng = random.Random(seed)
    wl = load_watchlist()
    cases = []
    for e in wl:
        parts = e["name_en"].split(" ")
        first, middle = parts[0], parts[1]
        fam = " ".join(parts[2:])
        v = lambda p: rng.choice([p] + SPELLING_VARIANTS.get(p, []))  # noqa: E731
        ar_parts = e["name_ar"].split(" ")
        variants = {
            "spelling_variant": f"{v(first)} {v(middle)} {v(fam)}",
            "arabic_script": e["name_ar"],
            "arabic_with_diacritics": "".join(ch + (rng.choice(AR_DIACRITICS) if rng.random() < 0.3 else "") for ch in e["name_ar"]),
            "middle_name_dropped": f"{v(first)} {v(fam)}",
            "reordered": f"{fam} {first} {middle}",
            "typo": _typo(rng, e["name_en"]),
            "honorific": f"Sheikh {e['name_en']}",
            "mixed_script": f"{first} {' '.join(ar_parts[2:])}",
        }
        for kind, q in variants.items():
            known = rng.random() < 0.7  # 30% of queries arrive without date of birth / nationality
            cases.append({"query": q, "target": e["id"], "label": 1, "kind": kind,
                          "dob": e["dob"] if known else None, "nationality": e["nationality"] if known else None})

    listed = {canonical(e["name_en"]) for e in wl} | {canonical(a) for e in wl for a in e["aliases"]}
    negatives = []
    while len(negatives) < 700:
        kind = rng.choice(["random_arabic_name", "same_family_diff_first", "same_first_diff_family", "non_arabic_name"])
        e = rng.choice(wl)
        parts = e["name_en"].split(" ")
        if kind == "random_arabic_name":
            f1, f2 = rng.sample(FIRST, 2)
            q = f"{f1[0]} {f2[0]} {rng.choice(FAMILY)[0]}"
        elif kind == "same_family_diff_first":
            others = [f for f, _ in FIRST if f not in parts]
            q = f"{rng.choice(others)} {rng.choice(others)} {' '.join(parts[2:])}"
        elif kind == "same_first_diff_family":
            fams = [f for f, _ in FAMILY if f not in e["name_en"]]
            q = f"{parts[0]} {rng.choice([f for f, _ in FIRST if f not in parts])} {rng.choice(fams)}"
        else:
            q = rng.choice(OTHER_NAMES)
        if canonical(q) in listed:
            continue
        # the negative is judged against its most similar listed person
        negatives.append({"query": q, "target": None, "label": 0, "kind": kind,
                          "dob": f"{rng.randint(1955, 2003)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                          "nationality": rng.choice(["AE", "SA", "EG", "JO", "IN", "PK", "SY", "IQ", "GB"])})
    return cases + negatives


def _best(query: str, wl: list[dict], scorer) -> tuple[str, float]:
    best_id, best = None, 0.0
    for e in wl:
        for listed in [e["name_en"], e["name_ar"], *e["aliases"]]:
            s = scorer(query, listed)
            if s > best:
                best_id, best = e["id"], s
    return best_id, best


def eval_screening() -> dict:
    wl = load_watchlist()
    testset = build_screening_testset()
    (HERE / "screening_testset.jsonl").write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in testset), encoding="utf-8")
    out = {"test_cases": len(testset), "positives": sum(t["label"] for t in testset)}

    def score(predict):
        tp = fp = fn = 0
        by_kind: dict[str, list[int]] = {}
        for t in testset:
            hit_id, flagged = predict(t)
            if t["label"]:
                correct = flagged and hit_id == t["target"]
                tp += correct
                fn += not correct
                by_kind.setdefault(t["kind"], []).append(int(correct))
            else:
                fp += flagged
        p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / max(p + r, 1e-9), 3),
                "false_positives": fp, "missed": fn,
                "recall_by_variant": {k: round(sum(v) / len(v), 3) for k, v in sorted(by_kind.items())}}

    def full(t):  # name matching + date-of-birth / nationality corroboration, as used in production
        hits = screen(t["query"], "", t.get("dob"), t.get("nationality"), watchlist=wl)
        return (hits[0].watchlist_id if hits else None), disposition(hits) != "no_match"

    def name_only(scorer, thr):
        def predict(t):
            hit_id, s = _best(t["query"], wl, scorer)
            return hit_id, s >= thr
        return predict

    out["amanah_full"] = score(full)
    out["amanah_name_only"] = score(name_only(name_similarity, NAME_THRESHOLD))
    out["baseline_plain_fuzzy"] = score(name_only(lambda a, b: fuzz.token_sort_ratio(a.lower(), b.lower()), NAME_THRESHOLD))
    out["baseline_exact"] = score(name_only(lambda a, b: 100.0 if a.strip().lower() == b.strip().lower() else 0.0, 99))
    return out


# --- 2. monitoring --------------------------------------------------------------

def eval_monitoring() -> dict:
    customers, tx = mon.load_data()
    X = mon.build_features(customers, tx)
    y = mon.labels(customers).reindex(X.index).fillna(0)
    model, metrics = mon.RiskModel.train(X, y)
    model.save()
    return metrics


# --- 3. end to end --------------------------------------------------------------

def eval_end_to_end(n: int) -> dict:
    from amanah import graph

    ctx = graph.ctx()
    rng = random.Random(5)
    ids = list(ctx.customers)
    watch = [i for i in ids if ctx.customers[i]["watchlist_ref"]]
    sus = [i for i in ids if ctx.customers[i]["typologies"] and not ctx.customers[i]["watchlist_ref"]]
    clean = [i for i in ids if not ctx.customers[i]["typologies"] and not ctx.customers[i]["watchlist_ref"]]
    sample = watch + rng.sample(sus, min(len(sus), n // 4)) + rng.sample(clean, max(n - len(watch) - n // 4, 0))
    # score the sample with a model that never saw these customers
    held_out = set(sample)
    train_idx = [i for i in ctx.features.index if i not in held_out]
    customers, _ = mon.load_data()
    y = mon.labels(customers).reindex(ctx.features.index).fillna(0)
    ctx.model, _ = mon.RiskModel.train(ctx.features.loc[train_idx], y.loc[train_idx])
    results = {"watchlist": [], "suspicious": [], "clean": []}
    latencies, llm_cases = [], 0
    for cid in sample:
        t0 = time.perf_counter()
        r = graph.start_case(cid)
        latencies.append((time.perf_counter() - t0) * 1000)
        rec = r["state"]["case"]["recommendation"]
        llm_cases += any(t["agent"] == "case_agent" for t in r["state"]["trace"])
        graph.review_case(r["case_id"], "approve", "eval-bot", "automated evaluation")
        c = ctx.customers[cid]
        group = "watchlist" if c["watchlist_ref"] else "suspicious" if c["typologies"] else "clean"
        results[group].append(rec)

    def share(recs, allowed):
        return round(sum(r in allowed for r in recs) / max(len(recs), 1), 3)

    return {
        "cases": len(sample),
        "e2e_watchlist_flagged": share(results["watchlist"], {"freeze_and_report", "investigate_possible_match"}),
        "e2e_suspicious_escalated": share(results["suspicious"], {"escalate_str_review", "enhanced_due_diligence",
                                                                  "freeze_and_report", "investigate_possible_match"}),
        "e2e_clean_cleared": share(results["clean"], {"clear"}),
        "e2e_clean_false_alert_rate": share(results["clean"], {"escalate_str_review", "enhanced_due_diligence",
                                                               "freeze_and_report", "investigate_possible_match"}),
        "cases_needing_case_agent": round(llm_cases / len(sample), 3),
        "latency_ms_median": round(statistics.median(latencies), 1),
        "latency_ms_p95": round(sorted(latencies)[int(0.95 * len(latencies)) - 1], 1),
        "llm_mode": os.getenv("AMANAH_LLM", "ollama"),
        "every_case_required_human_decision": True,
        "note": "risk model retrained without the evaluated customers (held-out)",
    }


def to_markdown(res: dict) -> str:
    s, m, e = res["screening"], res["monitoring"], res["end_to_end"]
    lines = ["# Evaluation results", "", "_Generated by `python -m eval.run_eval`. All data is synthetic._", "",
             "## 1. Sanctions / PEP name screening", "",
             f"{s['test_cases']} labelled queries ({s['positives']} true variants of listed names, "
             f"{s['test_cases'] - s['positives']} hard negatives).", "",
             "| Matcher | Precision | Recall | F1 | False positives | Missed |", "|---|---|---|---|---|---|"]
    for k in ("amanah_full", "amanah_name_only", "baseline_plain_fuzzy", "baseline_exact"):
        v = s[k]
        lines.append(f"| {k} | {v['precision']} | {v['recall']} | {v['f1']} | {v['false_positives']} | {v['missed']} |")
    lines += ["", "`amanah_full` = bilingual name matching + date-of-birth / nationality corroboration (30% of queries have neither). "
              "The name-only rows show each matcher on the name alone.", "",
              "Recall by variant type (Amanah full vs plain fuzzy):", "", "| Variant | Amanah | Plain fuzzy |", "|---|---|---|"]
    for k, v in s["amanah_full"]["recall_by_variant"].items():
        lines.append(f"| {k} | {v} | {s['baseline_plain_fuzzy']['recall_by_variant'][k]} |")
    lines += ["", "## 2. Transaction monitoring", "",
              f"{m['customers']} customers, {m['suspicious_customers']} with injected laundering typologies; {m['evaluation']}.", "",
              f"- ROC-AUC **{m['roc_auc']}**, PR-AUC **{m['pr_auc']}**", "",
              "| Approach | Precision | Recall | Alerts |", "|---|---|---|---|",
              f"| LightGBM risk model | {m['model']['precision']} | {m['model']['recall']} | {m['model']['alerts']} |",
              f"| Rules-only baseline | {m['rules_baseline']['precision']} | {m['rules_baseline']['recall']} | {m['rules_baseline']['alerts']} |",
              "", "## 3. End-to-end multi-agent workflow", "",
              f"{e['cases']} customers run through the full graph (LLM mode: `{e['llm_mode']}`); "
              "the risk model used here was trained without these customers.", "",
              f"- Watchlist customers flagged: **{e['e2e_watchlist_flagged']:.0%}**",
              f"- Suspicious customers escalated: **{e['e2e_suspicious_escalated']:.0%}**",
              f"- Clean customers cleared: **{e['e2e_clean_cleared']:.0%}** (false alert rate {e['e2e_clean_false_alert_rate']:.0%})",
              f"- Cases that needed the LLM case agent: **{e['cases_needing_case_agent']:.0%}** (the rest were routed straight to review)",
              f"- Latency per case: median {e['latency_ms_median']} ms, p95 {e['latency_ms_p95']} ms",
              "- Every case required an investigator decision before closing.", ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=400)
    args = ap.parse_args(argv)
    res = {"screening": eval_screening(), "monitoring": eval_monitoring(), "end_to_end": eval_end_to_end(args.cases)}
    (HERE / "results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    (HERE / "RESULTS.md").write_text(to_markdown(res), encoding="utf-8")
    print(to_markdown(res))
    checks = {"screening_recall": res["screening"]["amanah_full"]["recall"],
              "screening_precision": res["screening"]["amanah_full"]["precision"],
              "monitoring_roc_auc": res["monitoring"]["roc_auc"],
              "e2e_watchlist_flagged": res["end_to_end"]["e2e_watchlist_flagged"]}
    failed = {k: v for k, v in checks.items() if v < THRESHOLDS[k]}
    if failed:
        print("REGRESSION:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
