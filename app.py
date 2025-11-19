# ==============================================================================
# Soph_IA - V69 "Scoring Emotionnel & Détection de Détresse"
# - Ajout du module de scoring (7 questions) avec micro-interactions
# - Détection de détresse immédiate (phrases à risque)
# - Calcul pondéré du score final et orientation automatique
# - Humour adaptatif : désactivé si détresse, atténué selon criticité
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
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv
from typing import Dict, Optional, List

# >>> RAG INTEGRATION >>>
from rag import rag_query
# <<< RAG INTEGRATION <<<

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
MODEL_API_URL = os.getenv("MODEL_API_URL", "https://api.together.xyz/v1/chat/completions")
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-oss-20b")

# Behaviour params
MAX_RECENT_TURNS = int(os.getenv("MAX_RECENT_TURNS", "3"))
SUMMARY_TRIGGER_TURNS = int(os.getenv("SUMMARY_TRIGGER_TURNS", "8"))
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

# Weights for each dimension (sum = 100)
SCORING_WEIGHTS = {
    "anxiety": 20,
    "stress": 15,
    "sleep": 15,
    "mood": 20,
    "mental_load": 10,
    "control": 10,      # note: control will be inverted in scoring (higher control -> lower risk)
    "motivation": 10    # motivation inverted similarly
}

# Thresholds for orientation
ORIENTATION_THRESHOLDS = {
    "prevention": 30,    # 0-30
    "fragile": 60,       # 31-60
    "psychologist": 80,  # 61-80
    "severe": 100        # 81-100
}

# Dangerous phrases detection (simple keywords, can be extended)
DANGER_KEYWORDS = [
    r"\bme suicid(es|er|e)?\b", r"\bje veux mourir\b", r"\bj'ai envie de mourir\b",
    r"\bfinir ma vie\b", r"\bje vais me tuer\b", r"\bj'ai pensé à me tuer\b",
    r"\bje vais me faire du mal\b", r"\bje me ferai du mal\b", r"\bje ne veux plus vivre\b"
]

# -----------------------
# UTIL - appel modèle (AVEC RETRY)
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
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
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
# PROMPT DYNAMIQUE (hérite V68 persona)
# -----------------------
def build_adaptive_system_prompt(user_profile, emotional_summary):
    user_name = user_profile.get("name") or "l'ami(e) sans nom"
    env_info = user_profile.get("geo_info") or "Non précisé"
    pro_info = user_profile.get("pro_info") or "Non précisé"
    socle_info = user_profile.get("socle_info") or "Non précisé"

    # Keep persona text as in V68 (humour noir)
    persona_base = (
        f"Tu es Sophia, version relou. Tu parles uniquement en français. Ton ton est direct, décalé, pince-sans-rire et d'humour noir. "
        f"Ton rôle est d'écouter {user_name} et d'apporter un soutien, en dosant humour et sérieux.\n\n"
    )
    rules = (
        "Règles :\n"
        "- Commence par valider l'émotion exprimée.\n"
        "- Adapte ton humour : si l'utilisateur présente des signes de détresse, désactive l'humour et reste sérieux.\n"
        "- Si pas de détresse, tu peux doser une touche d'humour entre les propositions.\n"
    )
    memory = f"\nProfil: {user_name} | Environnement: {env_info} | Profession: {pro_info} | Socle: {socle_info}\n"
    if emotional_summary:
        memory += f"\nMémoire émotionnelle: {emotional_summary}\n"

    return persona_base + rules + memory

# -----------------------
# >>> RAG DECISION HELPER >>> 
def should_use_rag(message: str) -> bool:
    """
    Heuristique simple pour décider d'appeler le RAG :
    - Exclut small talk (ça va, salut, merci)
    - Utilise RAG si message contient mots-clés thématiques ou est long (>40 chars)
    """
    if not message or len(message.strip()) == 0:
        return False
    m = message.lower().strip()

    # quick small-talk blacklist (if exactly these common short phrases -> no RAG)
    small_talk = {"ça va", "ca va", "salut", "bonjour", "merci", "ok", "ok!", "quoi de neuf", "yo"}
    if m in small_talk or len(m.split()) <= 3 and any(s == m for s in small_talk):
        return False

    # keywords that indicate need for RAG (mental health, advice, explanation, sleep...)
    keywords = [
        "anx", "anxi", "stress", "déprim", "deprim", "suic", "sommeil", "dormir",
        "insomnie", "psy", "psych", "thérapie", "therapie", "conseil", "aide", 
        "comment", "pourquoi", "que faire", "je me sens", "angoiss", "panique", "phobie", "relation"
    ]
    if any(k in m for k in keywords):
        return True

    # fallback: long messages likely need context
    if len(m) > 40:
        return True

    return False
