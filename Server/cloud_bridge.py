import time
import threading
import requests
import os
import traceback
import json
import base64
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
heartbeats = {}  # user_id -> last_seen_timestamp

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
                print(f"[*] Data loaded from {DB_FILE}", flush=True)
        except Exception as e:
            print(f"[!] Error loading {DB_FILE}: {e}", flush=True)

def save_data():
    try:
        with open(DB_FILE, "w") as f:
            json.dump({
                "user_data": user_data,
                "answer_queue": answer_queue
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
        caption = (
            f"📡 *NODE {user_id}*\n"
            f"✅ *Answer:* `{answer_text}`\n"
            f"🧠 *Reasoning:* {reasoning}"
        )

        if isinstance(filepaths, str):
            filepaths = [filepaths]

        if len(filepaths) == 1:
            # Single photo
            with open(filepaths[0], "rb") as photo:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
                    files={"photo": photo},
                    timeout=15
                )
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
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMediaGroup",
                data={"chat_id": chat_id, "media": json.dumps(media)},
                files=files,
                timeout=30
            )
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
    if user_id:
        heartbeats[user_id] = time.time()
    return jsonify({"status": "alive"}), 200

@app.route("/poll", methods=["GET"])
def poll():
    """ESP32 calls this to get pending answers. Pops the first command from the user's queue."""
    if request.headers.get("X-Secret") != SECRET_KEY:
        return "Unauthorized", 401
    
    user_id = request.args.get("user_id")
    if not user_id:
        return "Missing user_id", 400
    
    uid = str(user_id)
    heartbeats[uid] = time.time()
    if uid in user_data:
        user_data[uid]["last_seen"] = time.strftime("%H:%M:%S")
    
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


def process_batch(user_id, filepaths, ts):
    """Called after 3s timeout: runs AI on all buffered photos and notifies."""
    print(f"[*] Processing batch for User {user_id}: {len(filepaths)} photo(s)", flush=True)

    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip().replace('"', '').replace("'", "")
    CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5").strip()
    answer = 0
    answer2 = 0
    reasoning = "No Claude key"

    if ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "your_key_here":
        try:
            import anthropic as anthropic_sdk
            content_blocks = []
            for fpath in filepaths:
                with open(fpath, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode('utf-8')
                content_blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}
                })

            prompt_prefix = (
                "You are an expert Professor analyzing exam screenshots "
                f"({len(filepaths)} image(s) may show different parts of the same question).\n\n"
            ) if len(filepaths) > 1 else "You are an expert Professor analyzing an exam screenshot.\n\n"

            content_blocks.append({
                "type": "text",
                "text": (
                    prompt_prefix +
                    "TASK TYPE DETECTION:\n"
                    "- If this is a MULTIPLE CHOICE question (options A/B/C/D/E/F): return type 'choice'\n"
                    "- If this is a DRAG & DROP task (match, order, categorize): return type 'drag'\n\n"
                    "FOR CHOICE: In 'answer' put the index: 1=A, 2=B, 3=C, 4=D, 5=E, 6=F. Set 'matches' to null.\n"
                    "FOR DRAG: In 'matches' field, return a LIST of all correct pairs: [{\"s\": source_idx, \"d\": dest_idx}, ...].\n"
                    "  's' is the item number, 'd' is the target slot number (1-based, top-to-bottom/left-to-right).\n\n"
                    "In 'reasoning' briefly explain in Russian.\n\n"
                    "Respond ONLY with raw JSON: {\"type\": \"choice|drag\", \"reasoning\": \"...\", \"answer\": <int>, \"matches\": [{\"s\":<int>,\"d\":<int>}, ...]}"
                )
            })

            client = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": content_blocks}]
            )

            content = message.content[0].text.strip()
            print(f"[Claude RAW] {content}", flush=True)
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            parsed = json.loads(content.strip())
            task_type = parsed.get("type", "choice")
            reasoning = parsed.get("reasoning", "Parsed OK")
            
            # Populate the queue
            user_queue = []
            tg_answer = str(answer) # Fallback

            if task_type == "drag":
                matches = parsed.get("matches", [])
                for i, m in enumerate(matches):
                    user_queue.append({"count": m.get("s", 0), "count2": m.get("d", 0), "cmd_id": ts + i})
                
                # Format for Telegram: "1→3 | 2→2"
                tg_answer = " | ".join([f"{m.get('s')}→{m.get('d')}" for m in matches])
                answer_val = matches[0].get("s", 0) if matches else 0
            else:
                answer_val = parsed.get("answer", 0)
                user_queue.append({"count": answer_val, "count2": 0, "cmd_id": ts})
                
                # Format for Telegram: "3 (C)"
                letters = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F"}
                tg_answer = f"{answer_val} ({letters.get(answer_val, '?')})"

            answer_queue[user_id] = user_queue
            print(f"[Claude] User {user_id} -> type={task_type}, queued {len(user_queue)} commands.", flush=True)

        except Exception as ai_e:
            print(f"[!] Claude Exception: {ai_e}", flush=True)
            traceback.print_exc()
            reasoning = f"Claude Error: {str(ai_e)}"
            tg_answer = "Error"

    if user_id not in user_data:
        user_data[user_id] = {"history": []}
    user_data[user_id]["history"].append({
        "timestamp": get_now(),
        "filename": os.path.basename(filepaths[0]),
        "answer": tg_answer, # Store the pretty string in history
        "reasoning": reasoning
    })
    send_to_telegram(user_id, filepaths, tg_answer, reasoning)
    save_data()


@app.route("/upload", methods=["POST"])
def upload():
    """Receives a photo from the agent. Buffers for 3s, then processes all."""
    user_id = request.headers.get("X-User-Id", "1")
    print(f"[*] Received upload from User {user_id}", flush=True)

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
        
        # Calculate ESP online status (active in last 20 seconds)
        last_poll = heartbeats.get(uid, 0)
        data["esp_online"] = (now - last_poll) < 20
        all_users[uid] = data
        
    return render_template("dashboard.html", users=all_users)

@app.route("/user/<user_id>")
def user_history(user_id):
    data = user_data.get(user_id, {"history": [], "last_seen": "Never", "last_img": None})
    return render_template("user_history.html", uid=user_id, history=data["history"], last_img=data.get("last_img"))

@app.route("/screenshots/<path:filename>")
def serve_screenshot(filename):
    return send_from_directory(SCREENSHOT_DIR, filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[*] Starting server on port {port}...", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
