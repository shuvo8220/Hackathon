"""
ROC Bangladesh - FastAPI Backend
=================================
Web API that powers the React frontend.
Endpoints:
  POST /api/detect-business   → business type detect kore
  POST /api/get-forms         → selected forms load kore
  POST /api/fill-forms        → AI diye forms fill kore
  GET  /api/sessions          → saved sessions list
  GET  /api/session/{id}      → single session load
"""

import io
import json
import os
import re
import uuid
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from openai import OpenAI

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── paths ──────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent.parent
FORMS_DB  = BASE_DIR / "forms_db"
SESSIONS  = BASE_DIR / "filled_forms"
SESSIONS.mkdir(exist_ok=True)

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)
MODEL  = "gpt-oss-120b"
app    = FastAPI(title="ROC Form Automation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── request models ──────────────────────────────────────
class DetectRequest(BaseModel):
    description: str

class FormsRequest(BaseModel):
    business_type: str

class FillRequest(BaseModel):
    business_type: str
    business_description: str
    user_info: dict          # {field_label: value}

# ── helpers ─────────────────────────────────────────────
def load_index() -> dict:
    with open(FORMS_DB / "forms_index.json", encoding="utf-8") as f:
        return json.load(f)

def load_form(business_type: str, form_id: str) -> dict | None:
    for folder in FORMS_DB.iterdir():
        p = folder / f"{form_id}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return None

def extract_fields(forms: list[dict]) -> list[dict]:
    seen, out = set(), []
    for form in forms:
        for f in form.get("fields", []):
            if f["id"] not in seen and not f.get("auto_fill_from"):
                seen.add(f["id"])
                out.append(f)
    return out

def apply_auto_fills(forms: list[dict], data: dict) -> dict:
    for form in forms:
        for f in form.get("fields", []):
            src = f.get("auto_fill_from")
            if src and src in data and f["id"] not in data:
                data[f["id"]] = data[src]
    return data

# ── routes ──────────────────────────────────────────────

@app.post("/api/detect-business")
def detect_business(req: DetectRequest):
    index = load_index()
    summary = "\n".join(
        f"- {k}: {v['label']} (keywords: {', '.join(v['keywords'][:4])})"
        for k, v in index.items()
    )
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=300,
        messages=[
            {"role": "system", "content": 'Reply ONLY with JSON: {"type":"...","reason":"...in Bangla"}. '
               'Valid types: private_limited, public_limited, partnership, sole_proprietorship, ngo'},
            {"role": "user", "content":
                f"Business types:\n{summary}\n\nUser said: \"{req.description}\"\n\nWhich type?"}
        ]
    )
    text = re.sub(r"```json|```", "", resp.choices[0].message.content).strip()
    result = json.loads(text)
    btype  = result.get("type", "private_limited")
    label  = index.get(btype, {}).get("label", btype)
    forms_needed = index.get(btype, {}).get("forms", [])
    return {
        "business_type": btype,
        "label": label,
        "reason": result.get("reason", ""),
        "forms_count": len(forms_needed),
        "forms": forms_needed
    }


@app.post("/api/get-forms")
def get_forms(req: FormsRequest):
    index = load_index()
    if req.business_type not in index:
        raise HTTPException(404, "Business type not found")
    form_ids = index[req.business_type]["forms"]
    schemas  = [f for fid in form_ids if (f := load_form(req.business_type, fid))]
    fields   = extract_fields(schemas)
    return {
        "business_type": req.business_type,
        "forms": [{"form_id": f["form_id"], "title": f["title"],
                   "title_bn": f.get("title_bn",""), "field_count": len(f.get("fields",[]))}
                  for f in schemas],
        "fields_to_collect": fields
    }


