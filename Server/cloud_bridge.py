import time
import threading
import requests
import os
import traceback
import json
import base64
import re
import concurrent.futures
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
from dotenv import load_dotenv

# Load local .env variables
load_dotenv()

app = Flask(__name__)

# --- SETTINGS ---
SECRET_KEY = "super-secret-key"
SCREENSHOT_DIR = "screenshots"

if not os.path.exists(SCREENSHOT_DIR):
    os.makedirs(SCREENSHOT_DIR)

DB_FILE = "database.json"

# --- MULTI-USER STATE ---
user_data = {}
answer_queue = {}
reconnect_queue = {}  # user_id -> True
heartbeats = {}  # user_id -> last_seen_timestamp
tg_users = {}  # user_id -> "@username" or "123456789" (Telegram user)

# --- PHOTO BUFFER (3-second server-side batching) ---
# {user_id: {"files": [...], "timer": threading.Timer}}
pending_uploads = {}

def load_data():
    global user_data, answer_queue
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                db = json.load(f)
                user_data = db.get("user_data", {})
                answer_queue = db.get("answer_queue", {})
                tg_users.update(db.get("tg_users", {}))
                print(f"[*] Data loaded from {DB_FILE}", flush=True)
        except Exception as e:
            print(f"[!] Error loading {DB_FILE}: {e}", flush=True)

def save_data():
    try:
        with open(DB_FILE, "w") as f:
            json.dump({
                "user_data": user_data,
                "answer_queue": answer_queue,
                "tg_users": tg_users
            }, f, indent=4)
    except Exception as e:
        print(f"[!] Error saving {DB_FILE}: {e}", flush=True)

load_data()

# --- TELEGRAM NOTIFICATIONS ---
def _build_tg_caption(user_id, task_type, answer_val, matches, subtype, reasoning, confidence, gpt_res=None, claude_res=None, verdict="—"):
    """Build a structured, premium Telegram caption for exam results."""
    LETTERS = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F"}
    tg_mention = tg_users.get(str(user_id), "").replace("_", "\\_")
    mention_line = f"\n👤 {tg_mention}" if tg_mention else ""
    
    conf_pct = int(round(confidence * 100))
    conf_char = "🟢" if conf_pct > 85 else "🟡" if conf_pct > 65 else "🔴"
    conf_bar = "█" * (conf_pct // 10) + "░" * (10 - conf_pct // 10)
    
    reasoning_esc = str(reasoning).replace("_", "\\_")
    
    # Pipeline Indicator
    pipeline_icon = "🧬" if "recon" in verdict or "hybrid" in verdict else "👁"
    pipeline_name = "Semantic Recon" if pipeline_icon == "🧬" else "Direct Vision"
    
    header = (
        f"📡 *NODE {user_id}* {mention_line}\n"
        f"{pipeline_icon} _Pipeline: {pipeline_name}_"
    )

    def _fmt_model(res, label):
        if not res or res.get("confidence", 0) <= 0:
            return f"{label}: ✗ —"
        t = res.get("type", "?")
        ans = res.get("answer", "?")
        if t == "drag":
            mx = res.get("matches", [])
            pairs = ",".join(f"{m.get('s')}→{m.get('d')}" for m in mx[:2])
            val = f"[{pairs}{'…' if len(mx)>2 else ''}]"
        elif t == "choice":
            val = f"{ans} ({LETTERS.get(ans, '?')})"
        else:
            val = str(ans)
        return f"{label}: *{val}*"

    gpt_line    = _fmt_model(gpt_res,    "🤖 GPT")
    claude_line = _fmt_model(claude_res, "🤖 CL")
    verdict_info = f"⚖️ *{verdict.upper()}*"

    # Task Header
    task_label = {
        "choice": "🎯 MULTIPLE CHOICE",
        "drag":   {
            "matching": "🔗 MATCHING", "ordering": "🔢 ORDERING",
            "fill_gap": "✏️ FILL GAP", "category": "📂 CATEGORY"
        }.get(subtype, "🖱 DRAG & DROP"),
        "number": "🔢 NUMERIC ANSWER"
    }.get(task_type, "❓ UNKNOWN")

    # Content building
    body = ""
    if task_type == "drag":
        sorted_m = sorted(matches or [], key=lambda x: x.get('d', 0))
        rows = "\n".join(f"  `Slot {m.get('d')}` ← *Item {m.get('s')}*" for m in sorted_m)
        body = f"{rows}\n"
    elif task_type == "number":
        body = f"   Ответ: `{answer_val}`\n"
    else:  # choice
        letter = LETTERS.get(answer_val, "?")
        body = f"   ✅ *{letter}* (option {answer_val})\n"

    return (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"*{task_label}*\n\n"
        f"{body}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{gpt_line}  {claude_line}\n"
        f"Status: {verdict_info}\n"
        f"📊 `{conf_bar}` {conf_pct}% {conf_char}\n"
        f"🧠 _{reasoning_esc}_"
    )


def send_to_telegram(user_id, filepaths, task_type, answer_val, matches, subtype, reasoning, confidence, gpt_res=None, claude_res=None, verdict="—"):
    """Send screenshot(s) + structured AI result to Telegram."""
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return

    try:
        caption = _build_tg_caption(user_id, task_type, answer_val, matches, subtype, reasoning, confidence, gpt_res, claude_res, verdict)

        if isinstance(filepaths, str):
            filepaths = [filepaths]

        if len(filepaths) == 1:
            with open(filepaths[0], "rb") as photo:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
                    files={"photo": photo},
                    timeout=15
                )
                print(f"[TG] Single photo status: {r.status_code}", flush=True)
        else:
            media = []
            files = {}
            for i, fp in enumerate(filepaths):
                field = f"photo_{i}"
                files[field] = open(fp, "rb")
                item = {"type": "photo", "media": f"attach://{field}"}
                if i == 0:
                    item["caption"] = caption
                    item["parse_mode"] = "Markdown"
                media.append(item)
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMediaGroup",
                data={"chat_id": chat_id, "media": json.dumps(media)},
                files=files,
                timeout=30
            )
            print(f"[TG] Media group status: {r.status_code}", flush=True)
            for f in files.values():
                f.close()

        print(f"[TG] Sent to Telegram for user {user_id} ({len(filepaths)} photo(s))", flush=True)
    except Exception as e:
        print(f"[!] Telegram error: {e}", flush=True)

