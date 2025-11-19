# ==============================================================================
# Soph_IA - V69 "Scoring Emotionnel & RAG Actif"
# - Personnalité : Sophia "Version Relou" (Humour noir/Cynique)
# - Fonctionnalité : Module de Scoring (7 questions) + Micro-interactions
# - Intelligence : RAG activé (Mémoire via rag.py)
# - Sécurité : Détection de détresse (DANGER_KEYWORDS)
# ==============================================================================

import os
import re
import json
import requests
import asyncio
import logging
import random
import time
from datetime import datetime
from typing import Dict, Optional, List
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

# --- IMPORT DU MODULE RAG (CRITIQUE) ---
try:
    from rag import rag_query
    RAG_ENABLED = True
except ImportError:
    logging.warning("⚠️ Module 'rag.py' introuvable. Le RAG est désactivé.")
    RAG_ENABLED = False

# Configuration du logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("sophia.v69")

load_dotenv()

# -----------------------
# CONFIG
# -----------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")

# Behaviour params
MAX_RECENT_TURNS = 3
SUMMARY_TRIGGER_TURNS = 8
SUMMARY_MAX_TOKENS = 120

RESPONSE_TIMEOUT = 70
MAX_RETRIES = 2

IDENTITY_PATTERNS = [r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une (?:intelligence artificielle|ia)"]

# Diagnostic / Scoring questions (7)
SCORING_QUESTIONS = [
    {"id": "anxiety", "q": "Sur une échelle de 1 à 10, à quel point tu te sens anxieux·se ces derniers jours ? (1 = pas du tout, 10 = extrêmement)"},
    {"id": "stress", "q": "Sur 1–10, quel est ton niveau de stress général en ce moment ?"},
    {"id": "sleep", "q": "Sur 1–10, à quel point ton sommeil est perturbé/de mauvaise qualité ?"},
    {"id": "mood", "q": "Sur 1–10, comment évaluerais-tu ton humeur globale (tristesse/dépression) ?"},
    {"id": "mental_load", "q": "Sur 1–10, quelle est ta charge mentale quotidienne (pensées, responsabilités) ?"},
    {"id": "control", "q": "Sur 1–10, à quel point tu sens que tu as le contrôle sur ta vie actuelle ? (1 = aucun contrôle, 10 = plein contrôle)"},
    {"id": "motivation", "q": "Sur 1–10, comment est ton niveau d'énergie / motivation pour faire des choses qui comptent pour toi ?"}
]

# Weights for each dimension
SCORING_WEIGHTS = {
    "anxiety": 20, "stress": 15, "sleep": 15, "mood": 20,
    "mental_load": 10, "control": 10, "motivation": 10
}

# Thresholds
ORIENTATION_THRESHOLDS = {
    "prevention": 30, "fragile": 60, "psychologist": 80, "severe": 100
}

# Dangerous phrases
DANGER_KEYWORDS = [
    r"\bme suicid(es|er|e)?\b", r"\bje veux mourir\b", r"\bj'ai envie de mourir\b",
    r"\bfinir ma vie\b", r"\bje vais me tuer\b", r"\bj'ai pensé à me tuer\b",
    r"\bje vais me faire du mal\b", r"\bje ne veux plus vivre\b"
]

# -----------------------
# UTIL - appel modèle
# -----------------------
def call_model_api_sync(messages: List[Dict], temperature: float = 0.85, max_tokens: int = 700):
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.8,
        "presence_penalty": 0.5,
        "frequency_penalty": 0.4
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}

    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=RESPONSE_TIMEOUT)
            if r.status_code in (401, 403):
                logger.critical("API Key Error (401/403). Check TOGETHER_API_KEY validity.")
                return "FATAL_API_KEY_ERROR"
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                time.sleep(2)
                continue
            return None
        except Exception as e:
            logger.error(f"API Error: %s", e)
            return None
    return None

