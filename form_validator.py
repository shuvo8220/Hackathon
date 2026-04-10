"""
Multi-Agent Form Validator
==========================
Agent 1 (Matcher): form JSON + act chunks theke relevant sections find kore
Agent 2 (Validator): matched data validate kore
Output: validated_forms/ folder e save kore

Run: python form_validator.py
Uses: OpenAI API
"""

import json
import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

BASE_DIR        = Path(__file__).parent
ACT_CHUNKS_FILE = BASE_DIR / "act" / "act-print-26_chunks.jsonl"
FORMS_DIR       = BASE_DIR / "company_Information"
OUTPUT_DIR      = BASE_DIR / "validated_forms"
OUTPUT_DIR.mkdir(exist_ok=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL  = "gpt-4o-mini"

# ── Load act chunks ───────────────────────────────────────

def load_act_chunks() -> list[dict]:
    chunks = []
    with open(ACT_CHUNKS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks

def load_form_jsons() -> list[dict]:
    forms = []
    for jf in sorted(FORMS_DIR.glob("*.json")):
        data = json.loads(jf.read_text(encoding="utf-8"))
        data["_filename"] = jf.name
        forms.append(data)
    return forms

# ── Agent 1: Matcher ──────────────────────────────────────

def agent_matcher(form: dict, act_chunks: list[dict]) -> dict:
    """
    Form JSON + act chunks dekhle relevant act sections find kore.
    Returns: {matched_sections, form_fields_mapped}
    """
    form_summary = json.dumps({
        "form_name":  form.get("form_metadata", {}).get("form_name", ""),
        "form_title": form.get("form_metadata", {}).get("form_title", ""),
        "act_name":   form.get("form_metadata", {}).get("act_name", ""),
        "section":    form.get("form_metadata", {}).get("section", ""),
        "fields":     list(form.keys())
    }, ensure_ascii=False)

    # Build act context (relevant chunks only)
    act_context = "\n\n".join([
        f"Section {c['section_num']}: {c['section_title']}\n{c['body'][:300]}"
        for c in act_chunks
    ])

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": """You are a legal document matching expert for Bangladesh law.
Given a government form and act sections, find which act sections are relevant to this form.
Return JSON:
{
  "form_name": "Form I",
  "matched_sections": [
    {"section": "25", "title": "...", "relevance": "why this section applies"}
  ],
  "legal_basis": "overall legal basis for this form",
  "required_fields": ["list of fields that are legally required"]
}"""},
            {"role": "user", "content": f"Form:\n{form_summary}\n\nAct Sections:\n{act_context[:3000]}"}
        ],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)

# ── Agent 2: Validator ────────────────────────────────────

def agent_validator(form: dict, matched: dict) -> dict:
    """
    Form data + matched act sections dekhle validate kore.
    Returns: {is_valid, issues, suggestions, validated_form}
    """
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": """You are a Bangladesh ROC form compliance validator.
Given a filled form and its matched legal sections, validate the form data.
Check:
1. All required fields are present
2. Field values match legal requirements
3. Any inconsistencies or missing data

Return JSON:
{
  "is_valid": true/false,
  "issues": ["list of problems found"],
  "suggestions": ["list of improvements"],
  "field_validations": {
    "field_name": {"valid": true/false, "note": "reason"}
  },
  "compliance_score": 0-100
}"""},
            {"role": "user", "content": f"Form data:\n{json.dumps(form, ensure_ascii=False, indent=2)[:2000]}\n\nLegal match:\n{json.dumps(matched, ensure_ascii=False, indent=2)[:1000]}"}
        ],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)

# ── Main pipeline ─────────────────────────────────────────

def main():
    print("Loading act chunks...")
    act_chunks = load_act_chunks()
    print(f"  {len(act_chunks)} chunks loaded")

    print("Loading form JSONs...")
    forms = load_form_jsons()
    print(f"  {len(forms)} forms loaded\n")

    for form in forms:
        filename = form.pop("_filename")
        form_name = form.get("form_metadata", {}).get("form_name", filename)
        print(f"{'='*55}")
        print(f"Processing: {form_name} ({filename})")

        # Agent 1: Match
        print(f"  [Agent 1] Matching with act sections...")
        matched = agent_matcher(form, act_chunks)
        sections = matched.get("matched_sections", [])
        print(f"  Matched {len(sections)} section(s): {[s['section'] for s in sections]}")

        # Agent 2: Validate
        print(f"  [Agent 2] Validating form data...")
        validation = agent_validator(form, matched)
        score = validation.get("compliance_score", 0)
        is_valid = validation.get("is_valid", False)
        issues = validation.get("issues", [])
        print(f"  Score: {score}/100 | Valid: {is_valid}")
        if issues:
            for issue in issues:
                print(f"  [!] {issue}")

        # Save MD report only
        issues_md      = "\n".join([f"- {i}" for i in issues]) or "- None"
        suggestions_md = "\n".join([f"- {s}" for s in validation.get('suggestions', [])]) or "- None"
        sections_md    = "\n".join([f"- **Section {s['section']}**: {s['title']} — {s['relevance']}" for s in sections]) or "- None"
        field_val      = validation.get("field_validations", {})
        fields_md      = "\n".join([
            f"| {f} | {'✅' if v.get('valid') else '❌'} | {v.get('note','')} |"
            for f, v in field_val.items()
        ]) or "| - | - | - |"

        md_content = f"""# {form_name} — Validation Report

## Summary
| Item | Value |
|------|-------|
| Form | {form_name} |
| File | {filename} |
| Valid | {'✅ Yes' if is_valid else '❌ No'} |
| Compliance Score | {score}/100 |
| Legal Basis | {matched.get('legal_basis', '-')} |

## Matched Act Sections
{sections_md}

## Field Validations
| Field | Status | Note |
|-------|--------|------|
{fields_md}

## Issues
{issues_md}

## Suggestions
{suggestions_md}
"""
        md_stem = filename.replace(".json", "")
        out_md  = OUTPUT_DIR / f"{md_stem}.md"
        out_md.write_text(md_content, encoding="utf-8")
        print(f"  Saved: {out_md.name}\n")

    print(f"Done! Results in: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
