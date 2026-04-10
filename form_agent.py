"""
Form Fill Agent
===============
1. Company type select koro
2. validated_forms/ theke form names nao
3. HTML form er blanks AI diye describe + fill koro
4. Filled HTML output save koro

Run: python form_agent.py
Uses: OpenAI API
"""

import os
import re
import json
from pathlib import Path
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

BASE_DIR         = Path(__file__).parent
HTML_STORAGE     = BASE_DIR / "roc_forms_html_storage"
VALIDATED_DIR    = BASE_DIR / "validated_forms"
OUTPUT_DIR       = BASE_DIR / "filled_forms_agent"
OUTPUT_DIR.mkdir(exist_ok=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL  = "gpt-4o-mini"

COMPANY_TYPES = {
    "1": {"key": "private_limited",    "label": "Private Limited Company",  "example": "IT firm, trading company, manufacturing"},
    "2": {"key": "partnership",        "label": "Partnership Firm",          "example": "Two or more people in business together"},
    "3": {"key": "ngo",                "label": "NGO / Society",             "example": "Nonprofit, association, club"},
}

# Form title -> HTML filename mapping
FORM_HTML_MAP = {
    "Declaration on Registration of Company":          "form_i.html",
    "Notice of situation of Registered Office Change": "form_vi.html",
    "List of Persons Consenting to be Directors":      "form_x.html",
}

DOCUMENTS_DIR = BASE_DIR / "documents_needed"
DOCUMENTS_DIR.mkdir(exist_ok=True)

# Registration forms per business type
REGISTRATION_FORMS = {
    "private_limited": [
        {"form": "Application",        "file": "application.html",  "purpose": "Name Clearance Application"},
        {"form": "Form I",             "file": "form_i.html",       "purpose": "Declaration on Registration of Company"},
        {"form": "Form IX",            "file": "form-ix.html",      "purpose": "Consent of Directors"},
        {"form": "Form XII",           "file": "form-xii.html",     "purpose": "Particulars of Directors"},
        {"form": "Form III",           "file": "form-iii.html",     "purpose": "Situation of Registered Office"},
        {"form": "Form VI",            "file": "form_vi.html",      "purpose": "Notice of Registered Office"},
    ],
    "partnership": [
        {"form": "Form I",             "file": "form_i.html",       "purpose": "Partnership Registration"},
        {"form": "Form II",            "file": "form-ii.html",      "purpose": "Alteration of Partnership"},
    ],
    "ngo": [
        {"form": "Society Registration Form", "file": "society_registration_form.html", "purpose": "NGO/Society Registration"},
        {"form": "Annual List",        "file": "annual_list_of_managing_body.html", "purpose": "Annual List of Managing Body"},
    ],
}

def generate_documents_needed(btype: str, label: str):
    """Business type er jonno ki ki form lagbe seta documents_needed/ e save koro"""
    forms = REGISTRATION_FORMS.get(btype, [])
    if not forms:
        return

    forms_md = "\n".join([
        f"| {f['form']} | {f['purpose']} | {f['file']} |"
        for f in forms
    ])

    md = f"""# Documents Needed: {label}

## Required Forms for Registration

| Form | Purpose | File |
|------|---------|------|
{forms_md}

## Steps
1. Name Clearance - Submit application first
2. Prepare all forms listed above
3. Fill each form with company information
4. Submit to Registrar of Joint Stock Companies (RJSC)

## Notes
- All forms must be signed by authorized person
- Keep copies of all submitted documents
- Registration fee must be paid at time of submission
"""

    out_path = DOCUMENTS_DIR / f"{btype}_documents_needed.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"\n  Documents checklist saved: {out_path.name}")
    print(f"  Required forms ({len(forms)}):")
    for f in forms:
        print(f"    - {f['form']}: {f['purpose']}")

# ── Load validated form names ─────────────────────────────

def get_validated_form_names() -> list[str]:
    names = []
    for md in sorted(VALIDATED_DIR.glob("*.md")):
        names.append(md.stem)
    return names

# ── Extract blanks from HTML ──────────────────────────────

def extract_blanks(html_path: Path) -> list[dict]:
    raw  = html_path.read_text(encoding="utf-8", errors="ignore")
    text = BeautifulSoup(raw, "html.parser").get_text(separator=" ")
    text = re.sub(r"\s+", " ", text)

    blanks = []
    for i, m in enumerate(re.finditer(r"_{5,}", text), start=1):
        before = text[max(0, m.start()-100):m.start()]
        before = re.sub(r"_{3,}", "", before)
        before = re.sub(r"\s+", " ", before).strip()
        after  = text[m.end():min(len(text), m.end()+50)]
        after  = re.sub(r"_{3,}", "", after).strip()
        context = f"{before[-60:]} ___ {after[:30]}".strip()
        blanks.append({
            "id":      f"blank_{i}",
            "context": context,
            "pattern": m.group(),
            "value":   ""
        })
    return blanks

# ── AI: describe + guide for a blank ─────────────────────

def ai_describe_blank(form_title: str, company_type: str, context: str) -> dict:
    try:
        resp = client.chat.completions.create(
            model=MODEL, max_tokens=150,
            messages=[
                {"role": "system", "content": f"""You are a Bangladesh ROC form expert.
Company type: {company_type}
Form: {form_title}
Given text around a blank field, identify what to fill.
Reply in exactly 4 lines:
EN: [English description, max 8 words]
BN: [Bangla description, max 8 words]
EX: [one realistic example]
RULE: [one validation rule, max 8 words]"""},
                {"role": "user", "content": f"Context: \"{context[-80:]}\""}
            ]
        )
        text   = resp.choices[0].message.content.strip()
        result = {"desc_en": context[-40:], "desc_bn": "", "example": "", "validation": ""}
        for line in text.split("\n"):
            line = line.strip()
            if line.upper().startswith("EN:"):
                result["desc_en"] = line[3:].strip()
            elif line.upper().startswith("BN:"):
                result["desc_bn"] = line[3:].strip()
            elif line.upper().startswith("EX:"):
                result["example"] = line[3:].strip()
            elif line.upper().startswith("RULE:"):
                result["validation"] = line[5:].strip()
        return result
    except Exception as e:
        return {"desc_en": context[-40:], "desc_bn": "", "example": "", "validation": ""}

# ── AI: validate user input ───────────────────────────────

def ai_validate(desc_en: str, rule: str, value: str) -> tuple[bool, str]:
    if not value:
        return False, "Field cannot be empty."
    try:
        resp = client.chat.completions.create(
            model=MODEL, max_tokens=80,
            messages=[
                {"role": "system", "content": "Validate user input for a Bangladesh ROC form field. Reply JSON: {\"valid\": true/false, \"feedback\": \"reason if invalid, else empty\"}"},
                {"role": "user", "content": f"Field: {desc_en}\nRule: {rule}\nInput: {value}"}
            ],
            response_format={"type": "json_object"}
        )
        result = json.loads(resp.choices[0].message.content)
        return result.get("valid", True), result.get("feedback", "")
    except:
        return True, ""

# ── Fill HTML ─────────────────────────────────────────────

def fill_html(html_path: Path, blanks: list[dict]) -> str:
    raw = html_path.read_text(encoding="utf-8", errors="ignore")
    for blank in blanks:
        if blank["value"]:
            raw = raw.replace(blank["pattern"], f"<u><b>{blank['value']}</b></u>", 1)
    return raw

# ── Main ──────────────────────────────────────────────────

def main():
    sep()
    print("  ROC Bangladesh - Form Fill Agent")
    sep()

    # Step 1: Company type
    print("\nSelect company type:\n")
    for num, ct in COMPANY_TYPES.items():
        print(f"  [{num}] {ct['label']}")
        print(f"      e.g. {ct['example']}\n")
    choice = input("  Select [1/2/3]: ").strip()
    if choice not in COMPANY_TYPES:
        print("Invalid. Exiting.")
        return
    btype = COMPANY_TYPES[choice]["key"]
    label = COMPANY_TYPES[choice]["label"]
    print(f"\n  Selected: {label}")

    # Generate documents needed checklist
    generate_documents_needed(btype, label)

    # Step 2: Get form names from validation reports
    form_names = get_validated_form_names()
    if not form_names:
        print("No validated forms found. Run form_validator.py first.")
        return

    print(f"\nForms from validation reports:")
    for i, name in enumerate(form_names, 1):
        print(f"  [{i}] {name}")

    # Step 3: Process each form
    answered_cache = {}  # norm -> value (avoid duplicate questions)

    for form_name in form_names:
        html_filename = FORM_HTML_MAP.get(form_name)
        if not html_filename:
            print(f"\n  [SKIP] No HTML mapping for: {form_name}")
            continue

        html_path = HTML_STORAGE / btype / html_filename
        if not html_path.exists():
            # Try other folders
            for folder in HTML_STORAGE.iterdir():
                alt = folder / html_filename
                if alt.exists():
                    html_path = alt
                    break

        if not html_path.exists():
            print(f"\n  [SKIP] HTML not found: {html_filename}")
            continue

        sep()
        print(f"\n  FORM: {form_name}")
        sep("-")

        blanks = extract_blanks(html_path)
        if not blanks:
            print("  No fillable fields found.")
            continue

        print(f"  {len(blanks)} fields to fill. AI will guide you.\n")

        for blank in blanks:
            norm = re.sub(r"[^a-z0-9 ]", "", blank["context"].lower())[:40]

            # Already answered?
            if norm in answered_cache:
                blank["value"] = answered_cache[norm]
                print(f"  Auto-filled: {blank['value']}\n")
                continue

            # AI describe
            info = ai_describe_blank(form_name, label, blank["context"])
            blank.update(info)

            print(f"  EN  : {info['desc_en']}")
            if info["example"]:
                print(f"  Ex  : {info['example']}")
            if info["validation"]:
                print(f"  Rule: {info['validation']}")
            print()

            while True:
                val = input("  Input > ").strip()
                if not val:
                    if input("  Skip? (y/n) > ").strip().lower() == "y":
                        break
                    continue
                is_valid, feedback = ai_validate(info["desc_en"], info["validation"], val)
                if is_valid:
                    blank["value"] = val
                    answered_cache[norm] = val
                    print("  OK\n")
                    break
                else:
                    print(f"  [!] {feedback}\n")

        # Save filled HTML
        filled_html = fill_html(html_path, blanks)
        out_path = OUTPUT_DIR / f"{html_path.stem}_filled.html"
        out_path.write_text(filled_html, encoding="utf-8")
        print(f"  Saved: {out_path.name}")

    sep()
    print(f"  Done! Filled forms in: {OUTPUT_DIR}")
    sep()

if __name__ == "__main__":
    main()
