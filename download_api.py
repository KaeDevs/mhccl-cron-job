#!/usr/bin/env python3
"""
download_api.py

Downloads the Madras High Court cause-list API JSON (Madurai + Madras),
transforms it directly into the exact JSON structure previously produced
by MainScript.py (which parsed Selenium-rendered HTML with BeautifulSoup),
and writes the result to jsons/mduDD-MM-YYYY.json and jsons/madrDD-MM-YYYY.json.

MainScript.py, Selenium, Chrome, and BeautifulSoup are no longer required.
"""

import json
import os
import re
import sys
from datetime import datetime

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Set to True to additionally dump the raw API response to downloaded_api/
# for debugging. Not needed for normal operation.
SAVE_RAW_API_RESPONSE = False


# ============================================================
# Court sort key (reused verbatim from MainScript.py)
# ============================================================
def court_sort_key_from_case(case):
    court_no = case.get("COURT NO.", "").strip()

    # 1️⃣ COURT NO. (Judge Name)
    if court_no.startswith("COURT NO. (") and court_no.endswith(")"):
        judge = court_no[len("COURT NO. ("):-1].strip().lower()
        return (0, 0, judge)

    # 2️⃣ COURT NO. 0 (administrative / registrar courts)
    if court_no == "COURT NO. 0":
        return (1, 0, "")

    # 3️⃣ COURT NO. <number> <optional suffix>
    m = re.match(r"COURT NO\.\s*(\d+)\s*([a-zA-Z]?)", court_no)
    if m:
        number = int(m.group(1))
        suffix = m.group(2).lower()
        suffix_rank = ord(suffix) - 96 if suffix else 0
        return (2, number, suffix_rank)

    # 4️⃣ Everything else (chambers, VC, etc.)
    return (3, 0, court_no.lower())


# ============================================================
# Small normalization helpers (the API is inconsistent about
# whether a field is a plain string, an empty list, or a list
# containing a single blank string)
# ============================================================
def normalize_field(value):
    if value is None:
        return ""

    if isinstance(value, list):
        return ",".join(
            str(v).strip()
            for v in value
            if str(v).strip()
        ) + ("," if value else "")

    return str(value).strip()


def build_case_number(case_type, case_no, case_yr):
    case_type = normalize_field(case_type)
    case_no = normalize_field(case_no)
    case_yr = normalize_field(case_yr)
    if not case_type and not case_no and not case_yr:
        return ""
    return f"{case_type} {case_no}/{case_yr}".strip()


def build_parties(pname, rname):
    pname = normalize_field(pname)
    rname = normalize_field(rname)
    return f"{pname} VS {rname}".strip()


def build_justice_list(record):
    """Construct the Justice list from judge1..judge5, exactly like MainScript."""
    justices = []
    for key in ("judge1", "judge2", "judge3", "judge4", "judge5"):
        val = normalize_field(record.get(key))
        if val:
            justices.append(val)
    return justices


def build_court_key(courtno, justices):
    """
    Replicates MainScript's court-naming logic:
    - "COURT NO." (blank number) -> "COURT NO. (Judge Name)" using the first judge
    - Anything else (e.g. "COURT NO. 14A", "SKRJ CHAMBERS") is kept as-is
    """
    raw_court = normalize_field(courtno)

    if raw_court == "COURT NO." or not raw_court:
        if justices:
            judge = justices[0].replace("The Honourable ", "").strip()
            return f"COURT NO. ({judge})"
        return "COURT NO. (UNKNOWN)"

    return raw_court


def normalize_extra(extra):
    """
    The API represents "extra" cases inconsistently:
      - {}                       -> no extra cases
      - { "excaseno": [], ... }  -> no extra cases (all fields blank)
      - { "excaseno": "123", ... } -> a single extra case (bare dict)
      - [ {...}, {...} ]          -> multiple extra cases

    Always returns a list of extra-case dicts (possibly empty).
    """
    if isinstance(extra, list):
        return [e for e in extra if isinstance(e, dict)]

    if isinstance(extra, dict):
        if not extra:
            return []
        if all(v in ([], "", None) for v in extra.values()):
            return []
        return [extra]

    return []


def build_case_dict(serial_number, case_number, parties, petitioner_advocates,
                     respondent_advocates, category, court_key, justices):
    return {
        "serial_number": serial_number,
        "case_number": case_number,
        "parties": parties,
        "petitioner_advocates": petitioner_advocates,
        "respondent_advocates": respondent_advocates,
        "category": category,
        "COURT NO.": court_key,
        "Justice": justices,
    }


