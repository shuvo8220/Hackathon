"""
ROC Bangladesh - AI Form Automation System
==========================================
Flow:
1. Select business type
2. Select process (registration, annual return, etc.)
3. See all blanks with descriptions - fill one by one
4. Generate filled PDFs
"""

import os
import re
import json
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

BASE_DIR     = Path(__file__).parent
HTML_STORAGE = BASE_DIR / "roc_forms_html_storage"
FILLED_DIR   = BASE_DIR / "filled_forms"
FILLED_DIR.mkdir(exist_ok=True)

SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)
MODEL = "ll"

# Business types with examples
BUSINESS_TYPES = {
    "1": {
        "key":     "private_limited",
        "label":   "Private Limited Company",
        "example": "IT company, software firm, trading company, manufacturing, restaurant chain",
    },
    "2": {
        "key":     "partnership",
        "label":   "Partnership Firm",
        "example": "Two or more people doing business together, law firm, accounting firm",
    },
    "3": {
        "key":     "ngo",
        "label":   "NGO / Society",
        "example": "Nonprofit organization, social club, association, charity",
    },
}

# Process → which forms to use (filename stems)
REGISTRATION_FORMS = {
    "private_limited": [
        "application",       # Name Clearance
        "form_i",            # Declaration on Registration
        "form-ix",           # Consent of Director
        "form-xii",          # Particulars of Directors
        "form-iii",          # Situation of Registered Office
        "form_vi",           # Notice of Registered Office
    ],
    "partnership": [
        "form_i",            # Partnership Registration
    ],
    "ngo": [
        "society_registration_form",
    ],
}

# ── Blank extraction ──────────────────────────────────────

def extract_blanks(html_path: Path, form_title: str) -> list[dict]:
    """HTML theke blanks extract koro with context as description"""
    raw  = html_path.read_text(encoding="utf-8", errors="ignore")
    text = BeautifulSoup(raw, "html.parser").get_text(separator=" ")
    text = re.sub(r"\s+", " ", text)

    blanks = []
    for i, m in enumerate(re.finditer(r"_{5,}", text), start=1):
        # Before blank
        before = text[max(0, m.start()-100):m.start()].strip()
        before = re.sub(r"_{3,}", "", before)  # remove other blanks
        before = re.sub(r"\s+", " ", before).strip()
        # After blank
        after  = text[m.end():min(len(text), m.end()+40)].strip()
        after  = re.sub(r"_{3,}", "", after).strip()

        # Build meaningful context
        context = before[-60:].strip()
        if after and len(after) > 3:
            context = f"{context} ___ {after[:30]}"

        blanks.append({
            "id":      f"blank_{i}",
            "desc":    context if context else f"Field {i}",
            "pattern": m.group(),
            "value":   ""
        })
    return blanks

def ai_describe_single_blank(form_title: str, context: str) -> dict:
    """Single blank er jonno AI description nao"""
    try:
        resp = client.chat.completions.create(
            model=MODEL, max_tokens=120,
            messages=[
                {"role": "system", "content": "You are a Bangladesh ROC form expert. Given text around a blank field in a government form, identify what information should be filled there. Reply in exactly 4 lines:\nEN: [English description, max 6 words]\nBN: [Bangla description, max 6 words]\nEX: [one example value]\nRULE: [one validation rule, max 6 words]"},
                {"role": "user", "content": f"Form: {form_title}\nText near blank: \"{context[-70:]}\""}
            ]
        )
        text = resp.choices[0].message.content.strip()
        result = {"desc_en": "", "desc_bn": "", "example": "", "validation": ""}
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
        # Fallback if parsing failed
        if not result["desc_en"]:
            result["desc_en"] = context[-50:].strip()
        return result
    except Exception as e:
        return {"desc_en": context[-50:].strip(), "desc_bn": "", "example": "", "validation": ""}

def ai_describe_blanks(form_title: str, blanks: list[dict]) -> list[dict]:
    for b in blanks:
        info = ai_describe_single_blank(form_title, b["desc"])
        b["desc_en"]    = info["desc_en"]
        b["desc_bn"]    = info["desc_bn"]
        b["example"]    = info["example"]
        b["validation"] = info["validation"]
    return blanks

