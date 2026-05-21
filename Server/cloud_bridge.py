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
def send_to_telegram(user_id, filepaths, answer_text, reasoning):
    """Send screenshot(s) + AI result to Telegram. Supports media groups for multiple images."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    
    try:
        # Escape underscores for Telegram Markdown (common cause of 400 Bad Request)
        tg_mention_escaped = tg_users.get(str(user_id), "").replace("_", "\\_")
        mention_line = f"\n👤 {tg_mention_escaped}" if tg_mention_escaped else ""
        
        reasoning_escaped = reasoning.replace("_", "\\_")
        
        caption = (
            f"📡 *NODE {user_id}*{mention_line}\n"
            f"✅ *Answer:* `{answer_text}`\n"
            f"🧠 *Reasoning:* {reasoning_escaped}"
        )

        if isinstance(filepaths, str):
            filepaths = [filepaths]

        if len(filepaths) == 1:
            # Single photo
            with open(filepaths[0], "rb") as photo:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
                    files={"photo": photo},
                    timeout=15
                )
                print(f"[TG] Single photo status: {r.status_code}, Response: {r.text}", flush=True)
        else:
            # Multiple photos — send as media group
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
            print(f"[TG] Media group status: {r.status_code}, Response: {r.text}", flush=True)
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


# ─── SHARED EXAM PROMPT ──────────────────────────────────────────────────────
def _build_exam_prompt(n_images):
    prefix = (
        f"You are an expert exam analyst examining {n_images} screenshot(s) "
        f"that may show different parts of the SAME question. Study ALL images together.\n\n"
    ) if n_images > 1 else "You are an expert exam analyst examining a screenshot of an exam question.\n\n"
    return (
        prefix +
        "═══ STEP 1 — IDENTIFY TASK TYPE ═══\n"
        "Carefully look at the interface and pick ONE type:\n"
        "  'choice'  — radio/checkbox options labeled A B C D E F (or 1 2 3 4 5)\n"
        "  'drag'    — any task where elements must be MOVED: matching pairs, ordering,\n"
        "              fill-in-the-blank with draggable tiles, sorting into categories\n"
        "  'number'  — open numeric input field (type a number as the answer)\n\n"

        "═══ STEP 2 — ANSWER RULES BY TYPE ═══\n\n"

        "FOR 'choice':\n"
        "  • Put the option index in 'answer': 1=A, 2=B, 3=C, 4=D, 5=E, 6=F\n\n"

        "FOR 'drag' — follow ALL steps below carefully:\n"
        "  1. READ THE CONTENT: Read every slot label and every draggable item label carefully.\n"
        "  2. DETECT SUBTYPE:\n"
        "       • MATCHING  — two columns, connect left item to right item\n"
        "       • ORDERING  — put items in correct sequence (1st, 2nd, 3rd…)\n"
        "       • FILL GAP  — drag tiles into blank spaces inside a text/diagram\n"
        "       • CATEGORY  — sort items into labeled groups/buckets\n"
        "  3. NUMBER THE SLOTS (destination 'd'): count empty drop-zones\n"
        "       strictly TOP-TO-BOTTOM, LEFT column before RIGHT column. Start at 1.\n"
        "  4. NUMBER THE SOURCE ITEMS (source 's'): count draggable buttons/tiles\n"
        "       strictly LEFT-TO-RIGHT, TOP row before BOTTOM row. Start at 1.\n"
        "  5. MATCH SEMANTICALLY: for each slot d=1,2,3… choose the source 's' whose\n"
        "       TEXT/MEANING best fits. Do NOT guess by visual position alone.\n"
        "  6. DISTRACTORS: there may be MORE source items than slots (extra wrong options).\n"
        "       Each source item should be used AT MOST ONCE.\n"
        "  7. If a slot has NO correct match among the sources, set s=0.\n"
        "  8. Output ONE entry per slot, sorted by 'd' ascending:\n"
        "       \"matches\": [{\"s\": <src_idx>, \"d\": <slot_idx>}, ...]\n\n"

        "FOR 'number':\n"
        "  • Put the integer answer in 'answer' (e.g. 42 or 235).\n\n"

        "═══ STEP 3 — QUALITY CHECKS ═══\n"
        "  ✓ Every slot has exactly one entry in 'matches'\n"
        "  ✓ No source index ('s') is reused (unless explicitly the same tile appears twice)\n"
        "  ✓ 'confidence' reflects true certainty (0.0–1.0); use <0.6 if unsure\n"
        "  ✓ 'reasoning' is 1–5 words in RUSSIAN describing your key reasoning\n\n"

        "═══ OUTPUT — RAW JSON ONLY, no markdown ═══\n"
        "{\"type\": \"choice|drag|number\", \"subtype\": \"matching|ordering|fill_gap|category|n/a\",\n"
        " \"reasoning\": \"...\", \"answer\": <int>, \"confidence\": <float>,\n"
        " \"matches\": [{\"s\":<int>, \"d\":<int>}, ...]}"
    )

def _parse_ai_json(raw_text):
    """Extract and parse JSON from raw AI response text."""
    m = re.search(r'\{.*\}', raw_text, re.DOTALL)
    return json.loads((m.group(0) if m else raw_text).strip())

# ─── GPT VISION CALL ─────────────────────────────────────────────────────────
def call_gpt_vision(filepaths):
    """Send images to GPT-4o Vision and return parsed JSON dict."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model   = os.environ.get("OPENAI_MODEL", "gpt-4o").strip()
    if not api_key:
        return None, "No OpenAI key"
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        messages_content = []
        for fpath in filepaths:
            with open(fpath, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            messages_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}
            })
        messages_content.append({"type": "text", "text": _build_exam_prompt(len(filepaths))})

        resp = client.chat.completions.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": messages_content}]
        )
        raw = resp.choices[0].message.content.strip()
        parsed = _parse_ai_json(raw)
        print(f"[GPT]  raw={raw[:120]}", flush=True)
        return parsed, None
    except Exception as e:
        print(f"[!] GPT Vision error: {e}", flush=True)
        return None, str(e)

