"""Convert the public UN Security Council Consolidated List into Amanah's watchlist format.

    python -m scripts.load_un_list                       # downloads the XML
    python -m scripts.load_un_list --file consolidated.xml
    set AMANAH_WATCHLIST=amanah/data/un_consolidated.json   (Windows)
    export AMANAH_WATCHLIST=amanah/data/un_consolidated.json (macOS/Linux)

Source: https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list
The list is public; check its terms before any production use.
"""
from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
OUT = Path(__file__).resolve().parent.parent / "amanah" / "data" / "un_consolidated.json"


def _text(el, tag):
    found = el.find(tag)
    return found.text.strip() if found is not None and found.text else ""


def parse(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    entries = []
    for ind in root.iter("INDIVIDUAL"):
        parts = [_text(ind, t) for t in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")]
        name = " ".join(p for p in parts if p)
        if not name:
            continue
        aliases = [a.text.strip() for a in ind.iter("ALIAS_NAME") if a.text and a.text.strip()]
        dob = ""
        for d in ind.iter("INDIVIDUAL_DATE_OF_BIRTH"):
            dob = _text(d, "DATE") or _text(d, "YEAR")
            if dob:
                break
        nationality = next((v.text.strip() for n in ind.iter("NATIONALITY") for v in n.iter("VALUE") if v.text), "")
        entries.append({
            "id": f"UN-{_text(ind, 'DATAID')}",
            "name_en": name,
            "name_ar": _text(ind, "NAME_ORIGINAL_SCRIPT"),
            "aliases": aliases[:10],
            "dob": dob[:10],
            "nationality": nationality,  # country name, not ISO code
            "list_name": f"UNSC-{_text(ind, 'UN_LIST_TYPE')}",
            "reason": _text(ind, "REFERENCE_NUMBER"),
        })
    return entries


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="local copy of consolidated.xml")
    args = ap.parse_args()
    data = Path(args.file).read_bytes() if args.file else httpx.get(URL, timeout=60, follow_redirects=True).content
    entries = parse(data)
    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(entries)} individuals to {OUT}")