# ============================================================
# Core transform: API records -> MainScript-compatible JSON
# ============================================================
def transform_records(records):
    data = []
    courts = {}
    court_numbers = []

    category_counts = {}      # court_key -> category -> count (main cases only)
    category_case_list = {}   # court_key -> category -> [case_dict, ...]

    last_block_signature = None  # tracks (court_key, justices, timing) to avoid
                                  # re-adding duplicate "courts" entries for every
                                  # case row belonging to the same bench block

    for record in records:
        justices = build_justice_list(record)
        court_key = build_court_key(record.get("courtno", ""), justices)
        timing = normalize_field(record.get("courtremarks", ""))

        category_counts.setdefault(court_key, {})
        category_case_list.setdefault(court_key, {})

        if court_key not in courts:
            courts[court_key] = []
            court_numbers.append(court_key)

        signature = (court_key, tuple(justices), timing)
        if signature != last_block_signature:
            courts[court_key].append({
                "court_number": court_key,
                "justices": justices,
                "timing": timing,
            })
            last_block_signature = signature

        category = normalize_field(record.get("stagename", ""))
        if not category:
            category = "Uncategorized"

        category_counts[court_key].setdefault(category, 0)
        category_case_list[court_key].setdefault(category, [])

        serial_number = normalize_field(record.get("serial_no", ""))
        case_number = build_case_number(
            record.get("mcasetype"), record.get("mcaseno"), record.get("mcaseyr")
        )
        parties = build_parties(record.get("pname"), record.get("rname"))
        petitioner_advocates = normalize_field(record.get("mpadv"))
        respondent_advocates = normalize_field(record.get("mradv"))

        if serial_number:
            category_counts[court_key][category] += 1

        case_data = build_case_dict(
            serial_number, case_number, parties,
            petitioner_advocates, respondent_advocates,
            category, court_key, justices
        )
        category_case_list[court_key][category].append(case_data)

        # -------------------- extra cases --------------------
        for extra_case in normalize_extra(record.get("extra")):
            ex_case_number = build_case_number(
                extra_case.get("excasetype"),
                extra_case.get("excaseno"),
                extra_case.get("excaseyr"),
            )
            ex_parties = build_parties(
                extra_case.get("expname"), extra_case.get("exrname")
            )
            ex_petitioner_advocates = normalize_field(extra_case.get("expadv"))
            ex_respondent_advocates = normalize_field(extra_case.get("exradv"))

            ex_case_data = build_case_dict(
                "",  # extra cases always have a blank serial number
                ex_case_number, ex_parties,
                ex_petitioner_advocates, ex_respondent_advocates,
                category, court_key, justices
            )
            category_case_list[court_key][category].append(ex_case_data)

    # -------------------- finalize category labels --------------------
    for court_key, categories in category_case_list.items():
        for category, cases in categories.items():
            count = category_counts[court_key].get(category, 0)
            label = f"{category} ({count})"
            for c in cases:
                c["category"] = label
            data.extend(cases)

    return {
        "cases": sorted(data, key=court_sort_key_from_case),
        "courts": courts,
        "court_numbers": court_numbers,
    }


# ============================================================
# Download
# ============================================================
def generate_xml_name(specified_date=None):
    if specified_date:
        current_date = datetime.strptime(specified_date, "%Y-%m-%d")
    else:
        current_date = datetime.now()
    return f"cause_{current_date.strftime('%d%m%Y')}.xml"


def download_api(xml_name, madurai):
    if madurai:
        url = (
            "https://mhc.tn.gov.in/judis/clists/clists-madurai/"
            f"api/result.php?file={xml_name}"
        )
        prefix = "mdu"
    else:
        url = (
            "https://mhc.tn.gov.in/judis/clists/clists-madras/"
            f"api/result.php?file={xml_name}"
        )
        prefix = "madr"

    print(url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        ),
        "Referer": "https://mhc.tn.gov.in/judis/clists/",
    }

    r = requests.get(url, headers=headers, timeout=60, verify=False)
    r.raise_for_status()

    return prefix, r.json()


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = datetime.now().strftime("%d-%m-%Y")

    dt = datetime.strptime(date_str, "%d-%m-%Y")
    xml_name = generate_xml_name(dt.strftime("%Y-%m-%d"))

    jsons_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jsons")
    os.makedirs(jsons_dir, exist_ok=True)

    if SAVE_RAW_API_RESPONSE:
        os.makedirs("downloaded_api", exist_ok=True)

    for madurai in (True, False):
        prefix, raw_data = download_api(xml_name, madurai)

        if SAVE_RAW_API_RESPONSE:
            raw_outfile = f"downloaded_api/{prefix}{date_str}.json"
            with open(raw_outfile, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, ensure_ascii=False, indent=2)
            print("Saved raw ->", raw_outfile)

        final_json = transform_records(raw_data)

        json_file_path = os.path.join(jsons_dir, f"{prefix}{date_str}.json")
        with open(json_file_path, "w", encoding="utf-8") as f:
            json.dump(final_json, f, indent=4)

        print(f"JSON saved to: {json_file_path}")