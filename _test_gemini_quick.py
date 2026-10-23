import os, requests
from dotenv import load_dotenv
load_dotenv()

key = os.getenv("GEMINI_API_KEY", "")
url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
body = {
    "contents": [{"role": "user", "parts": [{"text": "Return only valid JSON: {\"status\": \"ok\"}"}]}],
    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 50, "responseMimeType": "application/json"},
}
r = requests.post(url, params={"key": key}, headers={"Content-Type": "application/json"}, json=body, timeout=30)
print("Status:", r.status_code)
print("Response:", r.text[:300])