@app.post("/api/fill-forms")
def fill_forms(req: FillRequest):
    index  = load_index()
    if req.business_type not in index:
        raise HTTPException(404, "Business type not found")

    form_ids = index[req.business_type]["forms"]
    forms    = [f for fid in form_ids if (f := load_form(req.business_type, fid))]
    fields   = extract_fields(forms)
    today    = datetime.now().strftime("%Y-%m-%d")

    # Convert user_info dict to readable text for AI
    user_text = "\n".join(f"{k}: {v}" for k, v in req.user_info.items() if v)

    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=3000,
        messages=[
            {"role": "system", "content": f"""You are a Bangladesh ROC form expert.
Fill form fields from the user's information.
Rules:
- Fill ONLY from given info, never invent
- Today's date: {today}
- Nationality default: Bangladeshi
- Missing required → "[REQUIRED - NOT PROVIDED]"
- Missing optional → ""
- Reply ONLY with JSON object: {{field_id: value}}"""},
            {"role": "user", "content":
                f"Business: {req.business_description}\n\n"
                f"User info:\n{user_text}\n\n"
                f"Fields:\n{json.dumps(fields, ensure_ascii=False, indent=2)}\n\n"
                f"Return JSON only."}
        ]
    )

    text = re.sub(r"```json|```", "", resp.choices[0].message.content).strip()
    filled_data = json.loads(text)
    filled_data = apply_auto_fills(forms, filled_data)

    # Build filled forms
    filled_forms = []
    missing_total = 0
    for form in forms:
        ff_list = []
        for field in form.get("fields", []):
            val     = filled_data.get(field["id"], "")
            missing = field.get("required", False) and (not val or val == "[REQUIRED - NOT PROVIDED]")
            if missing:
                missing_total += 1
            ff_list.append({
                "id":       field["id"],
                "label":    field["label"],
                "label_bn": field.get("label_bn", ""),
                "value":    val,
                "required": field.get("required", False),
                "missing":  missing
            })
        filled_forms.append({
            "form_id":      form["form_id"],
            "title":        form["title"],
            "title_bn":     form.get("title_bn", ""),
            "filled_fields": ff_list
        })

    # Save session
    session_id = str(uuid.uuid4())[:8]
    session    = {
        "session_id":   session_id,
        "created_at":   datetime.now().isoformat(),
        "business_type": req.business_type,
        "description":   req.business_description,
        "forms":         filled_forms,
        "missing_count": missing_total
    }
    path = SESSIONS / f"{session_id}.json"
    path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "session_id":    session_id,
        "forms":         filled_forms,
        "missing_count": missing_total,
        "total_fields":  sum(len(f["filled_fields"]) for f in filled_forms)
    }


@app.get("/api/sessions")
def list_sessions():
    sessions = []
    for p in sorted(SESSIONS.glob("*.json"), reverse=True)[:20]:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            sessions.append({
                "session_id":    data["session_id"],
                "created_at":    data["created_at"],
                "business_type": data["business_type"],
                "description":   data["description"][:60],
                "forms_count":   len(data["forms"]),
                "missing_count": data.get("missing_count", 0)
            })
        except:
            pass
    return {"sessions": sessions}


@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    p = SESSIONS / f"{session_id}.json"
    if not p.exists():
        raise HTTPException(404, "Session not found")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/business-types")
def get_business_types():
    index = load_index()
    return {"types": [
        {"key": k, "label": v["label"], "forms_count": len(v["forms"])}
        for k, v in index.items()
    ]}


def _load_bangla_font():
    """Kalpurush or any bundled Bangla TTF font register koro"""
    font_candidates = [
        Path(__file__).parent / "fonts" / "Kalpurush.ttf",
        Path(__file__).parent / "fonts" / "NotoSansBengali-Regular.ttf",
    ]
    for fp in font_candidates:
        if fp.exists():
            pdfmetrics.registerFont(TTFont("Bangla", str(fp)))
            return "Bangla"
    return None  # fallback to Helvetica


