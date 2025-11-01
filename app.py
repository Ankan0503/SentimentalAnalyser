import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests, json, os, re
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ==============================
# 🔧 Model Configuration
# ==============================
PRIMARY_MODEL = "openai/gpt-oss-20b:free"
FALLBACK_MODEL = "mistralai/mistral-7b-instruct:free"

PRIMARY_API_KEY = os.getenv("PRIMARY_API_KEY")
FALLBACK_API_KEY = os.getenv("FALLBACK_API_KEY")

# ==============================
# 🗃️ Database Setup
# ==============================
def init_db():
    conn = sqlite3.connect("journal_history.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS journal_history
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              timestamp TEXT,
              dominant_emotion TEXT,
              emotion_scores TEXT,
              summary TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ======================================================
# 🧩 Utility: Call OpenRouter API
# ======================================================
def call_openrouter(model, api_key, prompt):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Referer": "http://localhost:5000",
        "X-Title": "Advanced Emotion Analyzer"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an expert psychologist AI that detects multiple emotions."},
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=60
    )

    result = response.json()
    if "choices" in result and len(result["choices"]) > 0:
        return result["choices"][0]["message"]["content"]
    elif "error" in result:
        raise ValueError(result["error"].get("message", "Unknown error"))
    else:
        raise ValueError("No valid output from model")


# ======================================================
# 🧩 Utility: Extract JSON safely
# ======================================================
def extract_json_from_text(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    json_part = match.group(0) if match else text
    json_part = json_part.replace("'", '"')
    json_part = re.sub(r",\s*}", "}", json_part)
    json_part = re.sub(r",\s*]", "]", json_part)
    return json.loads(json_part)


# ======================================================
# 🧠 Route: Analyze Journal Entry (merged)
# ======================================================
@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        text = data.get("text", "")
        images = data.get("images", [])

        # --- Emotion analysis prompt ---
        prompt = f"""
You are an expert emotion analysis AI. Analyze the user's journal text and attached images
to detect emotions and their intensities.

Text content:
{text}

There are {len(images)} image(s). Output only JSON in this format:
{{
  "EmotionScores": {{"Joy": 0.8, "Sadness": 0.1, "Anger": 0.0, "Calm": 0.6}},
  "DominantEmotion": "Joy",
  "EmotionalSummary": "You seem joyful and relaxed today."
}}
"""
    # ADD THIS after getting text in analyze():
        if not text.strip():
            return jsonify({
        "EmotionScores": {"Neutral": 1.0},
        "DominantEmotion": "Neutral",
        "EmotionalSummary": "No text to analyze. Please write something first."
    })
        # --- Try models ---
        try:
            output_text = call_openrouter(PRIMARY_MODEL, PRIMARY_API_KEY, prompt)
        except Exception as e:
            print(f"⚠️ Primary model failed: {e}")
            output_text = call_openrouter(FALLBACK_MODEL, FALLBACK_API_KEY, prompt)

        # --- Parse JSON output ---
        try:
            result_json = extract_json_from_text(output_text)
        except Exception as e:
            print("⚠️ Could not parse JSON:", e)
            result_json = {
                "EmotionScores": {"Unknown": 1.0},
                "DominantEmotion": "Unknown",
                "EmotionalSummary": output_text.strip()[:400]
            }

        # --- Save to SQLite ---
        emotion = result_json.get("DominantEmotion", "Unknown")
        summary = result_json.get("EmotionalSummary", "")
        conn = sqlite3.connect("journal_history.db")
        c = conn.cursor()
        emotion_scores_json = json.dumps(result_json.get("EmotionScores", {}))
        c.execute("""INSERT INTO journal_history 
             (timestamp, dominant_emotion, emotion_scores, summary) 
             VALUES (?, ?, ?, ?)""",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                emotion, 
                emotion_scores_json, 
                summary))
        conn.commit()
        conn.close()

        return jsonify(result_json)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ======================================================
# 📊 Route: Dashboard History (SQLite only)
# ======================================================
# REPLACE THE ENTIRE get_history() FUNCTION WITH:
@app.route("/history", methods=["GET"])
def get_history():
    try:
        conn = sqlite3.connect("journal_history.db")
        c = conn.cursor()
        c.execute("""SELECT timestamp, dominant_emotion, emotion_scores 
                     FROM journal_history 
                     ORDER BY id DESC 
                     LIMIT 10""")
        
        data = []
        for row in c.fetchall():
            timestamp, dominant_emotion, emotion_scores_str = row
            try:
                emotion_scores = json.loads(emotion_scores_str) if emotion_scores_str else {}
            except:
                emotion_scores = {}
            
            data.append({
                "timestamp": timestamp,
                "DominantEmotion": dominant_emotion,
                "EmotionScores": emotion_scores
            })
        
        conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ======================================================
# 🚀 Main Entry
# ======================================================
if __name__ == "__main__":
    print("✅ Emotion Analyzer running with GPT-OSS 20B + Mistral fallback")
    app.run(debug=True, port=5000)