# -----------------------
# PROMPT DYNAMIQUE (V69 Persona)
# -----------------------
def build_adaptive_system_prompt(user_profile, emotional_summary, rag_context=""):
    user_name = user_profile.get("name") or "l'ami(e) sans nom"
    env_info = user_profile.get("geo_info") or "Non précisé"
    pro_info = user_profile.get("pro_info") or "Non précisé"
    socle_info = user_profile.get("socle_info") or "Non précisé"

    # Persona Humour Noir / Relou
    persona_base = (
        f"Tu es Sophia, version relou. Tu parles uniquement en français. Ton ton est direct, décalé, pince-sans-rire et d'humour noir. "
        f"Ton rôle est d'écouter {user_name} et d'apporter un soutien, en dosant humour et sérieux.\n\n"
    )
    
    rag_instruction = ""
    if rag_context:
        rag_instruction = f"\n[CONTEXTE RAG]: Utilise ces infos pour répondre, mais garde ton ton décalé :\n{rag_context}\n"

    rules = (
        "Règles :\n"
        "- Commence par valider l'émotion exprimée.\n"
        "- Adapte ton humour : si l'utilisateur présente des signes de détresse, désactive l'humour et reste sérieux.\n"
        "- Si pas de détresse, tu peux doser une touche d'humour sarcastique entre les propositions.\n"
    )
    
    memory = f"\nProfil: {user_name} | Environnement: {env_info} | Profession: {pro_info} | Socle: {socle_info}\n"
    if emotional_summary:
        memory += f"\nMémoire émotionnelle: {emotional_summary}\n"

    return persona_base + rules + rag_instruction + memory

# -----------------------
# RAG DECISION HELPER
# -----------------------
def should_use_rag(message: str) -> bool:
    if not message or len(message.strip()) == 0: return False
    m = message.lower().strip()

    small_talk = {"ça va", "ca va", "salut", "bonjour", "merci", "ok", "ok!", "quoi de neuf", "yo"}
    if m in small_talk or (len(m.split()) <= 3 and any(s in m for s in small_talk)):
        return False

    keywords = [
        "anx", "stress", "déprim", "suic", "sommeil", "dormir", "insomnie", 
        "psy", "thérapie", "conseil", "aide", "comment", "pourquoi", 
        "que faire", "je me sens", "angoiss", "panique", "phobie", "relation", "seul", "triste"
    ]
    if any(k in m for k in keywords): return True
    if len(m) > 40: return True
    return False

# -----------------------
# Helpers Scoring
# -----------------------
def detect_dangerous_phrases(text: str) -> bool:
    txt = text.lower()
    for pat in DANGER_KEYWORDS:
        if re.search(pat, txt): return True
    return False

def invert_score(value: int) -> int:
    return 11 - value

def validate_numeric_response(text: str) -> Optional[int]:
    text = text.strip()
    m = re.search(r"\b([1-9]|10)\b", text)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 10: return val
    return None

def compute_weighted_score(scores: Dict[str, int]) -> float:
    total = 0.0
    for key, weight in SCORING_WEIGHTS.items():
        val = scores.get(key, 5)
        if key in ("control", "motivation"): val = invert_score(val)
        normalized = ((val - 1) / 9) * 100
        total += normalized * (weight / 100.0)
    return round(total, 1)

def decide_orientation(score: float) -> str:
    if score <= ORIENTATION_THRESHOLDS["prevention"]: return "coach / sophrologue / prévention"
    if score <= ORIENTATION_THRESHOLDS["fragile"]: return "coach mental + accompagnement bien-être"
    if score <= ORIENTATION_THRESHOLDS["psychologist"]: return "psychologue (évaluation plus approfondie recommandée)"
    return "psychiatre ou service d'urgence (détresse sévère) - orientation urgente requise"