def ai_validate_value(desc_en: str, validation: str, value: str, form_title: str) -> tuple[bool, str]:
    """User er dewa value validate koro. Returns (is_valid, feedback)"""
    if not value:
        return False, "This field cannot be empty. / এই ঘরটি খালি রাখা যাবে না।"
    try:
        resp = client.chat.completions.create(
            model=MODEL, max_tokens=150,
            messages=[
                {"role": "system", "content": """You are a Bangladesh ROC form validator.
Check if the user's input is valid for the given field.
Reply ONLY with JSON: {"valid": true/false, "feedback": "short message in English and Bangla if invalid"}
If valid, feedback should be empty string."""},
                {"role": "user", "content": f"Form: {form_title}\nField: {desc_en}\nRule: {validation}\nUser input: {value}"}
            ]
        )
        text = re.sub(r"```json|```", "", resp.choices[0].message.content.strip()).strip()
        result = json.loads(text)
        return result.get("valid", True), result.get("feedback", "")
    except:
        return True, ""
    """HTML theke blanks extract koro with context as description"""
    raw  = html_path.read_text(encoding="utf-8", errors="ignore")
    text = BeautifulSoup(raw, "html.parser").get_text(separator=" ")
    text = re.sub(r"\s+", " ", text)

    blanks = []
    for i, m in enumerate(re.finditer(r"_{5,}", text), start=1):
        before = text[max(0, m.start()-80):m.start()].strip()
        # Clean and take last meaningful phrase
        before = re.sub(r"\s+", " ", before)
        desc   = before[-60:].strip() if before else f"Field {i}"
        blanks.append({
            "id":      f"blank_{i}",
            "desc":    desc,
            "pattern": m.group(),
            "value":   ""
        })
    return blanks

# ── HTML fill + PDF ───────────────────────────────────────

def fill_html(html_path: Path, blanks: list[dict]) -> str:
    raw = html_path.read_text(encoding="utf-8", errors="ignore")
    for blank in blanks:
        value = blank["value"]
        if value:
            raw = raw.replace(blank["pattern"], f"<u><b>{value}</b></u>", 1)
    return raw

def html_to_pdf(html_content: str, out_path: Path) -> bool:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html",
                                     encoding="utf-8", delete=False) as tmp:
        tmp.write(html_content)
        tmp_path = Path(tmp.name)
    try:
        result = subprocess.run([
            SOFFICE, "--headless",
            "--convert-to", "pdf",
            "--outdir", str(out_path.parent.resolve()),
            str(tmp_path.resolve())
        ], capture_output=True, timeout=60)

        generated = out_path.parent / f"{tmp_path.stem}.pdf"
        if generated.exists():
            generated.rename(out_path)
            return True
        return False
    except Exception as e:
        print(f"  PDF error: {e}")
        return False
    finally:
        tmp_path.unlink(missing_ok=True)

# ── CLI ───────────────────────────────────────────────────

def sep(char="=", w=60):
    print(char * w)

