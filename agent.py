"""
ROC Bangladesh - Conversational Registration Agent
====================================================
- User er satha natural conversation kore (Bangla/English)
- Chain of thought diye entity/intent bujhe
- session.md e key-value pair a context store kore
- Protibar resume korte pare

Run: python agent.py
"""

import os
import json
from pathlib import Path
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

BASE_DIR     = Path(__file__).parent
SESSION_FILE = BASE_DIR / "session.md"

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL  = "gpt-4o-mini"

# ── Entity knowledge base ─────────────────────────────────

ENTITY_KNOWLEDGE = """
ENTITY: Trade License
  authority: City Corporation (DNCC/DSCC/Pourashava/Union Parishad)
  form_type:
    commercial business -> K Form
    manufacturing -> I Form
    general service -> Standard Form
  prerequisites:
    - TIN certificate (always required)
    - VAT certificate (if turnover > 30 lakh BDT)
    - incorporation certificate (if limited company)
    - fire license (if manufacturing)
    - environmental clearance (if manufacturing)
  fee_range: 1000-20000 BDT (based on capital, size, location)
  validity: Annual, renewal by June 30
  penalty_if_missing: BDT 50,000 + possible closure

ENTITY: TIN (Tax Identification Number)
  authority: National Board of Revenue (NBR)
  required_for: all businesses
  process: online via nbr.gov.bd or tax office
  documents: NID, business address proof

ENTITY: Private Limited Company
  authority: RJSC (Registrar of Joint Stock Companies)
  minimum_directors: 2
  minimum_capital: 1 lakh BDT
  forms_required: Form I, Form IX, Form XII, Form III, Form VI
  prerequisites: Name clearance, TIN, registered office address

ENTITY: Partnership Firm
  authority: RJSC
  minimum_partners: 2
  forms_required: Form I (Partnership Act)
  prerequisites: Partnership deed, TIN of all partners

ENTITY: Sole Proprietorship
  authority: City Corporation (Trade License only)
  no_rjsc_registration: true
  requires: Trade License, TIN, bank account

ENTITY: NGO/Society
  authority: Department of Social Services / NGO Affairs Bureau
  forms_required: Society Registration Form
  prerequisites: Constitution/bylaws, founding members list
"""

# ── Session management ────────────────────────────────────

def read_session() -> dict:
    if not SESSION_FILE.exists():
        return {}
    data = {}
    for line in SESSION_FILE.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line.startswith("- ") and ": " in line:
            key, _, val = line[2:].partition(": ")
            data[key.strip()] = val.strip()
    return data

