import json

def _build_tg_caption(user_id, task_type, answer_val, matches, subtype, reasoning, confidence, gpt_res=None, claude_res=None, verdict="—"):
    """Copied from cloud_bridge.py for verification."""
    LETTERS = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F"}
    mention_line = ""
    conf_pct = int(round(confidence * 100))
    conf_bar = "█" * (conf_pct // 10) + "░" * (10 - conf_pct // 10)
    reasoning_esc = str(reasoning).replace("_", "\\_")

    header = f"📡 *NODE {user_id}*{mention_line}\n"

    def _fmt_model(res, label):
        if not res or res.get("confidence", 0) <= 0:
            return f"{label}: ✗ _No answer_"
        
        t = res.get("type", "?")
        ans = res.get("answer", "?")
        if t == "drag":
            mx = res.get("matches", [])
            pairs = ",".join(f"{m.get('s')}→{m.get('d')}" for m in mx[:2])
            val = f"[{pairs}{'…' if len(mx)>2 else ''}] (drag)"
        elif t == "choice":
            val = f"{ans} ({LETTERS.get(ans, '?')})"
        else:
            val = str(ans)
        
        re_msg = str(res.get("reasoning", "OK")).replace("_", "\\_")
        return f"{label}: *{val}* _({re_msg})_"

    gpt_line    = _fmt_model(gpt_res,    "🤖 GPT")
    claude_line = _fmt_model(claude_res, "🤖 CL")
    verdict_line = f"⚖️ Verdict: *{verdict}*"

    if task_type == "drag":
        subtype_label = "🖱 Drag & Drop"
        sorted_m = sorted(matches or [], key=lambda x: x.get('d', 0))
        rows = "\n".join(
            f"  `Slot {m.get('d')}` ← *Item {m.get('s')}*"
            for m in sorted_m
        )
        return (
            header +
            f"*{subtype_label}*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{rows}\n\n"
            f"{gpt_line}\n"
            f"{claude_line}\n"
            f"{verdict_line}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🧠 {reasoning_esc}\n"
            f"📊 `{conf_bar}` {conf_pct}%"
        )
    else:  # choice
        letter = LETTERS.get(answer_val, "?")
        return (
            header +
            f"*🎯 Multiple Choice*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"   ✅ *{letter}* (option {answer_val})\n\n"
            f"{gpt_line}\n"
            f"{claude_line}\n"
            f"{verdict_line}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🧠 {reasoning_esc}\n"
            f"📊 `{conf_bar}` {conf_pct}%"
        )

# Test case for choice
gpt_r = {"type": "choice", "answer": 2, "reasoning": "Looks like B", "confidence": 0.8}
claude_r = {"type": "choice", "answer": 2, "reasoning": "Clear B", "confidence": 0.9}
cap = _build_tg_caption(5, "choice", 2, [], "n/a", "Models agreed", 0.85, gpt_res=gpt_r, claude_res=claude_r, verdict="agreed")
print("--- CHOICE TEST ---")
print(cap)

# Test case for drag
gpt_r = {"type": "drag", "matches": [{"s": 1, "d": 2}, {"s": 3, "d": 1}], "reasoning": "Match items", "confidence": 0.7}
claude_r = {"type": "drag", "matches": [{"s": 1, "d": 2}], "reasoning": "Found one", "confidence": 0.3}
cap = _build_tg_caption(5, "drag", None, [{"s": 1, "d": 2}, {"s": 3, "d": 1}], "matching", "Synth result", 0.75, gpt_res=gpt_r, claude_res=claude_r, verdict="synthesized")
print("\n--- DRAG TEST ---")
print(cap)