# ─── CLAUDE VISION CALL ──────────────────────────────────────────────────────
def call_claude_vision(filepaths):
    """Send images to Claude Vision and return parsed JSON dict."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip().replace('"','').replace("'","")
    model   = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20240620").strip()
    if not api_key or api_key == "your_key_here":
        return None, "No Anthropic key"
    try:
        import anthropic as anthropic_sdk
        content_blocks = []
        for fpath in filepaths:
            with open(fpath, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}
            })
        content_blocks.append({"type": "text", "text": _build_exam_prompt(len(filepaths))})

        client  = anthropic_sdk.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model, max_tokens=1024,
            messages=[{"role": "user", "content": content_blocks}]
        )
        raw = message.content[0].text.strip()
        parsed = _parse_ai_json(raw)
        print(f"[Claude] raw={raw[:120]}", flush=True)
        return parsed, None
    except Exception as e:
        print(f"[!] Claude Vision error: {e}", flush=True)
        return None, str(e)

# ─── GPT VERIFIER ────────────────────────────────────────────────────────────
def call_gpt_verifier(filepaths, gpt_result, claude_result):
    """GPT receives both answers + images, compares, and returns the best final JSON."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model   = os.environ.get("OPENAI_MODEL", "gpt-4o").strip()
    if not api_key:
        return None, "No OpenAI key for verifier"
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)

        messages_content = []
        for fpath in filepaths:
            with open(fpath, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            messages_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}
            })

        verifier_prompt = (
            "You are a FINAL JUDGE for an exam question. "
            "Two AI models already analyzed the image(s) independently.\n\n"
            f"Model A (GPT):    {json.dumps(gpt_result,    ensure_ascii=False)}\n"
            f"Model B (Claude): {json.dumps(claude_result, ensure_ascii=False)}\n\n"
            "YOUR TASK\n"
            "Re-examine the image(s) carefully, then produce the BEST final answer.\n\n"
            "GENERAL RULES\n"
            "• If both models agree → confirm (verdict='agreed').\n"
            "• If they disagree → reason from the image which is correct\n"
            "  (verdict='gpt_wins' or 'claude_wins').\n"
            "• If both are partially right → synthesize the best combination\n"
            "  (verdict='synthesized').\n\n"
            "DRAG & DROP SPECIAL RULES (apply when type='drag')\n"
            "• Compare the models SLOT BY SLOT (d=1, d=2, …).\n"
            "• For each slot where they disagree: re-read the slot label and both\n"
            "  candidate source items; pick the semantically correct one.\n"
            "• You MAY take slot assignments from different models for different slots\n"
            "  (mixed verdict → use 'synthesized').\n"
            "• Ensure no source index ('s') is reused across slots.\n"
            "• Keep all slots present in 'matches', sorted by 'd' ascending.\n\n"
            "OUTPUT RULES\n"
            "• 'reasoning': 1–5 words in Russian.\n"
            "• 'verdict': 'agreed' | 'gpt_wins' | 'claude_wins' | 'synthesized'\n"
            "• Preserve 'subtype' field if present in inputs.\n"
            "• Respond ONLY with raw JSON — no markdown, no explanations.\n\n"
            "{\"type\": \"choice|drag|number\", \"subtype\": \"...\", "
            "\"reasoning\": \"...\", \"verdict\": \"...\",\n"
            " \"answer\": <int>, \"confidence\": <float>,\n"
            " \"matches\": [{\"s\":<int>, \"d\":<int>}, ...]}"
        )
        messages_content.append({"type": "text", "text": verifier_prompt})

        resp = client.chat.completions.create(
            model=model, max_tokens=1024,
            messages=[{"role": "user", "content": messages_content}]
        )
        raw = resp.choices[0].message.content.strip()
        parsed = _parse_ai_json(raw)
        print(f"[GPT-Verifier] verdict={parsed.get('verdict','?')} raw={raw[:120]}", flush=True)
        return parsed, None
    except Exception as e:
        print(f"[!] GPT Verifier error: {e}", flush=True)
        return None, str(e)