def get_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

@app.route("/ping", methods=["GET"])
def ping():
    """Heartbeat from ESP32."""
    user_id = request.args.get("user_id")
    rssi = request.args.get("rssi")
    if user_id:
        heartbeats[user_id] = time.time()
        if user_id not in user_data:
            user_data[user_id] = {"history": []}
        if rssi:
            user_data[user_id]["rssi"] = int(rssi)
    return jsonify({"status": "alive"}), 200

@app.route("/poll", methods=["GET"])
def poll():
    """ESP32 calls this to get pending answers. Pops the first command from the user's queue."""
    if request.headers.get("X-Secret") != SECRET_KEY:
        # Check query param if header is missing for easier testing
        if request.args.get("secret") != SECRET_KEY:
            return "Unauthorized", 401
    
    user_id = request.args.get("user_id")
    rssi = request.args.get("rssi")
    ssid = request.args.get("ssid", "").replace("%20", " ")
    if not user_id:
        return "Missing user_id", 400
    
    uid = str(user_id)
    heartbeats[uid] = time.time()
    
    # Initialize user if not exists
    if uid not in user_data:
        user_data[uid] = {"history": [], "last_seen": "Never", "last_img": None}
    
    user_data[uid]["last_seen"] = time.strftime("%H:%M:%S")
    if rssi:
        user_data[uid]["rssi"] = int(rssi)
    if ssid:
        user_data[uid]["ssid"] = ssid

    # Check for pending reconnect command
    if reconnect_queue.pop(uid, None):
        print(f"[*] Sending reconnect command to Node {uid}", flush=True)
        return jsonify({"count": 0, "count2": 0, "cmd_id": 0, "reconnect": True}), 200
    
    # answer_queue[user_id] is now a list
    queue = answer_queue.get(user_id, [])
    if not isinstance(queue, list):
        queue = []

    if queue:
        # Take the first command
        data = queue.pop(0)
        count = data.get("count", 0)
        count2 = data.get("count2", 0)
        cmd_id = data.get("cmd_id", 0)
        
        answer_queue[user_id] = queue
        save_data()
        print(f"[*] Polled User {user_id}: {count}/{count2} (Remaining: {len(queue)})", flush=True)
        return jsonify({"count": count, "count2": count2, "cmd_id": cmd_id}), 200
    
    return jsonify({"count": 0, "count2": 0, "cmd_id": 0}), 200

