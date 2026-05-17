import time
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
def send_to_telegram(user_id, filepath, answer, reasoning):
    """Send screenshot + AI result to Telegram."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return  # Not configured, skip silently
    
    try:
        answer_letters = {0: "?", 1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F"}
        key = answer_letters.get(answer, str(answer))
        caption = (
            f"📡 *NODE {user_id}*\n"
            f"✅ *Answer:* `{key}`\n"
            f"🧠 *Reasoning:* {reasoning}"
        )
        with open(filepath, "rb") as photo:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
                files={"photo": photo},
                timeout=15
            )
        print(f"[TG] Sent to Telegram for user {user_id}", flush=True)
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
    """ESP32 calls this to get pending answers."""
    if request.headers.get("X-Secret") != SECRET_KEY:
        return "Unauthorized", 401
    
    user_id = request.args.get("user_id")
    if not user_id:
        return "Missing user_id", 400
    
    # Record activity
    uid = str(user_id)
    heartbeats[uid] = time.time()
    if uid in user_data:
        user_data[uid]["last_seen"] = time.strftime("%H:%M:%S")
    
    data = answer_queue.get(user_id, {"count": 0, "cmd_id": 0})
    count = data.get("count", 0)
    cmd_id = data.get("cmd_id", 0)

    if count > 0:
        # Reset count but keep cmd_id state if needed (or just clear)
        answer_queue[user_id] = {"count": 0, "cmd_id": cmd_id} 
        save_data()
        print(f"[*] Polled User {user_id}: returning {count} (ID: {cmd_id})", flush=True)
    
    return jsonify({"count": count, "cmd_id": cmd_id}), 200

@app.route("/upload", methods=["POST"])
def upload():
    user_id = request.headers.get("X-User-Id", "1")
    print(f"[*] Received upload from User {user_id}", flush=True)
    
    if SECRET_KEY and request.headers.get("X-Secret") != SECRET_KEY:
        return "Unauthorized", 401

    if "file" not in request.files:
        return "No file", 400
    
    file = request.files["file"]
    if file.filename == "":
        return "No filename", 400

    # Save with timestamp and user ID
    ts = int(time.time())
    filename = f"user_{user_id}_{ts}.jpg"
    filepath = os.path.join(SCREENSHOT_DIR, filename)
    
    try:
        file.save(filepath)
        
        # Update user tracking
        if user_id not in user_data:
            user_data[user_id] = {"history": []}
        
        user_data[user_id]["last_img"] = filename
        user_data[user_id]["last_seen"] = get_now()

        # AI INTEGRATION (Claude)
        ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip().replace('"', '').replace("'", "")
        CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20240620").strip()
        answer = 0
        reasoning = "No Claude key"

        if ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "your_key_here":
            print(f"[*] Attempting Claude API call (Model: {CLAUDE_MODEL}, Key prefix: {ANTHROPIC_API_KEY[:7]}...)", flush=True)
            try:
                with open(filepath, "rb") as f:
                    base64_image = base64.b64encode(f.read()).decode('utf-8')
                
                headers = {
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }

                payload = {
                    "model": CLAUDE_MODEL,
                    "max_tokens": 512,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": base64_image
                                }
                            },
                            {
                                "type": "text",
                                "text": (
                                    "You are an expert Professor. Analyze this exam screenshot and find the correct answer.\n\n"
                                    "INSTRUCTIONS:\n"
                                    "1. Identify the question and ALL available options.\n"
                                    "2. In the 'reasoning' field, briefly explain your logic in Russian.\n"
                                    "3. In the 'answer' field, provide the integer index of the correct option: 1=A, 2=B, 3=C, 4=D, 5=E, 6=F, and so on.\n"
                                    "4. If no clear answer is found, return 0.\n\n"
                                    "Respond ONLY with raw JSON: {\"reasoning\": \"...\", \"answer\": <int>}"
                                )
                            }
                        ]
                    }]
                }
                
                res = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=30)
                res_data = res.json()
                
                if 'content' in res_data:
                    content = res_data['content'][0]['text'].strip()
                    
                    if "```" in content:
                        content = content.split("```")[1]
                        if content.startswith("json"): content = content[4:]

                    parsed = json.loads(content.strip())
                    answer = parsed.get("answer", 0)
                    reasoning = parsed.get("reasoning", "Parsed OK")
                    
                    # Queue for ESP32 with unique command ID
                    answer_queue[user_id] = {"count": answer, "cmd_id": ts}
                    print(f"[Claude] User {user_id} -> Answer {answer} (CMD_ID: {ts})", flush=True)
                else:
                    print(f"[!] Claude Error Response: {json.dumps(res_data, indent=2)}", flush=True)
                    err_msg = res_data.get('error', {}).get('message', 'Unknown error')
                    reasoning = f"Claude API Error: {err_msg}"
                    # If model not found, suggest fallback
                    if "model" in err_msg.lower() or "not found" in err_msg.lower():
                        reasoning += " (Try checking model availability for your API key)"

            except Exception as ai_e:
                print(f"[!] AI Exception: {ai_e}", flush=True)
                traceback.print_exc()
                reasoning = f"Server Error: {str(ai_e)}"
        else:
            reasoning = "ANTHROPIC_API_KEY is not set correctly in .env"
            print("[!] Error: ANTHROPIC_API_KEY is still using 'your_key_here'", flush=True)

        # Store in history
        user_data[user_id]["history"].append({
            "timestamp": get_now(),
            "filename": filename,
            "answer": answer,
            "reasoning": reasoning
        })
        
        # Notify Telegram
        send_to_telegram(user_id, filepath, answer, reasoning)
        
        save_data()

        return jsonify({"user_id": user_id, "answer": answer}), 200
            
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
