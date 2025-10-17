# ==============================================================================
# Soph_IA - V27 "L'Âme Persistante"
# - Mémoire émotionnelle condensée
# - Prompt adaptatif
# - Filtrage sémantique (3 derniers tours + résumé)
# - Verrou langue FR et anti-redondance
# ==============================================================================

import os
import re
import json
import asyncio
import logging
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("sophia.v27")

load_dotenv()

# -----------------------
# CONFIG
# -----------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
MODEL_API_URL = os.getenv("MODEL_API_URL", "https://api.together.xyz/v1/chat/completions")
MODEL_NAME = os.getenv("MODEL_NAME", "mistralai/Mistral-7B-Instruct-v0.2")

# Behaviour params
MAX_RECENT_TURNS = int(os.getenv("MAX_RECENT_TURNS", "3"))       # nombre de tours complets conservés
SUMMARY_TRIGGER_TURNS = int(os.getenv("SUMMARY_TRIGGER_TURNS", "8"))  # quand consolider la mémoire
SUMMARY_MAX_TOKENS = 120
RESPONSE_TIMEOUT = 45  # secondes

# Anti-repetition patterns to remove if model restates identity
IDENTITY_PATTERNS = [
    r"je suis soph_?ia", r"je m'?appelle soph_?ia", r"je suis une (?:intelligence artificielle|ia)",
    r"je suis ton amie", r"je suis ta confidente"
]

# -----------------------
# UTIL - appel modèle
# -----------------------
def call_model_api_sync(messages, temperature=0.7, max_tokens=300):
    """Appel synchrone à l'API (utilisé via asyncio.to_thread)."""
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
    try:
        r = requests.post(MODEL_API_URL, json=payload, headers=headers, timeout=RESPONSE_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error("call_model_api_sync error: %s", e)
        return None

# -----------------------
# MÉMOIRE ÉMOTIONNELLE
# -----------------------
async def generate_emotional_summary(user_name, recent_history):
    """
    Génère un résumé affectif + thèmes à partir de l'historique récent.
    Renvoie une courte phrase (1-2 lignes) décrivant état émotionnel et sujets.
    """
    if not recent_history:
        return ""
    system = (
        "Tu es un assistant qui résume l'état émotionnel et les thèmes clés d'une conversation. "
        "Réponds en français en 1 à 2 phrases, concises et factuelles. "
        "Ne donnes pas de conseils ici, seulement un résumé émotionnel et les sujets principaux."
    )
    # On fournit uniquement le texte nécessaire (moins de tokens)
    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in recent_history])
    prompt = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Utilisateur: {user_name}\nConversation:\n{history_text}\n\nRésumé émotionnel et thèmes :"}
    ]
    summary = await asyncio.to_thread(call_model_api_sync, prompt, 0.3, SUMMARY_MAX_TOKENS)
    if summary:
        # Normaliser (une seule ligne)
        return " ".join(summary.splitlines()).strip()
    return ""

