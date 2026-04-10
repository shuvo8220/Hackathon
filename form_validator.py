"""
Multi-Agent Form Validator
==========================
Agent 1 (Searcher): form JSON er section number dekhle output/ folder theke
                    relevant act sections khuje ane
Agent 2 (Analyzer): matched sections + form structure dekhle
                    ki ki field lagbe seta explain kore
Output: validated_forms/ folder e .md file save kore

Run: python form_validator.py
"""

import json
import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

BASE_DIR      = Path(__file__).parent
OUTPUT_DIR    = BASE_DIR / "output" / "output"
FORMS_DIR     = BASE_DIR / "company_Information"
VALIDATED_DIR = BASE_DIR / "validated_forms"
VALIDATED_DIR.mkdir(exist_ok=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL  = "gpt-4o-mini"

# ── Load data ─────────────────────────────────────────────

def load_all_sections() -> dict:
    all_sections = {}
    for act_dir in OUTPUT_DIR.iterdir():
        if not act_dir.is_dir():
            continue
        sections = []
        for chapter_dir in act_dir.iterdir():
            if not chapter_dir.is_dir():
                continue
            for sec_file in chapter_dir.glob("section_*.json"):
                try:
                    sections.append(json.loads(sec_file.read_text(encoding="utf-8")))
                except:
                    pass
        if sections:
            all_sections[act_dir.name] = sections
    return all_sections

def load_form_jsons() -> list[dict]:
    forms = []
    for jf in sorted(FORMS_DIR.glob("*.json")):
        data = json.loads(jf.read_text(encoding="utf-8"))
        data["_filename"] = jf.name
        forms.append(data)
    return forms

# ── Agent 1: Searcher ─────────────────────────────────────

def agent_searcher(form: dict, all_sections: dict) -> list[dict]:
    """Relevant act sections search kore return kore"""
    form_meta    = form.get("form_metadata", {})
    form_section = str(form_meta.get("section", ""))
    form_act     = form_meta.get("act_name", "").lower()
    form_title   = form_meta.get("form_title", "")

    # Search across ALL acts - no filtering
    candidate_sections = []
    for act_name, sections in all_sections.items():
        candidate_sections.extend(sections)

    # Exact section number match
    exact = [s for s in candidate_sections
             if str(s.get("section_number", "")) == form_section]

    # Keyword match across all acts
    keywords = [w.lower() for w in (form_title + " " + form_act).split() if len(w) > 3]
    keyword_matches = [
        s for s in candidate_sections
        if any(kw in s.get("content", "").lower() for kw in keywords)
    ][:10]

    combined = {s["chunk_id"]: s for s in exact + keyword_matches}
    top_sections = list(combined.values())[:12]

    if not top_sections:
        return []

    sections_summary = "\n\n".join([
        f"[Section {s['section_number']}] {s.get('section_title','')}\n{s.get('content','')[:250]}"
        for s in top_sections
    ])

    form_summary = json.dumps({
        "form_name":  form_meta.get("form_name", ""),
        "form_title": form_title,
        "act":        form_meta.get("act_name", ""),
        "section":    form_section,
    }, ensure_ascii=False)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": """You are a Bangladesh legal expert.
Identify which act sections are directly relevant to this government form.
Return JSON: {"sections": [{"section_number": "25", "section_title": "...", "relevance": "why relevant", "key_requirement": "what this section requires"}]}
Return empty sections array if nothing matches."""},
            {"role": "user", "content": f"Form:\n{form_summary}\n\nAct Sections:\n{sections_summary}"}
        ],
        response_format={"type": "json_object"}
    )

    result = json.loads(response.choices[0].message.content)
    matched_basic = result.get("sections", [])

    # Enrich with full content from original sections
    sec_map = {str(s.get("section_number")): s for s in top_sections}
    for m in matched_basic:
        orig = sec_map.get(str(m.get("section_number")), {})
        m["act_name"]    = orig.get("act_name", "")
        m["full_content"] = orig.get("content", "")

    return matched_basic

# ── Agent 2: Analyzer ─────────────────────────────────────

def agent_analyzer(form: dict, matched_sections: list[dict]) -> dict:
    """
    Form structure + matched sections dekhle
    ki ki field lagbe seta explain kore.
    """
    form_meta   = form.get("form_metadata", {})
    form_fields = {k: v for k, v in form.items()
                   if not k.startswith("_") and k != "form_metadata"}

    sections_text = "\n\n".join([
        f"Section {s.get('section_number')}: {s.get('section_title')}\nRequirement: {s.get('key_requirement','')}"
        for s in matched_sections
    ]) or "No matching sections found."

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": """You are a Bangladesh ROC form expert.
Given a form structure and relevant legal sections, explain what information is needed.
Return JSON:
{
  "legal_basis": "brief legal basis for this form",
  "required_fields": [
    {"field": "company_name", "description": "what to provide", "legal_ref": "Section X requires..."}
  ],
  "important_notes": ["note 1", "note 2"]
}"""},
            {"role": "user", "content": f"Form: {form_meta.get('form_name')} - {form_meta.get('form_title')}\n\nForm fields:\n{json.dumps(list(form_fields.keys()), ensure_ascii=False)}\n\nLegal sections:\n{sections_text}"}
        ],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)

# ── MD Report ─────────────────────────────────────────────

def build_md_report(form: dict, matched: list[dict], analysis: dict) -> str:
    form_meta  = form.get("form_metadata", {})
    form_name  = form_meta.get("form_name", "Unknown")
    form_title = form_meta.get("form_title", "")
    filename   = form.get("_filename", "")

    sections_md = "\n\n".join([
        f"### Section {s.get('section_number')}: {s.get('section_title')}\n"
        f"**Act:** {s.get('act_name', '')}\n\n"
        f"**Relevance:** {s.get('relevance','')}\n\n"
        f"**Requirement:** {s.get('key_requirement','')}\n\n"
        f"**Full Text:**\n{s.get('full_content','')}"
        for s in matched
    ]) or "- No matching sections found"

    required_fields = analysis.get("required_fields", [])
    fields_md = "\n".join([
        f"| {f.get('field','')} | {f.get('description','')} | {f.get('legal_ref','')} |"
        for f in required_fields
    ]) or "| - | - | - |"

    notes = analysis.get("important_notes", [])
    notes_md = "\n".join([f"- {n}" for n in notes]) or "- None"

    return f"""# {form_name} - {form_title}

## Legal Basis
{analysis.get('legal_basis', '-')}

## Matched Act Sections
{sections_md}

## Required Fields
| Field | What to Provide | Legal Reference |
|-------|----------------|-----------------|
{fields_md}

## Important Notes
{notes_md}
"""

# ── Main ──────────────────────────────────────────────────

def main():
    print("Loading act sections...")
    all_sections = load_all_sections()
    total = sum(len(v) for v in all_sections.values())
    print(f"  {len(all_sections)} acts, {total} sections loaded")

    print("Loading forms...")
    forms = load_form_jsons()
    print(f"  {len(forms)} forms\n")

    for form in forms:
        filename  = form.get("_filename", "unknown.json")
        form_name = form.get("form_metadata", {}).get("form_name", filename)

        print("=" * 55)
        print(f"Processing: {form_name}")

        # Agent 1: Search
        print("  [Agent 1] Searching act sections...")
        matched = agent_searcher(form, all_sections)
        print(f"  Found {len(matched)} section(s): {[s.get('section_number') for s in matched]}")

        # Agent 2: Analyze
        print("  [Agent 2] Analyzing required fields...")
        analysis = agent_analyzer(form, matched)

        # Save MD
        md_content = build_md_report(form, matched, analysis)
        out_path   = VALIDATED_DIR / filename.replace(".json", ".md")
        out_path.write_text(md_content, encoding="utf-8")
        print(f"  Saved: {out_path.name}\n")

    print(f"Done! Reports in: {VALIDATED_DIR}")

if __name__ == "__main__":
    main()