# <<< RAG DECISION HELPER <<<

# -----------------------
# Helpers: Danger detection + scoring utils
# -----------------------
def detect_dangerous_phrases(text: str) -> bool:
    txt = text.lower()
    for pat in DANGER_KEYWORDS:
        if re.search(pat, txt):
            return True
    return False

def invert_score(value: int) -> int:
    """Invert 1-10 scale (10 -> 1, 1 -> 10) for control/motivation dimensions."""
    return 11 - value

def validate_numeric_response(text: str) -> Optional[int]:
    """Extract an integer 1-10 from text, or return None."""
    text = text.strip()
    # Try direct parse
    m = re.search(r"\b([1-9]|10)\b", text)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 10:
            return val
    # Try words? (optional) - skip for now
    return None

def compute_weighted_score(scores: Dict[str, int]) -> float:
    """Compute the final score 0-100 using SCORING_WEIGHTS.
       Note: 'control' and 'motivation' are inverted (more control -> lower risk)."""
    total = 0.0
    for key, weight in SCORING_WEIGHTS.items():
        val = scores.get(key, 5)  # default neutral
        if key in ("control", "motivation"):
            val = invert_score(val)
        # Map 1-10 to 0-100 then apply weight
        normalized = ((val - 1) / 9) * 100  # 1 -> 0, 10 -> 100
        total += normalized * (weight / 100.0)
    return round(total, 1)

def decide_orientation(score: float) -> str:
    """Return recommended practitioner based on final score."""
    if score <= ORIENTATION_THRESHOLDS["prevention"]:
        return "coach / sophrologue / prévention"
    if score <= ORIENTATION_THRESHOLDS["fragile"]:
        return "coach mental + accompagnement bien-être"
    if score <= ORIENTATION_THRESHOLDS["psychologist"]:
        return "psychologue (évaluation plus approfondie recommandée)"
    return "psychiatre ou service d'urgence (détresse sévère) - orientation urgente requise"

# -----------------------
# Re-usable chat helper
# -----------------------
async def chat_with_ai(user_profile: Dict, history: List[Dict], context: ContextTypes.DEFAULT_TYPE, temperature: float = 0.85, max_tokens: int = 400) -> str:
    if history and len(history) > MAX_RECENT_TURNS * 2:
        history = history[-(MAX_RECENT_TURNS * 2):]

    system_prompt = build_adaptive_system_prompt(user_profile, context.user_data.get("emotional_summary", ""))

    # >>> RAG CALL: decision + inject context BEFORE building payload_messages <<<
    last_user_text = history[-1]["content"] if history else ""
    try:
        if should_use_rag(last_user_text):
            # theme filtering: we attempt to detect a theme keyword from the user message (simple heuristic)
            theme_hint = None
            for t in ["anxiete", "anxious", "anxieux", "stress", "sommeil", "depression", "dépression", "relation", "couple", "travail"]:
                if t in last_user_text.lower():
                    theme_hint = t
                    break
            rag_data = rag_query(last_user_text, n_results=4, theme_filter=theme_hint)
            rag_context = rag_data.get("context", "")
            if rag_context:
                system_prompt += f"\n\nContexte pertinent (RAG):\n{rag_context}\n"
    except Exception as e:
        logger.warning("RAG query failed: %s", e)
        # continue without RAG

    payload_messages = [{"role": "system", "content": system_prompt}] + history
    raw_resp = await asyncio.to_thread(call_model_api_sync, payload_messages, temperature, max_tokens)
    if raw_resp == "FATAL_API_KEY_ERROR":
        return "ERREUR CRITIQUE : Ma clé API est invalide. Veuillez vérifier TOGETHER_API_KEY."
    if not raw_resp:
        return "Désolé, je n'arrive pas à me connecter à mon esprit pour le moment. Réessaie."
    return post_process_response(raw_resp)

