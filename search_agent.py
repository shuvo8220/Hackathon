"""
ROC Bangladesh - Search Agent
================================
- output/ folder theke act sections search kore (tool)
- agent.py er hook er satha connect hoy
- Sob answer Bangla te dey
- User er intent moto relevant legal info ane

Run: python search_agent.py
Or import as tool: from search_agent import search_tool, ask_search_agent
"""

import os
import json
import re
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

BASE_DIR    = Path(__file__).parent
OUTPUT_DIR  = BASE_DIR / "output" / "output"
SESSION_FILE = BASE_DIR / "session.md"

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL  = "gpt-4o-mini"

# ── Load all sections index ───────────────────────────────

_sections_cache = None

def load_sections_index() -> list[dict]:
    """Sob act section load kore cache kore"""
    global _sections_cache
    if _sections_cache is not None:
        return _sections_cache

    sections = []
    for act_dir in OUTPUT_DIR.iterdir():
        if not act_dir.is_dir():
            continue
        for chapter_dir in act_dir.iterdir():
            if not chapter_dir.is_dir():
                continue
            for sec_file in chapter_dir.glob("section_*.json"):
                try:
                    data = json.loads(sec_file.read_text(encoding="utf-8"))
                    sections.append({
                        "chunk_id":      data.get("chunk_id", ""),
                        "act_name":      data.get("act_name", ""),
                        "section_number": str(data.get("section_number", "")),
                        "section_title": data.get("section_title", ""),
                        "content":       data.get("content", ""),
                        "keywords":      data.get("keywords", []),
                    })
                except:
                    pass

    _sections_cache = sections
    return sections

# ── Search tool ───────────────────────────────────────────

def search_tool(query: str, top_k: int = 5) -> list[dict]:
    """
    User query theke relevant act sections search kore return kore.
    Keyword-based search with scoring.
    """
    sections = load_sections_index()
    query_words = re.findall(r"[a-zA-Z\u0980-\u09FF]+", query.lower())

    scored = []
    for sec in sections:
        score = 0
        content_lower = sec["content"].lower()
        title_lower   = sec["section_title"].lower()
        keywords      = [k.lower() for k in sec["keywords"]]

        for word in query_words:
            if word in title_lower:
                score += 3
            if word in content_lower:
                score += 1
            if word in keywords:
                score += 2

        if score > 0:
            scored.append((score, sec))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:top_k]]

# ── Session reader ────────────────────────────────────────

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

# ── OpenAI tool definition ────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_act_sections",
            "description": "Bangladesh er act/law theke relevant sections search kore. Company registration, trade license, partnership, NGO related legal info ane.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query - English or Bangla keywords"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default 3)",
                        "default": 3
                    }
                },
                "required": ["query"]
            }
        }
    }
]

def run_tool(tool_name: str, tool_args: dict) -> str:
    """Tool execute kore result return kore"""
    if tool_name == "search_act_sections":
        query = tool_args.get("query", "")
        top_k = tool_args.get("top_k", 3)
        results = search_tool(query, top_k)
        if not results:
            return "কোনো প্রাসঙ্গিক আইনি তথ্য পাওয়া যায়নি।"
        output = []
        for r in results:
            output.append(
                f"আইন: {r['act_name']}\n"
                f"ধারা {r['section_number']}: {r['section_title']}\n"
                f"{r['content'][:400]}"
            )
        return "\n\n---\n\n".join(output)
    return "Tool not found."

# ── Main agent ────────────────────────────────────────────

SYSTEM_PROMPT = """আপনি বাংলাদেশ ব্যবসা নিবন্ধন বিশেষজ্ঞ। আপনি সবসময় বাংলায় উত্তর দেন।

আপনার কাছে একটি tool আছে: search_act_sections
- এই tool দিয়ে বাংলাদেশের আইন থেকে প্রাসঙ্গিক ধারা খুঁজে আনতে পারেন
- যখনই legal requirement, form, বা process সম্পর্কে প্রশ্ন আসে, tool use করুন

আপনি যা করবেন:
1. User এর প্রশ্ন বুঝুন
2. প্রয়োজনে tool দিয়ে আইনি তথ্য খুঁজুন
3. সহজ বাংলায় উত্তর দিন
4. Step by step গাইড করুন

Session থেকে user সম্পর্কে যা জানা আছে তা ব্যবহার করুন।"""

def ask_search_agent(user_query: str, session: dict = None) -> str:
    """
    Search agent কে query করো।
    Hook হিসেবে agent.py থেকে call করা যাবে।
    """
    if session is None:
        session = read_session()

    session_ctx = {k: v for k, v in session.items()
                   if k not in ["last_updated", "conversation_log"]}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    if session_ctx:
        messages.append({
            "role": "system",
            "content": f"User সম্পর্কে জানা তথ্য: {json.dumps(session_ctx, ensure_ascii=False)}"
        })

    messages.append({"role": "user", "content": user_query})

    # First call - may use tool
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        max_tokens=800
    )

    msg = response.choices[0].message

    # Handle tool calls
    if msg.tool_calls:
        messages.append({"role": "assistant", "content": msg.content, "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]})

        for tc in msg.tool_calls:
            args   = json.loads(tc.function.arguments)
            result = run_tool(tc.function.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result
            })

        # Final response after tool use
        final = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=800
        )
        return final.choices[0].message.content.strip()

    return msg.content.strip() if msg.content else "দুঃখিত, উত্তর দিতে পারছি না।"

# ── Hook connector ────────────────────────────────────────

def hook_handler(event: str, data: dict) -> str:
    """
    agent.py থেকে hook event receive করে।
    event: "user_message", "phase_change", "info_extracted"
    """
    session = read_session()

    if event == "user_message":
        query = data.get("message", "")
        return ask_search_agent(query, session)

    elif event == "phase_change":
        phase = data.get("phase", "")
        if phase == "requirements":
            btype = session.get("business_type", "")
            query = f"{btype} registration requirements Bangladesh"
            return ask_search_agent(query, session)

    elif event == "info_extracted":
        # New info extracted - update context
        return ""

    return ""

# ── CLI mode ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  ROC Bangladesh - Search Agent (বাংলা)")
    print("  আইনি তথ্য খোঁজার জন্য প্রশ্ন করুন")
    print("  (exit লিখে বের হন)")
    print("=" * 60)

    session = read_session()
    print(f"\n  {len(load_sections_index())} টি আইনি ধারা লোড হয়েছে\n")

    while True:
        try:
            query = input("  আপনি: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not query or query.lower() == "exit":
            break

        print("\n  অনুসন্ধান করছি...")
        answer = ask_search_agent(query, session)
        print(f"\n  এজেন্ট: {answer}\n")

if __name__ == "__main__":
    main()