# ─── MAIN BATCH PROCESSOR ────────────────────────────────────────────────────
def process_batch(user_id, filepaths, ts):
    """Parallel GPT + Claude → GPT Verifier → final answer."""
    print(f"[*] Processing batch for User {user_id}: {len(filepaths)} photo(s)", flush=True)

    tg_answer  = "Error"
    reasoning  = "AI unavailable"
    confidence = 0.0
    user_queue = []

    # ── Step 1: call GPT and Claude in PARALLEL ──────────────────────────────
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fut_gpt    = pool.submit(call_gpt_vision,    filepaths)
        fut_claude = pool.submit(call_claude_vision, filepaths)
        gpt_result,    gpt_err    = fut_gpt.result()
        claude_result, claude_err = fut_claude.result()

    print(f"[*] GPT result: {gpt_result}, Claude result: {claude_result}", flush=True)

    # ── Step 2: decide which results to pass to verifier ────────────────────
    both_failed = (gpt_result is None and claude_result is None)
    if both_failed:
        reasoning = f"GPT: {gpt_err} | Claude: {claude_err}"
        print(f"[!] Both AI failed for User {user_id}", flush=True)
    else:
        # Fill in a stub if one side failed
        stub = {"type": "choice", "answer": 0, "confidence": 0.0,
                "reasoning": "N/A", "matches": []}
        gpt_r    = gpt_result    if gpt_result    is not None else stub
        claude_r = claude_result if claude_result is not None else stub

        # ── Step 3: GPT Verifier ─────────────────────────────────────────────
        # Only call verifier if BOTH models produced a real, useful answer
        # A model "really answered" drag if it has >=1 match with confidence>0
        # A model "really answered" choice/number if confidence>0
        def _is_real_answer(r):
            if r is None:
                return False
            if r.get("confidence", 0.0) <= 0.0:
                return False
            if r.get("type") == "drag" and not r.get("matches"):
                return False  # empty matches = model failed on drag
            return True

        gpt_real    = _is_real_answer(gpt_result)
        claude_real = _is_real_answer(claude_result)

        if gpt_real and claude_real:
            final, v_err = call_gpt_verifier(filepaths, gpt_r, claude_r)
            if final is None:
                # Verifier failed — fall back to GPT
                final = gpt_r
                print(f"[!] Verifier failed ({v_err}), using GPT answer", flush=True)
        else:
            # Only one model gave a real answer — use it directly, no verifier
            final = gpt_r if gpt_real else claude_r
            winner = "GPT" if gpt_real else "Claude"
            print(f"[*] Only {winner} gave real answer, skipping verifier", flush=True)

        # ── Step 4: build answer queue from final result ──────────────────────
        task_type  = final.get("type", "choice")
        reasoning  = final.get("reasoning", "OK")
        confidence = final.get("confidence", 0.0)
        verdict    = final.get("verdict", "—")

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

        # Add verdict + model summaries to reasoning for Telegram display
        def _short_summary(r, label):
            if r is None or r.get("confidence", 0) <= 0:
                return f"{label}:✗"
            t = r.get("type", "?")
            if t == "drag":
                mx = r.get("matches", [])
                pairs = ",".join(f"{m.get('s')}→{m.get('d')}" for m in mx[:3])
                return f"{label}:[{pairs}{'…' if len(mx)>3 else ''}]"
            return f"{label}:{r.get('answer', '?')}"

        gpt_summary    = _short_summary(gpt_result,    "GPT")
        claude_summary = _short_summary(claude_result, "CL")
        reasoning = f"{reasoning} {gpt_summary} {claude_summary} → {verdict}"

        answer_queue[user_id] = user_queue
        print(f"[Final] User {user_id} → type={task_type}, answer={tg_answer}, verdict={verdict}, queued {len(user_queue)}", flush=True)

    if user_id not in user_data:
        user_data[user_id] = {"history": []}

    filenames = [os.path.basename(f) for f in filepaths]
    user_data[user_id]["history"].append({
        "timestamp": get_now(),
        "filenames": filenames,
        "answer": tg_answer,
        "reasoning": reasoning,
        "confidence": confidence
    })
    send_to_telegram(user_id, filepaths, tg_answer, reasoning)
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
