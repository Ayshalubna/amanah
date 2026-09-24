"""Transaction monitoring: customer-level features, LightGBM risk model, SHAP reasons.

Rules alone either miss new patterns or drown investigators in alerts; a
model alone is a black box a regulator will not accept. Here the model ranks
customers by risk and every score ships with its top SHAP drivers plus the
named typology indicators an investigator recognises.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .synth import HIGH_RISK_COUNTRIES

DATA_DIR = Path(__file__).parent / "data"
ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"

FEATURES = [
    "n_tx", "total_in", "total_out", "in_out_ratio", "cash_in_count", "near_threshold_cash",
    "max_amount_to_income", "inflow_to_income", "high_risk_tx", "high_risk_amount",
    "foreign_share", "pass_through", "round_large", "max_gap_days", "is_sme",
]

FEATURE_LABELS = {
    "n_tx": "number of transactions",
    "total_in": "total inflows",
    "total_out": "total outflows",
    "in_out_ratio": "outflow-to-inflow ratio",
    "cash_in_count": "cash deposits",
    "near_threshold_cash": "cash deposits just under AED 55,000",
    "max_amount_to_income": "largest transaction vs declared income",
    "inflow_to_income": "inflows vs declared income",
    "high_risk_tx": "transfers to high-risk jurisdictions",
    "high_risk_amount": "value sent to high-risk jurisdictions",
    "foreign_share": "share of cross-border activity",
    "pass_through": "funds passed through within 72h",
    "round_large": "large round-amount transactions",
    "max_gap_days": "longest dormant period",
    "is_sme": "SME customer",
}


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    from .synth import ensure_data

    ensure_data()
    customers = pd.DataFrame(json.loads((DATA_DIR / "customers.json").read_text(encoding="utf-8")))
    tx = pd.read_csv(DATA_DIR / "transactions.csv", parse_dates=["timestamp"])
    return customers, tx


def _pass_through(g: pd.DataFrame) -> int:
    ins = g[g.type == "transfer_in"][["timestamp", "amount_aed"]].to_numpy()
    outs = g[g.type == "transfer_out"][["timestamp", "amount_aed"]].to_numpy()
    if len(ins) == 0 or len(outs) == 0:
        return 0
    count = 0
    for t_in, a_in in ins:
        if a_in < 20_000:
            continue
        window = (outs[:, 0] > t_in) & (outs[:, 0] <= t_in + pd.Timedelta(hours=72))
        if np.any(outs[window, 1] >= 0.85 * a_in):
            count += 1
    return count


def build_features(customers: pd.DataFrame, tx: pd.DataFrame) -> pd.DataFrame:
    income = customers.set_index("id")["declared_monthly_income"]
    rows = []
    for cid, g in tx.groupby("customer_id", sort=False):
        inflow = g[g.type.isin(["transfer_in", "cash_in"])].amount_aed
        outflow = g[g.type.isin(["transfer_out", "cash_out", "card"])].amount_aed
        cash_in = g[g.type == "cash_in"].amount_aed
        hr = g[g.counterparty_country.isin(HIGH_RISK_COUNTRIES)]
        inc = max(float(income.get(cid, 1)), 1.0)
        gaps = g.timestamp.sort_values().diff().dt.total_seconds().div(86400)
        rows.append({
            "customer_id": cid,
            "n_tx": len(g),
            "total_in": inflow.sum(),
            "total_out": outflow.sum(),
            "in_out_ratio": outflow.sum() / max(inflow.sum(), 1),
            "cash_in_count": len(cash_in),
            "near_threshold_cash": int(((cash_in >= 40_000) & (cash_in < 55_000)).sum()),
            "max_amount_to_income": g.amount_aed.max() / inc,
            "inflow_to_income": inflow.sum() / (inc * 3),
            "high_risk_tx": len(hr),
            "high_risk_amount": hr.amount_aed.sum(),
            "foreign_share": float((g.counterparty_country != "AE").mean()),
            "pass_through": _pass_through(g),
            "round_large": int(((g.amount_aed % 10_000 == 0) & (g.amount_aed >= 50_000)).sum()),
            "max_gap_days": float(gaps.max() if len(gaps) > 1 else 0),
            "is_sme": int(customers.set_index("id").at[cid, "segment"] == "sme"),
        })
    return pd.DataFrame(rows).set_index("customer_id")


def labels(customers: pd.DataFrame) -> pd.Series:
    return customers.set_index("id")["typologies"].apply(lambda t: int(len(t) > 0))


def typology_indicators(f: pd.Series) -> list[str]:
    """Named red flags an investigator recognises, straight from the features."""
    flags = []
    if f.near_threshold_cash >= 3:
        flags.append(f"Possible structuring: {int(f.near_threshold_cash)} cash deposits just under AED 55,000")
    if f.pass_through >= 2:
        flags.append(f"Rapid movement of funds: {int(f.pass_through)} inflows moved out within 72h")
    if f.high_risk_tx >= 2:
        flags.append(f"{int(f.high_risk_tx)} transfers to high-risk jurisdictions (AED {f.high_risk_amount:,.0f})")
    if f.inflow_to_income >= 4:
        flags.append(f"Inflows {f.inflow_to_income:.0f}x declared income")
    if f.max_gap_days >= 30 and f.round_large >= 1:
        flags.append(f"Dormant {f.max_gap_days:.0f} days then {int(f.round_large)} large round-amount movements")
    return flags


class RiskModel:
    def __init__(self, booster=None, threshold: float = 0.5):
        self.booster = booster
        self.threshold = threshold
        self._explainer = None

    # -- training ------------------------------------------------------------
    @classmethod
    def train(cls, X: pd.DataFrame, y: pd.Series, seed: int = 7) -> tuple[RiskModel, dict]:
        """5-fold out-of-fold evaluation, then a final fit on all data.

        The alert threshold is set on out-of-fold scores to keep recall >= 90%,
        because a missed launderer costs far more than an extra review.
        """
        import lightgbm as lgb
        from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
        from sklearn.model_selection import StratifiedKFold

        X, y = X[FEATURES], y.astype(int)
        params = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_data_in_leaf=20,
                      feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=seed)
        rounds = 150
        oof = np.zeros(len(y))
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
            b = lgb.train(params, lgb.Dataset(X.iloc[tr], y.iloc[tr]), rounds)
            oof[te] = b.predict(X.iloc[te])

        prec, rec, thr = precision_recall_curve(y, oof)
        ok = np.where(rec[:-1] >= 0.9)[0]
        best = ok[np.argmax(prec[ok])] if len(ok) else 0
        threshold = float(thr[best])
        pred = oof >= threshold
        rules = X.apply(lambda r: len(typology_indicators(r)) > 0, axis=1).to_numpy()
        yv = y.to_numpy()

        def pr(alerts):
            tp = int((alerts & (yv == 1)).sum())
            return round(tp / max(int(alerts.sum()), 1), 3), round(tp / max(int(yv.sum()), 1), 3), int(alerts.sum())

        m_p, m_r, m_n = pr(pred)
        r_p, r_r, r_n = pr(rules)
        metrics = {
            "customers": int(len(y)), "suspicious_customers": int(yv.sum()),
            "evaluation": "5-fold stratified cross-validation (out-of-fold scores)",
            "roc_auc": round(float(roc_auc_score(y, oof)), 3),
            "pr_auc": round(float(average_precision_score(y, oof)), 3),
            "threshold": round(threshold, 4),
            "model": {"precision": m_p, "recall": m_r, "alerts": m_n},
            "rules_baseline": {"precision": r_p, "recall": r_r, "alerts": r_n},
        }
        booster = lgb.train(params, lgb.Dataset(X, y), rounds)
        return cls(booster, threshold), metrics

    def save(self, path: Path = ARTIFACTS) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.booster.save_model(str(path / "risk_model.txt"))
        (path / "risk_model.json").write_text(json.dumps({"threshold": self.threshold, "features": FEATURES}))

    @classmethod
    def load(cls, path: Path = ARTIFACTS) -> RiskModel:
        import lightgbm as lgb

        meta = json.loads((path / "risk_model.json").read_text())
        return cls(lgb.Booster(model_file=str(path / "risk_model.txt")), meta["threshold"])

    # -- inference -----------------------------------------------------------
    def score(self, features: pd.DataFrame) -> np.ndarray:
        return self.booster.predict(features[FEATURES])

    def explain(self, row: pd.DataFrame, top: int = 4) -> list[dict]:
        import shap

        if self._explainer is None:
            self._explainer = shap.TreeExplainer(self.booster)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            values = self._explainer.shap_values(row[FEATURES])
        values = values[1] if isinstance(values, list) else values  # older SHAP returns [neg, pos]
        contrib = sorted(zip(FEATURES, values[0], row[FEATURES].iloc[0], strict=True), key=lambda t: -abs(t[1]))[:top]
        return [{"feature": FEATURE_LABELS[f], "value": round(float(v), 2),
                 "impact": round(float(s), 3), "direction": "raises risk" if s > 0 else "lowers risk"}
                for f, s, v in contrib]


def assess(customer_id: str, features: pd.DataFrame, model: RiskModel) -> dict:
    if customer_id not in features.index:
        return {"risk_score": 0.0, "alert": False, "indicators": [], "drivers": [], "note": "no transactions"}
    row = features.loc[[customer_id]]
    score = float(model.score(row)[0])
    return {
        "risk_score": round(score, 3),
        "alert": score >= model.threshold,
        "indicators": typology_indicators(row.iloc[0]),
        "drivers": model.explain(row),
    }
