"""Deterministic synthetic data: watchlist, customers, transactions.

Everything here is fictional. No real sanctions data, customers or
transactions are shipped with the repo. `scripts/load_un_list.py` shows how
to swap in the public UN Security Council consolidated list.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

# (english, arabic) pairs so each synthetic person has both scripts
FIRST = [
    ("Muhammad", "محمد"), ("Ahmad", "أحمد"), ("Ali", "علي"), ("Umar", "عمر"),
    ("Khalid", "خالد"), ("Yusuf", "يوسف"), ("Hasan", "حسن"), ("Ibrahim", "إبراهيم"),
    ("Saeed", "سعيد"), ("Rashid", "راشد"), ("Hamad", "حمد"), ("Sultan", "سلطان"),
    ("Majid", "ماجد"), ("Tariq", "طارق"), ("Nasser", "ناصر"), ("Faisal", "فيصل"),
    ("Fatima", "فاطمة"), ("Aisha", "عائشة"), ("Maryam", "مريم"), ("Noura", "نورة"),
    ("Layla", "ليلى"), ("Huda", "هدى"), ("Salma", "سلمى"), ("Reem", "ريم"),
]
FAMILY = [
    ("Al Hashimi", "الهاشمي"), ("Al Mansouri", "المنصوري"), ("Al Shamsi", "الشامسي"),
    ("Al Nuaimi", "النعيمي"), ("Al Qasimi", "القاسمي"), ("Al Marri", "المري"),
    ("Haddad", "حداد"), ("Khoury", "خوري"), ("Nasr", "نصر"), ("Saleh", "صالح"),
    ("Darwish", "درويش"), ("Qureshi", "قريشي"), ("Farouk", "فاروق"), ("Zayani", "الزياني"),
    ("Barakat", "بركات"), ("Othman", "عثمان"), ("Rahman", "الرحمن"), ("Jaber", "جابر"),
]
OTHER_NAMES = [
    "Priya Sharma", "Rahul Menon", "John Carter", "Elena Petrova", "Wei Zhang",
    "Maria Santos", "Arjun Nair", "Sofia Rossi", "Daniel Okafor", "Anna Kowalski",
    "Ravi Kumar", "Chen Li", "Olga Ivanova", "Kevin OBrien", "Grace Mensah",
]
NATIONALITIES = ["AE", "SA", "EG", "JO", "LB", "PK", "IN", "SY", "IQ", "YE", "GB", "RU", "PH"]
HIGH_RISK_COUNTRIES = ["IR", "KP", "MM", "SY", "YE", "AF"]  # illustrative, not an official list

SPELLING_VARIANTS = {
    "Muhammad": ["Mohammed", "Mohamed", "Mohammad", "Muhammed", "Mohd"],
    "Ahmad": ["Ahmed"], "Umar": ["Omar"], "Yusuf": ["Yousef", "Youssef", "Yousuf"],
    "Hasan": ["Hassan"], "Khalid": ["Khaled"], "Ibrahim": ["Ebrahim"],
    "Saeed": ["Said", "Saied"], "Nasser": ["Nasir", "Naser"], "Faisal": ["Faysal"],
    "Fatima": ["Fatma", "Fatimah"], "Aisha": ["Ayesha", "Aysha"], "Noura": ["Nora", "Nourah"],
    "Al Hashimi": ["Al-Hashemi", "Alhashimi", "El Hashimi"], "Al Mansouri": ["Al-Mansoori", "Almansouri"],
    "Al Shamsi": ["Al-Shamsy", "Alshamsi"], "Al Nuaimi": ["Al-Nuaimy", "Al Naimi"],
    "Al Qasimi": ["Al-Qassimi", "Al Kasimi"], "Othman": ["Osman", "Uthman"],
    "Haddad": ["Hadad"], "Khoury": ["Khouri", "Khuri"], "Darwish": ["Darweesh"],
}


@dataclass
class WatchlistEntry:
    id: str
    name_en: str
    name_ar: str
    aliases: list[str]
    dob: str
    nationality: str
    list_name: str
    reason: str


@dataclass
class Customer:
    id: str
    name_en: str
    name_ar: str
    dob: str
    nationality: str
    segment: str  # retail | sme
    occupation: str
    declared_monthly_income: int
    emirates_id: str
    id_expiry: str
    watchlist_ref: str | None = None
    typologies: list[str] = field(default_factory=list)


def luhn_check_digit(number: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def make_emirates_id(rng: random.Random, birth_year: int) -> str:
    body = f"784{birth_year}{rng.randint(0, 9_999_999):07d}"
    return f"784-{birth_year}-{body[7:]}-{luhn_check_digit(body)}"


def _variant(rng: random.Random, part: str) -> str:
    return rng.choice([part] + SPELLING_VARIANTS.get(part, []))


def _person(rng: random.Random) -> tuple[str, str, str, str]:
    f1, f2 = rng.sample(FIRST, 2)
    fam = rng.choice(FAMILY)
    en = f"{f1[0]} {f2[0]} {fam[0]}"
    ar = f"{f1[1]} {f2[1]} {fam[1]}"
    return en, ar, f1[0], fam[0]


def build_watchlist(rng: random.Random, n: int = 60) -> list[WatchlistEntry]:
    entries = []
    reasons = ["Terrorist financing (fictional)", "Proliferation financing (fictional)",
               "Sanctions evasion (fictional)", "Politically exposed person (fictional)"]
    for i in range(n):
        en, ar, first, fam = _person(rng)
        aliases = list({f"{_variant(rng, first)} {_variant(rng, fam)}" for _ in range(3)})
        year = rng.randint(1955, 1995)
        entries.append(WatchlistEntry(
            id=f"WL-{i + 1:04d}", name_en=en, name_ar=ar, aliases=aliases,
            dob=f"{year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            nationality=rng.choice(NATIONALITIES + HIGH_RISK_COUNTRIES),
            list_name=rng.choice(["SAMPLE-UNSC", "SAMPLE-LOCAL-TERRORIST-LIST", "SAMPLE-PEP"]),
            reason=rng.choice(reasons),
        ))
    return entries


def build_customers(rng: random.Random, watchlist: list[WatchlistEntry], n: int = 3000) -> list[Customer]:
    customers = []
    occupations = ["Engineer", "Teacher", "Trader", "Consultant", "Driver", "Accountant",
                   "Business owner", "Nurse", "Sales manager", "Student", "Real estate broker"]
    for i in range(n):
        watch = None
        if rng.random() < 0.02:  # a few true matches, spelled differently
            watch = rng.choice(watchlist)
            first, *rest = watch.name_en.split(" ")
            en = " ".join(_variant(rng, p) for p in [first, " ".join(rest[-2:]) if rest[-2] == "Al" else rest[-1]])
            ar, dob, nat = watch.name_ar, watch.dob, watch.nationality
        elif rng.random() < 0.25:
            en, ar = rng.choice(OTHER_NAMES), ""
            dob = f"{rng.randint(1960, 2003)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
            nat = rng.choice(["IN", "PH", "GB", "RU", "CN", "PK"])
        else:
            en, ar, _, _ = _person(rng)
            dob = f"{rng.randint(1960, 2003)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
            nat = rng.choice(NATIONALITIES)
        segment = "sme" if rng.random() < 0.3 else "retail"
        income = int(rng.lognormvariate(9.8 if segment == "retail" else 11.2, 0.5))
        expiry = date(2026, 10, 1) + timedelta(days=rng.randint(-60, 1400))
        customers.append(Customer(
            id=f"C{i + 1:05d}", name_en=en, name_ar=ar, dob=dob, nationality=nat,
            segment=segment, occupation=rng.choice(occupations),
            declared_monthly_income=income, emirates_id=make_emirates_id(rng, int(dob[:4])),
            id_expiry=expiry.isoformat(), watchlist_ref=watch.id if watch else None,
        ))
    return customers


# --- transactions -----------------------------------------------------------

TYPOLOGIES = ["structuring", "rapid_movement", "high_risk_corridor", "income_mismatch", "dormant_spike"]


def build_transactions(rng: random.Random, customers: list[Customer], days: int = 90) -> pd.DataFrame:
    """Normal behaviour for everyone; ~8% of customers get an injected typology."""
    np_rng = np.random.default_rng(rng.randint(0, 2**31))
    start = datetime(2026, 5, 1)
    rows = []
    for c in customers:
        base = c.declared_monthly_income
        n_tx = np_rng.poisson(28 if c.segment == "retail" else 70)
        for _ in range(n_tx):
            kind = np_rng.choice(["card", "transfer_in", "transfer_out", "cash_in", "cash_out"],
                                 p=[0.45, 0.2, 0.2, 0.08, 0.07])
            amount = float(np_rng.lognormal(np.log(max(base, 1000) / 12), 0.9))
            country = "AE" if np_rng.random() < 0.9 else np_rng.choice(["IN", "GB", "SA", "EG", "PK", "PH"])
            rows.append((c.id, start + timedelta(minutes=int(np_rng.integers(0, days * 1440))),
                         kind, round(amount, 2), country))

        # benign events that look suspicious on the surface (keeps the model honest)
        if np_rng.random() < 0.25:
            t0 = start + timedelta(days=int(np_rng.integers(5, days - 5)))
            event = np_rng.choice(["property_sale", "bonus", "supplier_run", "family_remittance", "car_purchase", "cash_business", "own_account_sweep"])
            if event == "property_sale":
                rows.append((c.id, t0, "transfer_in", float(np_rng.choice([750_000, 1_200_000, 2_000_000])), "AE"))
            elif event == "bonus":
                rows.append((c.id, t0, "transfer_in", round(base * float(np_rng.uniform(3, 8)), 2), "AE"))
            elif event == "supplier_run":
                for _ in range(int(np_rng.integers(3, 8))):
                    rows.append((c.id, t0 + timedelta(hours=int(np_rng.integers(0, 72))), "transfer_out",
                                 float(np_rng.choice([20_000, 50_000, 100_000])), str(np_rng.choice(["AE", "CN", "IN", "TR"]))))
            elif event == "family_remittance":
                for _ in range(int(np_rng.integers(2, 5))):
                    rows.append((c.id, t0 + timedelta(days=int(np_rng.integers(0, 30))), "transfer_out",
                                 round(float(np_rng.uniform(5_000, 30_000)), 2), str(np_rng.choice(["IN", "PK", "PH", "EG", "YE", "SY"]))))
            elif event == "cash_business":  # shops and restaurants legitimately bank cash takings
                for _ in range(int(np_rng.integers(2, 7))):
                    rows.append((c.id, t0 + timedelta(days=int(np_rng.integers(0, 40))), "cash_in",
                                 round(float(np_rng.uniform(15_000, 54_000)), 2), "AE"))
            elif event == "own_account_sweep":  # salary in, moved to own savings abroad
                for _ in range(int(np_rng.integers(1, 4))):
                    amt = round(float(np_rng.uniform(20_000, 90_000)), 2)
                    t = t0 + timedelta(days=int(np_rng.integers(0, 30)))
                    rows.append((c.id, t, "transfer_in", amt, "AE"))
                    rows.append((c.id, t + timedelta(hours=int(np_rng.integers(2, 30))), "transfer_out", round(amt * 0.95, 2), "GB"))
            else:
                rows.append((c.id, t0, "cash_out", float(np_rng.choice([45_000, 60_000, 90_000])), "AE"))

        if np_rng.random() < 0.08:
            typ = str(np_rng.choice(TYPOLOGIES))
            c.typologies.append(typ)
            t0 = start + timedelta(days=int(np_rng.integers(20, days - 10)))
            if typ == "structuring":  # many cash deposits just under a reporting threshold
                for _ in range(int(np_rng.integers(2, 8))):
                    rows.append((c.id, t0 + timedelta(hours=int(np_rng.integers(0, 480))), "cash_in",
                                 round(float(np_rng.uniform(30_000, 54_900)), 2), "AE"))
            elif typ == "rapid_movement":  # money in, straight back out
                for _ in range(int(np_rng.integers(1, 5))):
                    amt = round(float(np_rng.uniform(15_000, 200_000)), 2)
                    t = t0 + timedelta(hours=int(np_rng.integers(0, 200)))
                    rows.append((c.id, t, "transfer_in", amt, "AE"))
                    rows.append((c.id, t + timedelta(hours=int(np_rng.integers(1, 60))), "transfer_out",
                                 round(amt * np_rng.uniform(0.9, 0.99), 2), str(np_rng.choice(["GB", "HK", "TR", "CY"]))))
            elif typ == "high_risk_corridor":
                for _ in range(int(np_rng.integers(1, 5))):
                    rows.append((c.id, t0 + timedelta(days=int(np_rng.integers(0, 20))), "transfer_out",
                                 round(float(np_rng.uniform(5_000, 80_000)), 2), str(np_rng.choice(HIGH_RISK_COUNTRIES))))
            elif typ == "income_mismatch":  # inflows far above declared income
                for _ in range(int(np_rng.integers(1, 4))):
                    rows.append((c.id, t0 + timedelta(days=int(np_rng.integers(0, 25))), "transfer_in",
                                 round(base * float(np_rng.uniform(2, 9)), 2), "AE"))
            elif typ == "dormant_spike":  # quiet account suddenly moves round amounts
                rows = [r for r in rows if not (r[0] == c.id and r[1] > t0 - timedelta(days=45) and r[1] < t0)]
                for _ in range(int(np_rng.integers(1, 4))):
                    rows.append((c.id, t0 + timedelta(days=int(np_rng.integers(0, 5))),
                                 str(np_rng.choice(["transfer_in", "cash_in"])),
                                 float(np_rng.choice([50_000, 100_000, 150_000])), "AE"))

    tx = pd.DataFrame(rows, columns=["customer_id", "timestamp", "type", "amount_aed", "counterparty_country"])
    tx = tx.sort_values(["customer_id", "timestamp"]).reset_index(drop=True)
    tx.insert(0, "tx_id", [f"T{i + 1:07d}" for i in range(len(tx))])
    return tx


def generate(seed: int = 7, out_dir: Path = DATA_DIR) -> dict:
    rng = random.Random(seed)
    watchlist = build_watchlist(rng)
    customers = build_customers(rng, watchlist)
    tx = build_transactions(rng, customers)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "watchlist.json").write_text(json.dumps([asdict(w) for w in watchlist], ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "customers.json").write_text(json.dumps([asdict(c) for c in customers], ensure_ascii=False, indent=1), encoding="utf-8")
    tx.to_csv(out_dir / "transactions.csv", index=False)
    return {"watchlist": len(watchlist), "customers": len(customers), "transactions": len(tx),
            "customers_with_typology": sum(1 for c in customers if c.typologies),
            "true_watchlist_matches": sum(1 for c in customers if c.watchlist_ref)}


def ensure_data() -> None:
    """Generate the synthetic dataset on first use (it is not committed to git)."""
    if not all((DATA_DIR / f).exists() for f in ("watchlist.json", "customers.json", "transactions.csv")):
        generate()


if __name__ == "__main__":
    print(generate())