@app.route("/esp_report", methods=["POST"])
def esp_report():
    """Receives debug info from ESP32."""
    if request.headers.get("X-Secret") != SECRET_KEY:
        return "Unauthorized", 401
    
    data = request.json
    uid = str(data.get("user_id"))
    rssi = data.get("rssi")
    
    heartbeats[uid] = time.time()
    if uid not in user_data:
        user_data[uid] = {"history": [], "last_seen": get_now(), "last_img": None}
    
    if rssi:
        user_data[uid]["rssi"] = int(rssi)
        
    print(f"[*] Report from Node {uid}: {data.get('action')} (RSSI: {rssi})", flush=True)
    return "OK", 200


# ─── SEMANTIC RECONSTRUCTION PROMPTS ─────────────────────────────────────────

def _build_reconstruction_prompt(n_images):
    """Prompt for GPT-4o to extract ONLY the structure of the exam page."""
    prefix = (
        f"You are a PAGE SCANNER. Your ONLY job is to extract structure from {n_images} screenshot(s) "
        f"that may show different parts of the SAME question. Study ALL images together.\n"
        "Do NOT solve the question. Do NOT guess answers.\n\n"
    ) if n_images > 1 else "You are a PAGE SCANNER. Extract structure from the screenshot. Do NOT solve/guess.\n\n"

    return (
        prefix +
        "═══ TASK: EXTRACT ELEMENTS ═══\n"
        "1. questionText: Full text of the question (copy verbatim, no matter the language)\n"
        "2. taskType: Pick ONE: 'choice' | 'drag' | 'number'\n"
        "3. For 'choice': list all radio/checkbox options (index 1=A, 2=B...):\n"
        "   options: [{\"id\": 1, \"text\": \"...\"}]\n"
        "4. For 'drag': list all SLOTS (drop zones, top-to-bottom) and ITEMS (draggable, left-to-right):\n"
        "   slots: [{\"id\": 1, \"label\": \"...\"}]\n"
        "   items: [{\"id\": 1, \"text\": \"...\"}]\n"
        "5. subtype: 'matching' | 'ordering' | 'fill_gap' | 'category' | 'n/a'\n\n"

        "═══ RULES ═══\n"
        "• Copy text EXACTLY — include typos or symbols\n"
        "• For 'drag': slot ID d=1,2,3... top-to-bottom; item ID s=1,2,3... left-to-right\n"
        "• If a button has no text, describe its icon in brackets: [plus icon]\n"
        "• Respond ONLY with raw JSON:\n\n"
        "{\"taskType\": \"choice|drag|number\", \"subtype\": \"...\", \"questionText\": \"...\", "
        "\"options\": [], \"slots\": [], \"items\": []}"
    )

def _build_reasoning_prompt(digital_twin):
    """Prompt for Claude to solve the logical task based on extracted structure."""
    dt_json = json.dumps(digital_twin, ensure_ascii=False, indent=2)
    return (
        "You are an EXPERT EXAMINER. A page scanner already extracted the question structure. "
        "Your job is to solve it correctly.\n\n"
        f"═══ QUESTION STRUCTURE ═══\n{dt_json}\n\n"

        "═══ SOLVING RULES ═══\n"
        "• 'choice': Pick the correct option. Put its id (1, 2, 3...) in 'answer'.\n"
        "• 'drag': Match every slot to the best item. Output 'matches': [{\"s\": item_id, \"d\": slot_id}].\n"
        "  - Use each item ONLY ONCE unless it's a category task.\n"
        "  - If no match fits a slot, set s=0.\n"
        "• 'number': Calculate the correct integer and put it in 'answer'.\n\n"

        "═══ QUALITY ═══\n"
        "• Watch for 'NOT' or 'НЕ' in questions — think carefully.\n"
        "• 'confidence': 0.0 to 1.0 (your real certainty).\n"
        "• 'reasoning': 2-6 words in RUSSIAN.\n\n"
        "Respond ONLY with raw JSON:\n"
        "{\"type\": \"choice|drag|number\", \"subtype\": \"...\", \"answer\": <int>, "
        "\"confidence\": <float>, \"reasoning\": \"...\", "
        "\"matches\": [{\"s\": <int>, \"d\": <int>}]}"
    )

