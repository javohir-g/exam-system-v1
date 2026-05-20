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
        # Build mention string
        tg_mention = tg_users.get(str(user_id), "")
        mention_line = f"\n👤 {tg_mention}" if tg_mention else ""
        
        caption = (
            f"📡 *NODE {user_id}*{mention_line}\n"
            f"✅ *Answer:* `{answer_text}`\n"
            f"🧠 *Reasoning:* {reasoning}"
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
                    "- If this is a DRAG & DROP task (matching items, sorting, or filling gaps): return type 'drag'\n"
                    "- If this requires a NUMERIC OPEN ANSWER (e.g., math answer '235'): return type 'number'\n\n"
                    "FOR CHOICE: In 'answer' put the index: 1=A, 2=B, 3=C, 4=D, 5=E... \n\n"
                    "FOR DRAG & DROP:\n"
                    "1. Identify ALL empty boxes/slots. Number them 1, 2, 3... strictly from TOP-TO-BOTTOM.\n"
                    "2. Identify ALL source buttons. Number them 1, 2, 3... strictly from LEFT-TO-RIGHT.\n"
                    "3. In 'matches' return a list for EVERY slot. If a slot can't be filled, set 's' to 0.\n"
                    "   Format: [{\"s\": button_idx, \"d\": 1}, ...]\n\n"
                    "FOR NUMBER: In 'answer' put the integer value directly (e.g. 235).\n\n"
                    "In 'reasoning' provide an extremely brief note (1-3 words) in Russian.\n\n"
                    "ADDITIONAL: In 'confidence' return a number from 0 to 1 indicating your certainty.\n\n"
                    "Respond ONLY with raw JSON: {\"type\": \"choice|drag|number\", \"reasoning\": \"...\", \"answer\": <int>, \"confidence\": <float>, \"matches\": [{\"s\":<int>,\"d\":<int>}, ...]}"
                )
            })

            client = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": content_blocks}]
            )

            content = message.content[0].text.strip()
            
            # Robust JSON extraction using regex
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = content

            try:
                parsed = json.loads(json_str.strip())
            except Exception as parse_e:
                print(f"[!] JSON Parse Error: {parse_e}", flush=True)
                print(f"[RAW CONTENT]: {content}", flush=True)
                raise parse_e

            task_type = parsed.get("type", "choice")
            reasoning = parsed.get("reasoning", "Parsed OK")
            confidence = parsed.get("confidence", 0.0)
            
            # Populate the queue
            user_queue = []
            tg_answer = "0"

            if task_type == "drag":
                matches = parsed.get("matches", [])
                # Sort matches by target slot (d) to ensure 1, 2, 3... order
                sorted_matches = sorted(matches, key=lambda x: x.get('d', 0))
                
                for i, m in enumerate(sorted_matches):
                    user_queue.append({"count": m.get("s", 0), "count2": 0, "cmd_id": ts + i})
                
                tg_answer = "\n".join([f"{m.get('d')}) {m.get('s')}" for m in sorted_matches])
            elif task_type == "number":
                answer_val = parsed.get("answer", 0)
                user_queue.append({"count": answer_val, "count2": 0, "cmd_id": ts, "is_num": True})
                tg_answer = str(answer_val)
            else:
                answer_val = parsed.get("answer", 0)
                user_queue.append({"count": answer_val, "count2": 0, "cmd_id": ts})
                
                letters = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F"}
                tg_answer = f"{answer_val} ({letters.get(answer_val, '?')})"

            answer_queue[user_id] = user_queue
            print(f"[Claude] User {user_id} -> type={task_type}, queued {len(user_queue)} commands.", flush=True)

        except Exception as ai_e:
            print(f"[!] Claude Exception: {ai_e}", flush=True)
            traceback.print_exc()
            reasoning = f"Claude Error: {str(ai_e)}"
            tg_answer = "Error"
            confidence = 0.0

    if user_id not in user_data:
        user_data[user_id] = {"history": []}
    
    # Store ALL filenames from the batch
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
