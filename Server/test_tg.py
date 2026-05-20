import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

def test_tg():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip().replace('"', '').replace("'", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip().replace('"', '').replace("'", "")
    
    print(f"Token: {token[:5]}...{token[-5:] if token else ''}")
    print(f"Chat ID: {chat_id}")
    
    if not token or not chat_id:
        print("Error: Token or Chat ID is missing!")
        return

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        r = requests.get(url, timeout=10)
        print(f"getMe response: {r.status_code}")
        print(r.text)
        
        url_msg = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": "🛠 Diagnostic test message from Exam System server.",
            "parse_mode": "Markdown"
        }
        r2 = requests.post(url_msg, json=payload, timeout=10)
        print(f"sendMessage response: {r2.status_code}")
        print(r2.text)
        
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_tg()