def main():
    sep()
    print("  ROC Bangladesh - Form Automation System")
    sep()

    # Step 1: Select business type
    print("\nWhat type of business do you want to register?\n")
    for num, bt in BUSINESS_TYPES.items():
        print(f"  [{num}] {bt['label']}")
        print(f"      e.g. {bt['example']}\n")

    choice = input("  Select [1/2/3]: ").strip()
    if choice not in BUSINESS_TYPES:
        print("Invalid choice. Exiting.")
        return

    btype = BUSINESS_TYPES[choice]["key"]
    label = BUSINESS_TYPES[choice]["label"]
    print(f"\n  Selected: {label}")

    # Step 2: Show which forms will be filled
    form_stems = REGISTRATION_FORMS.get(btype, [])
    btype_dir  = HTML_STORAGE / btype

    html_files = []
    for stem in form_stems:
        # Try exact match first, then partial
        exact = btype_dir / f"{stem}.html"
        if exact.exists():
            html_files.append(exact)
        else:
            matches = list(btype_dir.glob(f"{stem}*.html"))
            if matches:
                html_files.append(matches[0])

    if not html_files:
        print(f"No registration forms found for {label}")
        return

    print(f"\nForms required for registration ({len(html_files)}):")
    for f in html_files:
        print(f"  - {f.stem.replace('_',' ').replace('-',' ').title()}")

    input("\n  Press Enter to start filling forms...")

    # Step 3: Collect ALL blanks from ALL forms first, deduplicate, then fill
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = FILLED_DIR / f"{btype}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n  Analyzing all forms for fields...")

    # Collect blanks only (no AI yet)
    all_forms_blanks = {}
    for html_file in html_files:
        title  = html_file.stem.replace("_", " ").replace("-", " ").title()
        blanks = extract_blanks(html_file, title)
        all_forms_blanks[html_file] = {"title": title, "blanks": blanks}

    # Global answered cache
    answered_cache = {}  # norm_key -> value

    # Step 4: Form by form — describe then fill
    for form_idx, (html_file, data) in enumerate(all_forms_blanks.items(), 1):
        title  = data["title"]
        blanks = data["blanks"]

        if not blanks:
            continue

        sep()
        print(f"  FORM {form_idx}/{len(all_forms_blanks)}: {title}")
        print(f"  Getting field descriptions...")

        # Describe blanks for THIS form only
        blanks = ai_describe_blanks(title, blanks)
        data["blanks"] = blanks

        sep("-", 60)

        for idx, blank in enumerate(blanks, 1):
            norm = re.sub(r"[^a-z0-9 ]", "", blank["desc_en"].lower())[:40]

            # Already answered in a previous form?
            if norm in answered_cache:
                blank["value"] = answered_cache[norm]
                print(f"  [{idx}/{len(blanks)}] {blank['desc_en']}")
                print(f"  Auto-filled: {blank['value']}\n")
                continue

            print(f"  [{idx}/{len(blanks)}]")
            print(f"  EN  : {blank['desc_en']}")
            try:
                if blank.get("desc_bn"):
                    print(f"  BN  : {blank['desc_bn']}")
            except:
                pass
            if blank.get("example"):
                print(f"  Ex  : {blank['example']}")
            if blank.get("validation"):
                print(f"  Rule: {blank['validation']}")
            print()

            while True:
                val = input("  Your input > ").strip()
                if not val:
                    confirm = input("  Skip? (y/n) > ").strip().lower()
                    if confirm == "y":
                        break
                    continue

                is_valid, feedback = ai_validate_value(
                    blank["desc_en"], blank.get("validation", ""), val, title
                )
                if is_valid:
                    blank["value"] = val
                    answered_cache[norm] = val
                    print(f"  OK\n")
                    break
                else:
                    print(f"\n  [!] {feedback}")
                    print(f"  Please correct and try again.\n")

        print(f"  Form {form_idx} complete.\n")

    # Step 5: Review & edit all
    sep()
    print("  FINAL REVIEW - Check all values\n")
    print("  (Enter to keep, type new value to change, 'd' to clear)\n")

    for norm, val in list(answered_cache.items()):
        # Find desc for display
        desc_en = norm
        for _, data in all_forms_blanks.items():
            for b in data["blanks"]:
                if re.sub(r"[^a-z0-9 ]", "", b["desc_en"].lower())[:40] == norm:
                    desc_en = b["desc_en"]
                    break

        print(f"  Field : {desc_en}")
        print(f"  Value : {val or '[empty]'}")
        new_val = input("  Edit  > ").strip()
        if new_val == "d":
            answered_cache[norm] = ""
        elif new_val:
            is_valid, feedback = ai_validate_value(desc_en, "", new_val, "Review")
            if not is_valid:
                print(f"  [!] {feedback}")
                if input("  Save anyway? (y/n) > ").strip().lower() == "y":
                    answered_cache[norm] = new_val
            else:
                answered_cache[norm] = new_val
        print()

    # Apply final values to blanks
    for html_file, data in all_forms_blanks.items():
        for blank in data["blanks"]:
            norm = re.sub(r"[^a-z0-9 ]", "", blank["desc_en"].lower())[:40]
            blank["value"] = answered_cache.get(norm, blank["value"])

    # Step 6: Save as HTML
    print("\n  Saving filled HTML files...\n")
    for html_file, data in all_forms_blanks.items():
        filled_html = fill_html(html_file, data["blanks"])
        out_path = out_dir / f"{html_file.stem}.html"
        out_path.write_text(filled_html, encoding="utf-8")
        print(f"  Saved: {out_path.name}")

    sep()
    print(f"  Done! PDFs saved to:")
    print(f"  {out_dir}")
    sep()

if __name__ == "__main__":
    main()