# Old prompt kept for legacy fallback
def _build_exam_prompt(n_images):
    """Old prompt for legacy direct vision fallback."""
    prefix = (
        f"You are an expert exam analyst examining {n_images} screenshot(s). "
    ) if n_images > 1 else "You are an expert exam analyst. "
    return prefix + "Analyze the question and return raw JSON: {\"type\": \"choice|drag|number\", \"answer\": <int>, \"confidence\": <float>, \"reasoning\": \"...\", \"matches\": []}"

def _parse_ai_json(raw_text):
    """Extract and parse JSON from raw AI response text."""
    m = re.search(r'\{.*\}', raw_text, re.DOTALL)
    return json.loads((m.group(0) if m else raw_text).strip())

# ─── SEMANTIC RECONSTRUCTOR AI CALLS ─────────────────────────────────────────

def call_gpt_reconstructor(filepaths):
    """GPT-4o Vision: Extracts structure (digital twin) from screenshots."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model   = os.environ.get("OPENAI_MODEL", "gpt-4o").strip()
    if not api_key: return None, "No API key"
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        content = []
        for fp in filepaths:
            with open(fp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}})
        content.append({"type": "text", "text": _build_reconstruction_prompt(len(filepaths))})
        
        resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": content}], max_tokens=1024)
        parsed = _parse_ai_json(resp.choices[0].message.content.strip())
        print(f"[GPT-Reconfig] Extracted structure for {len(filepaths)} images", flush=True)
        return parsed, None
    except Exception as e:
        print(f"[!] Reconstructor Error: {e}", flush=True)
        return None, str(e)

def call_claude_reasoner(digital_twin):
    """Claude 3.5 Sonnet: Solves the task based on TEXT structure (no vision)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip().replace('"','').replace("'","")
    model   = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20240620").strip()
    if not api_key or api_key == "your_key_here": return None, "No API key"
    try:
        import anthropic as anthropic_sdk
        client = anthropic_sdk.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model, max_tokens=1024,
            messages=[{"role": "user", "content": _build_reasoning_prompt(digital_twin)}]
        )
        parsed = _parse_ai_json(message.content[0].text.strip())
        print(f"[Claude-Reasoner] Solved based on twin. Conf={parsed.get('confidence')}", flush=True)
        return parsed, None
    except Exception as e:
        print(f"[!] Reasoner Error: {e}", flush=True)
        return None, str(e)

def call_claude_reasoner_with_image(filepaths, digital_twin):
    """Claude 3.5 Sonnet: Solves task seeing BOTH the image and the extracted structure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip().replace('"','').replace("'","")
    model   = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20240620").strip()
    if not api_key: return None, "No API key"
    try:
        import anthropic as anthropic_sdk
        client = anthropic_sdk.Anthropic(api_key=api_key)
        content = []
        for fp in filepaths:
            with open(fp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
        
        prompt = (
            "You are an EXPERT JUDGE. You have both the screenshot and a structured 'digital twin' "
            "representation of the question.\n\n"
            f"DIGITAL TWIN:\n{json.dumps(digital_twin, ensure_ascii=False, indent=2)}\n\n"
            "If the digital twin is accurate, use it to solve. If it missed something, use the image. "
            "Output final answer in standard JSON format."
        )
        content.append({"type": "text", "text": prompt})
        
        message = client.messages.create(model=model, max_tokens=1024, messages=[{"role": "user", "content": content}])
        parsed = _parse_ai_json(message.content[0].text.strip())
        print(f"[Claude-Hybrid] Verified answer. Conf={parsed.get('confidence')}", flush=True)
        return parsed, None
    except Exception as e:
        print(f"[!] Hybrid Error: {e}", flush=True)
        return None, str(e)

# ─── LEGACY VISION CALLS ─────────────────────────────────────────────────────

def call_gpt_vision(filepaths):
    """Send images to GPT-4o Vision and return parsed JSON dict (Legacy)."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model   = os.environ.get("OPENAI_MODEL", "gpt-4o").strip()
    if not api_key: return None, "No API key"
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        content = []
        for fp in filepaths:
            with open(fp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}})
        content.append({"type": "text", "text": _build_exam_prompt(len(filepaths))})
        resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": content}], max_tokens=1024)
        return _parse_ai_json(resp.choices[0].message.content.strip()), None
    except Exception as e:
        return None, str(e)