# -----------------------
# POST-PROCESS RESPONSE (same as V68)
# -----------------------
def post_process_response(raw_response):
    if not raw_response:
        return "Désolé, je n'arrive pas à formuler ma réponse. Peux-tu reformuler ?"
    text = raw_response.strip()
    for pat in IDENTITY_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(I am|I'm)\b", "", text, flags=re.IGNORECASE)
    text = "\n".join([ln.strip() for ln in text.splitlines() if ln.strip()])
    if re.search(r"[A-Za-z]{3,}", text) and not re.search(r"[àâéèêîôùûçœ]", text):
        return "Je suis désolée, je n'ai pas bien formulé cela en français. Peux-tu répéter ou reformuler ?"
    if len(text) > 1500:
        text = text[:1500].rsplit(".", 1)[0] + "."
    return text

# -----------------------
# NAME DETECTION (unchanged)
# -----------------------
def detect_name_from_text(text):
    text = text.strip()
    if len(text.split()) == 1 and text.lower() not in {"bonjour", "salut", "coucou", "hello", "hi"}:
        return text.capitalize()
    m = re.search(r"(?:mon nom est|je m'appelle|je me nomme|je suis|moi c'est|on m'appelle)\s*([A-Za-zÀ-ÖØ-öø-ÿ'\- ]+)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip().split()[0].capitalize()
    return None

# -----------------------
# HANDLERS TELEGRAM (intègre scoring flow)
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["profile"] = {"name": None, "geo_info": None, "pro_info": None, "socle_info": None}
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    context.user_data["emotional_summary"] = ""
    context.user_data["last_bot_reply"] = ""
    context.user_data["mental_scores"] = {}  # will hold numeric answers
    context.user_data["current_scoring_index"] = 0
    welcome = (
        "Salut ! 👋 Je suis SophIA, ton espace d'écoute confidentiel.\n\n"
        "Tu veux vider ton sac maintenant, ou je peux te poser quelques questions rapides pour mieux t'orienter (ça prend environ 2 minutes) ?\n\n"
        "Pour commencer, quel est ton prénom ?"
    )
    await update.message.reply_text(welcome)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = (update.message.text or "").strip()
    if not user_message:
        return

    profile = context.user_data.setdefault("profile", {"name": None, "geo_info": None, "pro_info": None, "socle_info": None})
    state = context.user_data.get("state", "awaiting_name")
    history = context.user_data.setdefault("history", [])

    # Early danger detection on any message
    if detect_dangerous_phrases(user_message):
        # Activate immediate safety mode (no humour)
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

    # === safety_mode (after dangerous phrase detected) ===
    if state == "safety_mode":
        resp = user_message.lower()
        if resp in {"oui", "non", "oui.", "non."}:
            if resp.startswith("oui"):  # user safe
                context.user_data["state"] = "awaiting_mode_choice"
                await update.message.reply_text("D'accord, merci. On continue prudemment. Tu veux parler librement ou que je te pose les questions rapides ?")
                return
            else:
                # Not safe -> provide urgent resources and escalate
                await update.message.reply_text(
                    "Je suis vraiment désolée que tu te sentes ainsi. Si tu es en danger immédiat, appelle les urgences locales maintenant. "
                    "Si tu veux, je peux te proposer des numéros d'aides et t'accompagner pour contacter quelqu'un."
                )
                # do not continue further; log and wait
                return
        else:
            await update.message.reply_text("Réponds simplement 'oui' si tu es en sécurité maintenant, ou 'non' si tu ne l'es pas.")
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
        if any(k in resp for k in ["question", "questions", "q", "questions rapides", "questions rapides", "score"]):
            # start scoring flow (micro-interactions)
            context.user_data["state"] = "scoring_q"
            context.user_data["current_scoring_index"] = 0
            context.user_data["mental_scores"] = {}
            await asyncio.sleep(0.5)
            await update.message.reply_text(f"D'accord {profile['name']}, on va faire un petit test rapide. Réponds par un chiffre 1–10 à chaque question. Pas de panique.")
            # ask first scoring question
            await asyncio.sleep(0.7)
            await update.message.reply_text(SCORING_QUESTIONS[0]["q"])
            return
        # fallback
        await update.message.reply_text("Je n'ai pas compris — écris 'parler' pour discuter librement ou 'questions' pour le petit test 1–10.")
        return

    # === scoring flow ===
    if state == "scoring_q":
        idx = context.user_data.get("current_scoring_index", 0)
        # validate numeric
        num = validate_numeric_response(user_message)
        if num is None:
            await update.message.reply_text("Merci d'indiquer un chiffre entre 1 et 10. Tu peux réessayer, je t'attends.")
            return

        # store answer
        key = SCORING_QUESTIONS[idx]["id"]
        context.user_data["mental_scores"][key] = num

        # Micro-comment according to adaptative humour rules
        # Determine interim distress: if any answer >=9 for anxiety/stress/mood -> take seriously
        interim_high = False
        if key in ("anxiety", "stress", "mood") and num >= 9:
            interim_high = True

        # craft brief comment (humour adaptatif)
        if interim_high:
            comment = f"Je vois {profile['name']}... c'est intense. On continue, je reste sérieux·se pour l'instant."
        else:
            # light humour
            comment = random.choice([
                "Ok reçu. On avance, t'inquiète pas, j'ai des blagues en réserve.",
                "Parfait. Continue, c'est rapide  promis je ne te poserai pas 52 questions.",
                "Merci, noté. Tu tiens le rythme, bravo."
            ])

        await update.message.reply_text(comment)

        # advance index
        idx += 1
        context.user_data["current_scoring_index"] = idx

        # If still questions left -> ask next
        if idx < len(SCORING_QUESTIONS):
            await asyncio.sleep(0.6)
            await update.message.reply_text(SCORING_QUESTIONS[idx]["q"])
            return
        else:
            # all answers collected -> compute final
            scores = context.user_data.get("mental_scores", {})
            final_score = compute_weighted_score(scores)
            orientation = decide_orientation(final_score)

            # determine humour mode: disable if severe (final_score > 80) or if any very high answers
            disable_humour = final_score >= 81 or any(v >= 9 for v in scores.values())

            # prepare summary text (serious if needed)
            if disable_humour:
                summary = (
                    f"{profile['name']}, merci d'avoir répondu honnêtement. Ton score global est {final_score}/100 — "
                    f"cela indique une détresse élevée. Je te recommande : {orientation}."
                )
                action_suggestion = (
                    "Souhaites-tu que je t'aide à trouver un professionnel près de chez toi ou que je prépare un petit message pour les contacter ?"
                )
            else:
                # adaptive humour / constructive tone
                summary = (
                    f"Ok {profile['name']}, ton score global est {final_score}/100. "
                    f"Interprétation : {orientation}."
                )
                action_suggestion = "Tu veux que je t'aide à trouver des options (psys, coachs) ou qu'on travaille ensemble sur une première action concrète ?"

            # store summary in memory short-term
            context.user_data["last_score"] = {"score": final_score, "orientation": orientation, "scores": scores}
            context.user_data["state"] = "chatting"

            # send result
            await update.message.reply_text(summary)
            await asyncio.sleep(0.6)
            await update.message.reply_text(action_suggestion)
            return

    # === chatting ===
    if state == "chatting":
        # normal conversation flow preserved from V68
        history.append({"role": "user", "content": user_message, "ts": datetime.utcnow().isoformat()})

        system_prompt = build_adaptive_system_prompt(profile, context.user_data.get("emotional_summary", ""))

        msgs = []
        tail = history[-(MAX_RECENT_TURNS * 2):]
        for item in tail:
            if item["role"] in {"user", "assistant"}:
                msgs.append({"role": item["role"], "content": item["content"]})

        payload_messages = [{"role": "system", "content": system_prompt}] + msgs

        raw_resp = await asyncio.to_thread(call_model_api_sync, payload_messages, 0.85, 700)

        # If API failed, fallback
        if not raw_resp or raw_resp == "FATAL_API_KEY_ERROR":
            reply = "Désolé, je n'arrive pas à me connecter à mon esprit. Réessaie dans un instant."
            if raw_resp == "FATAL_API_KEY_ERROR":
                reply = "ERREUR CRITIQUE : Ma clé API est invalide. Veuillez vérifier TOGETHER_API_KEY."

            await update.message.reply_text(reply)
            if history and history[-1]["role"] == "user":
                history.pop()
            context.user_data["history"] = history
            logger.warning("API failed. History purged of the last user message to prevent loop.")
            return

        clean_resp = post_process_response(raw_resp)

        last_bot_reply = context.user_data.get("last_bot_reply", "")
        if clean_resp == last_bot_reply:
            clean_resp = clean_resp + f"\n\n(Désolée {profile['name']}, je me suis répété, c'est l'âge de mes serveurs. Peux-tu reformuler ?)"

        history.append({"role": "assistant", "content": clean_resp, "ts": datetime.utcnow().isoformat()})
        context.user_data["history"] = history
        context.user_data["last_bot_reply"] = clean_resp

        await update.message.reply_text(clean_resp)
        return

    # default fallback
    await update.message.reply_text("Désolé, je n'ai pas compris. Peux-tu reformuler ?")
    return

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Exception: %s", context.error)

# -----------------------
# MAIN
# -----------------------
def main():
    if not TELEGRAM_BOT_TOKEN or not TOGETHER_API_KEY:
        logger.critical("Missing TELEGRAM_BOT_TOKEN or TOGETHER_API_KEY in environment.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    logger.info("Soph_IA V69 starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
