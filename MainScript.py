from datetime import datetime
import json
import os
from bs4 import BeautifulSoup
import re

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

def Generate_JSON(path, name):
    with open(path, 'r', encoding='utf-8') as file:
        content = file.read()

    soup = BeautifulSoup(content, 'html.parser')

    data = []
    courts = {}
    court_numbers = []

    # ❗ rolling state
    current_court_key = None          # <<< FIX
    current_justices_list = []        # <<< FIX
    timing = ""

    current_category = ""
    category_counts = {}
    category_case_list = {}

    rows = soup.find_all('tr')

    for row in rows:
        court_heading = row.find('span', class_='court')
        head_judge = row.find('span', class_='head_judge')
        court_timing = row.find('span', style=lambda v: v and 'font-size:12px' in v)

        # =========================
        # BENCH HEADER
        # =========================
        if court_heading and head_judge:
            raw_court = court_heading.get_text(strip=True)
            justices_text = head_judge.get_text(strip=True)

            current_justices_list = [
                f"The Honourable {j.strip()}"
                for j in justices_text.split("The Honourable")
                if j.strip()
            ]

            # 🔑 build UNIQUE court key
            if raw_court == "COURT NO." or not raw_court:
                if current_justices_list:
                    judge = current_justices_list[0].replace("The Honourable ", "").strip()
                    current_court_key = f"COURT NO. ({judge})"
                else:
                    current_court_key = "COURT NO. (UNKNOWN)"
            else:
                current_court_key = raw_court

            if court_timing:
                timing = court_timing.get_text(strip=True)

            if current_court_key not in courts:
                courts[current_court_key] = []
                court_numbers.append(current_court_key)

            category_counts.setdefault(current_court_key, {})
            category_case_list.setdefault(current_court_key, {})


            courts[current_court_key].append({
                "court_number": current_court_key,
                "justices": current_justices_list,
                "timing": timing
            })

            continue

        # =========================
        # CATEGORY HEADER
        # =========================
        heading = row.find('span', class_='stagename_heading')
        if heading:
            current_category = heading.get_text(strip=True)
            category_counts[current_court_key].setdefault(current_category, 0)
            category_case_list[current_court_key].setdefault(current_category, [])

            continue

        # =========================
        # CASE ROW
        # =========================
        cols = row.find_all('td')
        if not cols or not current_court_key:
            continue

        def col(i):
            return cols[i].get_text(strip=True) if len(cols) > i else ""

        serial_number = col(0)
        case_number = col(1)
        parties_text = col(2)
        petitioner_text = col(3)
        respondent_text = col(4)

        is_likely_case = (
            (case_number or parties_text)
            and ("VS" in parties_text or "/" in case_number or serial_number.isdigit())
        )

        if not is_likely_case:
            continue

        if not current_category:
            current_category = "Uncategorized"


        category_counts[current_court_key].setdefault(current_category, 0)
        category_case_list[current_court_key].setdefault(current_category, [])

        if(serial_number != ""):
            # category_counts.setdefault(current_court_key, {})
            category_counts[current_court_key][current_category] += 1    


        case_data = {
            "serial_number": serial_number,
            "case_number": case_number,
            "parties": parties_text.replace("VS", " VS "),
            "petitioner_advocates": petitioner_text,
            "respondent_advocates": respondent_text,
            "category": current_category,
            "COURT NO.": current_court_key,          # <<< FIX
            "Justice": current_justices_list          # <<< FIX
        }

        category_case_list[current_court_key][current_category].append(case_data)


    # =========================
    # FINAL CATEGORY COUNTS
    # =========================
    for court_key, categories in category_case_list.items():
        for category, cases in categories.items():
            count = category_counts[court_key].get(category, 0)
            label = f"{category} ({count})" if category else f"Uncategorized ({count})"
            for c in cases:
                c["category"] = label
            data.extend(cases)


    final_json = {
        "cases": sorted(data, key=court_sort_key_from_case),
        "courts": courts,
        "court_numbers": court_numbers
    }

    jsons_dir = os.path.join(os.path.dirname(__file__), "jsons")
    os.makedirs(jsons_dir, exist_ok=True)

    json_file_path = os.path.join(jsons_dir, f"{name}{current_date}.json")
    with open(json_file_path, "w", encoding="utf-8") as f:
        json.dump(final_json, f, indent=4)

    print(f"JSON saved to: {json_file_path}")


if __name__ == "__main__":
    import sys

    current_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%d-%m-%Y")

    Generate_JSON(f"saved_webpage/mdu{current_date}.html", "mdu")
    Generate_JSON(f"saved_webpage/madr{current_date}.html", "madr")