def call_claude_vision(filepaths):
    """Send images to Claude Vision and return parsed JSON dict (Legacy)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip().replace('"','').replace("'","")
    model   = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20240620").strip()
    if not api_key: return None, "No API key"
    try:
        import anthropic as anthropic_sdk
        client = anthropic_sdk.Anthropic(api_key=api_key)
        content = []
        for fp in filepaths:
            with open(fp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
        content.append({"type": "text", "text": _build_exam_prompt(len(filepaths))})
        message = client.messages.create(model=model, max_tokens=1024, messages=[{"role": "user", "content": content}])
        return _parse_ai_json(message.content[0].text.strip()), None
    except Exception as e:
        return None, str(e)

# ─── LEGACY VERIFIER ─────────────────────────────────────────────────────────

def call_gpt_verifier(filepaths, gpt_result, claude_result):
    """GPT receives both answers + images, compares, and returns the best final JSON (Legacy)."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model   = os.environ.get("OPENAI_MODEL", "gpt-4o").strip()
    if not api_key: return None, "No API key"
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        content = []
        for fp in filepaths:
            with open(fp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}})
        
        prompt = (
            "Final judge for exam question. Compare Model A and B.\n"
            f"A: {json.dumps(gpt_result)}\nB: {json.dumps(claude_result)}\n"
            "Return best JSON."
        )
        content.append({"type": "text", "text": prompt})
        resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": content}], max_tokens=1024)
        return _parse_ai_json(resp.choices[0].message.content.strip()), None
    except Exception as e:
        return None, str(e)

