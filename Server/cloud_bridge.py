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
    heartbeats[user_id] = time.time()
    
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

        # AI INTEGRATION
        OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
        answer = 0
        reasoning = "No AI key"

        if OPENAI_API_KEY:
            try:
                with open(filepath, "rb") as f:
                    base64_image = base64.b64encode(f.read()).decode('utf-8')
                
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}
                payload = {
                    "model": "gpt-4o",
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Analyze this exam screenshot. Find the correct answer. Respond ONLY with raw JSON: {\"reasoning\": \"...\", \"answer\": <1|2|3|4>}. 1=A, 2=B, 3=C, 4=D."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }],
                    "max_tokens": 150
                }
                
                res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
                res_data = res.json()
                content = res_data['choices'][0]['message']['content'].strip()
                
                if "```" in content:
                    content = content.split("```")[1]
                    if content.startswith("json"): content = content[4:]

                parsed = json.loads(content.strip())
                answer = parsed.get("answer", 0)
                reasoning = parsed.get("reasoning", "Parsed OK")
                
                # Queue for ESP32 with unique command ID
                answer_queue[user_id] = {"count": answer, "cmd_id": ts}
                print(f"[AI] User {user_id} -> Answer {answer} (CMD_ID: {ts})", flush=True)

            except Exception as ai_e:
                print(f"[!] AI Error: {ai_e}", flush=True)
                reasoning = str(ai_e)

        # Store in history
        user_data[user_id]["history"].append({
            "timestamp": get_now(),
            "filename": filename,
            "answer": answer,
            "reasoning": reasoning
        })
        
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
        data = user_data.get(uid, {"history": [], "last_seen": "Never", "last_img": None}).copy()
        
        # Calculate ESP online status (active in last 7 seconds)
        last_poll = heartbeats.get(uid, 0)
        data["esp_online"] = (now - last_poll) < 7
        all_users[uid] = data
        
    return render_template("dashboard.html", users=all_users)

@app.route("/user/<user_id>")
def user_history(user_id):
    data = user_data.get(user_id)
    if not data:
        return "User not found", 404
    return render_template("user_history.html", user_id=user_id, data=data)

@app.route("/screenshots/<path:filename>")
def serve_screenshot(filename):
    return send_from_directory(SCREENSHOT_DIR, filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[*] Starting server on port {port}...", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