def generate_pdf(session: dict) -> bytes:
    """Session data theke printable PDF banao"""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm
    )

    bangla_font = _load_bangla_font()
    base_font   = bangla_font or "Helvetica"
    bold_font   = bangla_font or "Helvetica-Bold"

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "roc_title", fontName=bold_font, fontSize=14,
        spaceAfter=4, alignment=1  # center
    )
    sub_style = ParagraphStyle(
        "roc_sub", fontName=base_font, fontSize=10,
        spaceAfter=2, alignment=1, textColor=colors.grey
    )
    form_title_style = ParagraphStyle(
        "form_title", fontName=bold_font, fontSize=11,
        spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#1a3c6e")
    )
    missing_style = ParagraphStyle(
        "missing", fontName=base_font, fontSize=9, textColor=colors.red
    )

    story = []

    # ── Header ──────────────────────────────────────────
    story.append(Paragraph("ROC Bangladesh", title_style))
    story.append(Paragraph("Registrar of Joint Stock Companies & Firms", sub_style))
    story.append(Paragraph("আরওসি ফর্ম — AI Auto-Fill", sub_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a3c6e")))
    story.append(Spacer(1, 4*mm))

    # ── Meta info ────────────────────────────────────────
    meta = [
        ["Session ID",    session["session_id"]],
        ["Business Type", session["business_type"].replace("_", " ").title()],
        ["Description",   session["description"][:80]],
        ["Generated",     session["created_at"][:19].replace("T", " ")],
    ]
    meta_table = Table(meta, colWidths=[45*mm, 125*mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME",    (0,0), (-1,-1), base_font),
        ("FONTSIZE",    (0,0), (-1,-1), 9),
        ("FONTNAME",    (0,0), (0,-1),  bold_font),
        ("TEXTCOLOR",   (0,0), (0,-1),  colors.HexColor("#1a3c6e")),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.HexColor("#f0f4ff"), colors.white]),
        ("BOX",         (0,0), (-1,-1), 0.5, colors.lightgrey),
        ("INNERGRID",   (0,0), (-1,-1), 0.3, colors.lightgrey),
        ("TOPPADDING",  (0,0), (-1,-1), 3),
        ("BOTTOMPADDING",(0,0),(-1,-1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 6*mm))

    # ── Each form ────────────────────────────────────────
    for form in session["forms"]:
        story.append(Paragraph(f"📄 {form['title']}", form_title_style))
        if form.get("title_bn"):
            story.append(Paragraph(form["title_bn"], sub_style))

        rows = [["Field", "Value", "Status"]]
        for ff in form["filled_fields"]:
            label  = ff["label"]
            value  = str(ff["value"]) if ff["value"] else "—"
            status = "⚠ Missing" if ff["missing"] else ("✓" if ff["value"] else "—")
            rows.append([label, value, status])

        col_w = [55*mm, 95*mm, 20*mm]
        tbl   = Table(rows, colWidths=col_w, repeatRows=1)
        tbl.setStyle(TableStyle([
            # Header row
            ("BACKGROUND",   (0,0), (-1,0),  colors.HexColor("#1a3c6e")),
            ("TEXTCOLOR",    (0,0), (-1,0),  colors.white),
            ("FONTNAME",     (0,0), (-1,0),  bold_font),
            ("FONTSIZE",     (0,0), (-1,-1), 9),
            ("FONTNAME",     (0,1), (-1,-1), base_font),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.white, colors.HexColor("#f7f9ff")]),
            ("BOX",          (0,0), (-1,-1), 0.5, colors.grey),
            ("INNERGRID",    (0,0), (-1,-1), 0.3, colors.lightgrey),
            ("TOPPADDING",   (0,0), (-1,-1), 3),
            ("BOTTOMPADDING",(0,0),(-1,-1), 3),
            ("VALIGN",       (0,0), (-1,-1), "TOP"),
            # Missing rows → light red background
            *[
                ("BACKGROUND", (0, i+1), (-1, i+1), colors.HexColor("#fff0f0"))
                for i, ff in enumerate(form["filled_fields"]) if ff["missing"]
            ],
        ]))
        story.append(tbl)
        story.append(Spacer(1, 5*mm))

    # ── Footer ───────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Paragraph(
        f"Generated by ROC Form Automation System • {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ParagraphStyle("footer", fontName=base_font, fontSize=8,
                       textColor=colors.grey, alignment=1)
    ))

    doc.build(story)
    return buf.getvalue()


@app.get("/api/session/{session_id}/pdf")
def download_pdf(session_id: str):
    p = SESSIONS / f"{session_id}.json"
    if not p.exists():
        raise HTTPException(404, "Session not found")
    session = json.loads(p.read_text(encoding="utf-8"))
    pdf_bytes = generate_pdf(session)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=roc_{session_id}.pdf"}
    )


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}