# ─── MAIN BATCH PROCESSOR ────────────────────────────────────────────────────
def process_batch(user_id, filepaths, ts):
    """Semantic Reconstruction: GPT (Eyes) -> Claude (Brain) pipeline."""
    print(f"[*] Processing batch for User {user_id}: {len(filepaths)} photo(s)", flush=True)

    tg_answer  = "Error"
    reasoning  = "AI pipeline failed"
    confidence = 0.0
    user_queue = []
    final = None
    gpt_r = None
    claude_r = None
    verdict = "—"

    # ── Step 1: GPT Reconstruction (Digital Twin) ────────────────────────────
    twin, twin_err = call_gpt_reconstructor(filepaths)
    
    if twin:
        # ── Step 2: Claude Reasoning (Text-only) ─────────────────────────────
        final, cl_err = call_claude_reasoner(twin)
        
        if final:
            reasoning = final.get("reasoning", "OK")
            confidence = final.get("confidence", 0.0)
            verdict = "recon_solved"

            # ── Step 3: Optional Hybrid Verification if confidence is low ────
            if confidence < 0.75:
                verified, v_err = call_claude_reasoner_with_image(filepaths, twin)
                if verified and verified.get("confidence", 0.0) > confidence:
                    final = verified
                    confidence = final.get("confidence", 0.0)
                    verdict = "hybrid_verified"
                    print(f"[*] Hybrid upgrade: confidence {confidence}", flush=True)
        else:
            reasoning = f"Reasoner fail: {cl_err}"
    else:
        # ── FALLBACK: Old Parallel Vision Method ─────────────────────────────
        print(f"[!] Reconstructor failed ({twin_err}), falling back to direct vision", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fut_gpt    = pool.submit(call_gpt_vision,    filepaths)
            fut_claude = pool.submit(call_claude_vision, filepaths)
            gpt_r, gpt_err = fut_gpt.result()
            claude_r, cl_err = fut_claude.result()
        
        # Use simple fallback selection
        if claude_r and claude_r.get("confidence", 0) > 0.5:
            final = claude_r
            verdict = "direct_claude"
        elif gpt_r:
            final = gpt_r
            verdict = "direct_gpt"
        else:
            reasoning = f"Fallback fail: GPT={gpt_err}, CL={cl_err}"

    # ── Step 4: Build answer queue and notify ────────────────────────────────
    if final:
        task_type = final.get("type", "choice")
        confidence = final.get("confidence", 0.0)
        
        if task_type == "drag":
            matches = final.get("matches", [])
            sorted_matches = sorted(matches, key=lambda x: x.get('d', 0))
            for i, m in enumerate(sorted_matches):
                user_queue.append({"count": m.get("s", 0), "count2": 0, "cmd_id": ts + i})
            tg_answer = "\n".join([f"{m.get('d')}) {m.get('s')}" for m in sorted_matches])
        elif task_type == "number":
            answer_val = final.get("answer", 0)
            user_queue.append({"count": answer_val, "count2": 0, "cmd_id": ts, "is_num": True})
            tg_answer = str(answer_val)
        else:
            answer_val = final.get("answer", 0)
            user_queue.append({"count": answer_val, "count2": 0, "cmd_id": ts})
            letters = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F"}
            tg_answer = f"{answer_val} ({letters.get(answer_val, '?')})"

        answer_queue[user_id] = user_queue
        print(f"[Final] User {user_id} -> {tg_answer} (Verdict: {verdict})", flush=True)

    # Legacy formatting for TG
    if user_id not in user_data: user_data[user_id] = {"history": []}
    filenames = [os.path.basename(f) for f in filepaths]
    
    user_data[user_id]["history"].append({
        "timestamp": get_now(), "filenames": filenames,
        "task_type": final.get("type", "choice") if final else "err",
        "answer": tg_answer, "reasoning": reasoning,
        "confidence": confidence, "verdict": verdict,
        "twin": twin  # Save digital twin for dashboard visualization
    })
    
    # Small wrapper to call TG with minimal arguments for now or keep old signature
    send_to_telegram(
        user_id, filepaths, 
        final.get("type", "choice") if final else "choice",
        final.get("answer", 0) if final else 0,
        final.get("matches", []) if final else [],
        final.get("subtype", "n/a") if final else "n/a",
        reasoning, confidence,
        gpt_res=gpt_r, claude_res=claude_r, verdict=verdict
    )
    save_data()

@app.route("/reconnect", methods=["POST"])
def reconnect_node():
    """Queue a reconnect command for the specified node."""
    data = request.json or {}
    if SECRET_KEY and data.get("secret") != SECRET_KEY:
        if request.headers.get("X-Secret") != SECRET_KEY:
            return "Unauthorized", 401
    user_id = str(data.get("user_id"))
    reconnect_queue[user_id] = True
    print(f"[*] Reconnect queued for Node {user_id}", flush=True)
    return jsonify({"status": "queued"}), 200

@app.route("/vibrate", methods=["POST"])
def vibrate():
    """Manually add a vibration command to the queue."""
    if SECRET_KEY and request.headers.get("X-Secret") != SECRET_KEY:
        # Check either header or JSON secret for flexibility from browser
        data = request.json or {}
        if data.get("secret") != SECRET_KEY:
            return "Unauthorized", 401

    data = request.json
    user_id = str(data.get("user_id"))
    count = int(data.get("count", 1))
    
    if user_id not in answer_queue:
        answer_queue[user_id] = []
    
    # Priority vibration: insert at front
    answer_queue[user_id].insert(0, {"count": count, "count2": 0, "cmd_id": int(time.time())})
    save_data()
    print(f"[*] Manual Vibrate: User {user_id} (count={count})", flush=True)
    return jsonify({"status": "queued"}), 200


@app.route("/set_tg_user", methods=["POST"])
def set_tg_user():
    """Map a node ID to a Telegram username or user ID for group mentions."""
    data = request.json or {}
    if SECRET_KEY and data.get("secret") != SECRET_KEY:
        if request.headers.get("X-Secret") != SECRET_KEY:
            return "Unauthorized", 401
    node_id = str(data.get("node_id", ""))
    tg_user = str(data.get("tg_user", "")).strip()
    if not node_id:
        return jsonify({"error": "Missing node_id"}), 400
    if tg_user:
        tg_users[node_id] = tg_user
    else:
        tg_users.pop(node_id, None)  # clear mapping if empty
    save_data()
    print(f"[*] TG user for Node {node_id} set to: {tg_user!r}", flush=True)
    return jsonify({"status": "ok", "node_id": node_id, "tg_user": tg_user}), 200


@app.route("/tg_users", methods=["GET"])
def get_tg_users():
    """Return current node -> Telegram user mapping."""
    return jsonify(tg_users), 200


@app.route("/upload", methods=["POST"])
def upload():
    """Receives a photo from the agent. Buffers for 3s, then processes all."""
    user_id = request.headers.get("X-User-Id", "1")
    rssi = request.headers.get("X-RSSI")
    print(f"[*] Received upload from User {user_id} (RSSI: {rssi})", flush=True)

    if SECRET_KEY and request.headers.get("X-Secret") != SECRET_KEY:
        return "Unauthorized", 401

    if "file" not in request.files:
        return "No file", 400

    file = request.files["file"]
    if file.filename == "":
        return "No filename", 400

    ts = int(time.time())
    filename = f"user_{user_id}_{ts}.jpg"
    filepath = os.path.join(SCREENSHOT_DIR, filename)

    try:
        file.save(filepath)

        if user_id not in user_data:
            user_data[user_id] = {"history": []}
        user_data[user_id]["last_img"] = filename
        user_data[user_id]["last_seen"] = get_now()
        if rssi:
            user_data[user_id]["rssi"] = int(rssi)

        # --- 3-second batch buffer ---
        if user_id in pending_uploads and pending_uploads[user_id]["timer"] is not None:
            pending_uploads[user_id]["timer"].cancel()  # Reset timer
        
        if user_id not in pending_uploads:
            pending_uploads[user_id] = {"files": [], "timer": None}
        
        pending_uploads[user_id]["files"].append(filepath)
        files_snapshot = pending_uploads[user_id]["files"]
        batch_ts = ts

        def fire():
            batch_files = pending_uploads.pop(user_id, {}).get("files", [filepath])
            process_batch(user_id, batch_files, batch_ts)

        timer = threading.Timer(3.0, fire)
        pending_uploads[user_id]["timer"] = timer
        timer.start()
        print(f"[*] Buffered photo {len(pending_uploads[user_id]['files'])} for User {user_id}, waiting 3s...", flush=True)
        # --------------------------------

        return jsonify({"user_id": user_id, "status": "buffered"}), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "info": str(e)}), 500

# --- DASHBOARD ROUTES ---

@app.route("/dashboard")
def dashboard():
    now = time.time()
    all_users = {}
    for i in range(1, 16):
        uid = str(i)
        # Get base data
        base_data = user_data.get(uid, {"history": [], "last_seen": "Never", "last_img": None})
        data = base_data.copy()
        
        # Calculate ESP online status (active in last 12 seconds)
        last_poll = heartbeats.get(uid, 0)
        data["esp_online"] = (now - last_poll) < 12
        all_users[uid] = data
        
    return render_template("dashboard.html", users=all_users)

@app.route("/user/<user_id>")
def user_history(user_id):
    now = time.time()
    data = user_data.get(user_id, {"history": [], "last_seen": "Never", "last_img": None}).copy()
    data["esp_online"] = (now - heartbeats.get(user_id, 0)) < 12
    # Pass as 'users' dict so template can use users[uid]
    return render_template("user_history.html", uid=user_id, history=data.get("history", []), users={user_id: data})

@app.route("/screenshots/<path:filename>")
def serve_screenshot(filename):
    return send_from_directory(SCREENSHOT_DIR, filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[*] Starting server on port {port}...", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