# -----------------------
# PROMPT DYNAMIQUE
# -----------------------
def build_adaptive_system_prompt(user_profile, emotional_summary):
    """
    Compose le system prompt adaptatif final envoyé au modèle.
    Contient:
      - consignes de ton
      - mémoire émotionnelle (si existante)
      - règles anti-redondance et interdiction d'anglais
      - instruction claire: reformuler émotion + question ouverte
    """
    user_name = user_profile.get("name") or "ami"
    persona_base = (
        f"Tu es Soph_IA, une confidente intime parlant uniquement en français. "
        "Ton ton est doux, empathique, poétique et naturel. "
        "Tu dois écouter, valider l'émotion, reformuler brièvement l'essentiel, puis poser une question ouverte "
        "qui prolonge la discussion et aide l'utilisateur à explorer ses sentiments. "
        "Ne donne pas de conseils médicaux ni de prescriptions. Ne révéle jamais des processus internes.\n\n"
    )

    rules = (
        "Règles strictes :\n"
        "- Réponds uniquement en français. Interdiction totale d'anglais.\n"
        "- Ne te présentes pas à nouveau (ne dis pas \"Je suis Soph_IA\" ni variations) dans les réponses.\n"
        "- N'utilise pas de phrases génériques répétitives comme \"Je suis là si tu veux\".\n"
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

    # Remplacer occurrences trop robotique
    text = re.sub(r"\b(I am|I'm)\b", "", text, flags=re.IGNORECASE)

    # Condense espaces et lignes
    text = "\n".join([ln.strip() for ln in text.splitlines() if ln.strip()])

    # Si modèle a retourné anglais majoritairement (détection simple), forcer une reprise FR courte
    if re.search(r"[A-Za-z]{3,}", text) and not re.search(r"[àâéèêîôùûçœ]", text):
        # fallback short FR message
        return "Je suis désolée, je n'ai pas bien formulé cela en français. Peux-tu répéter ou reformuler ?"

    # Garder max ~1500 chars
    if len(text) > 1500:
        text = text[:1500].rsplit(".", 1)[0] + "."

    # Éviter réponses identiques successives (gestion du caller)
    return text

# -----------------------
# HANDLERS TELEGRAM
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["profile"] = {"name": None}
    context.user_data["state"] = "awaiting_name"
    context.user_data["history"] = []      # liste de dicts role/content
    context.user_data["emotional_summary"] = ""
    context.user_data["last_bot_reply"] = ""
    await update.message.reply_text("Bonjour, je suis Soph_IA. Pour commencer, comment dois-je t'appeler ?")

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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = (update.message.text or "").strip()
    if not user_message:
        return

    profile = context.user_data.setdefault("profile", {"name": None})
    state = context.user_data.get("state", "awaiting_name")
    history = context.user_data.setdefault("history", [])
    emotional_summary = context.user_data.get("emotional_summary", "")
    last_bot_reply = context.user_data.get("last_bot_reply", "")

    # If we don't have name yet, try detect it
    if state == "awaiting_name":
        name_candidate = detect_name_from_text(user_message)
        if name_candidate:
            profile["name"] = name_candidate
            context.user_data["profile"] = profile
            context.user_data["state"] = "chatting"
            context.user_data["history"] = []
            context.user_data["emotional_summary"] = ""
            await update.message.reply_text(f"Enchanté {profile['name']}. Dis-moi, qu'est-ce qui t'amène aujourd'hui ?")
            return
        else:
            await update.message.reply_text("Je n'ai pas bien saisi ton prénom. Peux-tu me l'indiquer simplement ?")
            return

    # Normal chatting flow
    # Append user message to history
    history.append({"role": "user", "content": user_message, "ts": datetime.utcnow().isoformat()})

    # Build recent turns for summarization and context: keep last N turns (user+assistant)
    # history currently stores sequential entries, so we need to get last 2*MAX_RECENT_TURNS messages approximately
    recent = history[-(MAX_RECENT_TURNS * 2 * 2):]  # safe overshoot
    # Collapse recent into alternation user/assistant for summary
    recent_for_summary = []
    # keep only role/content for model consumption
    for item in recent:
        if item.get("role") and item.get("content"):
            recent_for_summary.append({"role": item["role"], "content": item["content"]})

    # Generate/update emotional summary if threshold reached
    # Use length of history as proxy for conversation length
    if len(history) >= SUMMARY_TRIGGER_TURNS and (not emotional_summary):
        # generate summary from the recent messages
        emotional_summary = await generate_emotional_summary(profile.get("name", "ami"), recent_for_summary)
        context.user_data["emotional_summary"] = emotional_summary
        logger.info("Generated emotional summary: %s", emotional_summary)

    # Compose system prompt
    system_prompt = build_adaptive_system_prompt(profile, emotional_summary)

    # Compose messages payload: system + condensed context
    # Keep last MAX_RECENT_TURNS exchange pairs fully (user+assistant)
    # Build a list "messages" with roles system/user/assistant
    # First, gather last complete turns
    msgs = []
    # reconstruct last turns from the history: we will iterate and collect last pairs
    # history contains sequence user/assistant... we will take last 2*MAX_RECENT_TURNS items
    tail = history[-(MAX_RECENT_TURNS * 2):]
    # Convert tail to role/content for payload
    for item in tail:
        if item["role"] in {"user", "assistant"}:
            msgs.append({"role": item["role"], "content": item["content"]})

    # Prepend system prompt
    payload_messages = [{"role": "system", "content": system_prompt}] + msgs + [{"role": "user", "content": user_message}]

    # Call model
    raw_resp = await asyncio.to_thread(call_model_api_sync, payload_messages, 0.75, 400)

    # If API failed, send friendly fallback
    if not raw_resp:
        reply = "Désolé, je n'arrive pas à me connecter à mon esprit. Réessaie dans un instant."
        await update.message.reply_text(reply)
        return

    # Post-process response: remove identity repetition, ensure FR, shorten long outputs
    clean_resp = post_process_response(raw_resp)

    # Avoid identical repeats
    if clean_resp == last_bot_reply:
        clean_resp = clean_resp + "\n\n(Je reformule) " + ("Peux-tu préciser ?" if len(clean_resp) < 100 else "")

    # Update history with assistant reply
    history.append({"role": "assistant", "content": clean_resp, "ts": datetime.utcnow().isoformat()})
    context.user_data["history"] = history
    context.user_data["last_bot_reply"] = clean_resp

    # If emotional summary empty but big conversation, keep generating periodically
    if not emotional_summary and len(history) >= SUMMARY_TRIGGER_TURNS:
        emotional_summary = await generate_emotional_summary(profile.get("name", "ami"), recent_for_summary)
        context.user_data["emotional_summary"] = emotional_summary

    await update.message.reply_text(clean_resp)

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

    logger.info("Soph_IA V27 starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
