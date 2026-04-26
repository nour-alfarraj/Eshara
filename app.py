"""
app.py — Eshara Backend (Flask)
يستقبل صورة من المتصفح، يستخرج نقاط اليد بـ MediaPipe، ويتنبأ بالحرف.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Optional

import cv2
import joblib
import mediapipe as mp
import numpy as np
from flask import Flask, jsonify, request, send_from_directory

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ─── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
MODEL_PATH = BASE_DIR / "model.pkl"
LE_PATH    = BASE_DIR / "label_encoder.pkl"
MAP_PATH   = BASE_DIR / "labels_map.json"

# ─── Load model artifacts ────────────────────────────────────────────────────
try:
    pipeline = joblib.load(MODEL_PATH)
    label_encoder = joblib.load(LE_PATH)
    log.info("Model loaded successfully.")
except Exception as exc:
    log.error("Failed to load model: %s", exc)
    raise SystemExit(1) from exc

# Label map: English key → Arabic character
LABELS_MAP: dict[str, str] = {}
if MAP_PATH.exists():
    try:
        LABELS_MAP = json.loads(MAP_PATH.read_text(encoding="utf-8")).get("key_to_ar", {})
        log.info("Loaded %d label mappings.", len(LABELS_MAP))
    except Exception as exc:
        log.warning("Could not load labels_map.json: %s", exc)

# Normalise inconsistent label spellings from training data
LABEL_ALIASES: dict[str, str] = {
    "shen": "sheen", "wow": "waw", "gaf": "qaf",
    "haaa": "haa",   "alef": "alif", "taa": "ta",
    "thaa": "tha",   "toot": "taa_marbouta",
}

def normalise_label(name: str) -> str:
    return LABEL_ALIASES.get(name.lower().strip(), name.lower().strip())


def predict_top1(features: np.ndarray) -> tuple[str, float]:
    """Return (label, probability) for the most-likely class."""
    proba = pipeline.predict_proba([features])[0]
    idx = int(np.argmax(proba))
    label = label_encoder.inverse_transform([idx])[0]
    return label, float(proba[idx])


# ─── MediaPipe Hands (single session reuse) ──────────────────────────────────
_mp_hands = mp.solutions.hands
hands_detector = _mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=0,          # fastest
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)

MAX_IMG_WIDTH = 640  # resize larger frames for speed


def extract_hand_features(img_bgr: np.ndarray) -> Optional[np.ndarray]:
    """
    Run MediaPipe on *img_bgr* and return a normalised 63-d feature vector,
    or None if no hand is detected.
    """
    if img_bgr.shape[1] > MAX_IMG_WIDTH:
        scale = MAX_IMG_WIDTH / img_bgr.shape[1]
        img_bgr = cv2.resize(img_bgr, (MAX_IMG_WIDTH, int(img_bgr.shape[0] * scale)))

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    result  = hands_detector.process(img_rgb)

    if not result.multi_hand_landmarks:
        return None

    landmarks = result.multi_hand_landmarks[0].landmark
    pts = np.array([(lm.x, lm.y, lm.z) for lm in landmarks], dtype=np.float32)

    # Translate so wrist (index 0) is origin
    pts -= pts[0]

    # Scale by distance between index MCP (5) and pinky MCP (17)
    scale = np.linalg.norm(pts[5, :2] - pts[17, :2]) + 1e-6
    pts  /= scale

    return pts.flatten()  # shape: (63,)


def decode_image(data_url: str) -> Optional[np.ndarray]:
    """Decode a base64 data-URL into an OpenCV BGR image."""
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    raw_bytes = base64.b64decode(data_url)
    buf = np.frombuffer(raw_bytes, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return img  # None if decoding fails


# ─── Flask App ───────────────────────────────────────────────────────────────
app = Flask(__name__, static_url_path="", static_folder=str(BASE_DIR))


@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR), "index.html")


@app.route("/predict", methods=["POST"])
def predict():
    """
    POST /predict
    Body: { "image": "<data-url>" }
    Returns:
        { "label": str, "arabic": str|null, "prob": float }
      or
        { "nohand": true }
      or
        { "error": str } with 4xx status
    """
    payload = request.get_json(silent=True) or {}
    data_url = payload.get("image")

    if not data_url:
        return jsonify({"error": "missing 'image' field"}), 400

    img = decode_image(data_url)
    if img is None:
        return jsonify({"error": "could not decode image"}), 400

    try:
        features = extract_hand_features(img)
    except Exception as exc:
        log.exception("Feature extraction failed")
        return jsonify({"error": str(exc)}), 500

    if features is None:
        return jsonify({"nohand": True})

    try:
        raw_label, prob = predict_top1(features)
    except Exception as exc:
        log.exception("Prediction failed")
        return jsonify({"error": str(exc)}), 500

    key    = normalise_label(raw_label)
    arabic = None

    # Functional pseudo-labels don't map to a printable character
    if key not in {"space", "delete", "clear"}:
        arabic = LABELS_MAP.get(key) or LABELS_MAP.get(raw_label) or raw_label

    return jsonify({"label": key, "arabic": arabic, "prob": prob})


# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