# -----------------------
# POST-PROCESS
# -----------------------
def post_process_response(raw_response):
    if not raw_response: return "Désolé, je n'arrive pas à formuler ma réponse. Peux-tu reformuler ?"
    text = raw_response.strip()
    for pat in IDENTITY_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(I am|I'm)\b", "", text, flags=re.IGNORECASE)
    text = "\n".join([ln.strip() for ln in text.splitlines() if ln.strip()])
    
    if re.search(r"[A-Za-z]{3,}", text) and not re.search(r"[àâéèêîôùûçœ]", text):
        return "Je suis désolée, je n'ai pas bien formulé cela en français. Peux-tu reformuler ?"
    
    if len(text) > 1500:
        text = text[:1500].rsplit(".", 1)[0] + "."
    return text

# -----------------------
# CHAT ORCHESTRATOR (RAG + LLM)
# -----------------------
async def chat_with_ai(user_profile: Dict, history: List[Dict], context: ContextTypes.DEFAULT_TYPE, temperature: float = 0.85, max_tokens: int = 700) -> str:
    if history and len(history) > MAX_RECENT_TURNS * 2:
        history = history[-(MAX_RECENT_TURNS * 2):]

    last_user_text = history[-1]["content"] if history else ""
    
    # 1. RAG
    rag_context_str = ""
    if RAG_ENABLED and should_use_rag(last_user_text):
        try:
            logger.info(f"🔍 RAG activé pour : {last_user_text[:20]}...")
            rag_result = await asyncio.to_thread(rag_query, last_user_text, 3)
            rag_context_str = rag_result.get("context", "")
        except Exception as e:
            logger.warning(f"RAG query failed: {e}")

    # 2. Prompt Build (avec le contexte RAG)
    system_prompt = build_adaptive_system_prompt(user_profile, context.user_data.get("emotional_summary", ""), rag_context=rag_context_str)

    payload_messages = [{"role": "system", "content": system_prompt}] + history
    
    # 3. Call LLM
    raw_resp = await asyncio.to_thread(call_model_api_sync, payload_messages, temperature, max_tokens)
    
    if raw_resp == "FATAL_API_KEY_ERROR":
        return "ERREUR CRITIQUE : Ma clé API est invalide. Veuillez vérifier TOGETHER_API_KEY."
    if not raw_resp:
        return "Désolé, je n'arrive pas à me connecter à mon esprit pour le moment. Réessaie."
        
    return post_process_response(raw_resp)

# -----------------------
# NAME DETECTION
# -----------------------
def detect_name_from_text(text):
    text = text.strip()
    if len(text.split()) == 1 and text.lower() not in {"bonjour", "salut", "coucou", "hello", "hi"}:
        return text.capitalize()
    m = re.search(r"(?:mon nom est|je m'appelle|je me nomme|je suis|moi c'est|on m'appelle)\s*([A-Za-zÀ-ÖØ-öø-ÿ'\- ]+)", text, re.IGNORECASE)
    if m: return m.group(1).strip().split()[0].capitalize()
    return None

# -----------------------
# HANDLERS TELEGRAM
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["profile"] = {"name": None, "geo_info": None, "pro_info": None, "socle_info": None}
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    context.user_data["emotional_summary"] = ""
    context.user_data["last_bot_reply"] = ""
    context.user_data["mental_scores"] = {}
    context.user_data["current_scoring_index"] = 0
    
    welcome = (
        "Salut ! 👋 Je suis SophIA, ton espace d'écoute confidentiel.\n\n"
        "Tu veux vider ton sac maintenant, ou je peux te poser quelques questions rapides pour mieux t'orienter (ça prend environ 2 minutes) ?\n\n"
        "Pour commencer, quel est ton prénom ?"
    )
    await update.message.reply_text(welcome)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = (update.message.text or "").strip()
    if not user_message: return

    profile = context.user_data.setdefault("profile", {"name": None, "geo_info": None, "pro_info": None, "socle_info": None})
    state = context.user_data.get("state", "awaiting_name")
    history = context.user_data.setdefault("history", [])

    # DANGER DETECTION
    if detect_dangerous_phrases(user_message):
        context.user_data["state"] = "safety_mode"
        await update.message.reply_text(
            "Merci de m'avoir dit cela. Je prends ça très au sérieux. Si tu es en danger immédiat, contacte les services d'urgence locaux maintenant.\n"
            "Est-ce que tu te sens en sécurité en ce moment ? (réponds oui/non)"
        )
        return

    # === awaiting_name ===
    if state == "awaiting_name":
        name_candidate = detect_name_from_text(user_message)
        if name_candidate:
            profile["name"] = name_candidate
            context.user_data["state"] = "awaiting_mode_choice"
            await update.message.reply_text(
                f"Yo {profile['name']} ! Enchantée. Tu veux d'abord parler librement, ou je te pose mes 7 questions rapides (score 1–10) pour t'orienter ? (Écris 'parler' ou 'questions')"
            )
            return
        else:
            await update.message.reply_text("S'il te plaît, donne-moi ton prénom ou un surnom — ça rend tout plus simple.")
            return

    # === safety_mode ===
    if state == "safety_mode":
        resp = user_message.lower()
        if resp.startswith("oui"):
            context.user_data["state"] = "awaiting_mode_choice"
            await update.message.reply_text("D'accord, merci. On continue prudemment. Tu veux parler librement ou que je te pose les questions rapides ?")
            return
        else:
            await update.message.reply_text(
                "Je suis vraiment désolée. Appelle les urgences locales maintenant. Si tu veux, je peux te proposer des numéros d'aides."
            )
            return

    # === awaiting_mode_choice ===
    if state == "awaiting_mode_choice":
        resp = user_message.lower()
        if any(k in resp for k in ["parler", "écoute", "libre", "je parle"]):
            context.user_data["state"] = "chatting"
            history.append({"role": "user", "content": user_message, "ts": datetime.utcnow().isoformat()})
            response = await chat_with_ai(profile, history, context)
            history.append({"role": "assistant", "content": response, "ts": datetime.utcnow().isoformat()})
            context.user_data["history"] = history
            await update.message.reply_text(response)
            return
        
        if any(k in resp for k in ["question", "questions", "q", "score"]):
            context.user_data["state"] = "scoring_q"
            context.user_data["current_scoring_index"] = 0
            context.user_data["mental_scores"] = {}
            await update.message.reply_text(f"D'accord {profile['name']}, petit test rapide. Réponds par un chiffre 1–10.")
            await asyncio.sleep(0.5)
            await update.message.reply_text(SCORING_QUESTIONS[0]["q"])
            return
        
        await update.message.reply_text("Je n'ai pas compris — écris 'parler' pour discuter ou 'questions' pour le test.")
        return

    # === scoring flow ===
    if state == "scoring_q":
        idx = context.user_data.get("current_scoring_index", 0)
        num = validate_numeric_response(user_message)
        if num is None:
            await update.message.reply_text("Merci d'indiquer un chiffre entre 1 et 10.")
            return

        key = SCORING_QUESTIONS[idx]["id"]
        context.user_data["mental_scores"][key] = num

        # Micro-comment
        interim_high = (key in ("anxiety", "stress", "mood") and num >= 9)
        if interim_high:
            comment = f"Je vois {profile['name']}... c'est intense. On continue."
        else:
            comment = random.choice(["Ok reçu.", "C'est noté.", "Merci, on continue."])
        await update.message.reply_text(comment)

        idx += 1
        context.user_data["current_scoring_index"] = idx

        if idx < len(SCORING_QUESTIONS):
            await asyncio.sleep(0.5)
            await update.message.reply_text(SCORING_QUESTIONS[idx]["q"])
            return
        else:
            scores = context.user_data.get("mental_scores", {})
            final_score = compute_weighted_score(scores)
            orientation = decide_orientation(final_score)
            
            disable_humour = final_score >= 81
            if disable_humour:
                summary = f"Ton score est {final_score}/100. Détresse élevée. Je recommande : {orientation}."
            else:
                summary = f"Score : {final_score}/100. Interprétation : {orientation}."
            
            context.user_data["last_score"] = {"score": final_score, "orientation": orientation}
            context.user_data["state"] = "chatting"
            await update.message.reply_text(summary)
            await asyncio.sleep(0.5)
            await update.message.reply_text("Tu veux qu'on en parle ou qu'on cherche une solution ?")
            return

    # === chatting ===
    if state == "chatting":
        history.append({"role": "user", "content": user_message, "ts": datetime.utcnow().isoformat()})
        
        # RAG et LLM appelés ici
        response = await chat_with_ai(profile, history, context)
        
        history.append({"role": "assistant", "content": response, "ts": datetime.utcnow().isoformat()})
        context.user_data["history"] = history
        await update.message.reply_text(response)
        return

async def error_handler(update, context):
    logger.exception("Exception: %s", context.error)

def main():
    if not TELEGRAM_BOT_TOKEN or not TOGETHER_API_KEY:
        logger.critical("Missing ENV variables.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    logger.info("Soph_IA V69+RAG starting...")
    application.run_polling()

if __name__ == "__main__":
    main()