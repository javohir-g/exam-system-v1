import os
import requests
import json
from dotenv import load_dotenv

# Load variables
load_dotenv()

key = os.environ.get("ANTHROPIC_API_KEY", "").strip().replace('"', '').replace("'", "")
model = os.environ.get("CLAUDE_MODEL", "claude-3-haiku-20240307").strip()

print(f"--- Claude API Diagnostics ---")
print(f"Key starts with: {key[:10]}...")
print(f"Model: {model}")

if not key or key == "your_key_here":
    print("ERROR: ANTHROPIC_API_KEY is not set or is still a placeholder!")
    exit()

headers = {
    "x-api-key": key,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json"
}

payload = {
    "model": model,
    "max_tokens": 10,
    "messages": [{"role": "user", "content": "Hello, are you there?"}]
}

print("\n[*] Sending test request...")
try:
    res = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=15)
    print(f"Status Code: {res.status_code}")
    
    data = res.json()
    if res.status_code == 200:
        print("SUCCESS! Claude responded:")
        print(data['content'][0]['text'])
    else:
        print("FAILED. Error details:")
        print(json.dumps(data, indent=2))
except Exception as e:
    print(f"CRITICAL ERROR: {e}")

print("\n--- End of Diagnostics ---")