def write_session(data: dict):
    lines = ["# ROC Bangladesh - Session", "",
             f"- last_updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    for k, v in data.items():
        if k != "last_updated":
            lines.append(f"- {k}: {v}")
    SESSION_FILE.write_text("\n".join(lines), encoding="utf-8")

def update_session(updates: dict):
    data = read_session()
    data.update({k: v for k, v in updates.items() if v})
    write_session(data)

# ── Conversation history ──────────────────────────────────

def build_history(session: dict) -> list[dict]:
    """Session theke conversation history reconstruct koro"""
    history = []
    if session.get("conversation_log"):
        try:
            history = json.loads(session["conversation_log"])
        except:
            pass
    return history

def save_history(history: list[dict], session: dict):
    session["conversation_log"] = json.dumps(history[-20:], ensure_ascii=False)
    write_session(session)

# ── Main agent ────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are a Bangladesh business registration assistant. You help people register their businesses.

You speak both Bangla and English - match the user's language.

KNOWLEDGE BASE:
{ENTITY_KNOWLEDGE}

YOUR BEHAVIOR:
1. Ask natural conversational questions to understand the business
2. Use chain of thought to determine:
   - What type of entity they need (sole proprietorship, partnership, private limited, NGO)
   - What documents/forms they need
   - What steps to follow
3. Guide them step by step
4. Extract and remember: business_type, business_name, location, partners, capital, owner_name, phone

RESPONSE FORMAT:
Always respond with JSON:
{{
  "message": "your conversational response to user (in their language)",
  "thinking": "your chain of thought reasoning (English, brief)",
  "extracted": {{
    "key": "value"
  }},
  "phase": "current phase: discovery|entity_determination|requirements|action",
  "next_question": "what to ask next (optional)",
  "action": "none|show_requirements|start_forms|complete"
}}

PHASES:
- discovery: learning about the business
- entity_determination: figuring out what legal entity they need
- requirements: explaining what documents/forms needed
- action: directing to specific tools/forms
"""

def chat(user_msg: str, history: list[dict], session: dict) -> dict:
    """Single turn conversation"""
    # Build messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add session context
    session_ctx = {k: v for k, v in session.items()
                   if k not in ["last_updated", "conversation_log"]}
    if session_ctx:
        messages.append({
            "role": "system",
            "content": f"Already known about user: {json.dumps(session_ctx, ensure_ascii=False)}"
        })

    # Add history
    messages.extend(history[-10:])

    # Add current message
    messages.append({"role": "user", "content": user_msg})

    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=500,
        messages=messages,
        response_format={"type": "json_object"}
    )

    return json.loads(resp.choices[0].message.content)

def handle_action(action: str, session: dict):
    """Action based on agent decision"""
    if action == "show_requirements":
        btype = session.get("business_type", "")
        if btype == "sole_proprietorship":
            print("\n  [REQUIREMENTS]")
            print("  1. Trade License (City Corporation)")
            print("  2. TIN Certificate (NBR)")
            print("  3. Bank Account")
            print("  No RJSC registration needed.\n")
        elif btype in ["private_limited", "partnership", "ngo"]:
            print(f"\n  [REQUIREMENTS] Run: python form_agent.py\n")

    elif action == "start_forms":
        print("\n  [ACTION] Run: python form_agent.py")
        print("  This will guide you through filling all required forms.\n")

    elif action == "complete":
        print("\n  [DONE] All steps identified. Check session.md for summary.\n")

# ── Main ──────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  ROC Bangladesh - Business Registration Assistant")
    print("  (type 'exit' to quit | 'status' to see session)")
    print("=" * 60)

    session = read_session()
    history = build_history(session)

    # Resume or start fresh
    if session and session.get("phase") not in [None, "", "discovery"]:
        print(f"\n  Resuming session (phase: {session.get('phase', 'discovery')})")
        known = {k: v for k, v in session.items()
                 if k not in ["last_updated", "conversation_log", "phase"]}
        if known:
            print(f"  Known: {', '.join([f'{k}={v}' for k, v in known.items()])}")
        print()
    else:
        # Fresh start
        print("\n  Assistant: Welcome! What kind of business are you starting or do you already have?\n")

    while True:
        try:
            user_input = input("  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Session saved. Goodbye.")
            break

        if not user_input:
            continue

        if user_input.lower() == "exit":
            print("  Session saved. Goodbye.")
            break

        if user_input.lower() == "status":
            print("\n  --- Session ---")
            for k, v in session.items():
                if k != "conversation_log":
                    print(f"  {k}: {v}")
            print()
            continue

        if user_input.lower() == "reset":
            SESSION_FILE.unlink(missing_ok=True)
            session = {}
            history = []
            print("  Session reset.\n")
            continue

        # Get agent response
        try:
            result = chat(user_input, history, session)
        except Exception as e:
            print(f"  [Error] {e}\n")
            continue

        # Hook: search_agent call for legal info if needed
        from search_agent import hook_handler
        hook_result = hook_handler("user_message", {"message": user_input})
        if hook_result:
            result["message"] = result.get("message", "") + f"\n\n  [আইনি তথ্য]\n  {hook_result}"
        message   = result.get("message", "")
        thinking  = result.get("thinking", "")
        extracted = result.get("extracted", {})
        phase     = result.get("phase", "discovery")
        action    = result.get("action", "none")

        # Update history
        history.append({"role": "user",      "content": user_input})
        history.append({"role": "assistant", "content": message})

        # Update session
        updates = extracted.copy()
        updates["phase"] = phase
        update_session(updates)
        session.update(updates)
        save_history(history, session)

        # Print response
        print(f"\n  Assistant: {message}\n")

        # Show thinking in debug mode
        if os.getenv("DEBUG") == "1" and thinking:
            print(f"  [thinking] {thinking}\n")

        # Handle action
        if action and action != "none":
            handle_action(action, session)

        if action == "complete":
            break

if __name__ == "__main__":
    main()
