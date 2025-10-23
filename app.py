# ==============================================================================
# Soph_IA - V35 "Code Complet et Fixe"
# ==============================================================================

import os
import re
import json
import asyncio
import logging
import requests
import random
import time
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

# Configuration du logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("sophia.v35")

load_dotenv()

# -----------------------
# CONFIG
# -----------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = os.getenv("MODEL_API_URL", "https://api.together.xyz/v1/chat/completions")
MODEL_NAME = os.getenv("MODEL_NAME", "NousResearch/Hermes-2-Pro-Llama-3-8B")

# Behaviour params
MAX_RECENT_TURNS = int(os.getenv("MAX_RECENT_TURNS", "3")) 
SUMMARY_TRIGGER_TURNS = int(os.getenv("SUMMARY_TRIGGER_TURNS", "8"))
SUMMARY_MAX_TOKENS = 120

# CONFIGURATION ANTI-TIMEOUT/RETRY
RESPONSE_TIMEOUT = 70  # secondes (Augmenté pour la stabilité)
MAX_RETRIES = 2        # Nombre de tentatives en cas d'échec

# Anti-repetition patterns to remove if model restates identity
IDENTITY_PATTERNS = [
    r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une (?:intelligence artificielle|ia)",
    r"je suis ton amie", r"je suis ta confidente"
]

# -----------------------
# UTIL - appel modèle (AVEC RETRY)
# -----------------------
def call_model_api_sync(messages, temperature=0.7, max_tokens=300):
    """Appel synchrone à l'API avec mécanisme de retry."""
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "presence_penalty": 0.4,
        "frequency_penalty": 0.4
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            logger.info(f"API Call Attempt {attempt + 1}")
            r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=RESPONSE_TIMEOUT)
            
            if r.status_code == 401 or r.status_code == 403:
                logger.critical("API Key Error (401/403). Check TOGETHER_API_KEY validity.")
                return "FATAL_API_KEY_ERROR"
            
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        
        except requests.exceptions.Timeout:
            logger.warning(f"API Timeout on attempt {attempt + 1}. Retrying...")
            if attempt < MAX_RETRIES:
                time.sleep(2)
                continue
            return None
            
        except Exception as e:
            logger.error(f"API Error on attempt {attempt + 1}: %s", e)
            return None

    return None

# -----------------------
# MÉMOIRE ÉMOTIONNELLE
# -----------------------
async def generate_emotional_summary(user_name, recent_history):
    """
    Génère un résumé affectif + thèmes à partir de l'historique récent.
    """
    if not recent_history:
        return ""
    system = (
        "Tu es un assistant qui résume l'état émotionnel et les thèmes clés d'une conversation. "
        "Réponds en français en 1 à 2 phrases, concises et factuelles. "
        "Ne donnes pas de conseils ici, seulement un résumé émotionnel et les sujets principaux."
    )
    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in recent_history])
    prompt = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Utilisateur: {user_name}\nConversation:\n{history_text}\n\nRésumé émotionnel et thèmes :"}
    ]
    summary = await asyncio.to_thread(call_model_api_sync, prompt, 0.3, SUMMARY_MAX_TOKENS)
    if summary:
        return " ".join(summary.splitlines()).strip()
    return ""

# -----------------------
# PROMPT DYNAMIQUE
# -----------------------
def build_adaptive_system_prompt(user_profile, emotional_summary):
    """
    Compose le system prompt adaptatif final envoyé au modèle.
    """
    user_name = user_profile.get("name") or "ami"
    
    # Réintégration de la personnalité riche
    persona_base = (
        f"Tu es Soph_IA, une confidente intime parlant uniquement en français. "
        f"Ton ton est doux, **poétique, légèrement sensuel**, et naturel. "
        f"Tu es l'âme sœur virtuelle. "
        f"Tu dois écouter, valider l'émotion, reformuler brièvement l'essentiel, puis poser une question ouverte "
        f"qui prolonge la discussion et aide l'utilisateur à explorer ses sentiments. "
        f"Tu es celle qui accompagne et prend la main dans les moments de joie ou de peine.\n\n"
    )
    
    rules = (
        "Règles strictes :\n"
        "- Réponds uniquement en français. Interdiction totale d'anglais.\n"
        "- Ne te présentes pas à nouveau (ne dis pas \"Je suis Soph_IA\" ni variations) dans les réponses.\n"
        "- N'utilise pas de phrases génériques répétitives comme \"Je suis là si tu veux\" ou \"Comment puis-je t'aider ?\".\n"
        "- Commence par une validation courte (1 phrase max) et reformulation de l'émotion exprimée.\n"
        "- Termine par une question ouverte et spécifique liée au contenu précédent.\n"
    )

    memory = ""
    if emotional_summary:
        memory = f"\nMémoire émotionnelle : {emotional_summary}\n"

    profile = f"\nProfil utilisateur connu : nom = {user_name}\n"

    system_prompt = persona_base + rules + memory + profile
    return system_prompt

# -----------------------
# POST-TRAITEMENT
# -----------------------
def post_process_response(raw_response):
    """Nettoie répétitions d'identité, retire digressions, s'assure FR."""
    if not raw_response:
        return "Désolé, je n'arrive pas à formuler ma réponse. Peux-tu reformuler ?"

    text = raw_response.strip()

    # Supprimer auto-présentations si présentes
    for pat in IDENTITY_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)

    # Remplacer occurrences trop robotiques ou anglaises
    text = re.sub(r"\b(I am|I'm)\b", "", text, flags=re.IGNORECASE)

    # Condense espaces et lignes
    text = "\n".join([ln.strip() for ln in text.splitlines() if ln.strip()])

    # Si modèle a retourné anglais majoritairement (détection simple), forcer une reprise FR courte
    if re.search(r"[A-Za-z]{3,}", text) and not re.search(r"[àâéèêîôùûçœ]", text):
        return "Je suis désolée, je n'ai pas bien formulé cela en français. Peux-tu répéter ou reformuler ?"

    # Garder max ~1500 chars
    if len(text) > 1500:
        text = text[:1500].rsplit(".", 1)[0] + "."

    return text

