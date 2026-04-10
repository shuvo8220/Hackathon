"""
ROC Bangladesh - Main Entry Point
===================================
Single command e sob connected:
  1. agent.py      - Conversational agent (intent + phase tracking)
  2. search_agent.py - Legal search tool (act sections)
  3. form_agent.py  - Form filling with AI guidance
  4. form_validator.py - Form validation against act

Run: python run.py
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ── Hook system ───────────────────────────────────────────

class HookSystem:
    """
    Sob agent er moddhe event pass kore.
    agent.py -> search_agent.py -> form_agent.py -> form_validator.py
    """
    def __init__(self):
        self._hooks = {}

    def register(self, event: str, handler):
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(handler)

    def emit(self, event: str, data: dict) -> list:
        results = []
        for handler in self._hooks.get(event, []):
            try:
                result = handler(event, data)
                if result:
                    results.append(result)
            except Exception as e:
                print(f"  [Hook error] {event}: {e}")
        return results

hooks = HookSystem()

# ── Register hooks ────────────────────────────────────────

def setup_hooks():
    from search_agent import hook_handler as search_hook

    # When user sends a message -> search agent looks for legal info
    hooks.register("user_message", search_hook)

    # When phase changes to requirements -> search agent fetches requirements
    hooks.register("phase_change", search_hook)

    # When info is extracted -> log it
    def log_hook(event, data):
        if event == "info_extracted" and data.get("extracted"):
            pass  # session.md already handles this
    hooks.register("info_extracted", log_hook)

# ── Patched agent chat ────────────────────────────────────

def run_agent_with_hooks():
    """agent.py run kore but hooks inject kore"""
    import agent
    from search_agent import ask_search_agent, load_sections_index

    # Pre-load sections
    print("  আইনি ডেটাবেস লোড হচ্ছে...")
    sections = load_sections_index()
    print(f"  {len(sections)} টি আইনি ধারা লোড হয়েছে\n")

    # Patch agent's chat loop to include hooks
    original_chat = agent.chat

    def hooked_chat(user_msg, history, session):
        result = original_chat(user_msg, history, session)

        # Fire hooks
        hook_results = hooks.emit("user_message", {"message": user_msg})

        # If search agent found legal info, append to response
        if hook_results:
            legal_info = hook_results[0]
            if legal_info and len(legal_info) > 20:
                result["legal_context"] = legal_info

        return result

    agent.chat = hooked_chat

    # Patch print_response to show legal context
    original_main = agent.main

    def patched_main():
        import agent as ag

        print("=" * 60)
        print("  ROC Bangladesh - সম্পূর্ণ নিবন্ধন সহায়তা")
        print("  (exit = বের হন | status = অবস্থা দেখুন | forms = ফর্ম পূরণ)")
        print("=" * 60)

        session = ag.read_session()
        history = ag.build_history(session)

        if not session.get("phase"):
            session["phase"] = "greeting"
            ag.write_session(session)
            print("\n  সহায়ক: স্বাগতম! আপনি কি ধরনের ব্যবসা শুরু করতে চান বা ইতিমধ্যে করছেন?\n")
        else:
            print(f"\n  পূর্বের সেশন থেকে চালু হচ্ছে (পর্যায়: {session.get('phase')})\n")

        while True:
            try:
                user_input = input("  আপনি: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  সেশন সংরক্ষিত হয়েছে। ধন্যবাদ।")
                break

            if not user_input:
                continue

            if user_input.lower() == "exit":
                print("  সেশন সংরক্ষিত হয়েছে। ধন্যবাদ।")
                break

            if user_input.lower() == "status":
                print("\n  --- বর্তমান সেশন ---")
                for k, v in session.items():
                    if k != "conversation_log":
                        print(f"  {k}: {v}")
                print()
                continue

            if user_input.lower() == "forms":
                print("\n  ফর্ম পূরণ শুরু হচ্ছে...")
                run_form_agent(session)
                continue

            if user_input.lower() == "validate":
                print("\n  যাচাইকরণ শুরু হচ্ছে...")
                run_validator()
                continue

            if user_input.lower() == "reset":
                ag.SESSION_FILE.unlink(missing_ok=True)
                session = {}
                history = []
                print("  সেশন রিসেট হয়েছে।\n")
                continue

            # Agent response
            try:
                result = hooked_chat(user_input, history, session)
            except Exception as e:
                print(f"  [ত্রুটি] {e}\n")
                continue

            message      = result.get("message", "")
            extracted    = result.get("extracted", {})
            phase        = result.get("phase", "discovery")
            action       = result.get("action", "none")
            legal_context = result.get("legal_context", "")

            # Update history + session
            history.append({"role": "user",      "content": user_input})
            history.append({"role": "assistant", "content": message})
            updates = extracted.copy()
            updates["phase"] = phase
            ag.update_session(updates)
            session.update(updates)
            ag.save_history(history, session)

            # Print response
            print(f"\n  সহায়ক: {message}\n")

            # Show legal context if available
            if legal_context:
                print(f"  [আইনি তথ্য] {legal_context[:300]}...\n" if len(legal_context) > 300 else f"  [আইনি তথ্য] {legal_context}\n")

            # Handle actions
            if action == "start_forms":
                print("  'forms' লিখুন ফর্ম পূরণ শুরু করতে।\n")
            elif action == "complete":
                print("  [সম্পন্ন] সব ধাপ চিহ্নিত হয়েছে।\n")
                break

    patched_main()

# ── Form agent runner ─────────────────────────────────────

def run_form_agent(session: dict = None):
    """form_agent.py er main() call kore"""
    import form_agent
    form_agent.main()

# ── Validator runner ──────────────────────────────────────

def run_validator():
    """form_validator.py er main() call kore"""
    import form_validator
    form_validator.main()

# ── Menu ──────────────────────────────────────────────────

def show_menu():
    print("\n" + "=" * 60)
    print("  ROC Bangladesh - নিবন্ধন সিস্টেম")
    print("=" * 60)
    print("\n  [1] সহায়ক এজেন্ট (Conversational Agent)")
    print("  [2] ফর্ম পূরণ (Form Filling)")
    print("  [3] আইনি যাচাই (Form Validation)")
    print("  [4] আইনি তথ্য অনুসন্ধান (Legal Search)")
    print("  [5] সম্পূর্ণ প্রক্রিয়া (Full Process - Recommended)")
    print("  [0] বের হন\n")
    return input("  নির্বাচন করুন: ").strip()

def main():
    setup_hooks()

    choice = show_menu()

    if choice == "1":
        import agent
        agent.main()

    elif choice == "2":
        import form_agent
        form_agent.main()

    elif choice == "3":
        run_validator()

    elif choice == "4":
        import search_agent
        search_agent.main()

    elif choice == "5":
        run_agent_with_hooks()

    elif choice == "0":
        print("  ধন্যবাদ।")
    else:
        print("  অবৈধ নির্বাচন।")

if __name__ == "__main__":
    main()
