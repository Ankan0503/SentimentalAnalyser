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

PRIMARY_API_KEY = "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"
FALLBACK_API_KEY = "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"

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
# 🗃️ Database Setup
# ======================================================
def init_db():
    conn = sqlite3.connect("journal_history.db")
    c = conn.cursor()

    # Journals
    c.execute('''CREATE TABLE IF NOT EXISTS journal_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  dominant_emotion TEXT,
                  emotion_scores TEXT,
                  summary TEXT)''')

    # Community posts
    c.execute('''CREATE TABLE IF NOT EXISTS community_posts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  text TEXT,
                  timestamp TEXT)''')

    # Comments
    c.execute('''CREATE TABLE IF NOT EXISTS community_comments
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  post_id INTEGER,
                  comment TEXT,
                  timestamp TEXT,
                  FOREIGN KEY(post_id) REFERENCES community_posts(id))''')

    conn.commit()
    conn.close()

init_db()

# ======================================================
# 🧹 Text Sanitization
# ======================================================
def sanitize_text(text):
    bad_words = [
        "hate", "worthless", "useless", "stupid", "idiot", "kill",
        "suicide", "hopeless", "depressed", "sad", "die",
        "fuck", "shit", "bitch", "bastard", "asshole"
    ]
    for word in bad_words:
        text = re.sub(rf"\b{word}\b", "❤️", text, flags=re.IGNORECASE)
    return text

# ======================================================
# 🧩 Extract JSON Safely
# ======================================================
def extract_json_from_text(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    json_part = match.group(0) if match else text
    json_part = json_part.replace("'", '"')
    json_part = re.sub(r",\s*}", "}", json_part)
    json_part = re.sub(r",\s*]", "]", json_part)
    try:
        return json.loads(json_part)
    except Exception:
        return {
            "EmotionScores": {"Unknown": 1.0},
            "DominantEmotion": "Unknown",
            "EmotionalSummary": text.strip()[:400]
        }

# ======================================================
# 🧠 Analyze Journal Entry
# ======================================================
@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        text = data.get("text", "")
        if not text.strip():
            return jsonify({"error": "No text provided."}), 400

        prompt = f"""
        Analyze the following journal text and detect emotions:
        {text}
        Return JSON only:
        {{
          "EmotionScores": {{"Joy": 0.8, "Sadness": 0.1}},
          "DominantEmotion": "Joy",
          "EmotionalSummary": "You seem joyful and relaxed today."
        }}
        """

        try:
            output_text = call_openrouter(PRIMARY_MODEL, PRIMARY_API_KEY, prompt)
        except Exception as e:
            print(f"Primary model failed: {e}")
            output_text = call_openrouter(FALLBACK_MODEL, FALLBACK_API_KEY, prompt)

        result_json = extract_json_from_text(output_text)

        conn = sqlite3.connect("journal_history.db")
        c = conn.cursor()
        c.execute("""INSERT INTO journal_history (timestamp, dominant_emotion, emotion_scores, summary)
                     VALUES (?, ?, ?, ?)""",
                  (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   result_json.get("DominantEmotion", "Unknown"),
                   json.dumps(result_json.get("EmotionScores", {})),
                   result_json.get("EmotionalSummary", "")))
        conn.commit()
        conn.close()

        return jsonify(result_json)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ======================================================
# 📊 Dashboard History
# ======================================================
@app.route("/history", methods=["GET"])
def get_history():
    try:
        conn = sqlite3.connect("journal_history.db")
        c = conn.cursor()
        c.execute("""SELECT timestamp, dominant_emotion, emotion_scores
                     FROM journal_history ORDER BY id DESC LIMIT 10""")
        data = []
        for row in c.fetchall():
            timestamp, dominant_emotion, emotion_scores_str = row
            emotion_scores = json.loads(emotion_scores_str) if emotion_scores_str else {}
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
# 💬 COMMUNITY ENDPOINTS (updated)
# ======================================================
@app.route("/community", methods=["GET"])
def get_community():
    try:
        conn = sqlite3.connect("journal_history.db")
        c = conn.cursor()

        # Fetch all posts (newest first)
        c.execute("""SELECT id, text, timestamp FROM community_posts ORDER BY id DESC""")
        posts = []
        for post_id, text, timestamp in c.fetchall():
            # Fetch comments for this post (newest first)
            c.execute("""SELECT comment, timestamp FROM community_comments 
                         WHERE post_id=? ORDER BY id DESC""", (post_id,))
            comments = [{"comment": cm[0], "timestamp": cm[1]} for cm in c.fetchall()]
            posts.append({
                "id": post_id,
                "text": text,
                "timestamp": timestamp,
                "comments": comments,
                "comment_count": len(comments)
            })
        conn.close()
        return jsonify(posts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/community", methods=["POST"])
def add_community():
    try:
        data = request.get_json()
        text = sanitize_text(data.get("text", "").strip())
        if not text:
            return jsonify({"error": "Empty post"}), 400
        timestamp = data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M"))
        conn = sqlite3.connect("journal_history.db")
        c = conn.cursor()
        c.execute("INSERT INTO community_posts (text, timestamp) VALUES (?, ?)", (text, timestamp))
        conn.commit()
        conn.close()
        return jsonify({"message": "Post added successfully"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/community/<int:post_id>/comments", methods=["POST"])
def add_comment(post_id):
    try:
        data = request.get_json()
        comment = sanitize_text(data.get("comment", "").strip())
        if not comment:
            return jsonify({"error": "Empty comment"}), 400
        timestamp = data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M"))
        conn = sqlite3.connect("journal_history.db")
        c = conn.cursor()
        c.execute("INSERT INTO community_comments (post_id, comment, timestamp) VALUES (?, ?, ?)",
                  (post_id, comment, timestamp))
        conn.commit()
        conn.close()
        return jsonify({"message": "Comment added successfully"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ======================================================
# 🚀 Main
# ======================================================
if __name__ == "__main__":
    print("✅ Emotion Analyzer + Dashboard + Community running at http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