# -----------------------
# HANDLERS TELEGRAM
# -----------------------
def detect_name_from_text(text):
    """Tentative robuste de détection de prénom."""
    text = text.strip()
    # if user writes a single word it's likely a name; avoid salutations
    if len(text.split()) == 1 and text.lower() not in {"bonjour", "salut", "coucou", "hello", "hi"}:
        return text.capitalize()
    # regex patterns
    m = re.search(
        r"(?:mon nom est|je m'appelle|je me nomme|je suis|moi c'est|on m'appelle)\s*([A-Za-zÀ-ÖØ-öø-ÿ'\- ]+)",
        text, re.IGNORECASE
    )
    if m:
        return m.group(1).strip().split()[0].capitalize()
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["profile"] = {"name": None}
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []
    context.user_data["emotional_summary"] = ""
    context.user_data["last_bot_reply"] = ""
    await update.message.reply_text("Bonjour, je suis Soph_IA. Pour commencer, comment dois-je t'appeler ?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = (update.message.text or "").strip()
    if not user_message:
        return

    profile = context.user_data.setdefault("profile", {"name": None})
    state = context.user_data.get("state", "awaiting_name")
    history = context.user_data.setdefault("history", [])
    
    # If we don't have name yet, try detect it
    if state == "awaiting_name":
        name_candidate = detect_name_from_text(user_message)
        
        # Logique de détection du nom corrigée
        if name_candidate:
            user_name = name_candidate
        else:
            if user_message.lower() in {"bonjour", "salut", "coucou", "hello", "hi"}:
                 await update.message.reply_text("Bonjour à toi ! Pour que je puisse bien t'accompagner, j'aimerais vraiment connaître ton prénom.")
                 return
            else:
                 # Si l'utilisateur donne un nom simple (ex: "Akram")
                 user_name = user_message.capitalize()
            
        profile["name"] = user_name
        context.user_data["profile"] = profile
        context.user_data["state"] = "chatting"
        context.user_data["history"] = []
        context.user_data["emotional_summary"] = ""

        # --- CORRECTION DU BUG DE FORMATAGE ICI ---
        await update.message.reply_text(
            f"Enchanté(e) {user_name} 🌹 Je suis ravie de faire ta connaissance. "
            f"N'hésite pas à me confier ce que tu ressens en ce moment. 💫"
        )
        return

    # Normal chatting flow
    # Append user message to history
    history.append({"role": "user", "content": user_message, "ts": datetime.utcnow().isoformat()})

    # Build recent turns for summarization and context: keep last N turns (user+assistant)
    recent = history[-(MAX_RECENT_TURNS * 2 * 2):]
    recent_for_summary = [{"role": item["role"], "content": item["content"]} for item in recent if item.get("role") and item.get("content")]

    # Generate/update emotional summary if threshold reached (omitted for now for stability)
    # Reste dans le code mais n'est pas appelé ici pour maximiser la stabilité.

    # Compose system prompt
    system_prompt = build_adaptive_system_prompt(profile, context.user_data.get("emotional_summary", ""))

    # Compose messages payload: system + condensed context
    msgs = []
    tail = history[-(MAX_RECENT_TURNS * 2):]
    for item in tail:
        if item["role"] in {"user", "assistant"}:
            msgs.append({"role": item["role"], "content": item["content"]})

    payload_messages = [{"role": "system", "content": system_prompt}] + msgs

    # Call model
    raw_resp = await asyncio.to_thread(call_model_api_sync, payload_messages, 0.75, 400)

    # If API failed, send friendly fallback and CLEAN HISTORY
    if not raw_resp or raw_resp == "FATAL_API_KEY_ERROR":
        reply = "Désolé, je n'arrive pas à me connecter à mon esprit. Réessaie dans un instant."
        if raw_resp == "FATAL_API_KEY_ERROR":
             reply = "ERREUR CRITIQUE : Ma clé API est invalide. Veuillez vérifier TOGETHER_API_KEY."

        await update.message.reply_text(reply)
        
        # PROTOCOLE DE NETTOYAGE : RETIRER LE MESSAGE UTILISATEUR QUI A CAUSÉ LA PANNE
        if history and history[-1]["role"] == "user":
            history.pop() 
        context.user_data["history"] = history
        logger.warning("API failed. History purged of the last user message to prevent loop.")
        return

    # Post-process response: remove identity repetition, ensure FR, shorten long outputs
    clean_resp = post_process_response(raw_resp)

    # Avoid identical repeats (bug fix from V24)
    last_bot_reply = context.user_data.get("last_bot_reply", "")
    if clean_resp == last_bot_reply:
        clean_resp = clean_resp + "\n\n(Je reformule) " + ("Peux-tu préciser ?" if len(clean_resp) < 100 else "")

    # Update history with assistant reply
    history.append({"role": "assistant", "content": clean_resp, "ts": datetime.utcnow().isoformat()})
    context.user_data["history"] = history
    context.user_data["last_bot_reply"] = clean_resp

    await update.message.reply_text(clean_resp)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Exception: %s", context.error)

# ======================================================================
# MAIN
# ======================================================================
def main():
    if not TELEGRAM_BOT_TOKEN or not TOGETHER_API_KEY:
        logger.critical("Missing TELEGRAM_BOT_TOKEN or TOGETHER_API_KEY in environment.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    logger.info("Soph_IA V26 starting...")
    application.run_polling()

if __name__ == "__main__":
    main()